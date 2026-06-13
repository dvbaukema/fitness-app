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
# HARDCODED PROTOCOL TARGETS & MULTIPLIERS
# ══════════════════════════════════════════════════════════════
DEFAULT_PROFILES = {
    "Aggressive Cut":  {'Weight (kg)': [-3.0, -4.0, -2.0], 'Muscle Mass (kg)': [-0.2, -0.5], 'Body Fat (%)': [-1.2, -1.8, -0.6]},
    "Lean Cut":        {'Weight (kg)': [-1.5, -2.0, -1.0], 'Muscle Mass (kg)': [0.0, -0.1],  'Body Fat (%)': [-0.6, -1.0, -0.3]},
    "Recomposition":   {'Weight (kg)': [0.0, -0.5, 0.5],   'Muscle Mass (kg)': [0.3, 0.1],   'Body Fat (%)': [-0.4, -0.8, -0.1]},
    "Lean Bulk":       {'Weight (kg)': [1.0, 0.5, 1.5],    'Muscle Mass (kg)': [0.6, 0.3],   'Body Fat (%)': [0.1, -0.1, 0.4]},
    "Aggressive Bulk": {'Weight (kg)': [2.5, 2.0, 3.5],    'Muscle Mass (kg)': [0.8, 0.5],   'Body Fat (%)': [0.6, 0.3, 1.0]},
}

ACTIVITY_MULTIPLIERS = {
    "Sedentary (Office job)": 1.2, 
    "Light (1-3 days/wk)": 1.375, 
    "Moderate (3-5 days/wk)": 1.55, 
    "Active (6-7 days/wk)": 1.725, 
    "Athlete (2x/day)": 1.9
}

# ══════════════════════════════════════════════════════════════
# AUTO‑LOGIN & PERMANENT STORAGE ENGINE (localStorage)
# ══════════════════════════════════════════════════════════════
st.markdown("""
<script>
(function() {
    const urlParams = new URLSearchParams(window.location.search);
    let redirect = false;
    
    const savedUser = localStorage.getItem('metrics_user');
    if (savedUser && !urlParams.has('user')) { urlParams.set('user', savedUser); redirect = true; } 
    else if (urlParams.has('user')) { localStorage.setItem('metrics_user', urlParams.get('user')); }
    
    const savedGoal = localStorage.getItem('metrics_goal');
    if (savedGoal && !urlParams.has('goal')) { urlParams.set('goal', savedGoal); redirect = true; } 
    else if (urlParams.has('goal')) { localStorage.setItem('metrics_goal', urlParams.get('goal')); }
    
    const savedStart = localStorage.getItem('metrics_start');
    if (savedStart && !urlParams.has('start')) { urlParams.set('start', savedStart); redirect = true; } 
    else if (urlParams.has('start')) { localStorage.setItem('metrics_start', urlParams.get('start')); }

    const savedEnd = localStorage.getItem('metrics_end');
    if (savedEnd && !urlParams.has('end')) { urlParams.set('end', savedEnd); redirect = true; } 
    else if (urlParams.has('end')) { localStorage.setItem('metrics_end', urlParams.get('end')); }

    const savedTheme = localStorage.getItem('metrics_theme');
    if (savedTheme && !urlParams.has('theme')) { urlParams.set('theme', savedTheme); redirect = true; } 
    else if (urlParams.has('theme')) { localStorage.setItem('metrics_theme', urlParams.get('theme')); }

    const savedActivity = localStorage.getItem('metrics_activity');
    if (savedActivity && !urlParams.has('activity')) { urlParams.set('activity', savedActivity); redirect = true; } 
    else if (urlParams.has('activity')) { localStorage.setItem('metrics_activity', urlParams.get('activity')); }

    const savedProt = localStorage.getItem('metrics_protein_custom');
    if (savedProt && !urlParams.has('protein_custom')) { urlParams.set('protein_custom', savedProt); redirect = true; } 
    else if (urlParams.has('protein_custom')) { localStorage.setItem('metrics_protein_custom', urlParams.get('protein_custom')); }

    const savedOffset = localStorage.getItem('metrics_calorie_offset');
    if (savedOffset && !urlParams.has('calorie_offset')) { urlParams.set('calorie_offset', savedOffset); redirect = true; } 
    else if (urlParams.has('calorie_offset')) { localStorage.setItem('metrics_calorie_offset', urlParams.get('calorie_offset')); }

    if (redirect) {
        const newUrl = window.location.origin + window.location.pathname + '?' + urlParams.toString();
        window.location.replace(newUrl);
    }
})();
</script>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# GOOGLE SHEETS API SETUP
# ══════════════════════════════════════════════════════════════
@st.cache_resource
def get_google_sheets_service():
    try:
        credentials_dict = dict(st.secrets["gcp_service_account"])
        creds = service_account.Credentials.from_service_account_info(credentials_dict, scopes=['https://www.googleapis.com/auth/spreadsheets'])
        return build('sheets', 'v4', credentials=creds)
    except Exception:
        return None

def extract_sheet_id(url):
    if not url: return None
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
    if match: return match.group(1)
    if re.match(r'^[a-zA-Z0-9-_]{20,}$', url): return url
    return None

def read_sheet_range(sheet_url, range_name):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id: return pd.DataFrame()
    try:
        res = service.spreadsheets().values().get(spreadsheetId=sheet_id, range=range_name).execute()
        vals = res.get('values', [])
        if len(vals) < 2: return pd.DataFrame()
        headers = vals[0]
        data = vals[1:]
        return pd.DataFrame(data, columns=headers)
    except HttpError:
        return pd.DataFrame()

def load_body_constants(sheet_url):
    df = read_sheet_range(sheet_url, 'Body!A:C')
    if df.empty:
        return {'height': 180.0, 'gender': 'male', 'age': 25}
    try:
        row = df.iloc[0]
        # Strict order: Height, Gender, Age
        h = float(row.iloc[0]) if len(row) > 0 else 180.0
        g = str(row.iloc[1]).lower().strip() if len(row) > 1 else 'male'
        a = int(float(row.iloc[2])) if len(row) > 2 else 25
        return {'height': h, 'gender': g, 'age': a}
    except:
        return {'height': 180.0, 'gender': 'male', 'age': 25}

def read_gsheet(sheet_url):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id: return pd.DataFrame(columns=['Date', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)'])
    try:
        result = service.spreadsheets().values().get(spreadsheetId=sheet_id, range='A:E').execute()
        values = result.get('values', [])
        if not values or len(values) < 2: return pd.DataFrame(columns=['Date', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)'])
        headers = values[0]
        data = values[1:]
        df = pd.DataFrame(data, columns=headers)
        if 'Time' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Time'].astype(str), format='mixed', errors='coerce')
        else:
            df['Date'] = pd.to_datetime(df['Date'], format='mixed', errors='coerce')
        for m in ['Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']:
            df[m] = pd.to_numeric(df[m], errors='coerce') if m in df.columns else np.nan
        return df[['Date', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']].sort_values('Date').dropna().reset_index(drop=True)
    except HttpError:
        return pd.DataFrame(columns=['Date', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)'])

def append_to_gsheet(sheet_url, date_str, weight, muscle_mass, body_fat):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id: return False
    try:
        time_now = datetime.utcnow() + timedelta(hours=2)
        time_str = time_now.strftime('%H:%M:%S')
        values = [[date_str, time_str, weight, body_fat, muscle_mass]]
        body = {'values': values}
        service.spreadsheets().values().append(spreadsheetId=sheet_id, range='A:E', valueInputOption='USER_ENTERED', insertDataOption='INSERT_ROWS', body=body).execute()
        return True
    except HttpError:
        return False

def overwrite_gsheet(sheet_url, df):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id: return False
    try:
        service.spreadsheets().values().clear(spreadsheetId=sheet_id, range='A:Z').execute()
        values = [['Date', 'Time', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']]
        for _, row in df.iterrows():
            d = pd.Timestamp(row['Date'])
            values.append([d.strftime('%Y-%m-%d'), d.strftime('%H:%M:%S'), float(row['Weight (kg)']), float(row['Body Fat (%)']), float(row['Muscle Mass (kg)'])])
        body = {'values': values}
        service.spreadsheets().values().update(spreadsheetId=sheet_id, range='A:E', valueInputOption='USER_ENTERED', body=body).execute()
        return True
    except HttpError:
        return False

# ══════════════════════════════════════════════════════════════
# LOAD SECRETS & DIRECTORY
# ══════════════════════════════════════════════════════════════
dan_url = st.secrets.get("daniel_gsheets_url", "")
bram_url = st.secrets.get("bram_gsheets_url", "")
jurien_url = st.secrets.get("jurien_gsheets_url", "")

dan_key = st.secrets.get("daniel_user_key", "Daniel")
bram_key = st.secrets.get("bram_user_key", "Bram")
jurien_key = st.secrets.get("jurien_user_key", "Jurien")
admin_key = st.secrets.get("admin_user_key", "Admin")

USER_DATA = {dan_key: dan_url, bram_key: bram_url, jurien_key: jurien_url}
KEY_TO_LABEL = {dan_key: "Daniel", bram_key: "Bram", jurien_key: "Jurien"}
def get_display_name(user_key): return KEY_TO_LABEL.get(user_key, "Unknown User")

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
# INITIALIZE SESSION STATE & QUERY PARAMS
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

if 'activity_level' not in st.session_state: st.session_state['activity_level'] = st.query_params.get("activity", "Moderate (3-5 days/wk)")
if 'calorie_offset' not in st.session_state: st.session_state['calorie_offset'] = int(st.query_params.get("calorie_offset", 0))
if 'protein_custom' not in st.session_state: st.session_state['protein_custom'] = int(st.query_params.get("protein_custom", 160))

if 'analysis_start_date' not in st.session_state:
    default_start = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    st.session_state['analysis_start_date'] = pd.to_datetime(st.query_params.get("start", default_start)).date()
if 'target_end_date' not in st.session_state:
    default_end = '2026-09-01'
    st.session_state['target_end_date'] = pd.to_datetime(st.query_params.get("end", default_end)).date()

if st.session_state['auth_status'] and 'body_constants' not in st.session_state:
    st.session_state['body_constants'] = load_body_constants(st.session_state['sheet_url'])

# ══════════════════════════════════════════════════════════════
# CSS — COMPLETE DESIGN OVERHAUL
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

/* ══════════════════════════════
   APP BAR
══════════════════════════════ */
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

/* ══════════════════════════════
   NAVIGATION — FLOATING RADIO HACK
══════════════════════════════ */
div[role="radiogroup"] {
    display: flex;
    flex-wrap: wrap;
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

/* Hide regular segmented controls if they render */
div[data-testid="stSegmentedControl"] { display: none !important; }

/* ══════════════════════════════
   SECTION HEADERS
══════════════════════════════ */
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

/* ══════════════════════════════
   QUOTE BOX
══════════════════════════════ */
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

/* ══════════════════════════════
   METRIC CARDS GRID
══════════════════════════════ */
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

/* ══════════════════════════════
   COLOR UTILITIES
══════════════════════════════ */
.c-ok  { color: var(--c-emerald) !important; }
.c-wrn { color: var(--c-amber) !important; }
.c-err { color: var(--c-rose) !important; }
.c-neu { color: var(--text-muted) !important; }
.c-blue { color: var(--c-blue) !important; }

/* ══════════════════════════════
   CHART BLOCKS
══════════════════════════════ */
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

/* ══════════════════════════════
   HUD DIAGNOSTIC CARDS
══════════════════════════════ */
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

/* ══════════════════════════════
   TRAJECTORY BARS
══════════════════════════════ */
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

/* ══════════════════════════════
   ACHIEVEMENTS / TIERS
══════════════════════════════ */
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

/* ══════════════════════════════
   HISTORY ROWS
══════════════════════════════ */
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

/* ══════════════════════════════
   ALERT BANNERS
══════════════════════════════ */
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

/* ══════════════════════════════
   SLIDERS
══════════════════════════════ */
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

/* ══════════════════════════════
   INPUTS & SELECTS
══════════════════════════════ */
div[data-testid="stSelectbox"] { margin-bottom: 0 !important; }
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
div[data-testid="stSelectbox"] [class*="placeholder"] {
  color: var(--text-muted) !important;
}
div[data-testid="stSelectbox"] [class*="menu"] {
  background: var(--surface) !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: 12px !important;
}
div[data-testid="stSelectbox"] [class*="option"] {
  color: var(--input-text) !important;
  background: transparent !important;
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

/* ══════════════════════════════
   BUTTONS
══════════════════════════════ */
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

/* Toggle */
div[data-testid="stToggle"] label p {
  color: var(--text-main) !important;
  font-size: 0.85rem !important;
}

/* Expander Force Light Mode Visibility */
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

/* Spinner steppers hidden */
button[aria-label="Step down"], button[aria-label="Step up"],
button[title="Step down"], button[title="Step up"] {
  display: none !important;
}

/* Streamlit error/info messages */
div[data-testid="stAlert"] {
  border-radius: 12px !important;
}

/* Protocol selector center label */
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

/* Scrollbar */
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
        display_name = get_display_name(user_key)
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
# DATA LOADING & STATISTICAL ENGINE
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=60, show_spinner=False)
def load_data(url): 
    return load_body_data(url)

try:
    df = load_data(st.session_state['sheet_url'])
    st.session_state['active_df'] = df
except Exception as e:
    st.error(f"System Error: Could not load data. {str(e)}")
    st.stop()

df = st.session_state['active_df']

if st.session_state['auth_status'] and 'body_constants' not in st.session_state:
    st.session_state['body_constants'] = load_body_constants(st.session_state['sheet_url'])

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
# MAIN ROUTING ENGINE
# ══════════════════════════════════════════════════════════════
active_goal = st.session_state.get('current_goal', 'Lean Bulk')
ideal_rates = st.session_state['goal_profiles'].get(active_goal, st.session_state['goal_profiles']['Lean Bulk'])

header_placeholder = st.empty()

# ── STREAMLIT RADIO HACK FOR FLOATING TABS ──
app_view = st.radio("Nav", ["Entry", "Nutrition", "Trends", "Analysis", "Data", "Settings"], horizontal=True, label_visibility="collapsed")

header_placeholder.markdown(f"""
<div class="app-bar">
    <div>
        <div class="wordmark">Metrics</div>
        <div class="tagline">{get_display_name(st.session_state['current_user'])} · Alpha 1</div>
    </div>
    <div class="live-pill"><div class="live-dot"></div>SYNCED</div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# ENTRY TAB
# ══════════════════════════════════════════════════════════════
if app_view == "Entry":
    if st.session_state['enable_quotes']:
        if 'daily_quote' not in st.session_state:
            st.session_state['daily_quote'] = random.choice(st.session_state['all_quotes'])
        st.markdown(f"<div class='quote-box'><div class='quote-text'>\"{st.session_state['daily_quote']}\"</div></div>", unsafe_allow_html=True)

    selected = st.selectbox("Protocol", list(st.session_state['goal_profiles'].keys()), index=list(st.session_state['goal_profiles'].keys()).index(active_goal))
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
# NUTRITION TAB
# ══════════════════════════════════════════════════════════════
elif app_view == "Nutrition":
    st.markdown('<div class="s-head" style="margin-top:0;">Targets & Coaching</div>', unsafe_allow_html=True)
    
    w_curr = df.iloc[-1]['Weight (kg)'] if len(df) > 0 else 75.0
    bc = st.session_state.get('body_constants', {'height': 180.0, 'gender': 'male', 'age': 25})
    h_curr = float(bc['height'])
    g_curr = str(bc['gender']).lower()
    a_curr = int(bc['age'])
    
    act_lvl = st.session_state['activity_level']
    cal_offset = int(st.session_state['calorie_offset'])
    custom_prot = int(st.session_state['protein_custom'])
    
    # Mifflin-St Jeor
    if g_curr == "male": 
        bmr = (10 * w_curr) + (6.25 * h_curr) - (5 * a_curr) + 5
    else: 
        bmr = (10 * w_curr) + (6.25 * h_curr) - (5 * a_curr) - 161
        
    tdee = bmr * ACTIVITY_MULTIPLIERS.get(act_lvl, 1.55)
    
    if "Aggressive Cut" in active_goal: cal_adj, pro_min, pro_max = -750, 2.0, 2.4
    elif "Lean Cut" in active_goal: cal_adj, pro_min, pro_max = -400, 2.0, 2.3
    elif "Recomposition" in active_goal: cal_adj, pro_min, pro_max = -100, 1.8, 2.1
    elif "Lean Bulk" in active_goal: cal_adj, pro_min, pro_max = +300, 1.8, 2.2
    else: cal_adj, pro_min, pro_max = +500, 1.6, 1.9
    
    calc_cals = int(tdee + cal_adj)
    target_cals = calc_cals + cal_offset
    
    st.markdown(f"""
    <div class="mini-grid">
        <div class="mini-cell" style="grid-column: span 3; text-align:center;">
            <span class="mini-lbl">Daily Caloric Target</span>
            <span class="mini-val">{target_cals}<span class="mini-unit">kcal</span></span>
            <div class="mini-sub c-neu">Baseline Estimate: {calc_cals} kcal</div>
        </div>
        <div class="mini-cell" style="grid-column: span 3; text-align:center;">
            <span class="mini-lbl">Daily Protein Target</span>
            <span class="mini-val">{custom_prot}<span class="mini-unit">g</span></span>
            <div class="mini-sub c-neu">Protocol Range: {int(w_curr * pro_min)}g – {int(w_curr * pro_max)}g</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="s-head">Adaptive Engine</div>', unsafe_allow_html=True)
    
    wt_trend = monthly_trends.get('Weight (kg)', 0)
    w_t, w_min, w_max = ideal_rates['Weight (kg)']
    
    if len(df_window_full) < 5:
        st.markdown(hud_card("c-neu", "⏳", "Calibrating", "Need more data since the Start Date to provide adaptive calorie adjustments."), unsafe_allow_html=True)
    else:
        if wt_trend > w_max:
            st.markdown(hud_card("c-err", "↓", "Pace Too Fast", f"Gaining {wt_trend:.2f} kg/mo (Limit: {w_max} kg). Recommend lowering intake by 200 kcal."), unsafe_allow_html=True)
            if st.button("Accept & Lower Calories by 200", use_container_width=True):
                st.session_state['calorie_offset'] -= 200
                st.session_state['analysis_start_date'] = datetime.now().date()
                st.query_params.calorie_offset = st.session_state['calorie_offset']
                st.query_params.start = datetime.now().strftime('%Y-%m-%d')
                system_alert("Phase Reset")
                st.rerun()
        elif wt_trend < w_min:
            st.markdown(hud_card("c-wrn", "↑", "Pace Too Slow", f"Tracking at {wt_trend:.2f} kg/mo (Minimum: {w_min} kg). Recommend increasing intake by 200 kcal."), unsafe_allow_html=True)
            if st.button("Accept & Increase Calories by 200", use_container_width=True):
                st.session_state['calorie_offset'] += 200
                st.session_state['analysis_start_date'] = datetime.now().date()
                st.query_params.calorie_offset = st.session_state['calorie_offset']
                st.query_params.start = datetime.now().strftime('%Y-%m-%d')
                system_alert("Phase Reset")
                st.rerun()
        else:
            st.markdown(hud_card("c-ok", "✓", "Pace Locked In", f"Weight trend ({wt_trend:.2f} kg/mo) is exactly within protocol bounds. Maintain current intake."), unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# TRENDS TAB
# ══════════════════════════════════════════════════════════════
elif app_view == "Trends":
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
        
        if 'preds' in traj_data.get(metric, {}):
            final_pred = traj_data[metric]['preds'][-10] 
            final_error = traj_data[metric]['final_error']
            lower_proj = final_pred - final_error
            upper_proj = final_pred + final_error
            proj_html = f"<div style='font-family:\"DM Mono\", monospace; font-size:0.65rem; color:var(--text-subtle); margin-top:5px; letter-spacing:0.3px;'>{end_label} PROJ: <span style='color:var(--text-main); font-weight:600;'>{lower_proj:.1f} – {upper_proj:.1f} {unit}</span></div>"
        else:
            proj_html = ""
        
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
            mode='lines+markers', name='Active Data',
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
# ANALYSIS TAB
# ══════════════════════════════════════════════════════════════
elif app_view == "Analysis":
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
    <div class="s-head" style="margin-top:0;">Performance Data</div>
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
    <div class="s-head">Trajectory Logic</div>
    """, unsafe_allow_html=True)

    st.markdown(traj_bar("BODY WEIGHT", wt, 'Weight (kg)', ideal_rates, "kg/mo", mmt, bft), unsafe_allow_html=True)
    if has_enough_comp_data:
        st.markdown(
            traj_bar("MUSCLE MASS", mmt, 'Muscle Mass (kg)', ideal_rates, "kg/mo", mmt, bft) +
            traj_bar("BODY FAT", bft, 'Body Fat (%)', ideal_rates, "%/mo", mmt, bft),
            unsafe_allow_html=True
        )

    st.markdown('<div class="s-head">System Diagnostics</div>', unsafe_allow_html=True)
    w_tgt, w_lower, w_upper = ideal_rates['Weight (kg)']
    diags = []
    
    is_muscle_driven = (wt > w_upper) and has_enough_comp_data and (mmt >= (wt * 0.4)) and (bft <= 0.2)
    bf_lower = ideal_rates['Body Fat (%)'][1] if len(ideal_rates['Body Fat (%)']) > 1 else -99
    is_fat_loss_driven = (wt < w_lower) and has_enough_comp_data and (mmt >= -0.2) and (bft < bf_lower)

    if is_muscle_driven:
        diags.append(hud_card("c-ok", "🧬", "Hyper-Anabolic Response", f"Weight is increasing rapidly (+{wt:.2f} kg/mo), but it is heavily driven by muscle gain (+{mmt:.2f} kg/mo). Do not cut calories. Ride this muscle memory wave."))
    elif is_fat_loss_driven:
        diags.append(hud_card("c-ok", "🔥", "Hyper-Lipolytic Response", f"Weight is dropping fast ({wt:.2f} kg/mo), but muscle is preserved and fat is melting (-{abs(bft):.2f} %/mo). Excellent recomposition."))
    elif wt > w_upper:
        diags.append(hud_card("c-err", "↓", "Over Upper Limit", f"Weight accumulation ({wt:.2f} kg/mo) exceeds limits. Reduce caloric intake by 200-300 kcal."))
    elif wt < w_lower:
        if w_lower < 0:
            diags.append(hud_card("c-err", "⚠", "Catabolic Danger", f"Losing weight too rapidly ({wt:.2f} kg/mo). Increase caloric intake immediately."))
        else:
            diags.append(hud_card("c-wrn", "↑", "Anabolic Stall", f"Weight accumulation lagging below {w_lower} kg/mo. Increase daily caloric intake by 200-300 kcal."))
    
    if has_enough_comp_data and not is_muscle_driven and not is_fat_loss_driven:
        m_tgt, m_lower = ideal_rates['Muscle Mass (kg)'][:2]
        bf_tgt, bf_lower_v, bf_upper = ideal_rates['Body Fat (%)']
        if wt >= w_lower and mmt < m_lower:
            diags.append(hud_card("c-wrn", "⚠", "Low Muscle Synthesis", f"Weight tracking properly, but muscle accumulation lagging ({mmt:.2f} kg/mo). Ensure high protein intake (1.6-2.2g/kg)."))
        if bft > bf_upper:
            diags.append(hud_card("c-err", "⚠", "Excessive Fat Gain", f"Body fat accumulation ({bft:.2f} %/mo) exceeds limits. Dial back carbs/fats slightly."))
            
    if not diags:
        diags.append(hud_card("c-ok", "✓", "Locked In", "All tracked parameters are within optimal bounds. Stay the course."))
    
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
            engine_html += f"<div class='tier-item completed'><div class='tier-emoji'>{t['emoji']}</div><div class='tier-details'><div class='tier-name'>{t['name']}</div><div class='tier-req'>UNLOCKED: {t['days']} DAYS</div></div><div style='color:var(--c-blue); font-weight:800; font-size:1.1rem;'>✓</div></div>\n"
        t_curr = TIERS[current_tier_idx]
        if current_tier_idx < len(TIERS) - 1:
            t_next = TIERS[current_tier_idx + 1]
            progress = ((days_elapsed - t_curr['days']) / (t_next['days'] - t_curr['days'])) * 100
            engine_html += f"<div class='tier-item current'><div class='tier-emoji'>{t_curr['emoji']}</div><div class='tier-details'><div style='display:flex; justify-content:space-between; align-items:flex-end;'><div class='tier-name' style='color:var(--c-blue);'>{t_curr['name']}</div><div style='font-family:\"DM Mono\",monospace; font-size:0.58rem; color:var(--text-subtle); font-weight:500;'>{days_elapsed} / {t_next['days']} d</div></div><div class='prog-tk'><div class='prog-fill' style='width:{progress:.1f}%;'></div></div></div></div>\n"
        else:
            engine_html += f"<div class='tier-item current'><div class='tier-emoji'>{t_curr['emoji']}</div><div class='tier-details'><div class='tier-name' style='color:var(--c-blue);'>{t_curr['name']}</div><div class='tier-req'>MAXIMUM TIER REACHED</div></div></div>\n"
        end_idx = min(len(TIERS), current_tier_idx + 3)
        for i in range(current_tier_idx + 1, end_idx):
            t = TIERS[i]
            engine_html += f"<div class='tier-item locked'><div class='tier-emoji'>🔒</div><div class='tier-details'><div class='tier-name'>{t['name']}</div><div class='tier-req'>REQUIRES: {t['days']} DAYS</div></div></div>\n"
        engine_html += "</div>"
        st.markdown(engine_html, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# DATA TAB
# ══════════════════════════════════════════════════════════════
elif app_view == "Data":
    st.markdown('<div class="s-head" style="margin-top:0;">Record History</div>', unsafe_allow_html=True)
    
    seven_days_ago = pd.Timestamp(datetime.now() - timedelta(days=7))
    
    st.markdown("""
    <div style='display: grid; grid-template-columns: 2.2fr 1.2fr 1.2fr 1.2fr; gap: 8px; padding: 0 16px; margin-bottom: 10px; font-family:"DM Mono", monospace; font-size:0.6rem; color:var(--text-subtle); text-transform:uppercase; letter-spacing: 1.5px; font-weight: 600;'>
        <div>Date</div>
        <div style='text-align:right;'>Weight</div>
        <div style='text-align:right;'>Muscle</div>
        <div style='text-align:right;'>Fat</div>
    </div>
    """, unsafe_allow_html=True)
    
    for i in range(len(df)-1, max(-1, len(df)-21), -1):
        row = df.iloc[i]
        
        if i > 0:
            prev_row = df.iloc[i-1]
            delta_w = row['Weight (kg)'] - prev_row['Weight (kg)']
            delta_m = row['Muscle Mass (kg)'] - prev_row['Muscle Mass (kg)']
            delta_bf = row['Body Fat (%)'] - prev_row['Body Fat (%)']
            
            dw_color = "var(--c-emerald)" if ("Cut" in active_goal and delta_w <= 0) or ("Bulk" in active_goal and delta_w >= 0) else "var(--c-rose)"
            dm_color = "var(--c-emerald)" if delta_m >= 0 else "var(--c-rose)"
            dbf_color = "var(--c-emerald)" if delta_bf <= 0 else "var(--c-rose)"
            
            delta_html_w = f"<div style='color:{dw_color}; font-size:0.58rem; margin-top:2px;'>{sgn(delta_w)}{delta_w:.1f}</div>"
            delta_html_m = f"<div style='color:{dm_color}; font-size:0.58rem; margin-top:2px;'>{sgn(delta_m)}{delta_m:.1f}</div>"
            delta_html_bf = f"<div style='color:{dbf_color}; font-size:0.58rem; margin-top:2px;'>{sgn(delta_bf)}{delta_bf:.1f}</div>"
        else:
            delta_html_w, delta_html_m, delta_html_bf = "", "", ""

        can_delete = pd.Timestamp(row['Date']) >= seven_days_ago
        c1, c2 = st.columns([5.5, 0.8])
        with c1:
            st.markdown(f"""
            <div class="hist-row" style="padding-right:0;">
                <div style="display: grid; grid-template-columns: 2.2fr 1.2fr 1.2fr 1.2fr; gap: 8px; align-items: center; width: 100%;">
                    <div class="hist-date">{row['Date'].strftime('%d %b %Y')}</div>
                    <div class="hist-vals" style="text-align:right;">{row['Weight (kg)']:.1f}{delta_html_w}</div>
                    <div class="hist-vals" style="text-align:right;">{row['Muscle Mass (kg)']:.1f}{delta_html_m}</div>
                    <div class="hist-vals" style="text-align:right;">{row['Body Fat (%)']:.1f}%{delta_html_bf}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        with c2:
            if can_delete:
                st.markdown("<div class='del-btn' style='height:100%; display:flex; align-items:center; justify-content:center; padding-top:14px;'>", unsafe_allow_html=True)
                if st.button("Del", key=f"del_{i}"):
                    new_df = df.drop(index=i).reset_index(drop=True)
                    overwrite_body_sheet(st.session_state['sheet_url'], new_df)
                    st.session_state['active_df'] = new_df
                    load_data.clear()
                    system_alert("Deleted", "err")
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# SETTINGS TAB
# ══════════════════════════════════════════════════════════════
elif app_view == "Settings":
    header_placeholder.empty()

    st.markdown('<div class="settings-lbl" style="margin-top:0;">Profile</div>', unsafe_allow_html=True)
    st.markdown(f"<div style='font-size:0.95rem; font-weight:600; color:var(--text-muted); margin-bottom: 1.5rem;'>👤 {get_display_name(st.session_state['current_user'])}</div>", unsafe_allow_html=True)
    
    st.markdown('<div class="settings-lbl" style="margin-top:0;">Physiology (Read-Only)</div>', unsafe_allow_html=True)
    bc = st.session_state.get('body_constants', {'height': 180, 'gender': 'male', 'age': 25})
    
    st.markdown(f"""
    <div style="background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:12px; display:flex; justify-content:space-between; margin-bottom:1.5rem; font-family:'DM Mono', monospace; font-size:0.8rem;">
        <div><b style="color:var(--text-main);">Height:</b> <span style="color:var(--text-muted);">{bc['height']} cm</span></div>
        <div><b style="color:var(--text-main);">Age:</b> <span style="color:var(--text-muted);">{bc['age']} yrs</span></div>
        <div><b style="color:var(--text-main);">Gender:</b> <span style="color:var(--text-muted);">{bc['gender'].capitalize()}</span></div>
    </div>
    <div style="font-size:0.6rem; color:var(--text-subtle); margin-top:-1rem; margin-bottom:1.5rem;"><i>* Edit these values directly in the 'Body' tab of your Google Sheet.</i></div>
    """, unsafe_allow_html=True)

    with st.expander("Active Protocol Parameters"):
        w_t, w_min, w_max = ideal_rates['Weight (kg)']
        m_t, m_min = ideal_rates['Muscle Mass (kg)'][:2]
        bf_t, bf_min, bf_max = ideal_rates['Body Fat (%)']
        
        st.markdown(f"""
        <div style="font-size:0.75rem; color:var(--text-muted); line-height:1.8; font-family: 'DM Mono', monospace;">
        <b style="color:var(--text-main);">WEIGHT</b>  Target {w_t:+.2f} kg/mo · Range [{w_min:+.2f}, {w_max:+.2f}]<br>
        <b style="color:var(--text-main);">MUSCLE</b>  Target {m_t:+.2f} kg/mo · Min {m_min:+.2f}<br>
        <b style="color:var(--text-main);">FAT</b>     Target {bf_t:+.2f} %/mo · Range [{bf_min:+.2f}, {bf_max:+.2f}]<br>
        <br><span style="font-family:'Inter', sans-serif;"><i>Note: Base parameters are hardcoded in the Python core. Change protocol using the main dropdown.</i></span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('<div class="settings-lbl" style="margin-top:0;">Nutrition Config</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1: 
        n_act = st.selectbox("Activity Level", list(ACTIVITY_MULTIPLIERS.keys()), index=list(ACTIVITY_MULTIPLIERS.keys()).index(st.session_state.get('activity_level', 'Moderate (3-5 days/wk)')))
    with c2: 
        n_prot = st.number_input("Target Protein (g)", value=st.session_state.get('protein_custom', 160))
        
    if st.button("Save Nutrition Settings", use_container_width=True):
        st.session_state['activity_level'] = n_act
        st.session_state['protein_custom'] = n_prot
        st.query_params.activity = n_act
        st.query_params.protein_custom = n_prot
        system_alert("Saved")
        st.rerun()

    st.markdown('<div class="settings-lbl">Analysis Range</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1: new_start = st.date_input("Trend Start", value=st.session_state['analysis_start_date'])
    with c2: new_end = st.date_input("Target End", value=st.session_state['target_end_date'])
    if st.button("Save Dates", use_container_width=True):
        st.session_state['analysis_start_date'] = new_start
        st.session_state['target_end_date'] = new_end
        st.query_params.start = new_start.strftime('%Y-%m-%d')
        st.query_params.end = new_end.strftime('%Y-%m-%d')
        system_alert("Dates Saved")
        st.rerun()

    st.markdown('<div class="settings-lbl">System Preferences</div>', unsafe_allow_html=True)
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
