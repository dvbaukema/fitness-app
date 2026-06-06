import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import random
import re
from sklearn.linear_model import LinearRegression
import scipy.stats as stats
from datetime import datetime, timedelta
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ══════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="METRICS | Alpha 1",
    layout="centered",
    initial_sidebar_state="collapsed"
)

def system_alert(message, kind="ok"):
    bg = "var(--c-emerald)" if kind == "ok" else "var(--c-rose)"
    ph = st.empty()
    html_str = f"<div style='position:fixed; top:30px; left:50%; transform:translateX(-50%); background:{bg}; color:var(--bg-primary); padding:15px 40px; border-radius:30px; font-weight:800; font-family:\"Inter\", sans-serif; z-index:99999; box-shadow: 0 10px 40px rgba(0,0,0,0.6); text-transform:uppercase; letter-spacing:1.5px; font-size: 0.85rem;'>{message}</div>"
    ph.markdown(html_str, unsafe_allow_html=True)
    time.sleep(1.2)
    ph.empty()

# ══════════════════════════════════════════════════════════════
# PROTOCOL TARGETS
# ══════════════════════════════════════════════════════════════
DEFAULT_PROFILES = {
    "Aggressive Cut":  {'Weight (kg)': [-3.0, -4.0, -2.0], 'Muscle Mass (kg)': [-0.2, -0.5], 'Body Fat (%)': [-1.2, -1.8, -0.6]},
    "Lean Cut":        {'Weight (kg)': [-1.5, -2.0, -1.0], 'Muscle Mass (kg)': [0.0, -0.1],  'Body Fat (%)': [-0.6, -1.0, -0.3]},
    "Recomposition":   {'Weight (kg)': [0.0, -0.5, 0.5],   'Muscle Mass (kg)': [0.3, 0.1],   'Body Fat (%)': [-0.4, -0.8, -0.1]},
    "Lean Bulk":       {'Weight (kg)': [1.0, 0.5, 1.5],    'Muscle Mass (kg)': [0.6, 0.3],   'Body Fat (%)': [0.1, -0.1, 0.4]},
    "Aggressive Bulk": {'Weight (kg)': [2.5, 2.0, 3.5],    'Muscle Mass (kg)': [0.8, 0.5],   'Body Fat (%)': [0.6, 0.3, 1.0]},
}

# ══════════════════════════════════════════════════════════════
# LOCALSTORAGE SYNC SCRIPT
# ══════════════════════════════════════════════════════════════
st.markdown("""
<script>
(function() {
    const urlParams = new URLSearchParams(window.location.search);
    let redirect = false;
    function sync(key) {
        const saved = localStorage.getItem('metrics_' + key);
        if (saved && !urlParams.has(key)) { urlParams.set(key, saved); redirect = true; }
        else if (urlParams.has(key)) { localStorage.setItem('metrics_' + key, urlParams.get(key)); }
    }
    sync('user'); sync('goal'); sync('start'); sync('end'); sync('theme');
    sync('height'); sync('gender'); sync('age');
    sync('activity'); sync('day_type'); sync('protein_custom'); sync('calorie_offset');
    if (redirect) window.location.replace(window.location.origin + window.location.pathname + '?' + urlParams.toString());
})();
</script>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# GOOGLE SHEETS API SETUP
# ══════════════════════════════════════════════════════════════
@st.cache_resource
def get_google_sheets_service():
    try:
        creds = service_account.Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]),
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        return build('sheets', 'v4', credentials=creds)
    except Exception:
        return None

def extract_sheet_id(url):
    if not url: return None
    m = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
    return m.group(1) if m else (url if re.match(r'^[a-zA-Z0-9-_]{20,}$', url) else None)

def read_sheet_range(sheet_url, range_name):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id: return pd.DataFrame()
    try:
        res = service.spreadsheets().values().get(spreadsheetId=sheet_id, range=range_name).execute()
        vals = res.get('values', [])
        if len(vals) < 2: return pd.DataFrame()
        headers = vals[0]; data = vals[1:]
        return pd.DataFrame(data, columns=headers)
    except HttpError:
        return pd.DataFrame()

def append_to_sheet(sheet_url, range_name, values):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id: return False
    try:
        body = {'values': values}
        service.spreadsheets().values().append(
            spreadsheetId=sheet_id, range=range_name,
            valueInputOption='USER_ENTERED', insertDataOption='INSERT_ROWS', body=body
        ).execute()
        return True
    except HttpError:
        return False

def overwrite_sheet_range(sheet_url, range_name, df):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id: return False
    try:
        service.spreadsheets().values().clear(spreadsheetId=sheet_id, range=range_name).execute()
        values = [df.columns.tolist()] + df.values.tolist()
        body = {'values': values}
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id, range=range_name,
            valueInputOption='USER_ENTERED', body=body
        ).execute()
        return True
    except HttpError:
        return False

# ══════════════════════════════════════════════════════════════
# SPECIFIC SHEET READ/WRITE HELPERS
# ══════════════════════════════════════════════════════════════
def load_body_data(sheet_url):
    df = read_sheet_range(sheet_url, 'Body!A:E')
    if df.empty:
        return pd.DataFrame(columns=['Date', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)'])
    if 'Time' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'] + ' ' + df['Time'], format='mixed', errors='coerce')
    else:
        df['Date'] = pd.to_datetime(df['Date'], format='mixed', errors='coerce')
    for m in ['Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']:
        df[m] = pd.to_numeric(df[m], errors='coerce') if m in df.columns else np.nan
    return df[['Date', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']].sort_values('Date').dropna().reset_index(drop=True)

def append_body_entry(sheet_url, date_str, weight, muscle_mass, body_fat):
    time_str = (datetime.utcnow() + timedelta(hours=2)).strftime('%H:%M:%S')
    return append_to_sheet(sheet_url, 'Body!A:E', [[date_str, time_str, weight, body_fat, muscle_mass]])

def overwrite_body_sheet(sheet_url, df):
    values = [['Date', 'Time', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']]
    for _, row in df.iterrows():
        d = pd.Timestamp(row['Date'])
        values.append([d.strftime('%Y-%m-%d'), d.strftime('%H:%M:%S'), float(row['Weight (kg)']), float(row['Body Fat (%)']), float(row['Muscle Mass (kg)'])])
    return overwrite_sheet_range(sheet_url, 'Body!A:E', pd.DataFrame(values[1:], columns=values[0]))

def load_data_constants(sheet_url):
    df = read_sheet_range(sheet_url, 'Data!A1:C2')
    if df.empty:
        return {'height': 180, 'gender': 'male', 'age': 25}
    try:
        h = int(df.iloc[0,0]) if not df.empty else 180
        g = df.iloc[0,1] if df.shape[1]>1 else 'male'
        a = int(df.iloc[0,2]) if df.shape[1]>2 else 25
        return {'height': h, 'gender': g.lower(), 'age': a}
    except:
        return {'height': 180, 'gender': 'male', 'age': 25}

def write_data_constants(sheet_url, height, gender, age):
    vals = [[height, gender, age]]
    return overwrite_sheet_range(sheet_url, 'Data!A1:C2', pd.DataFrame(vals, columns=['Height', 'Gender', 'Age']))

def load_workout_data(sheet_url):
    df = read_sheet_range(sheet_url, 'Workout!A:F')
    if df.empty:
        return pd.DataFrame(columns=['Date', 'Workout Type', 'Exercise', 'Weight', 'Set', 'Reps'])
    df.columns = ['Date', 'Workout Type', 'Exercise', 'Weight', 'Set', 'Reps']
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df['Weight'] = pd.to_numeric(df['Weight'], errors='coerce')
    df['Set'] = pd.to_numeric(df['Set'], errors='coerce')
    df['Reps'] = pd.to_numeric(df['Reps'], errors='coerce')
    return df.dropna(subset=['Date', 'Exercise'])

# ══════════════════════════════════════════════════════════════
# LOAD SECRETS & DIRECTORY
# ══════════════════════════════════════════════════════════════
dan_url = st.secrets.get("daniel_gsheets_url", "")
bram_url = st.secrets.get("bram_gsheets_url", "")
dan_key = st.secrets.get("daniel_user_key", "Daniel")
bram_key = st.secrets.get("bram_user_key", "Bram")
admin_key = st.secrets.get("admin_user_key", "Admin")

USER_DATA = {dan_key: dan_url, bram_key: bram_url}
KEY_TO_LABEL = {dan_key: "Daniel", bram_key: "Bram"}

DEFAULT_QUOTES = [
    "The man who loves walking will walk further than the man who loves the destination.",
    "Intensity > Volume.",
    "No man has the right to be an amateur in the matter of physical training. — Socrates",
    "Discipline equals freedom. — Jocko Willink",
    "It's not about perfect. It's about effort.",
    "The iron never lies. — Henry Rollins",
    "We are what we repeatedly do. Excellence, then, is not an act, but a habit. — Aristotle",
    "There is no reason to be alive and not be strong. — Socrates",
    "If you want something you've never had, you must be willing to do something you've never done.",
    "Strength does not come from winning. Your struggles develop your strengths.",
    "Nothing truly great ever came from a comfort zone."
]

# ══════════════════════════════════════════════════════════════
# SESSION STATE INITIALIZATION
# ══════════════════════════════════════════════════════════════
if 'users' not in st.session_state: st.session_state['users'] = USER_DATA
if 'auth_status' not in st.session_state: st.session_state['auth_status'] = False
if 'current_user' not in st.session_state: st.session_state['current_user'] = None
if 'sheet_url' not in st.session_state: st.session_state['sheet_url'] = ""
if 'is_admin' not in st.session_state: st.session_state['is_admin'] = False

if 'all_quotes' not in st.session_state: st.session_state['all_quotes'] = DEFAULT_QUOTES
if 'enable_quotes' not in st.session_state: st.session_state['enable_quotes'] = True
if 'enable_achievements' not in st.session_state: st.session_state['enable_achievements'] = True
if 'gym_start_date' not in st.session_state: st.session_state['gym_start_date'] = datetime(2026, 3, 17).date()
if 'goal_profiles' not in st.session_state: st.session_state['goal_profiles'] = DEFAULT_PROFILES

if 'current_goal' not in st.session_state: st.session_state['current_goal'] = st.query_params.get("goal", "Lean Bulk")
if 'theme_pref' not in st.session_state: st.session_state['theme_pref'] = st.query_params.get("theme", "System")

if 'analysis_start_date' not in st.session_state:
    default_start = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    st.session_state['analysis_start_date'] = pd.to_datetime(st.query_params.get("start", default_start)).date()
if 'target_end_date' not in st.session_state:
    st.session_state['target_end_date'] = pd.to_datetime(st.query_params.get("end", '2026-09-01')).date()

# Nutrition state
if 'day_type' not in st.session_state:
    st.session_state['day_type'] = st.query_params.get("day_type", "gym_cycling")
if 'calorie_offset' not in st.session_state:
    st.session_state['calorie_offset'] = int(st.query_params.get("calorie_offset", 0))
if 'protein_custom' not in st.session_state:
    st.session_state['protein_custom'] = int(st.query_params.get("protein_custom", 150))
if 'nutrition_phase_start' not in st.session_state:
    st.session_state['nutrition_phase_start'] = datetime.now().date()

# Body constants (from Data sheet)
if 'body_constants' not in st.session_state:
    st.session_state['body_constants'] = load_data_constants(st.session_state['sheet_url'])

# Workout state (exercises pre-defined, but could be extended)
if 'exercises' not in st.session_state:
    st.session_state['exercises'] = [
        {"Name": "DB Press (45°)", "Category": "Chest", "Muscle Group": "Upper Chest"},
        {"Name": "Incline Chest Press Machine", "Category": "Chest", "Muscle Group": "Upper Chest"},
        {"Name": "Assisted Pullup", "Category": "Back", "Muscle Group": "Lats"},
        {"Name": "Single Hand Seated Row", "Category": "Back", "Muscle Group": "Lats/Mid Back"},
        {"Name": "Side Delt Flys", "Category": "Shoulders", "Muscle Group": "Side Delts"},
        {"Name": "Cross-Body Cable Tricep Ext", "Category": "Arms", "Muscle Group": "Triceps"},
        {"Name": "Barbell Squat", "Category": "Legs", "Muscle Group": "Quads"},
        {"Name": "Leg Press", "Category": "Legs", "Muscle Group": "Quads"},
        {"Name": "Leg Extensions", "Category": "Legs", "Muscle Group": "Quads"},
        {"Name": "Leg Curls", "Category": "Legs", "Muscle Group": "Hamstrings"},
        {"Name": "Standing Calf Raises", "Category": "Legs", "Muscle Group": "Calves"},
        {"Name": "Abs Rope", "Category": "Core", "Muscle Group": "Abs"},
        {"Name": "Lat Pulldown", "Category": "Back", "Muscle Group": "Lats"},
        {"Name": "Shoulder Press Machine", "Category": "Shoulders", "Muscle Group": "Front/Side Delts"},
        {"Name": "Upper Back Row", "Category": "Back", "Muscle Group": "Upper Back"},
        {"Name": "Pec Deck Fly", "Category": "Chest", "Muscle Group": "Chest"},
        {"Name": "Brachialis Rope Curl", "Category": "Arms", "Muscle Group": "Brachialis"},
        {"Name": "Overhead Tricep Ext", "Category": "Arms", "Muscle Group": "Triceps"},
        {"Name": "RDLs", "Category": "Legs", "Muscle Group": "Hamstrings/Glutes"},
        {"Name": "45° Hyperextension", "Category": "Legs", "Muscle Group": "Glutes/Lower Back"},
    ]

# ══════════════════════════════════════════════════════════════
# CSS THEME & STYLES
# ══════════════════════════════════════════════════════════════
css_light_vars = """
  --bg-primary: #F0EDE8;
  --bg-secondary: #E8E4DD;
  --text-main: #1A1A1A;
  --text-muted: #6B6560;
  --text-subtle: #A09890;
  --surface: #FAFAF8;
  --surface-hover: #F0EDE8;
  --surface-active: #E8E4DD;
  --border: rgba(0,0,0,0.08);
  --border-strong: rgba(0,0,0,0.15);
  --c-emerald: #059669;
  --c-emerald-bg: rgba(5, 150, 105, 0.1);
  --c-amber: #D97706;
  --c-amber-bg: rgba(217, 119, 6, 0.1);
  --c-rose: #DC2626;
  --c-rose-bg: rgba(220, 38, 38, 0.1);
  --c-blue: #2563EB;
  --c-blue-bg: rgba(37, 99, 235, 0.1);
  --c-blue-soft: rgba(37, 99, 235, 0.15);
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.04);
  --shadow-lg: 0 10px 30px rgba(0,0,0,0.1), 0 4px 8px rgba(0,0,0,0.06);
  --nav-bg: rgba(240, 237, 232, 0.85);
  --nav-pill: #1A1A1A;
  --nav-pill-text: #FAFAF8;
  --nav-text: #6B6560;
  --input-bg: #FAFAF8;
  --input-text: #1A1A1A;
"""

css_dark_vars = """
  --bg-primary: #0F0F0F;
  --bg-secondary: #181818;
  --text-main: #F0EDE8;
  --text-muted: rgba(240,237,232,0.55);
  --text-subtle: rgba(240,237,232,0.3);
  --surface: #1C1C1C;
  --surface-hover: #222222;
  --surface-active: #282828;
  --border: rgba(255,255,255,0.07);
  --border-strong: rgba(255,255,255,0.14);
  --c-emerald: #10B981;
  --c-emerald-bg: rgba(16, 185, 129, 0.12);
  --c-amber: #F59E0B;
  --c-amber-bg: rgba(245, 158, 11, 0.12);
  --c-rose: #F87171;
  --c-rose-bg: rgba(248, 113, 113, 0.12);
  --c-blue: #60A5FA;
  --c-blue-bg: rgba(96, 165, 250, 0.12);
  --c-blue-soft: rgba(96, 165, 250, 0.2);
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.3);
  --shadow-md: 0 4px 16px rgba(0,0,0,0.4);
  --shadow-lg: 0 12px 40px rgba(0,0,0,0.5);
  --nav-bg: rgba(15, 15, 15, 0.88);
  --nav-pill: #F0EDE8;
  --nav-pill-text: #0F0F0F;
  --nav-text: rgba(240,237,232,0.5);
  --input-bg: #1C1C1C;
  --input-text: #F0EDE8;
"""

if st.session_state['theme_pref'] == "Dark":
    theme_block = f":root {{{css_dark_vars}}}"
elif st.session_state['theme_pref'] == "Light":
    theme_block = f":root {{{css_light_vars}}}"
else:
    theme_block = f":root {{{css_light_vars}}} @media (prefers-color-scheme: dark) {{ :root {{{css_dark_vars}}} }}"

css = theme_block + """
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;0,9..40,800;1,9..40,400&family=DM+Mono:wght@400;500;600&display=swap');

*, *::before, *::after { box-sizing: border-box; }

.stApp {
  background: var(--bg-primary) !important;
  font-family: 'DM Sans', sans-serif !important;
}

.block-container {
  padding-top: 1.5rem !important;
  padding-bottom: 6rem !important;
  max-width: 580px !important;
}

#MainMenu, footer, header { display: none !important; }

.app-bar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 2rem;
}
.wordmark {
  font-family: 'DM Sans', sans-serif;
  font-size: 1.75rem;
  font-weight: 800;
  color: var(--text-main);
  letter-spacing: -1.5px;
  line-height: 1;
}
.tagline {
  font-family: 'DM Mono', monospace;
  font-size: 0.6rem;
  color: var(--text-subtle);
  margin-top: 5px;
  letter-spacing: 0.5px;
}
.live-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--c-emerald-bg);
  border: 1px solid rgba(16, 185, 129, 0.25);
  border-radius: 100px;
  padding: 5px 12px;
  font-family: 'DM Mono', monospace;
  font-size: 0.58rem;
  color: var(--c-emerald);
  font-weight: 600;
  letter-spacing: 1.5px;
}
.live-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--c-emerald);
  animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.7); }
}

div[role="radiogroup"] {
    display: flex;
    justify-content: center;
    gap: 8px;
    margin-bottom: 2.5rem;
    margin-top: -0.5rem;
    background: transparent !important;
}
div[role="radiogroup"] > label {
    background: var(--surface) !important;
    border: 1px solid var(--border-strong) !important;
    border-radius: 100px !important;
    padding: 8px 18px !important;
    margin: 0 !important;
    cursor: pointer;
    box-shadow: var(--shadow-sm);
    transition: all 0.2s ease;
}
div[role="radiogroup"] > label:hover {
    border-color: var(--text-muted) !important;
    transform: translateY(-1px);
}
div[role="radiogroup"] > label[data-checked="true"] {
    background: var(--nav-pill) !important;
    border-color: var(--nav-pill) !important;
    box-shadow: var(--shadow-md);
}
div[role="radiogroup"] > label div {
    color: var(--text-muted) !important;
    font-weight: 600 !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.85rem !important;
    letter-spacing: 0.5px !important;
}
div[role="radiogroup"] > label[data-checked="true"] div {
    color: var(--nav-pill-text) !important;
    font-weight: 800 !important;
}
div[role="radiogroup"] span[data-baseweb="radio"] { display: none !important; }
div[role="radiogroup"] div[data-testid="stMarkdownContainer"] p { margin: 0 !important; padding: 0 !important; }

div[data-testid="stSegmentedControl"] { display: none !important; }

.s-head {
  font-family: 'DM Mono', monospace !important;
  font-size: 0.65rem;
  letter-spacing: 2.5px;
  color: var(--text-subtle);
  margin: 2rem 0 1rem;
  font-weight: 500;
  text-transform: uppercase;
}

.settings-lbl {
  font-family: 'DM Sans', sans-serif !important;
  font-size: 0.85rem;
  color: var(--text-main);
  font-weight: 700;
  text-transform: uppercase;
  margin-top: 2rem;
  margin-bottom: 1rem;
  letter-spacing: 1px;
}

.quote-box {
  text-align: center;
  padding: 1.2rem 1.4rem;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface);
  margin-bottom: 1.75rem;
  box-shadow: var(--shadow-sm);
}
.quote-text {
  font-family: 'DM Sans', sans-serif;
  font-size: 0.82rem;
  color: var(--text-muted);
  font-style: italic;
  font-weight: 400;
  line-height: 1.6;
  letter-spacing: 0.1px;
}

.mini-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-bottom: 1.75rem;
}
.mini-cell {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 1.1rem 1rem;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.2s ease;
}
.mini-cell:hover { box-shadow: var(--shadow-md); }
.mini-lbl {
  font-family: 'DM Mono', monospace;
  font-size: 0.58rem;
  color: var(--text-subtle);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  margin-bottom: 8px;
  display: block;
}
.mini-val {
  font-family: 'DM Mono', monospace;
  font-size: 1.55rem;
  font-weight: 600;
  color: var(--text-main);
  line-height: 1;
  display: inline-block;
}
.mini-unit {
  font-size: 0.65rem;
  color: var(--text-subtle);
  margin-left: 2px;
  font-weight: 400;
}
.mini-sub {
  font-family: 'DM Mono', monospace;
  font-size: 0.65rem;
  font-weight: 600;
  margin-top: 8px;
  display: block;
  letter-spacing: 0.5px;
}

.c-ok  { color: var(--c-emerald) !important; }
.c-wrn { color: var(--c-amber) !important; }
.c-err { color: var(--c-rose) !important; }
.c-neu { color: var(--text-muted) !important; }
.c-blue { color: var(--c-blue) !important; }

.chart-blk {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 1.2rem;
  margin-bottom: 1rem;
  box-shadow: var(--shadow-sm);
}
.chart-meta {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 4px;
}
.t-chip {
  font-family: 'DM Mono', monospace;
  font-size: 0.58rem;
  padding: 4px 9px;
  border-radius: 100px;
  font-weight: 600;
  display: inline-block;
  letter-spacing: 0.5px;
}
.t-chip.c-ok  { background: var(--c-emerald-bg); color: var(--c-emerald) !important; }
.t-chip.c-wrn { background: var(--c-amber-bg); color: var(--c-amber) !important; }
.t-chip.c-err { background: var(--c-rose-bg); color: var(--c-rose) !important; }
.t-chip.c-neu { background: var(--surface-active); color: var(--text-muted) !important; }

.hud-card {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  background: var(--surface);
  border: 1px solid var(--border);
  padding: 1rem 1.1rem;
  border-radius: 16px;
  margin-bottom: 0.6rem;
  box-shadow: var(--shadow-sm);
}
.hud-icon {
  font-size: 1.1rem;
  width: 38px;
  height: 38px;
  min-width: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: var(--surface-active);
  flex-shrink: 0;
  line-height: 1;
}
.hud-title {
  font-size: 0.78rem;
  color: var(--text-main);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  margin-bottom: 3px;
}
.hud-desc {
  font-size: 0.76rem;
  color: var(--text-muted);
  line-height: 1.5;
}

.tj-blk { margin-bottom: 2.2rem; }
.tj-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
  align-items: flex-end;
}
.tj-nm {
  font-family: 'DM Mono', monospace;
  font-size: 0.72rem;
  color: var(--text-muted);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 1.5px;
}
.bar-tk {
  height: 20px;
  border-radius: 10px;
  overflow: hidden;
  margin-bottom: 8px;
  position: relative;
}
.bar-pin {
  position: absolute;
  top: -2px;
  bottom: -2px;
  width: 3px;
  background: var(--text-main);
  box-shadow: 0 0 0 2px var(--bg-primary), 0 0 12px rgba(255,255,255,0.3);
  z-index: 5;
  transform: translateX(-50%);
  border-radius: 2px;
}
.tj-st {
  font-family: 'DM Mono', monospace;
  font-size: 0.58rem;
  font-weight: 600;
  letter-spacing: 2px;
  text-transform: uppercase;
  display: block;
  margin-top: 8px;
}

.tier-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 14px;
  border-radius: 14px;
  margin-bottom: 8px;
  background: var(--surface);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-sm);
}
.tier-item.completed {
  background: var(--c-blue-bg);
  border-color: rgba(96,165,250,0.25);
}
.tier-item.completed .tier-name { color: var(--c-blue); }
.tier-item.current {
  background: var(--c-blue-soft);
  border-color: var(--c-blue);
  box-shadow: 0 4px 20px rgba(96,165,250,0.15);
}
.tier-item.locked { opacity: 0.35; }
.tier-emoji {
  font-size: 1.4rem;
  width: 42px;
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-active);
  border-radius: 10px;
  flex-shrink: 0;
}
.tier-details { flex-grow: 1; }
.tier-name {
  font-weight: 700;
  font-size: 0.85rem;
  color: var(--text-main);
  margin-bottom: 2px;
}
.tier-req {
  font-family: 'DM Mono', monospace;
  font-size: 0.6rem;
  color: var(--text-subtle);
  letter-spacing: 0.5px;
}
.prog-tk {
  height: 5px;
  background: var(--border);
  border-radius: 3px;
  overflow: hidden;
  margin-top: 10px;
}
.prog-fill {
  height: 100%;
  background: var(--c-blue);
  border-radius: 3px;
  transition: width 0.6s ease;
}

.hist-row {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 14px 16px;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.15s ease;
}
.hist-row:hover { box-shadow: var(--shadow-md); }
.hist-date {
  font-family: 'DM Mono', monospace;
  font-size: 0.68rem;
  color: var(--text-subtle);
  font-weight: 500;
  letter-spacing: 0.5px;
}
.hist-vals {
  font-family: 'DM Mono', monospace;
  font-size: 0.8rem;
  color: var(--text-main);
  font-weight: 600;
}
.hist-sep {
  color: var(--border-strong);
  margin: 0 6px;
  font-weight: 300;
}
.del-btn button {
    background: transparent !important;
    border: none !important;
    color: var(--text-subtle) !important;
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.7rem !important;
    letter-spacing: 1px !important;
    text-transform: uppercase !important;
    padding: 0 !important;
    margin: 0 !important;
    box-shadow: none !important;
}
.del-btn button:hover {
    color: var(--c-rose) !important;
}

.alert-banner {
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 0.72rem;
  font-weight: 600;
  text-align: center;
  margin-bottom: 1rem;
  letter-spacing: 0.5px;
}
.alert-banner.warn {
  background: var(--c-amber-bg);
  border: 1px solid rgba(217,119,6,0.2);
  color: var(--c-amber);
}
.alert-banner.danger {
  background: var(--c-rose-bg);
  border: 1px solid rgba(220,38,38,0.2);
  color: var(--c-rose);
}
.alert-banner.info {
  background: var(--c-blue-bg);
  border: 1px solid rgba(37,99,235,0.2);
  color: var(--c-blue);
}

div[data-testid="stSlider"] label {
  font-family: 'DM Mono', monospace !important;
  font-size: 0.65rem !important;
  color: var(--text-subtle) !important;
  text-transform: uppercase !important;
  font-weight: 500 !important;
  letter-spacing: 1.5px !important;
}
div[data-testid="stSlider"] > div > div > div {
  height: 10px !important;
  border-radius: 5px !important;
  background: var(--surface-active) !important;
}
div[data-testid="stSlider"] div[role="slider"] {
  width: 22px !important;
  height: 22px !important;
  background: var(--text-main) !important;
  border: 3px solid var(--bg-primary) !important;
  box-shadow: var(--shadow-md) !important;
}

div[data-testid="stSelectbox"] > div > div {
  background: var(--input-bg) !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: 12px !important;
  color: var(--input-text) !important;
  min-height: 3.2rem !important;
  box-shadow: var(--shadow-sm) !important;
}
div[data-testid="stSelectbox"] div[class*="singleValue"] {
  color: var(--input-text) !important;
  font-weight: 600 !important;
  font-family: 'DM Sans', sans-serif !important;
}
div[data-testid="stSelectbox"] [class*="menu"] {
  background: var(--surface) !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: 12px !important;
}
div[data-testid="stSelectbox"] [class*="option"] {
  color: var(--input-text) !important;
}
div[data-testid="stSelectbox"] [class*="option"]:hover {
  background: var(--surface-active) !important;
}

div[data-testid="stTextInput"] > div > div {
  background: var(--input-bg) !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: 12px !important;
  min-height: 3rem !important;
}
div[data-testid="stTextInput"] input {
  color: var(--input-text) !important;
  font-family: 'DM Mono', monospace !important;
  font-size: 1rem !important;
  text-align: center !important;
  background: transparent !important;
}

div[data-testid="stForm"] button {
  background: var(--text-main) !important;
  color: var(--bg-primary) !important;
  font-family: 'DM Sans', sans-serif !important;
  font-weight: 700 !important;
  font-size: 0.82rem !important;
  border: none !important;
  border-radius: 100px !important;
  padding: 1rem !important;
  margin-top: 1.5rem !important;
  text-transform: uppercase !important;
  letter-spacing: 2px !important;
  box-shadow: var(--shadow-md) !important;
  transition: all 0.2s ease !important;
}
div[data-testid="stForm"] button:hover {
  transform: translateY(-1px) !important;
  box-shadow: var(--shadow-lg) !important;
}

.stButton > button {
  background: var(--surface) !important;
  color: var(--text-main) !important;
  font-family: 'DM Sans', sans-serif !important;
  font-weight: 700 !important;
  font-size: 0.82rem !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: 100px !important;
  padding: 0.6rem 1.2rem !important;
  margin-top: 0 !important;
  text-transform: uppercase !important;
  letter-spacing: 1.5px !important;
  box-shadow: var(--shadow-sm) !important;
  transition: all 0.2s ease !important;
}
.stButton > button:hover {
  background: var(--surface-active) !important;
  box-shadow: var(--shadow-md) !important;
}

div[data-testid="stDateInput"] > div > div {
  background: var(--input-bg) !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: 12px !important;
  color: var(--input-text) !important;
}
div[data-testid="stDateInput"] input {
  color: var(--input-text) !important;
}

div[data-testid="stToggle"] label p {
  color: var(--text-main) !important;
  font-size: 0.85rem !important;
}

div[data-testid="stExpander"] {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: 14px !important;
  overflow: hidden;
}
div[data-testid="stExpander"] summary p {
  color: var(--text-main) !important;
  font-size: 0.82rem !important;
  font-weight: 600 !important;
}
div[data-testid="stExpander"] div[data-testid="stMarkdownContainer"] p {
  color: var(--text-main) !important;
}

button[aria-label="Step down"], button[aria-label="Step up"],
button[title="Step down"], button[title="Step up"] {
  display: none !important;
}

div[data-testid="stAlert"] {
  border-radius: 12px !important;
}

div[data-testid="stSelectbox"] > div > div {
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  text-align: center !important;
}
div[data-testid="stSelectbox"] div[data-baseweb="select"] {
  width: 100% !important;
  justify-content: center !important;
  text-align: center !important;
}
div[data-testid="stSelectbox"] div[class*="singleValue"] {
  text-align: center !important;
  margin: 0 auto !important;
  position: absolute;
  left: 0;
  right: 0;
}

::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 2px; }
"""

st.markdown(f'<style>{css}</style>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# AUTO‑LOGIN via URL parameter
# ══════════════════════════════════════════════════════════════
if not st.session_state['auth_status']:
    saved_user = st.query_params.get("user", None)
    if saved_user:
        if saved_user == admin_key:
            st.session_state['is_admin'] = True
            st.session_state['auth_status'] = False
        elif saved_user in USER_DATA:
            st.session_state['auth_status'] = True
            st.session_state['current_user'] = saved_user
            st.session_state['sheet_url'] = USER_DATA[saved_user]
            st.session_state['is_admin'] = False
        else:
            st.query_params.clear()
            st.error("🔒 Access Denied. Invalid link.")
            st.stop()
    else:
        st.error("🔒 Access Denied. Use your personal link to log in.")
        st.stop()

# ══════════════════════════════════════════════════════════════
# ADMIN PROFILE SELECTION SCREEN
# ══════════════════════════════════════════════════════════════
if st.session_state.get('is_admin') and not st.session_state['auth_status']:
    st.markdown("""
    <div style="text-align:center; margin-top:4rem; margin-bottom:3rem;">
        <div class="wordmark" style="font-size:2.5rem;">METRICS</div>
        <div class="tagline" style="font-size:0.65rem; margin-top:6px;">Admin Console</div>
    </div>
    <div class="s-head" style="text-align:center;">Select Profile</div>
    """, unsafe_allow_html=True)

    cols = st.columns(len(USER_DATA))
    for i, (user_key, url) in enumerate(USER_DATA.items()):
        display_name = KEY_TO_LABEL.get(user_key, user_key)
        with cols[i]:
            if st.button(display_name.upper(), key=f"admin_{user_key}", use_container_width=True):
                st.session_state['auth_status'] = True
                st.session_state['current_user'] = user_key
                st.session_state['sheet_url'] = url
                st.session_state['is_admin'] = True
                st.query_params.user = user_key
                st.rerun()
    st.stop()

# ══════════════════════════════════════════════════════════════
# RECOMPOSITION MATH ENGINE & GLOBAL HELPERS
# ══════════════════════════════════════════════════════════════
def sgn(v): return "+" if v > 0 else ""

def dclass(v, invert=False):
    if invert: v = -v
    return "c-ok" if v > 0 else ("c-err" if v < 0 else "c-neu")

def eval_metric(metric, actual, profile, mmt=None, bft=None):
    tgt, lower, upper = profile[metric] if len(profile[metric]) == 3 else (profile[metric][0], profile[metric][1], float('inf'))
    
    if metric == 'Weight (kg)':
        if mmt is not None and bft is not None:
            if actual > upper and mmt >= (actual * 0.4) and bft <= 0.2:
                return ('c-ok', 'bg-ok', 'MUSCLE DRIVEN', 'var(--c-emerald)')
            if actual < lower and mmt >= -0.2 and bft < lower:
                return ('c-ok', 'bg-ok', 'FAT LOSS DRIVEN', 'var(--c-emerald)')

    if metric == 'Muscle Mass (kg)':
        if actual >= tgt: return ('c-ok', 'bg-ok', 'EXCEPTIONAL', 'var(--c-emerald)')
        if actual >= lower: return ('c-wrn', 'bg-wrn', 'LAGGING', 'var(--c-amber)')
        return ('c-err', 'bg-err', 'SUB-OPTIMAL', 'var(--c-rose)')
        
    if actual > upper: return ('c-err', 'bg-err', 'EXCEEDING LIMIT', 'var(--c-rose)')
    if actual < lower: return ('c-wrn', 'bg-wrn', 'BELOW TARGET', 'var(--c-amber)')
    return ('c-ok', 'bg-ok', 'OPTIMAL RANGE', 'var(--c-emerald)')

def get_gradient(metric, profile, max_mag, is_smart_override=False):
    c_g = "var(--c-emerald)"
    c_o = "var(--c-amber)"
    c_r = "var(--c-rose)"
    
    def to_pct(val): return max(min(((val + max_mag) / (2 * max_mag)) * 100, 100), 0)

    if metric == 'Muscle Mass (kg)':
        tgt, lower = profile[metric][:2]
        p_l = to_pct(lower); p_t = to_pct(tgt)
        return f"linear-gradient(to right, {c_r} 0%, {c_r} {p_l}%, {c_o} {p_l}%, {c_o} {p_t}%, {c_g} {p_t}%, {c_g} 100%)"
    else:
        tgt, lower, upper = profile[metric]
        p_lower = to_pct(lower); p_upper = to_pct(upper)
        if is_smart_override == "OVER":
            return f"linear-gradient(to right, {c_o} 0%, {c_o} {p_lower}%, {c_g} {p_lower}%, {c_g} 100%)"
        elif is_smart_override == "UNDER":
            return f"linear-gradient(to right, {c_g} 0%, {c_g} {p_upper}%, {c_r} {p_upper}%, {c_r} 100%)"
        return f"linear-gradient(to right, {c_o} 0%, {c_o} {p_lower}%, {c_g} {p_lower}%, {c_g} {p_upper}%, {c_r} {p_upper}%, {c_r} 100%)"

def hud_card(kind, icon, title, desc):
    color_map = {
        'c-ok': 'var(--c-emerald)', 'c-emerald': 'var(--c-emerald)',
        'c-wrn': 'var(--c-amber)', 'c-amber': 'var(--c-amber)',
        'c-err': 'var(--c-rose)', 'c-rose': 'var(--c-rose)',
        'c-neu': 'var(--text-muted)',
    }
    border_color = color_map.get(kind, 'var(--border)')
    return f"""
    <div class='hud-card' style='border-left: 3px solid {border_color};'>
      <div class='hud-icon'>{icon}</div>
      <div>
        <div class='hud-title' style='color:{border_color};'>{title}</div>
        <div class='hud-desc'>{desc}</div>
      </div>
    </div>"""

def traj_bar(label, actual_rate, metric, profile, unit, mmt=None, bft=None):
    tgt_rate = profile[metric][0]
    s = sgn(actual_rate); ts = sgn(tgt_rate)
    c_txt, c_bg, status, hex_col = eval_metric(metric, actual_rate, profile, mmt, bft)
    
    is_smart_override = False
    if status == 'MUSCLE DRIVEN': is_smart_override = "OVER"
    if status == 'FAT LOSS DRIVEN': is_smart_override = "UNDER"

    if metric == 'Muscle Mass (kg)':
        max_bound = max(abs(profile[metric][1]), abs(tgt_rate), abs(actual_rate), 0.1) * 1.3
        bounds_html = f"<div style='display:grid; grid-template-columns: 1fr 1fr 1fr; text-align:center; font-family:\"DM Mono\", monospace; font-size:0.58rem; color:var(--text-subtle); margin-top:6px; font-weight:500;'><span style='text-align:left;'>MIN {profile[metric][1]:.2f}</span><span style='color:var(--text-main); font-weight:700;'>TGT {tgt_rate:.2f}</span><span style='text-align:right;'>MAX ∞</span></div>"
    else:
        max_bound = max(abs(profile[metric][1]), abs(profile[metric][2]), abs(tgt_rate), abs(actual_rate), 0.1) * 1.3
        min_val = min(profile[metric][1], profile[metric][2])
        max_val = max(profile[metric][1], profile[metric][2])
        bounds_html = f"<div style='display:grid; grid-template-columns: 1fr 1fr 1fr; text-align:center; font-family:\"DM Mono\", monospace; font-size:0.58rem; color:var(--text-subtle); margin-top:6px; font-weight:500;'><span style='text-align:left;'>MIN {min_val:.2f}</span><span style='color:var(--text-main); font-weight:700;'>TGT {tgt_rate:.2f}</span><span style='text-align:right;'>MAX {max_val:.2f}</span></div>"
        
    pct = ((actual_rate + max_bound) / (2 * max_bound)) * 100
    pct = max(min(pct, 97), 3)
    bg_grad = get_gradient(metric, profile, max_bound, is_smart_override)

    html_block = f"""
    <div class='tj-blk'>
      <div class='tj-row' style='margin-bottom:10px;'>
        <span class='tj-nm'>{label}</span>
        <div style='text-align:right;'>
          <div style='font-family:\"DM Mono\", monospace; font-size:1.2rem; font-weight:700; color:var(--text-main); line-height:1;'>
            {s}{actual_rate:.2f} <span style='font-size:0.65rem; color:var(--text-subtle); font-weight:400;'>{unit}</span>
          </div>
        </div>
      </div>
      <div class='bar-tk' style='background: {bg_grad};'>
        <div class='bar-pin' style='left: {pct}%;'></div>
      </div>
      {bounds_html}
      <div class='tj-st {c_txt}'>{status}</div>
    </div>"""
    return html_block

# ══════════════════════════════════════════════════════════════
# NUTRITION CONTEXT ADAPTIVE (NEW)
# ══════════════════════════════════════════════════════════════
def get_context_adaptive_recommendation(protocol, weight_trend, bf_trend, current_offset, base_calories):
    """Return (message, new_offset) using weight AND body‑fat trend."""
    w_lower, w_upper = DEFAULT_PROFILES[protocol]['Weight (kg)'][1], DEFAULT_PROFILES[protocol]['Weight (kg)'][2]
    bf_target, bf_lower, bf_upper = DEFAULT_PROFILES[protocol]['Body Fat (%)']

    # Only decrease if both weight and fat are above upper bound (fat gain)
    if weight_trend > w_upper and bf_trend > bf_upper:
        return (f"Fat gain detected – weight +{weight_trend:.1f} kg/mo, fat +{bf_trend:.1f}%/mo. Consider reducing calories.",
                current_offset - 200)
    # If weight high but fat stable → muscle gain, maintain
    if weight_trend > w_upper and bf_trend <= bf_target:
        return (f"Lean mass progression – weight +{weight_trend:.1f} kg/mo, fat trend good. Maintain current intake.",
                current_offset)
    # Weight too low → increase
    if weight_trend < w_lower:
        if "Cut" in protocol:
            return (f"Weight loss too fast ({weight_trend:.1f} kg/mo). Increase calories to preserve muscle.",
                    current_offset + 200)
        else:
            return (f"Weight gain below target ({weight_trend:.1f} kg/mo). Increase calories.",
                    current_offset + 250)
    # Default no change
    return ("Trends are on track. No adjustment needed.", current_offset)

# ══════════════════════════════════════════════════════════════
# DATA LOADING & STATISTICAL ENGINE
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=60, show_spinner=False)
def load_data(url):
    if not url: raise Exception("URL Missing")
    df = load_body_data(url)
    if df.empty: raise Exception("No body data found – check sharing permissions.")
    return df

try:
    df = load_data(st.session_state['sheet_url'])
    st.session_state['active_df'] = df
except Exception as e:
    st.error(f"System Error: Could not load body data. {str(e)}")
    st.stop()

GOAL_PROFILES = st.session_state['goal_profiles']
METRICS = ['Weight (kg)', 'Muscle Mass (kg)', 'Body Fat (%)']
METRIC_SHORT = {'Weight (kg)': 'Body Weight', 'Muscle Mass (kg)': 'Muscle Mass', 'Body Fat (%)': 'Body Fat'}
METRIC_UNIT  = {'Weight (kg)': 'kg', 'Muscle Mass (kg)': 'kg', 'Body Fat (%)': '%'}

analysis_start = pd.to_datetime(st.session_state['analysis_start_date'])
target_end_date = pd.to_datetime(st.session_state['target_end_date'])
end_label = target_end_date.strftime('%b %d').upper()

df_window_full = df[df['Date'] >= analysis_start].copy()
has_enough_weight_data = len(df_window_full) >= 3 or len(df) >= 3
has_enough_comp_data = len(df_window_full) >= 5 or len(df) >= 5

monthly_trends, traj_data = {}, {}
recent_dfs_for_plot = {}

if has_enough_weight_data:
    df_w = df_window_full if len(df_window_full) >= 3 else df.tail(3)
    recent_dfs_for_plot['Weight (kg)'] = df_w
    X_w_raw = df_w['Date'].map(lambda d: (d - df_w['Date'].min()).days).values
    X_w = X_w_raw.reshape(-1, 1)
    y_w = df_w['Weight (kg)'].values
    res_w = stats.linregress(X_w_raw, y_w)
    slope_w = res_w.slope
    stderr_w = res_w.stderr
    monthly_trends['Weight (kg)'] = slope_w * 30
    start_day_w = (df_w['Date'].min() - df_w['Date'].min()).days
    days_to_end_w = (target_end_date.date() - df_w['Date'].min().date()).days
    if days_to_end_w > 0:
        future_days_w  = np.array([[start_day_w + i] for i in range(0, days_to_end_w + 10)])
        future_dates_w = [df_w['Date'].min() + timedelta(days=i) for i in range(0, days_to_end_w + 10)]
        pred_y_w = res_w.intercept + slope_w * future_days_w.flatten()
        margin_of_error_w = stderr_w * future_days_w.flatten() * 1.96
        traj_data['Weight (kg)'] = {
            'dates': future_dates_w,
            'preds': pred_y_w,
            'upper': pred_y_w + margin_of_error_w,
            'lower': pred_y_w - margin_of_error_w,
            'final_error': margin_of_error_w[-10]
        }

if has_enough_comp_data:
    df_c = df_window_full if len(df_window_full) >= 5 else df.tail(5)
    X_c_raw = df_c['Date'].map(lambda d: (d - df_c['Date'].min()).days).values
    X_c = X_c_raw.reshape(-1, 1)
    days_to_end_c = (target_end_date.date() - df_c['Date'].min().date()).days
    if days_to_end_c > 0:
        start_day_c = (df_c['Date'].min() - df_c['Date'].min()).days
        future_days_c  = np.array([[start_day_c + i] for i in range(0, days_to_end_c + 10)])
        future_dates_c = [df_c['Date'].min() + timedelta(days=i) for i in range(0, days_to_end_c + 10)]
        for m in ['Muscle Mass (kg)', 'Body Fat (%)']:
            recent_dfs_for_plot[m] = df_c
            y_c = df_c[m].values
            res_c = stats.linregress(X_c_raw, y_c)
            slope_c = res_c.slope
            stderr_c = res_c.stderr
            monthly_trends[m] = slope_c * 30
            pred_y_c = res_c.intercept + slope_c * future_days_c.flatten()
            margin_of_error_c = stderr_c * future_days_c.flatten() * 1.96
            traj_data[m] = {
                'dates': future_dates_c,
                'preds': pred_y_c,
                'upper': pred_y_c + margin_of_error_c,
                'lower': pred_y_c - margin_of_error_c,
                'final_error': margin_of_error_c[-10]
            }

# ══════════════════════════════════════════════════════════════
# MAIN ROUTING
# ══════════════════════════════════════════════════════════════
if "goal" in st.query_params: st.session_state['current_goal'] = st.query_params.get("goal")
active_goal = st.session_state.get('current_goal', 'Lean Bulk')
ideal_rates = GOAL_PROFILES.get(active_goal, GOAL_PROFILES['Lean Bulk'])

header_placeholder = st.empty()

app_view = st.radio("Nav", ["Entry", "Trends", "Analysis", "Data", "Nutrition", "Workout", "Settings"],
                    horizontal=True, label_visibility="collapsed")

# ══════════════════════════════════════════════════════════════
# ENTRY TAB
# ══════════════════════════════════════════════════════════════
if app_view == "Entry":
    header_placeholder.markdown(f"""
    <div class="app-bar">
        <div>
            <div class="wordmark">Metrics</div>
            <div class="tagline">{KEY_TO_LABEL.get(st.session_state['current_user'], 'User')} · Alpha 1</div>
        </div>
        <div class="live-pill"><div class="live-dot"></div>SYNCED</div>
    </div>
    """, unsafe_allow_html=True)

    if st.session_state['enable_quotes']:
        if 'daily_quote' not in st.session_state:
            st.session_state['daily_quote'] = random.choice(st.session_state['all_quotes'])
        st.markdown(f"<div class='quote-box'><div class='quote-text'>{st.session_state['daily_quote']}</div></div>", unsafe_allow_html=True)

    selected = st.selectbox("Protocol", list(GOAL_PROFILES.keys()), index=list(GOAL_PROFILES.keys()).index(active_goal))
    if selected != st.session_state['current_goal']:
        st.session_state['current_goal'] = selected
        st.query_params.goal = selected
        st.rerun()
    
    if len(df) > 0:
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last
    else:
        last = pd.Series({'Weight (kg)': 70.0, 'Body Fat (%)': 15.0, 'Muscle Mass (kg)': 35.0})
        prev = last

    if len(df) > 0:
        recent_bf_avg = df.tail(7)['Body Fat (%)'].mean()
        if "Bulk" in st.session_state['current_goal'] and recent_bf_avg > 18.0:
            st.markdown(f"<div class='alert-banner danger'>⚠ High body fat for bulk — {recent_bf_avg:.1f}% avg</div>", unsafe_allow_html=True)
        elif "Cut" in st.session_state['current_goal'] and recent_bf_avg < 10.0:
            st.markdown(f"<div class='alert-banner danger'>⚠ Too lean to cut safely — {recent_bf_avg:.1f}% avg</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='alert-banner info'>✓ Valid for current body composition — {recent_bf_avg:.1f}% avg fat</div>", unsafe_allow_html=True)

    delta_w = last['Weight (kg)'] - prev['Weight (kg)']
    delta_bf = last['Body Fat (%)'] - prev['Body Fat (%)']
    delta_m = last['Muscle Mass (kg)'] - prev['Muscle Mass (kg)']

    st.markdown(f"""
    <div class="mini-grid" style="margin-top:1.5rem;">
        <div class="mini-cell">
            <span class="mini-lbl">Weight</span>
            <span class="mini-val">{last['Weight (kg)']:.1f}<span class="mini-unit">kg</span></span>
            <div class="mini-sub {dclass(delta_w, invert=('Cut' in active_goal))}">{sgn(delta_w)}{delta_w:.1f} kg</div>
        </div>
        <div class="mini-cell">
            <span class="mini-lbl">Muscle</span>
            <span class="mini-val">{last['Muscle Mass (kg)']:.1f}<span class="mini-unit">kg</span></span>
            <div class="mini-sub {dclass(delta_m)}">{sgn(delta_m)}{delta_m:.1f} kg</div>
        </div>
        <div class="mini-cell">
            <span class="mini-lbl">Body Fat</span>
            <span class="mini-val">{last['Body Fat (%)']:.1f}<span class="mini-unit">%</span></span>
            <div class="mini-sub {dclass(delta_bf, invert=True)}">{sgn(delta_bf)}{delta_bf:.1f}%</div>
        </div>
    </div>
    <div class="s-head">New Entry</div>
    """, unsafe_allow_html=True)

    with st.form("log_form", border=False):
        w_val = float(last['Weight (kg)'])
        w = st.slider("Weight (kg)", min_value=max(0.0, w_val-2.5), max_value=w_val+2.5, value=w_val, step=0.1)
        m_val = float(last['Muscle Mass (kg)'])
        m = st.slider("Muscle Mass (kg)", min_value=max(0.0, m_val-2.5), max_value=m_val+2.5, value=m_val, step=0.1)
        bf_val = float(last['Body Fat (%)'])
        bf = st.slider("Body Fat (%)", min_value=max(3.0, bf_val-2.5), max_value=bf_val+2.5, value=bf_val, step=0.1)

        if st.form_submit_button("Save Record", use_container_width=True):
            now = datetime.now()
            date_str = now.strftime('%Y-%m-%d')
            append_body_entry(st.session_state['sheet_url'], date_str, w, m, bf)
            new_row = pd.DataFrame({'Date': [now], 'Weight (kg)': [w], 'Body Fat (%)': [bf], 'Muscle Mass (kg)': [m]})
            st.session_state['active_df'] = pd.concat([st.session_state['active_df'], new_row], ignore_index=True)
            load_data.clear()
            if st.session_state['enable_quotes']:
                st.session_state['daily_quote'] = random.choice(st.session_state['all_quotes'])
            system_alert("Saved")
            st.rerun()

# ══════════════════════════════════════════════════════════════
# TRENDS TAB (unchanged)
# ══════════════════════════════════════════════════════════════
elif app_view == "Trends":
    header_placeholder.empty()
    if not has_enough_weight_data:
        st.markdown(hud_card("c-neu", "⏳", "Calibrating", f"Need 3 logged measurements for trends. Currently: {len(df)}/3."), unsafe_allow_html=True)
        st.stop()
        
    if len(df_window_full) < 3:
        st.markdown(f"<div class='alert-banner warn'>⚠ Not enough data since custom start date — using last available logs</div>", unsafe_allow_html=True)

    font_cfg = dict(family='DM Mono, monospace', size=9, color='rgba(128,128,128,0.8)')
    
    for metric in METRICS:
        if metric != 'Weight (kg)' and not has_enough_comp_data:
            continue
            
        last_val = df.iloc[-1][metric]
        unit = METRIC_UNIT[metric]
        trend = monthly_trends[metric]
        target = ideal_rates[metric][0]
        c_txt, c_bg, _, hex_col = eval_metric(metric, trend, ideal_rates)
        
        proj_html = ""
        if 'preds' in traj_data.get(metric, {}):
            final_pred = traj_data[metric]['preds'][-10] 
            final_error = traj_data[metric]['final_error']
            lower_proj = final_pred - final_error
            upper_proj = final_pred + final_error
            proj_html = f"<div style='font-family:\"DM Mono\", monospace; font-size:0.65rem; color:var(--text-subtle); margin-top:5px; letter-spacing:0.3px;'>{end_label} PROJ: <span style='color:var(--text-main); font-weight:600;'>{lower_proj:.1f} – {upper_proj:.1f} {unit}</span></div>"
        
        st.markdown(f"""
        <div class="chart-blk">
            <div class="chart-meta">
                <div>
                    <div style="font-size:0.7rem; color:var(--text-muted); font-weight:600; text-transform:uppercase; letter-spacing:1.5px; font-family:'DM Mono',monospace;">{METRIC_SHORT[metric]}</div>
                    <div style="font-size:2rem; font-weight:700; color:var(--text-main); line-height:1.1; margin-top:2px; font-family:'DM Mono',monospace;">{last_val:.1f}<span style="font-size:0.9rem; color:var(--text-subtle); font-weight:400; margin-left:3px;">{unit}</span></div>
                    {proj_html}
                </div>
                <div style="text-align: right; display:flex; flex-direction:column; gap:5px; align-items:flex-end;">
                    <span class="t-chip {c_txt}" style="display:block;">{sgn(trend)}{trend:.2f}/mo</span>
                    <span class="t-chip c-neu" style="display:block;">TGT {sgn(target)}{target:.2f}</span>
                </div>
            </div>
        """, unsafe_allow_html=True)
        
        fig = go.Figure()
        df_hist = df[~df.index.isin(recent_dfs_for_plot[metric].index)]
        fig.add_trace(go.Scatter(
            x=df_hist['Date'], y=df_hist[metric],
            mode='lines+markers', name='History',
            line=dict(color='rgba(128,128,128,0.2)', width=1.5),
            marker=dict(size=3, color='rgba(128,128,128,0.25)'),
            hoverinfo='skip'
        ))
        spec_recent = recent_dfs_for_plot[metric]
        fig.add_trace(go.Scatter(
            x=spec_recent['Date'], y=spec_recent[metric],
            mode='lines+markers', name='Active',
            line=dict(color='#3B82F6', width=2.5),
            marker=dict(size=5, color='#3B82F6', line=dict(width=1.5, color='white')),
            hovertemplate='%{x|%b %d}: %{y:.1f}<extra></extra>'
        ))
        epoch_date = spec_recent['Date'].min()
        fig.add_vline(x=epoch_date, line_width=1.5, line_dash="solid", line_color="rgba(128,128,128,0.4)",
                      annotation_text="START", annotation_position="bottom right",
                      annotation_font_size=9, annotation_font_color="rgba(128,128,128,0.6)")
        current_date = spec_recent['Date'].max()
        daily_rate = ideal_rates[metric][0] / 30.0
        
        if metric == 'Weight (kg)':
            start_x = epoch_date
            start_y = spec_recent.iloc[0][metric]
        elif metric == 'Muscle Mass (kg)':
            start_x = current_date
            start_y = spec_recent.iloc[-1][metric]
        else:
            start_x = current_date
            start_y = spec_recent[metric].mean()
        days_span = (target_end_date.date() - start_x.date()).days
        if days_span > 0:
            target_val_at_end = start_y + (daily_rate * days_span)
            fig.add_vline(x=target_end_date, line_width=1.5, line_dash="dash", line_color="#10B981",
                          annotation_text=end_label, annotation_position="top left",
                          annotation_font_size=9, annotation_font_color="#10B981")
            fig.add_trace(go.Scatter(
                x=[target_end_date], y=[target_val_at_end],
                mode='markers+text', name=f'{end_label} Goal',
                marker=dict(size=8, color='#10B981', symbol='diamond', line=dict(width=1.5, color='white')),
                text=[f"{target_val_at_end:.1f}{unit}"],
                textposition="middle right",
                textfont=dict(color="#10B981", size=10, family="DM Mono"),
                hoverinfo='skip'
            ))
            fig.add_trace(go.Scatter(
                x=[start_x, target_end_date], y=[start_y, target_val_at_end],
                mode='lines', name='Target Path',
                line=dict(color='rgba(128,128,128,0.4)', width=1.5, dash='dot'),
                hoverinfo='skip'
            ))
        if 'dates' in traj_data.get(metric, {}):
            x_vals = traj_data[metric]['dates']
            y_upper = traj_data[metric]['upper']
            y_lower = traj_data[metric]['lower']
            fig.add_trace(go.Scatter(
                x=x_vals + x_vals[::-1],
                y=list(y_upper) + list(y_lower)[::-1],
                fill='toself',
                fillcolor='rgba(128,128,128,0.06)',
                line=dict(color='rgba(0,0,0,0)'),
                hoverinfo="skip", showlegend=False
            ))
            fig.add_trace(go.Scatter(
                x=x_vals, y=traj_data[metric]['preds'],
                mode='lines', name='Trajectory',
                line=dict(color=hex_col, width=2, dash='dash'),
                hoverinfo='skip'
            ))
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=0, r=0, t=16, b=40), height=195, showlegend=True,
            legend=dict(orientation="h", yanchor="top", y=-0.3, xanchor="center", x=0.5,
                       font=dict(size=9, color='rgba(128,128,128,0.6)'), bgcolor='rgba(0,0,0,0)'),
            xaxis=dict(showgrid=False, zeroline=False, tickfont=font_cfg, tickformat='%b %d',
                      range=[df['Date'].min(), target_end_date + timedelta(days=10)]),
            yaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.08)', zeroline=False,
                      tickfont=font_cfg, side='right')
        )
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        st.markdown("</div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# ANALYSIS TAB (unchanged, but might include nutrition hints later)
# ══════════════════════════════════════════════════════════════
elif app_view == "Analysis":
    header_placeholder.empty()
    if not has_enough_weight_data:
        st.markdown(hud_card("c-neu", "⏳", "Calibrating Engine", f"Need 3 logged measurements. Currently: {len(df)}/3."), unsafe_allow_html=True)
        st.stop()

    if len(df_window_full) < 3:
        st.markdown(f"<div class='alert-banner warn'>⚠ Not enough data since custom start date — using last available logs</div>", unsafe_allow_html=True)

    last = df.iloc[-1]
    w, bf, mm = last['Weight (kg)'], last['Body Fat (%)'], last['Muscle Mass (kg)']
    wt = monthly_trends.get('Weight (kg)', 0)
    mmt = monthly_trends.get('Muscle Mass (kg)', 0)
    bft = monthly_trends.get('Body Fat (%)', 0)

    c_w, _, _, _ = eval_metric('Weight (kg)', wt, ideal_rates, mmt, bft)
    if has_enough_comp_data:
        c_bf, _, _, _ = eval_metric('Body Fat (%)', bft, ideal_rates, mmt, bft)
        c_mm, _, _, _ = eval_metric('Muscle Mass (kg)', mmt, ideal_rates, mmt, bft)
        bf_disp = f"""<div class="mini-sub {c_bf}">{sgn(bft)}{bft:.2f} %/mo</div>"""
        mm_disp = f"""<div class="mini-sub {c_mm}">{sgn(mmt)}{mmt:.2f} kg/mo</div>"""
    else:
        bf_disp = f"""<div class="mini-sub c-neu">Calibrating ({len(df)}/5)</div>"""
        mm_disp = f"""<div class="mini-sub c-neu">Calibrating ({len(df)}/5)</div>"""

    st.markdown(f"""
    <div class="s-head" style="margin-top:0;">Performance</div>
    <div class="mini-grid">
        <div class="mini-cell">
            <span class="mini-lbl">Weight</span>
            <span class="mini-val">{w:.1f}</span>
            <div class="mini-sub {c_w}">{sgn(wt)}{wt:.2f} kg/mo</div>
        </div>
        <div class="mini-cell">
            <span class="mini-lbl">Muscle</span>
            <span class="mini-val">{mm:.1f}</span>
            {mm_disp}
        </div>
        <div class="mini-cell">
            <span class="mini-lbl">Body Fat</span>
            <span class="mini-val">{bf:.1f}</span>
            {bf_disp}
        </div>
    </div>
    <div class="s-head">Rate of Change</div>
    """, unsafe_allow_html=True)

    st.markdown(traj_bar("Body Weight", wt, 'Weight (kg)', ideal_rates, "kg/mo", mmt, bft), unsafe_allow_html=True)
    if has_enough_comp_data:
        st.markdown(
            traj_bar("Muscle Mass", mmt, 'Muscle Mass (kg)', ideal_rates, "kg/mo", mmt, bft) +
            traj_bar("Body Fat", bft, 'Body Fat (%)', ideal_rates, "%/mo", mmt, bft),
            unsafe_allow_html=True
        )

    st.markdown('<div class="s-head">Diagnostics</div>', unsafe_allow_html=True)
    diags = []
    
    is_muscle_driven = (wt > w_upper) and has_enough_comp_data and (mmt >= (wt * 0.4)) and (bft <= 0.2)
    bf_lower = ideal_rates['Body Fat (%)'][1] if len(ideal_rates['Body Fat (%)']) > 1 else -99
    is_fat_loss_driven = (wt < w_lower) and has_enough_comp_data and (mmt >= -0.2) and (bft < bf_lower)

    if is_muscle_driven:
        diags.append(hud_card("c-ok", "🧬", "Hyper-Anabolic Response", f"Weight rising fast (+{wt:.2f} kg/mo) but muscle-driven (+{mmt:.2f} kg/mo). Don't cut calories — ride the wave."))
    elif is_fat_loss_driven:
        diags.append(hud_card("c-ok", "🔥", "Hyper-Lipolytic Response", f"Weight dropping fast ({wt:.2f} kg/mo) but muscle is preserved and fat is melting (-{abs(bft):.2f} %/mo). Excellent recomposition."))
    elif wt > w_upper:
        diags.append(hud_card("c-err", "↓", "Over Upper Limit", f"Weight accumulation ({wt:.2f} kg/mo) exceeds ceiling. Reduce caloric intake by 200–300 kcal."))
    elif wt < w_lower:
        if w_lower < 0:
            diags.append(hud_card("c-err", "⚠", "Catabolic Danger", f"Losing weight too fast ({wt:.2f} kg/mo). Increase calories immediately."))
        else:
            diags.append(hud_card("c-wrn", "↑", "Anabolic Stall", f"Weight gain lagging below {w_lower} kg/mo. Add 200–300 kcal to daily intake."))
    
    if has_enough_comp_data and not is_muscle_driven and not is_fat_loss_driven:
        m_tgt, m_lower = ideal_rates['Muscle Mass (kg)'][:2]
        bf_tgt, bf_lower_v, bf_upper = ideal_rates['Body Fat (%)']
        if wt >= w_lower and mmt < m_lower:
            diags.append(hud_card("c-wrn", "⚠", "Low Muscle Synthesis", f"Weight tracking OK, but muscle lagging ({mmt:.2f} kg/mo). Ensure 1.6–2.2g protein/kg bodyweight."))
        if bft > bf_upper:
            diags.append(hud_card("c-err", "⚠", "Excessive Fat Gain", f"Fat accumulation ({bft:.2f} %/mo) exceeds limits. Dial back carbs or fats slightly."))
            
    if not diags:
        diags.append(hud_card("c-ok", "✓", "Locked In", "All parameters within optimal bounds. Stay the course."))
    
    for d in diags:
        st.markdown(d, unsafe_allow_html=True)

    if st.session_state.get('enable_achievements', True):
        start_gym_time = st.session_state['gym_start_date']
        days_elapsed = max(0, (datetime.now().date() - start_gym_time).days)
        TIERS = [
            {"name": "Day 1", "emoji": "👋", "days": 0},
            {"name": "1 Week", "emoji": "🌱", "days": 7},
            {"name": "2 Weeks", "emoji": "🌿", "days": 14},
            {"name": "3 Weeks", "emoji": "🍃", "days": 21},
            {"name": "4 Weeks", "emoji": "🪴", "days": 28},
            {"name": "10 Weeks", "emoji": "🌲", "days": 70},
            {"name": "15 Weeks", "emoji": "🌳", "days": 105},
            {"name": "20 Weeks", "emoji": "🥉", "days": 140},
            {"name": "25 Weeks", "emoji": "🥈", "days": 175},
            {"name": "30 Weeks", "emoji": "🥇", "days": 210},
            {"name": "40 Weeks", "emoji": "🏅", "days": 280},
            {"name": "1 Year", "emoji": "🏆", "days": 365},
            {"name": "2 Years", "emoji": "🔥", "days": 730},
            {"name": "3 Years", "emoji": "⚡", "days": 1095},
            {"name": "4 Years", "emoji": "🦾", "days": 1460},
            {"name": "5 Years", "emoji": "⚙️", "days": 1825},
            {"name": "6 Years", "emoji": "💎", "days": 2190},
            {"name": "7 Years", "emoji": "🔮", "days": 2555},
            {"name": "8 Years", "emoji": "👑", "days": 2920},
            {"name": "9 Years", "emoji": "🚀", "days": 3285},
            {"name": "10 Years", "emoji": "🌌", "days": 3650}
        ]
        current_tier_idx = 0
        for i, t in enumerate(TIERS):
            if days_elapsed >= t["days"]: current_tier_idx = i

        st.markdown('<div class="s-head">Achievements</div>', unsafe_allow_html=True)
        engine_html = "<div style='margin-bottom: 2rem;'>\n"
        start_idx = max(0, current_tier_idx - 3)
        for i in range(start_idx, current_tier_idx):
            t = TIERS[i]
            engine_html += f"<div class='tier-item completed'><div class='tier-emoji'>{t['emoji']}</div><div class='tier-details'><div class='tier-name'>{t['name']}</div><div class='tier-req'>Unlocked · {t['days']} days</div></div><div style='color:var(--c-blue); font-weight:800; font-size:1.1rem;'>✓</div></div>\n"
        t_curr = TIERS[current_tier_idx]
        if current_tier_idx < len(TIERS) - 1:
            t_next = TIERS[current_tier_idx + 1]
            progress = ((days_elapsed - t_curr['days']) / (t_next['days'] - t_curr['days'])) * 100
            engine_html += f"<div class='tier-item current'><div class='tier-emoji'>{t_curr['emoji']}</div><div class='tier-details'><div style='display:flex; justify-content:space-between; align-items:flex-end;'><div class='tier-name' style='color:var(--c-blue);'>{t_curr['name']}</div><div style='font-family:\"DM Mono\",monospace; font-size:0.58rem; color:var(--text-subtle); font-weight:500;'>{days_elapsed} / {t_next['days']} d</div></div><div class='prog-tk'><div class='prog-fill' style='width:{progress:.1f}%;'></div></div></div></div>\n"
        else:
            engine_html += f"<div class='tier-item current'><div class='tier-emoji'>{t_curr['emoji']}</div><div class='tier-details'><div class='tier-name' style='color:var(--c-blue);'>{t_curr['name']}</div><div class='tier-req'>Maximum tier reached</div></div></div>\n"
        end_idx = min(len(TIERS), current_tier_idx + 3)
        for i in range(current_tier_idx + 1, end_idx):
            t = TIERS[i]
            engine_html += f"<div class='tier-item locked'><div class='tier-emoji'>🔒</div><div class='tier-details'><div class='tier-name'>{t['name']}</div><div class='tier-req'>Requires {t['days']} days</div></div></div>\n"
        engine_html += "</div>"
        st.markdown(engine_html, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# DATA TAB (FIXED LAYOUT)
# ══════════════════════════════════════════════════════════════
elif app_view == "Data":
    header_placeholder.empty()
    st.markdown('<div class="s-head" style="margin-top:0;">Record History</div>', unsafe_allow_html=True)
    
    hcol1, hcol2, hcol3, hcol4, hcol5 = st.columns([3, 1.2, 1.2, 1.2, 0.8])
    with hcol1:
        st.markdown("<span style='font-family:DM Mono,monospace; font-size:0.6rem; color:var(--text-subtle); font-weight:600; text-transform:uppercase; letter-spacing:1.5px;'>Date</span>", unsafe_allow_html=True)
    with hcol2:
        st.markdown("<span style='font-family:DM Mono,monospace; font-size:0.6rem; color:var(--text-subtle); font-weight:600; text-transform:uppercase; letter-spacing:1.5px;'>Weight</span>", unsafe_allow_html=True)
    with hcol3:
        st.markdown("<span style='font-family:DM Mono,monospace; font-size:0.6rem; color:var(--text-subtle); font-weight:600; text-transform:uppercase; letter-spacing:1.5px;'>Muscle</span>", unsafe_allow_html=True)
    with hcol4:
        st.markdown("<span style='font-family:DM Mono,monospace; font-size:0.6rem; color:var(--text-subtle); font-weight:600; text-transform:uppercase; letter-spacing:1.5px;'>Fat</span>", unsafe_allow_html=True)
    with hcol5:
        st.write("")
    
    seven_days_ago = pd.Timestamp(datetime.now() - timedelta(days=7))
    
    for i in range(len(df)-1, max(-1, len(df)-21), -1):
        row = df.iloc[i]
        row_date = row['Date']
        if i > 0:
            prev_row = df.iloc[i-1]
            delta_w = row['Weight (kg)'] - prev_row['Weight (kg)']
            delta_m = row['Muscle Mass (kg)'] - prev_row['Muscle Mass (kg)']
            delta_bf = row['Body Fat (%)'] - prev_row['Body Fat (%)']
            dw_color = "var(--c-emerald)" if ("Cut" in active_goal and delta_w <= 0) or ("Bulk" in active_goal and delta_w >= 0) else "var(--c-rose)"
            dm_color = "var(--c-emerald)" if delta_m >= 0 else "var(--c-rose)"
            dbf_color = "var(--c-emerald)" if delta_bf <= 0 else "var(--c-rose)"
            delta_w_str = f"<span style='color:{dw_color}; font-size:0.55rem;'>{sgn(delta_w)}{delta_w:.1f}</span>"
            delta_m_str = f"<span style='color:{dm_color}; font-size:0.55rem;'>{sgn(delta_m)}{delta_m:.1f}</span>"
            delta_bf_str = f"<span style='color:{dbf_color}; font-size:0.55rem;'>{sgn(delta_bf)}{delta_bf:.1f}</span>"
        else:
            delta_w_str = delta_m_str = delta_bf_str = ""
        
        col1, col2, col3, col4, col5 = st.columns([3, 1.2, 1.2, 1.2, 0.8])
        with col1:
            st.markdown(f"<span style='font-family:DM Mono,monospace; font-size:0.7rem; color:var(--text-main);'>{row_date.strftime('%d %b %Y')}</span>", unsafe_allow_html=True)
        with col2:
            st.markdown(f"<span style='font-family:DM Mono,monospace; font-size:0.8rem; color:var(--text-main);'>{row['Weight (kg)']:.1f}</span><br>{delta_w_str}", unsafe_allow_html=True)
        with col3:
            st.markdown(f"<span style='font-family:DM Mono,monospace; font-size:0.8rem; color:var(--text-main);'>{row['Muscle Mass (kg)']:.1f}</span><br>{delta_m_str}", unsafe_allow_html=True)
        with col4:
            st.markdown(f"<span style='font-family:DM Mono,monospace; font-size:0.8rem; color:var(--text-main);'>{row['Body Fat (%)']:.1f}%</span><br>{delta_bf_str}", unsafe_allow_html=True)
        with col5:
            if pd.Timestamp(row_date) >= seven_days_ago:
                if st.button("✕", key=f"del_{i}", help="Delete this entry"):
                    new_df = df.drop(index=i).reset_index(drop=True)
                    overwrite_body_sheet(st.session_state['sheet_url'], new_df)
                    st.session_state['active_df'] = new_df
                    load_data.clear()
                    system_alert("Deleted", "err")
                    st.rerun()
            else:
                st.write("")

# ══════════════════════════════════════════════════════════════
# NUTRITION TAB (REVISED)
# ══════════════════════════════════════════════════════════════
elif app_view == "Nutrition":
    header_placeholder.empty()

    day_map = {
        "rest": "Rest Day – 2800 kcal",
        "school": "School / Cycling – 3000 kcal",
        "gym_cycling": "Gym + Cycling – 3200 kcal"
    }
    base_calories = {"rest": 2800, "school": 3000, "gym_cycling": 3200}
    day_keys = list(day_map.keys())

    selected_day_label = st.selectbox("Today's Activity", list(day_map.values()),
                                      index=day_keys.index(st.session_state['day_type']))
    selected_day_key = day_keys[list(day_map.values()).index(selected_day_label)]
    if selected_day_key != st.session_state['day_type']:
        st.session_state['day_type'] = selected_day_key
        st.query_params.day_type = selected_day_key
        st.session_state['nutrition_phase_start'] = datetime.now().date()
        st.rerun()

    offset = st.session_state['calorie_offset']
    daily_cal = base_calories[selected_day_key] + offset

    if len(df) > 0:
        current_weight = df.iloc[-1]['Weight (kg)']
    else:
        current_weight = 70.0

    prot_factor = {"Aggressive Cut": 2.5, "Lean Cut": 2.3, "Recomposition": 2.0,
                   "Lean Bulk": 1.8, "Aggressive Bulk": 1.6}.get(active_goal, 2.0)
    rec_protein = int(current_weight * prot_factor)

    st.markdown(f"""
    <div class="s-head" style="margin-top:0;">Daily Targets</div>
    <div style="display:flex; gap:20px; margin-bottom:1.5rem;">
        <div style="flex:1; background:var(--surface); border:1px solid var(--border); border-radius:16px; padding:1.2rem; text-align:center;">
            <div style="font-family:'DM Mono',monospace; font-size:0.65rem; color:var(--text-subtle); letter-spacing:2px;">CALORIES</div>
            <div style="font-size:2.5rem; font-weight:700; color:var(--text-main); font-family:'DM Mono',monospace;">{daily_cal}</div>
            <div style="font-size:0.7rem; color:var(--text-muted);">kcal/day (base {base_calories[selected_day_key]} + offset {offset:+d})</div>
        </div>
        <div style="flex:1; background:var(--surface); border:1px solid var(--border); border-radius:16px; padding:1.2rem; text-align:center;">
            <div style="font-family:'DM Mono',monospace; font-size:0.65rem; color:var(--text-subtle); letter-spacing:2px;">PROTEIN</div>
            <div style="font-size:2.5rem; font-weight:700; color:var(--text-main); font-family:'DM Mono',monospace;">{st.session_state['protein_custom']}</div>
            <div style="font-size:0.7rem; color:var(--text-muted);">g/day (custom · rec {rec_protein})</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    new_prot = st.number_input("Custom Protein Target (g)", min_value=50, max_value=300,
                               value=st.session_state['protein_custom'], step=5)
    if new_prot != st.session_state['protein_custom']:
        st.session_state['protein_custom'] = new_prot
        st.query_params.protein_custom = str(new_prot)
        st.rerun()

    if has_enough_weight_data and has_enough_comp_data:
        wt_trend = monthly_trends.get('Weight (kg)', 0)
        bf_trend = monthly_trends.get('Body Fat (%)', 0)
        msg, new_offset = get_context_adaptive_recommendation(active_goal, wt_trend, bf_trend, offset, daily_cal)

        st.markdown(f"<div class='alert-banner info'>{msg}</div>", unsafe_allow_html=True)
        if new_offset != offset and st.button("Accept Adjustment", use_container_width=True):
            st.session_state['calorie_offset'] = new_offset
            st.query_params.calorie_offset = str(new_offset)
            st.session_state['nutrition_phase_start'] = datetime.now().date()
            system_alert(f"Offset set to {new_offset:+d}")
            st.rerun()
    else:
        st.info("Need at least 3 body weight + 5 composition entries for adaptive feedback.")

# ══════════════════════════════════════════════════════════════
# WORKOUT TAB (TEMPLATE-BASED)
# ══════════════════════════════════════════════════════════════
elif app_view == "Workout":
    header_placeholder.empty()

    # Predefined templates
    UPPER1 = [
        ("DB Press (45°)", 20),
        ("Incline Chest Press Machine", 22.5),
        ("Assisted Pullup", -18),
        ("Single Hand Seated Row", 20),
        ("Side Delt Flys", 2.3),
        ("Cross-Body Cable Tricep Ext", 6.8)
    ]
    LOWER1 = [
        ("Barbell Squat", 70),
        ("Leg Press", 0),
        ("Leg Extensions", -39),
        ("Leg Curls", 52),
        ("Standing Calf Raises", 10),
        ("Abs Rope", 30)
    ]
    UPPER2 = [
        ("Lat Pulldown", 45),
        ("Shoulder Press Machine", 10),
        ("Upper Back Row", 10),
        ("Pec Deck Fly", None),
        ("Brachialis Rope Curl", 11.3),
        ("Overhead Tricep Ext", 9)
    ]
    LOWER2 = [
        ("RDLs", 40),
        ("Barbell Squat", 75),
        ("Seated or Lying Hamstring Curls", 59),
        ("45° Hyperextension", 10),
        ("Calf Raises", 35),
        ("Abs Rope", 45)
    ]
    templates = {
        "Upper 1": UPPER1,
        "Lower 1": LOWER1,
        "Upper 2": UPPER2,
        "Lower 2": LOWER2
    }

    workout_type = st.selectbox("Workout", list(templates.keys()))
    exercises = templates[workout_type]

    # Load workout history for weight prefill
    workout_df = load_workout_data(st.session_state['sheet_url'])
    if not workout_df.empty:
        last_date = workout_df['Date'].max().strftime('%d %b %Y')
    else:
        last_date = "never"

    st.markdown(f"**Last recorded workout:** {last_date}")
    st.markdown("---")

    with st.form("workout_form", clear_on_submit=False):
        log_data = []
        for ex_name, default_weight in exercises:
            st.markdown(f"**{ex_name}**")
            # Prefill weight from last history
            if not workout_df.empty:
                ex_hist = workout_df[workout_df['Exercise'] == ex_name]
                last_weight = ex_hist['Weight'].values[0] if not ex_hist.empty else default_weight
                if last_weight is None:
                    last_weight = 0.0
            else:
                last_weight = default_weight if default_weight else 0.0

            weight = st.number_input(f"{ex_name} Weight (kg)", value=float(last_weight),
                                     step=0.5, key=f"w_{ex_name}_{workout_type}")
            sets = st.number_input("Number of sets", min_value=1, max_value=6, value=2, key=f"sets_{ex_name}_{workout_type}")
            reps = []
            for s in range(sets):
                rep_val = st.number_input(f"Set {s+1} reps", min_value=0, value=8, key=f"rep_{ex_name}_{s}_{workout_type}")
                reps.append(rep_val)
            log_data.append((ex_name, weight, reps))
            st.markdown("---")
        
        workout_date = st.date_input("Workout Date", datetime.now().date())
        if st.form_submit_button("Log Workout"):
            for ex_name, weight, reps in log_data:
                for s, rep in enumerate(reps):
                    if rep > 0:
                        append_to_sheet(st.session_state['sheet_url'], 'Workout!A:F',
                                        [[workout_date.strftime('%Y-%m-%d'), workout_type, ex_name, weight, s+1, rep]])
            system_alert("Workout saved")
            st.rerun()

# ══════════════════════════════════════════════════════════════
# SETTINGS TAB (with Data sheet sync)
# ══════════════════════════════════════════════════════════════
elif app_view == "Settings":
    header_placeholder.empty()

    st.markdown('<div class="settings-lbl" style="margin-top:0;">Profile</div>', unsafe_allow_html=True)
    st.markdown(f"<div style='font-size:0.95rem; font-weight:600; color:var(--text-muted); margin-bottom: 1.5rem;'>👤 {KEY_TO_LABEL.get(st.session_state['current_user'], 'User')}</div>", unsafe_allow_html=True)

    with st.expander("Active Protocol Parameters"):
        w_t, w_min, w_max = ideal_rates['Weight (kg)']
        m_t, m_min = ideal_rates['Muscle Mass (kg)'][:2]
        bf_t, bf_min, bf_max = ideal_rates['Body Fat (%)']
        st.markdown(f"""
        <div style="font-size:0.75rem; color:var(--text-muted); line-height:1.8; font-family: 'DM Mono', monospace;">
        <b style="color:var(--text-main);">WEIGHT</b>  Target {w_t:+.2f} kg/mo · Range [{w_min:+.2f}, {w_max:+.2f}]<br>
        <b style="color:var(--text-main);">MUSCLE</b>  Target {m_t:+.2f} kg/mo · Min {m_min:+.2f}<br>
        <b style="color:var(--text-main);">FAT</b>     Target {bf_t:+.2f} %/mo · Range [{bf_min:+.2f}, {bf_max:+.2f}]<br>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('<div class="settings-lbl">Body Profile</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        new_height = st.number_input("Height (cm)", min_value=100, max_value=250, value=st.session_state['body_constants']['height'], step=1)
    with c2:
        new_gender = st.selectbox("Gender", ["male", "female"], index=0 if st.session_state['body_constants']['gender']=="male" else 1)
    with c3:
        new_age = st.number_input("Age", min_value=10, max_value=100, value=st.session_state['body_constants']['age'], step=1)

    if st.button("Save Body Profile", use_container_width=True):
        st.session_state['body_constants'] = {'height': new_height, 'gender': new_gender, 'age': new_age}
        write_data_constants(st.session_state['sheet_url'], new_height, new_gender, new_age)
        st.query_params.height = str(new_height)
        st.query_params.gender = new_gender
        st.query_params.age = str(new_age)
        system_alert("Profile updated")
        st.rerun()

    st.markdown('<div class="settings-lbl">Appearance</div>', unsafe_allow_html=True)
    new_theme = st.selectbox("Theme", ["System", "Dark", "Light"], index=["System", "Dark", "Light"].index(st.session_state['theme_pref']))
    if new_theme != st.session_state['theme_pref']:
        st.session_state['theme_pref'] = new_theme
        st.query_params.theme = new_theme
        st.rerun()

    st.markdown('<div class="settings-lbl">Features</div>', unsafe_allow_html=True)
    st.session_state['enable_quotes'] = st.toggle("Motivational Quotes", value=st.session_state.get('enable_quotes', True))
    st.session_state['enable_achievements'] = st.toggle("Achievements System", value=st.session_state.get('enable_achievements', True))

    if st.session_state.get('enable_quotes'):
        with st.expander("Manage Quotes"):
            for q in st.session_state['all_quotes']:
                st.markdown(f"<div style='font-size:0.75rem; color:var(--text-muted); margin-bottom:8px; padding:8px; background:var(--surface-active); border-radius:8px; line-height:1.5;'>{q}</div>", unsafe_allow_html=True)
            new_quote = st.text_input("New quote", placeholder="Enter quote...")
            if st.button("Add to Rotation"):
                if new_quote and new_quote not in st.session_state['all_quotes']:
                    st.session_state['all_quotes'].append(new_quote)
                    system_alert("Added")
                    st.rerun()

    st.markdown('<div class="settings-lbl">Analysis Range</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        new_analysis_start = st.date_input("Trend Start", value=st.session_state['analysis_start_date'])
    with c2:
        new_target_end = st.date_input("Target End", value=st.session_state['target_end_date'])
    if st.button("Save & Recalibrate", use_container_width=True):
        st.session_state['analysis_start_date'] = new_analysis_start
        st.session_state['target_end_date'] = new_target_end
        st.query_params.start = new_analysis_start.strftime('%Y-%m-%d')
        st.query_params.end = new_target_end.strftime('%Y-%m-%d')
        system_alert("Saved")
        st.rerun()

    if st.session_state.get('is_admin'):
        st.markdown('<div class="settings-lbl" style="color:var(--c-rose);">Admin</div>', unsafe_allow_html=True)
        if st.button("Switch Profile", use_container_width=True):
            st.markdown("<script>localStorage.removeItem('metrics_user');</script>", unsafe_allow_html=True)
            st.session_state['auth_status'] = False
            st.session_state['current_user'] = None
            st.session_state['sheet_url'] = ""
            if 'active_df' in st.session_state:
                del st.session_state['active_df']
            st.query_params.clear()
            st.cache_data.clear()
            st.rerun()
