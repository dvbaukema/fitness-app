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
# PAGE CONFIG & WORKOUT DATABASE
# ══════════════════════════════════════════════════════════════
st.set_page_config(page_title="METRICS | Beta 2", layout="centered", initial_sidebar_state="collapsed")

ROUTINES = {
    "Upper Body 1 (Chest & Horiz)": [
        "DB Press (45°) [2x8-10]", "Incline Chest Press machine [2x8-10]", "Assisted Pullup [2x10-12]", 
        "Single Hand Seated Row [2x8-10]", "Side Delt Flys [2xFail]", "Cross-Body Cable Tricep Ext [2x12-15]"
    ],
    "Lower Body 1 (Quad-Dominant)": [
        "Barbell Squat [2x3-5]", "Leg Press/Hack Squat [2x8-10]", "Leg Extensions [2xFail]", 
        "Leg Curls [2x10-12]", "Standing Calf Raises [2x12-20]", "Abs Rope [2xFail]"
    ],
    "Upper Body 2 (Back & Vert)": [
        "Lat Pulldown [2x10-12]", "Shoulder Press Machine [2x8-10]", "Upper Back Row [2x12-15]", 
        "Pec Deck Fly / Cable Cross [2x10-15]", "Brachialis Rope Curl [2x12-15]", "Overhead Tricep Ext [2x12-15]"
    ],
    "Lower Body 2 (Posterior)": [
        "RDLs [2x10-12]", "Barbell Squat [2x3-5]", "Seated/Lying Hamstring Curls [2x10-12]", 
        "45 Degree Hyperextension [2x10-12]", "Calf Raises [2x12-20]", "Abs Rope [2xFail]"
    ]
}

def system_alert(message, kind="ok"):
    bg = "#10B981" if kind == "ok" else "#EF4444"
    ph = st.empty()
    html_str = f"<div style='position:fixed; top:30px; left:50%; transform:translateX(-50%); background:{bg}; color:#FFFFFF; padding:14px 36px; border-radius:100px; font-weight:800; font-family:\"DM Sans\", sans-serif; z-index:99999; box-shadow: 0 8px 32px rgba(0,0,0,0.25); text-transform:uppercase; letter-spacing:2px; font-size: 0.78rem;'>{message}</div>"
    ph.markdown(html_str, unsafe_allow_html=True)
    time.sleep(1.2)
    ph.empty()

# ══════════════════════════════════════════════════════════════
# HARDCODED PROTOCOL TARGETS
# ══════════════════════════════════════════════════════════════
DEFAULT_PROFILES = {
    "Aggressive Cut":  {'Weight (kg)': [-3.0, -4.0, -2.0], 'Muscle Mass (kg)': [-0.2, -0.5], 'Body Fat (%)': [-1.2, -1.8, -0.6]},
    "Lean Cut":        {'Weight (kg)': [-1.5, -2.0, -1.0], 'Muscle Mass (kg)': [0.0, -0.1],  'Body Fat (%)': [-0.6, -1.0, -0.3]},
    "Recomposition":   {'Weight (kg)': [0.0, -0.5, 0.5],   'Muscle Mass (kg)': [0.3, 0.1],   'Body Fat (%)': [-0.4, -0.8, -0.1]},
    "Lean Bulk":       {'Weight (kg)': [1.0, 0.5, 1.5],    'Muscle Mass (kg)': [0.6, 0.3],   'Body Fat (%)': [0.1, -0.1, 0.4]},
    "Aggressive Bulk": {'Weight (kg)': [2.5, 2.0, 3.5],    'Muscle Mass (kg)': [0.8, 0.5],   'Body Fat (%)': [0.6, 0.3, 1.0]},
}

ACTIVITY_MULTIPLIERS = {"Sedentary (Office job)": 1.2, "Light (1-3 days/wk)": 1.375, "Moderate (3-5 days/wk)": 1.55, "Active (6-7 days/wk)": 1.725, "Athlete (2x/day)": 1.9}

# ══════════════════════════════════════════════════════════════
# AUTO‑LOGIN & PERMANENT STORAGE ENGINE (localStorage)
# ══════════════════════════════════════════════════════════════
st.markdown("""
<script>
(function() {
    const urlParams = new URLSearchParams(window.location.search);
    let redirect = false;
    const keys = ['user', 'goal', 'start', 'end', 'theme', 'activity', 'protein_custom', 'calorie_offset'];
    keys.forEach(k => {
        const sk = 'metrics_' + k;
        const val = localStorage.getItem(sk);
        if (val && !urlParams.has(k)) { urlParams.set(k, val); redirect = true; }
        else if (urlParams.has(k)) { localStorage.setItem(sk, urlParams.get(k)); }
    });
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
    except Exception: return None

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
        return pd.DataFrame(vals[1:], columns=vals[0])
    except HttpError: return pd.DataFrame()

def append_to_sheet(sheet_url, range_name, values):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id: return False
    try:
        service.spreadsheets().values().append(
            spreadsheetId=sheet_id, range=range_name,
            valueInputOption='USER_ENTERED', insertDataOption='INSERT_ROWS', body={'values': values}
        ).execute()
        return True
    except HttpError: return False

def overwrite_sheet_range(sheet_url, range_name, df):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id: return False
    try:
        service.spreadsheets().values().clear(spreadsheetId=sheet_id, range=range_name).execute()
        values = [df.columns.tolist()] + df.values.tolist()
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id, range=range_name,
            valueInputOption='USER_ENTERED', body={'values': values}
        ).execute()
        return True
    except HttpError: return False

# ══════════════════════════════════════════════════════════════
# SHEET‑SPECIFIC DATA LOADERS
# ══════════════════════════════════════════════════════════════
def load_body_constants(sheet_url):
    df = read_sheet_range(sheet_url, 'Body!A:C')
    if df.empty: return {'height': 180.0, 'gender': 'male', 'age': 25}
    try:
        row = df.iloc[0]
        h = float(row.get('Height', 180))
        g = str(row.get('Gender', 'male')).lower().strip()
        a = int(float(row.get('Age', 25)))
        return {'height': h, 'gender': g, 'age': a}
    except: return {'height': 180.0, 'gender': 'male', 'age': 25}

def load_body_data(sheet_url):
    df = read_sheet_range(sheet_url, 'Data!A:E')
    if df.empty: return pd.DataFrame(columns=['Date', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)'])
    df['Date'] = pd.to_datetime(df['Date'] + ' ' + df['Time'] if 'Time' in df.columns else df['Date'], format='mixed', errors='coerce')
    for m in ['Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']: df[m] = pd.to_numeric(df[m], errors='coerce') if m in df.columns else np.nan
    return df[['Date', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']].sort_values('Date').dropna().reset_index(drop=True)

def append_body_entry(sheet_url, date_str, weight, muscle_mass, body_fat):
    time_str = (datetime.utcnow() + timedelta(hours=2)).strftime('%H:%M:%S')
    return append_to_sheet(sheet_url, 'Data!A:E', [[date_str, time_str, weight, body_fat, muscle_mass]])

def overwrite_body_sheet(sheet_url, df):
    values = [['Date', 'Time', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']]
    for _, row in df.iterrows():
        d = pd.Timestamp(row['Date'])
        values.append([d.strftime('%Y-%m-%d'), d.strftime('%H:%M:%S'), float(row['Weight (kg)']), float(row['Body Fat (%)']), float(row['Muscle Mass (kg)'])])
    return overwrite_sheet_range(sheet_url, 'Data!A:E', pd.DataFrame(values[1:], columns=values[0]))

def load_workout_data(sheet_url):
    df = read_sheet_range(sheet_url, 'Workouts!A:F')
    expected = ['Date','Workout Type','Exercise','Weight','Set','Reps']
    if df.empty: return pd.DataFrame(columns=expected)
    for c in expected:
        if c not in df.columns: df[c] = '' if c == 'Exercise' else np.nan
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df['Weight'] = pd.to_numeric(df['Weight'], errors='coerce')
    df['Set'] = pd.to_numeric(df['Set'], errors='coerce').fillna(1).astype(int)
    df['Reps'] = pd.to_numeric(df['Reps'], errors='coerce').fillna(0).astype(int)
    return df[expected].dropna(subset=['Date','Exercise']).reset_index(drop=True)

def append_workout_rows(sheet_url, rows):
    return append_to_sheet(sheet_url, 'Workouts!A:F', rows)

# ══════════════════════════════════════════════════════════════
# SECRETS DIRECTORY
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

DEFAULT_QUOTES = [
    "The man who loves walking will walk further than the man who loves the destination.",
    "Intensity > Volume.",
    "Discipline equals freedom. — Jocko Willink",
    "It's not about perfect. It's about effort.",
    "The iron never lies. — Henry Rollins",
    "We are what we repeatedly do. Excellence, then, is not an act, but a habit. — Aristotle",
    "There is no reason to be alive and not be strong. — Socrates",
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

qp = st.query_params
st.session_state['current_goal'] = qp.get("goal", "Lean Bulk")
st.session_state['theme_pref'] = qp.get("theme", "System")
st.session_state['activity_level'] = qp.get("activity", "Moderate (3-5 days/wk)")
st.session_state['calorie_offset'] = int(qp.get("calorie_offset", 0))
st.session_state['protein_custom'] = int(qp.get("protein_custom", 160))

if 'analysis_start_date' not in st.session_state:
    st.session_state['analysis_start_date'] = pd.to_datetime(qp.get("start", (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d'))).date()
if 'target_end_date' not in st.session_state:
    st.session_state['target_end_date'] = pd.to_datetime(qp.get("end", '2026-09-01')).date()

if st.session_state['auth_status'] and 'body_constants' not in st.session_state:
    st.session_state['body_constants'] = load_body_constants(st.session_state['sheet_url'])

# ══════════════════════════════════════════════════════════════
# CSS THEMES
# ══════════════════════════════════════════════════════════════
css_light_vars = """
  --bg-primary: #F0EDE8; --bg-secondary: #E8E4DD; --text-main: #1A1A1A; --text-muted: #6B6560; --text-subtle: #A09890;
  --surface: #FAFAF8; --surface-hover: #F0EDE8; --surface-active: #E8E4DD;
  --border: rgba(0,0,0,0.08); --border-strong: rgba(0,0,0,0.15);
  --c-emerald: #059669; --c-emerald-bg: rgba(5, 150, 105, 0.1);
  --c-amber: #D97706; --c-amber-bg: rgba(217, 119, 6, 0.1);
  --c-rose: #DC2626; --c-rose-bg: rgba(220, 38, 38, 0.1);
  --c-blue: #2563EB; --c-blue-bg: rgba(37, 99, 235, 0.1); --c-blue-soft: rgba(37, 99, 235, 0.15);
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.04);
  --nav-bg: rgba(240, 237, 232, 0.85); --nav-pill: #1A1A1A; --nav-pill-text: #FAFAF8; --nav-text: #6B6560;
  --input-bg: #FAFAF8; --input-text: #1A1A1A;
"""
css_dark_vars = """
  --bg-primary: #0F0F0F; --bg-secondary: #181818; --text-main: #F0EDE8; --text-muted: rgba(240,237,232,0.55); --text-subtle: rgba(240,237,232,0.3);
  --surface: #1C1C1C; --surface-hover: #222222; --surface-active: #282828;
  --border: rgba(255,255,255,0.07); --border-strong: rgba(255,255,255,0.14);
  --c-emerald: #10B981; --c-emerald-bg: rgba(16, 185, 129, 0.12);
  --c-amber: #F59E0B; --c-amber-bg: rgba(245, 158, 11, 0.12);
  --c-rose: #F87171; --c-rose-bg: rgba(248, 113, 113, 0.12);
  --c-blue: #60A5FA; --c-blue-bg: rgba(96, 165, 250, 0.12); --c-blue-soft: rgba(96, 165, 250, 0.2);
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.3); --shadow-md: 0 4px 16px rgba(0,0,0,0.4);
  --nav-bg: rgba(15, 15, 15, 0.88); --nav-pill: #F0EDE8; --nav-pill-text: #0F0F0F; --nav-text: rgba(240,237,232,0.5);
  --input-bg: #1C1C1C; --input-text: #F0EDE8;
"""

theme_block = f":root {{{css_dark_vars}}}" if st.session_state['theme_pref'] == "Dark" else (f":root {{{css_light_vars}}}" if st.session_state['theme_pref'] == "Light" else f":root {{{css_light_vars}}} @media (prefers-color-scheme: dark) {{ :root {{{css_dark_vars}}} }}")

css = theme_block + """
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;0,9..40,800;1,9..40,400&family=DM+Mono:wght@400;500;600&display=swap');

*, *::before, *::after { box-sizing: border-box; }
.stApp { background: var(--bg-primary) !important; font-family: 'DM Sans', sans-serif !important; }
.block-container { padding-top: 1.5rem !important; padding-bottom: 6rem !important; max-width: 580px !important; }
#MainMenu, footer, header { display: none !important; }

.s-head { font-family: 'DM Mono', monospace !important; font-size: 0.65rem; letter-spacing: 2.5px; color: var(--text-subtle); margin: 2rem 0 1rem; font-weight: 500; text-transform: uppercase; }
.settings-lbl { font-family: 'DM Sans', sans-serif !important; font-size: 0.85rem; color: var(--text-main); font-weight: 700; text-transform: uppercase; margin-top: 2rem; margin-bottom: 1rem; letter-spacing: 1px;}
.app-bar { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 2rem; }
.wordmark { font-family: 'DM Sans', sans-serif; font-size: 1.75rem; font-weight: 800; color: var(--text-main); letter-spacing: -1.5px; line-height: 1; }
.tagline { font-family: 'DM Mono', monospace; font-size: 0.6rem; color: var(--text-subtle); margin-top: 5px; letter-spacing: 0.5px; }
.live-pill { display: inline-flex; align-items: center; gap: 6px; background: var(--c-emerald-bg); border: 1px solid rgba(16, 185, 129, 0.25); border-radius: 100px; padding: 5px 12px; font-family: 'DM Mono', monospace; font-size: 0.58rem; color: var(--c-emerald); font-weight: 600; letter-spacing: 1.5px; }

div[role="radiogroup"] { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-bottom: 2.5rem; margin-top: -0.5rem; background: transparent !important; }
div[role="radiogroup"] > label { background: var(--surface) !important; border: 1px solid var(--border-strong) !important; border-radius: 100px !important; padding: 6px 14px !important; margin: 0 !important; cursor: pointer; box-shadow: var(--shadow-sm); transition: all 0.2s ease; }
div[role="radiogroup"] > label:hover { border-color: var(--text-muted) !important; transform: translateY(-1px); }
div[role="radiogroup"] > label[data-checked="true"] { background: var(--nav-pill) !important; border-color: var(--nav-pill) !important; box-shadow: var(--shadow-md); }
div[role="radiogroup"] > label div { color: var(--text-muted) !important; font-weight: 600 !important; font-family: 'DM Sans', sans-serif !important; font-size: 0.75rem !important; letter-spacing: 0.5px !important; }
div[role="radiogroup"] > label[data-checked="true"] div { color: var(--nav-pill-text) !important; font-weight: 800 !important; }
div[role="radiogroup"] span[data-baseweb="radio"], div[data-testid="stSegmentedControl"] { display: none !important; }
div[role="radiogroup"] div[data-testid="stMarkdownContainer"] p { margin: 0 !important; padding: 0 !important; }

.mini-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 1.75rem; }
.mini-cell { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 1.1rem 1rem; box-shadow: var(--shadow-sm); }
.mini-lbl { font-family: 'DM Mono', monospace; font-size: 0.58rem; color: var(--text-subtle); font-weight: 500; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 8px; display: block; }
.mini-val { font-family: 'DM Mono', monospace; font-size: 1.55rem; font-weight: 600; color: var(--text-main); line-height: 1; display: inline-block;}
.mini-unit { font-size: 0.65rem; color: var(--text-subtle); margin-left: 2px; font-weight: 400;}
.mini-sub { font-family: 'DM Mono', monospace; font-size: 0.65rem; font-weight: 600; margin-top: 8px; display: block; letter-spacing: 0.5px;}

.c-ok  { color: var(--c-emerald) !important; } .c-wrn { color: var(--c-amber) !important; } .c-err { color: var(--c-rose) !important; } .c-neu { color: var(--text-muted) !important; }

.chart-blk { background: var(--surface); border: 1px solid var(--border); border-radius: 20px; padding: 1.2rem; margin-bottom: 1rem; box-shadow: var(--shadow-sm); }
.chart-meta { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px; }
.t-chip { font-family: 'DM Mono', monospace; font-size: 0.58rem; padding: 4px 9px; border-radius: 100px; font-weight: 600; display: inline-block; letter-spacing: 0.5px;}
.t-chip.c-ok  { background: var(--c-emerald-bg); color: var(--c-emerald) !important; }
.t-chip.c-wrn { background: var(--c-amber-bg); color: var(--c-amber) !important; }
.t-chip.c-err { background: var(--c-rose-bg); color: var(--c-rose) !important; }
.t-chip.c-neu { background: var(--surface-active); color: var(--text-muted) !important; }

.hud-card { display: flex; gap: 14px; align-items: flex-start; background: var(--surface); border: 1px solid var(--border); padding: 1rem 1.1rem; border-radius: 16px; margin-bottom: 0.6rem; box-shadow: var(--shadow-sm); }
.hud-icon { font-size: 1.1rem; width: 38px; height: 38px; display: flex; align-items: center; justify-content: center; border-radius: 10px; background: var(--surface-active); flex-shrink: 0; }
.hud-title { font-size: 0.78rem; color: var(--text-main); font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 3px; }
.hud-desc { font-size: 0.76rem; color: var(--text-muted); line-height: 1.5; }

.tj-blk { margin-bottom: 2.2rem; }
.tj-row { display: flex; justify-content: space-between; margin-bottom: 10px; align-items: flex-end; }
.tj-nm { font-family: 'DM Mono', monospace; font-size: 0.72rem; color: var(--text-muted); font-weight: 500; text-transform: uppercase; letter-spacing: 1.5px; }
.bar-tk { height: 20px; border-radius: 10px; overflow: hidden; margin-bottom: 8px; position: relative; }
.bar-pin { position: absolute; top: -2px; bottom: -2px; width: 3px; background: var(--text-main); box-shadow: 0 0 0 2px var(--bg-primary), 0 0 12px rgba(255,255,255,0.3); z-index: 5; transform: translateX(-50%); border-radius: 2px; }
.tj-st { font-family: 'DM Mono', monospace; font-size: 0.58rem; font-weight: 600; letter-spacing: 2px; text-transform: uppercase; display: block; margin-top: 8px; }

.hist-row { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 14px 16px; margin-bottom: 8px; display: flex; align-items: center; box-shadow: var(--shadow-sm); transition: box-shadow 0.15s ease; }
.hist-grid { display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; width: 100%; align-items: center; gap: 10px; }
.hist-header { display: grid; grid-template-columns: 2fr 1fr 1fr 1fr 40px; padding: 0 16px; margin-bottom: 8px; font-family: 'DM Mono', monospace; font-size: 0.6rem; color: var(--text-subtle); text-transform: uppercase; letter-spacing: 1.5px; font-weight: 600; }
.hist-date { font-family: 'DM Mono', monospace; font-size: 0.68rem; color: var(--text-subtle); font-weight: 500; letter-spacing: 0.5px; }
.hist-vals { font-family: 'DM Mono', monospace; font-size: 0.8rem; color: var(--text-main); font-weight: 600; text-align: right; }
.del-btn button { background: transparent !important; border: none !important; color: var(--text-subtle) !important; font-weight: 600 !important; font-size: 1.2rem !important; padding: 0 !important; margin: 0 !important; box-shadow: none !important; }
.del-btn button:hover { color: var(--c-rose) !important; }

div[data-testid="stSlider"] label { font-family: 'DM Mono', monospace !important; font-size: 0.65rem !important; color: var(--text-subtle) !important; text-transform: uppercase !important; font-weight: 500 !important; letter-spacing: 1.5px !important; }
div[data-testid="stSlider"] div[role="slider"] { width: 22px !important; height: 22px !important; background: var(--c-blue) !important; border: 3px solid var(--bg-primary) !important; box-shadow: var(--shadow-md) !important; }

div[data-testid="stSelectbox"] > div > div { background: var(--input-bg) !important; border: 1px solid var(--border-strong) !important; border-radius: 12px !important; color: var(--input-text) !important; min-height: 3.2rem !important; box-shadow: var(--shadow-sm) !important; }
div[data-testid="stTextInput"] > div > div { background: var(--input-bg) !important; border: 1px solid var(--border-strong) !important; border-radius: 12px !important; min-height: 3.2rem !important; }
div[data-testid="stTextInput"] input { color: var(--input-text) !important; font-family: 'DM Mono', monospace !important; font-size: 1rem !important; text-align: center !important; }

div[data-testid="stForm"] button, .stButton > button { background: var(--text-main) !important; color: var(--bg-primary) !important; font-family: 'DM Sans', sans-serif !important; font-weight: 700 !important; font-size: 0.82rem !important; border: none !important; border-radius: 100px !important; padding: 1rem !important; margin-top: 1.5rem !important; text-transform: uppercase !important; letter-spacing: 2px !important; box-shadow: var(--shadow-md) !important; }
div[data-testid="stForm"] button:hover { transform: translateY(-1px) !important; box-shadow: var(--shadow-lg) !important; }
"""
st.markdown(f'<style>{css}</style>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════
if not st.session_state['auth_status']:
    st.markdown("""
    <div style="text-align:center; margin-top:4rem; margin-bottom:3rem;">
        <div class="wordmark" style="font-size:2.5rem;">METRICS</div><div class="tagline" style="font-size:0.65rem; margin-top:6px;">Auth Required</div>
    </div><div class="s-head" style="text-align:center;">Select User</div>
    """, unsafe_allow_html=True)
    for k, url in USER_DATA.items():
        if st.button(get_display_name(k).upper(), key=f"auth_{k}", use_container_width=True):
            st.session_state['auth_status'] = True
            st.session_state['current_user'] = k
            st.session_state['sheet_url'] = url
            st.query_params.user = k
            st.rerun()
    st.stop()

# ══════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=60, show_spinner=False)
def load_data(url): return load_body_data(url)

try:
    df = load_data(st.session_state['sheet_url'])
    st.session_state['active_df'] = df
except Exception: st.stop()

df = st.session_state['active_df']
workout_df = load_workout_data(st.session_state['sheet_url'])

METRICS = ['Weight (kg)', 'Muscle Mass (kg)', 'Body Fat (%)']
METRIC_SHORT = {'Weight (kg)': 'BODY WEIGHT', 'Muscle Mass (kg)': 'MUSCLE MASS', 'Body Fat (%)': 'BODY FAT'}
METRIC_UNIT  = {'Weight (kg)': 'kg', 'Muscle Mass (kg)': 'kg', 'Body Fat (%)': '%'}

analysis_start = pd.to_datetime(st.session_state['analysis_start_date'])
target_end_date = pd.to_datetime(st.session_state['target_end_date'])
end_label = target_end_date.strftime('%b %d').upper()

df_win = df[df['Date'] >= analysis_start].copy()
has_w = len(df_window_full := df_win) >= 3 or len(df) >= 3
has_c = len(df_window_full) >= 5 or len(df) >= 5

monthly_trends, traj_data = {}, {}
recent_dfs = {}

if has_w:
    df_w = df_window_full if len(df_window_full) >= 3 else df.tail(3)
    recent_dfs['Weight (kg)'] = df_w 
    X_w = df_w['Date'].map(lambda d: (d - df_w['Date'].min()).days).values
    res_w = stats.linregress(X_w, df_w['Weight (kg)'].values)
    monthly_trends['Weight (kg)'] = res_w.slope * 30 
    
    d_to_end = (target_end_date.date() - df_w['Date'].min().date()).days
    if d_to_end > 0:
        f_days = np.array([[i] for i in range(0, d_to_end + 10)])
        traj_data['Weight (kg)'] = {
            'dates': [df_w['Date'].min() + timedelta(days=i) for i in range(0, d_to_end + 10)], 
            'preds': res_w.intercept + res_w.slope * f_days.flatten(),
            'final_error': res_w.stderr * f_days.flatten()[-10] * 1.96 
        }

if has_c:
    df_c = df_window_full if len(df_window_full) >= 5 else df.tail(5)
    X_c = df_c['Date'].map(lambda d: (d - df_c['Date'].min()).days).values
    d_to_end = (target_end_date.date() - df_c['Date'].min().date()).days
    if d_to_end > 0:
        f_days = np.array([[i] for i in range(0, d_to_end + 10)])
        f_dates = [df_c['Date'].min() + timedelta(days=i) for i in range(0, d_to_end + 10)]
        for m in ['Muscle Mass (kg)', 'Body Fat (%)']:
            recent_dfs[m] = df_c
            res_c = stats.linregress(X_c, df_c[m].values)
            monthly_trends[m] = res_c.slope * 30
            traj_data[m] = {'dates': f_dates, 'preds': res_c.intercept + res_c.slope * f_days.flatten(), 'final_error': res_c.stderr * f_days.flatten()[-10] * 1.96}

# ══════════════════════════════════════════════════════════════
# MAIN ROUTING
# ══════════════════════════════════════════════════════════════
def sgn(v): return "+" if v > 0 else ""
def dclass(v, invert=False): return "c-ok" if (v > 0 and not invert) or (v < 0 and invert) else ("c-err" if v != 0 else "c-neu")

def eval_metric(metric, actual, profile, mmt=None, bft=None):
    tgt, lower, upper = profile[metric] if len(profile[metric]) == 3 else (profile[metric][0], profile[metric][1], float('inf'))
    if metric == 'Weight (kg)' and mmt is not None and bft is not None:
        if actual > upper and mmt >= (actual * 0.4) and bft <= 0.2: return ('c-ok', 'bg-ok', 'MUSCLE DRIVEN', 'var(--c-emerald)')
        if actual < lower and mmt >= -0.2 and bft < lower: return ('c-ok', 'bg-ok', 'FAT LOSS DRIVEN', 'var(--c-emerald)')
    if metric == 'Muscle Mass (kg)':
        if actual >= tgt: return ('c-ok', 'bg-ok', 'EXCEPTIONAL', 'var(--c-emerald)')
        if actual >= lower: return ('c-wrn', 'bg-wrn', 'LAGGING', 'var(--c-amber)')
        return ('c-err', 'bg-err', 'SUB-OPTIMAL', 'var(--c-rose)')
    if actual > upper: return ('c-err', 'bg-err', 'EXCEEDING LIMIT', 'var(--c-rose)')
    if actual < lower: return ('c-wrn', 'bg-wrn', 'BELOW TARGET', 'var(--c-amber)')
    return ('c-ok', 'bg-ok', 'OPTIMAL RANGE', 'var(--c-emerald)')

def traj_bar(label, actual_rate, metric, profile, unit, mmt=None, bft=None):
    tgt_rate = profile[metric][0]
    s = sgn(actual_rate); ts = sgn(tgt_rate)
    c_txt, c_bg, status, hex_col = eval_metric(metric, actual_rate, profile, mmt, bft)
    
    is_smart_override = status in ['MUSCLE DRIVEN', 'FAT LOSS DRIVEN']
    
    max_bound = max(abs(profile[metric][1]), abs(profile[metric][2]) if len(profile[metric]) > 2 else 0, abs(tgt_rate), abs(actual_rate), 0.1) * 1.3
    p_l = max(min(((profile[metric][1] + max_bound) / (2 * max_bound)) * 100, 100), 0)
    p_t = max(min(((tgt_rate + max_bound) / (2 * max_bound)) * 100, 100), 0)
    
    if len(profile[metric]) > 2:
        p_u = max(min(((profile[metric][2] + max_bound) / (2 * max_bound)) * 100, 100), 0)
        b_html = f"<span style='text-align:left;'>MIN {profile[metric][1]:.2f}</span><span style='color:var(--text-main); font-weight:700;'>TGT {tgt_rate:.2f}</span><span style='text-align:right;'>MAX {profile[metric][2]:.2f}</span>"
    else:
        b_html = f"<span style='text-align:left;'>MIN {profile[metric][1]:.2f}</span><span style='color:var(--text-main); font-weight:700;'>TGT {tgt_rate:.2f}</span><span style='text-align:right;'>MAX ∞</span>"
        
    bounds_html = f"<div style='display:grid; grid-template-columns: 1fr 1fr 1fr; text-align:center; font-family:\"DM Mono\", monospace; font-size:0.58rem; color:var(--text-subtle); margin-top:6px; font-weight:500;'>{b_html}</div>"
        
    pct = ((actual_rate + max_bound) / (2 * max_bound)) * 100
    pct = max(min(pct, 97), 3)
    
    c_g, c_o, c_r = "var(--c-emerald)", "var(--c-amber)", "var(--c-rose)"
    bg_grad = f"linear-gradient(to right, {c_r} 0%, {c_r} {p_l}%, {c_o} {p_l}%, {c_o} {p_t}%, {c_g} {p_t}%, {c_g} 100%)" if metric == 'Muscle Mass (kg)' else f"linear-gradient(to right, {c_o} 0%, {c_o} {p_l}%, {c_g} {p_l}%, {c_g} {p_u if len(profile[metric]) > 2 else 100}%, {c_r} {p_u if len(profile[metric]) > 2 else 100}%, {c_r} 100%)"
    if is_smart_override: bg_grad = f"linear-gradient(to right, {c_o} 0%, {c_o} {p_l}%, {c_g} {p_l}%, {c_g} 100%)" if status == 'MUSCLE DRIVEN' else f"linear-gradient(to right, {c_g} 0%, {c_g} {p_u if len(profile[metric]) > 2 else 100}%, {c_r} {p_u if len(profile[metric]) > 2 else 100}%, {c_r} 100%)"

    return f"""
    <div class='tj-blk'>
      <div class='tj-row' style='margin-bottom:10px;'>
        <span class='tj-nm'>{label}</span>
        <div style='text-align:right;'>
          <div style='font-family:\"DM Mono\", monospace; font-size:1.2rem; font-weight:700; color:var(--text-main); line-height:1;'>
            {s}{actual_rate:.2f} <span style='font-size:0.65rem; color:var(--text-subtle); font-weight:400;'>{unit}</span>
          </div>
        </div>
      </div>
      <div class='bar-tk' style='background: {bg_grad};'><div class='bar-pin' style='left: {pct}%;'></div></div>
      {bounds_html}
      <div class='tj-st {c_txt}'>{status}</div>
    </div>"""

def hud_card(kind, icon, title, desc):
    color_map = {'c-ok': 'var(--c-emerald)', 'c-wrn': 'var(--c-amber)', 'c-err': 'var(--c-rose)', 'c-neu': 'var(--text-muted)'}
    border_color = color_map.get(kind, 'var(--border)')
    return f"<div class='hud-card' style='border-left: 3px solid {border_color};'><div class='hud-icon'>{icon}</div><div><div class='hud-title' style='color:{border_color};'>{title}</div><div class='hud-desc'>{desc}</div></div></div>"

active_goal = st.session_state['current_goal']
ideal_rates = DEFAULT_PROFILES.get(active_goal, DEFAULT_PROFILES['Lean Bulk'])

header_ph = st.empty()
app_view = st.radio("Nav", ["Entry", "Workouts", "Nutrition", "Trends", "Analysis", "Data", "Settings"], horizontal=True, label_visibility="collapsed")

header_ph.markdown(f"""
<div class="app-bar">
    <div><div class="wordmark">Metrics</div><div class="tagline">{get_display_name(st.session_state['current_user'])} · Beta 2</div></div>
    <div class="live-pill"><div class="live-dot"></div>SYNCED</div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# ENTRY
# ══════════════════════════════════════════════════════════════
if app_view == "Entry":
    selected = st.selectbox("Protocol", list(DEFAULT_PROFILES.keys()), index=list(DEFAULT_PROFILES.keys()).index(active_goal))
    if selected != active_goal:
        st.session_state['current_goal'] = selected
        st.query_params.goal = selected
        st.rerun()
    
    last = df.iloc[-1] if len(df) > 0 else pd.Series({'Weight (kg)': 70.0, 'Body Fat (%)': 15.0, 'Muscle Mass (kg)': 35.0})
    prev = df.iloc[-2] if len(df) > 1 else last

    delta_w = last['Weight (kg)'] - prev['Weight (kg)']
    delta_m = last['Muscle Mass (kg)'] - prev['Muscle Mass (kg)']
    delta_bf = last['Body Fat (%)'] - prev['Body Fat (%)']

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
        w = st.slider("Weight (kg)", min_value=max(0.0, float(last['Weight (kg)'])-2.5), max_value=float(last['Weight (kg)'])+2.5, value=float(last['Weight (kg)']), step=0.1)
        m = st.slider("Muscle Mass (kg)", min_value=max(0.0, float(last['Muscle Mass (kg)'])-2.5), max_value=float(last['Muscle Mass (kg)'])+2.5, value=float(last['Muscle Mass (kg)']), step=0.1)
        bf = st.slider("Body Fat (%)", min_value=max(3.0, float(last['Body Fat (%)'])-2.5), max_value=float(last['Body Fat (%)'])+2.5, value=float(last['Body Fat (%)']), step=0.1)
        if st.form_submit_button("Save Record", use_container_width=True):
            now_str = datetime.now().strftime('%Y-%m-%d')
            append_body_entry(st.session_state['sheet_url'], now_str, w, m, bf)
            st.session_state['active_df'] = pd.concat([st.session_state['active_df'], pd.DataFrame({'Date': [datetime.now()], 'Weight (kg)': [w], 'Body Fat (%)': [bf], 'Muscle Mass (kg)': [m]})], ignore_index=True)
            load_data.clear()
            system_alert("Saved")
            st.rerun()

# ══════════════════════════════════════════════════════════════
# WORKOUTS TAB
# ══════════════════════════════════════════════════════════════
elif app_view == "Workouts":
    st.markdown('<div class="s-head" style="margin-top:0;">Log Session</div>', unsafe_allow_html=True)
    
    routine = st.selectbox("Select Routine", list(ROUTINES.keys()))
    exercise = st.selectbox("Select Exercise", ROUTINES[routine])
    
    ex_hist = workout_df[(workout_df['Workout Type'] == routine) & (workout_df['Exercise'] == exercise)]
    if not ex_hist.empty:
        last_log = ex_hist.iloc[-1]
        st.markdown(f"<div style='font-family:\"DM Mono\", monospace; font-size:0.75rem; color:var(--text-subtle); margin-bottom:1rem;'>Last Session ({last_log['Date'].strftime('%d %b')}): <strong style='color:var(--text-main);'>{last_log['Weight']}kg | {last_log['Set']} Sets x {last_log['Reps']} Reps</strong></div>", unsafe_allow_html=True)
    else:
        st.markdown("<div style='font-family:\"DM Mono\", monospace; font-size:0.75rem; color:var(--text-subtle); margin-bottom:1rem;'>No previous history found for this exercise.</div>", unsafe_allow_html=True)
        
    with st.form("workout_form", border=False):
        c1, c2, c3 = st.columns(3)
        with c1: weight = st.number_input("Weight (kg)", min_value=0.0, step=0.5, format="%.1f")
        with c2: sets = st.number_input("Sets", min_value=1, step=1, value=2)
        with c3: reps = st.number_input("Reps", min_value=1, step=1, value=10)
        
        if st.form_submit_button("Log Exercise", use_container_width=True):
            if append_workout_rows(st.session_state['sheet_url'], [[datetime.now().strftime('%Y-%m-%d'), routine, exercise, weight, sets, reps]]):
                system_alert("Exercise Logged")
                time.sleep(0.5)
                st.rerun()
            else:
                st.error("Failed to save. Ensure you created a 'Workouts' tab in your Google Sheet!")

# ══════════════════════════════════════════════════════════════
# NUTRITION TAB (Dynamically calculated based on Body Tab Constants)
# ══════════════════════════════════════════════════════════════
elif app_view == "Nutrition":
    st.markdown('<div class="s-head" style="margin-top:0;">Targets & Coaching</div>', unsafe_allow_html=True)
    
    w_curr = df.iloc[-1]['Weight (kg)'] if len(df) > 0 else 75.0
    h_curr = float(st.session_state['body_constants']['height'])
    a_curr = int(st.session_state['body_constants']['age'])
    g_curr = st.session_state['body_constants']['gender']
    act_lvl = st.session_state['activity_level']
    cal_offset = int(st.session_state['calorie_offset'])
    custom_prot = int(st.session_state['protein_custom'])
    
    # Mifflin-St Jeor
    if g_curr == "male": bmr = (10 * w_curr) + (6.25 * h_curr) - (5 * a_curr) + 5
    else: bmr = (10 * w_curr) + (6.25 * h_curr) - (5 * a_curr) - 161
    
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
    
    if len(df) < 5:
        st.markdown(hud_card("c-neu", "⏳", "Calibrating", "Need more data to provide adaptive calorie adjustments."))
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
# TRENDS & ANALYSIS TABS
# ══════════════════════════════════════════════════════════════
elif app_view == "Trends":
    if not has_w: st.stop()
    for metric in METRICS:
        if metric != 'Weight (kg)' and not has_c: continue
        last_val = df.iloc[-1][metric]
        unit = METRIC_UNIT[metric]
        trend = monthly_trends[metric]
        
        if 'preds' in traj_data.get(metric, {}):
            f_err = traj_data[metric]['final_error']
            f_pred = traj_data[metric]['preds'][-10]
            proj_html = f"<div style='font-family:\"DM Mono\", monospace; font-size:0.65rem; color:var(--text-subtle); margin-top:5px;'>{target_end_date.strftime('%b %d').upper()} PROJ: <span style='color:var(--text-main); font-weight:600;'>{f_pred-f_err:.1f} – {f_pred+f_err:.1f} {unit}</span></div>"
        else: proj_html = ""
        
        st.markdown(f"""
        <div class="chart-blk">
            <div class="chart-meta">
                <div>
                    <div style="font-size:0.7rem; color:var(--text-muted); font-weight:600; text-transform:uppercase; font-family:'DM Mono',monospace;">{METRIC_SHORT[metric]}</div>
                    <div style="font-size:2rem; font-weight:700; color:var(--text-main); line-height:1.1; font-family:'DM Mono',monospace;">{last_val:.1f}<span style="font-size:0.9rem; color:var(--text-subtle); margin-left:3px;">{unit}</span></div>
                    {proj_html}
                </div>
                <div style="text-align: right;">
                    <span class="t-chip {'c-ok' if trend > 0 else 'c-err'}" style="display:block; margin-bottom:4px;">ACTUAL {sgn(trend)}{trend:.2f}/mo</span>
                    <span class="t-chip c-neu" style="display:block;">TGT {sgn(ideal_rates[metric][0])}{ideal_rates[metric][0]:.2f}/mo</span>
                </div>
            </div>
        """, unsafe_allow_html=True)
        
        fig = go.Figure()
        df_hist = df[~df.index.isin(recent_dfs[metric].index)]
        fig.add_trace(go.Scatter(x=df_hist['Date'], y=df_hist[metric], mode='lines+markers', line=dict(color='rgba(128,128,128,0.2)', width=1.5), marker=dict(size=3, color='rgba(128,128,128,0.25)'), hoverinfo='skip'))
        
        spec = recent_dfs[metric]
        fig.add_trace(go.Scatter(x=spec['Date'], y=spec[metric], mode='lines+markers', line=dict(color='#3B82F6', width=2.5), marker=dict(size=5, color='#3B82F6', line=dict(width=1.5, color='white')), hovertemplate='%{x|%b %d}: %{y:.1f}<extra></extra>'))
        
        fig.add_vline(x=spec['Date'].min(), line_width=1.5, line_dash="solid", line_color="rgba(128,128,128,0.4)", annotation_text="START", annotation_position="bottom right", annotation_font_size=9, annotation_font_color="rgba(128,128,128,0.6)")
        
        if 'preds' in traj_data.get(metric, {}):
            x_vals = traj_data[metric]['dates']
            fig.add_trace(go.Scatter(x=x_vals + x_vals[::-1], y=list(traj_data[metric]['upper']) + list(traj_data[metric]['lower'])[::-1], fill='toself', fillcolor='rgba(128,128,128,0.06)', line=dict(color='rgba(0,0,0,0)'), hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=x_vals, y=traj_data[metric]['preds'], mode='lines', line=dict(color='var(--text-main)', width=2, dash='dash'), hoverinfo='skip'))
            
        fig.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', margin=dict(l=0, r=0, t=16, b=40), height=195, showlegend=False, xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(family='DM Mono', size=9, color='rgba(128,128,128,0.8)'), range=[df['Date'].min(), target_end_date + timedelta(days=10)]), yaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.08)', zeroline=False, tickfont=dict(family='DM Mono', size=9, color='rgba(128,128,128,0.8)'), side='right'))
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        st.markdown("</div>", unsafe_allow_html=True)

elif app_view == "Analysis":
    if not has_w: st.stop()
    w, bf, mm = df.iloc[-1]['Weight (kg)'], df.iloc[-1]['Body Fat (%)'], df.iloc[-1]['Muscle Mass (kg)']
    wt, mmt, bft = monthly_trends.get('Weight (kg)', 0), monthly_trends.get('Muscle Mass (kg)', 0), monthly_trends.get('Body Fat (%)', 0)

    st.markdown('<div class="s-head" style="margin-top:0;">Performance</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="mini-grid">
        <div class="mini-cell"><span class="mini-lbl">Weight</span><span class="mini-val">{w:.1f}</span><div class="mini-sub {dclass(wt)}">{sgn(wt)}{wt:.2f} kg/mo</div></div>
        <div class="mini-cell"><span class="mini-lbl">Muscle</span><span class="mini-val">{mm:.1f}</span><div class="mini-sub {dclass(mmt)}">{sgn(mmt)}{mmt:.2f} kg/mo</div></div>
        <div class="mini-cell"><span class="mini-lbl">Body Fat</span><span class="mini-val">{bf:.1f}</span><div class="mini-sub {dclass(bft, True)}">{sgn(bft)}{bft:.2f} %/mo</div></div>
    </div>
    <div class="s-head">Diagnostics</div>
    """, unsafe_allow_html=True)

    w_tgt, w_lower, w_upper = ideal_rates['Weight (kg)']
    diags = []
    is_muscle_driven = (wt > w_upper) and has_c and (mmt >= (wt * 0.4)) and (bft <= 0.2)
    is_fat_loss_driven = (wt < w_lower) and has_c and (mmt >= -0.2) and (bft < ideal_rates['Body Fat (%)'][1])

    if is_muscle_driven: diags.append(hud_card("c-ok", "🧬", "Hyper-Anabolic Response", f"Weight rising (+{wt:.2f} kg/mo) but muscle-driven (+{mmt:.2f} kg/mo)."))
    elif is_fat_loss_driven: diags.append(hud_card("c-ok", "🔥", "Hyper-Lipolytic Response", f"Weight dropping ({wt:.2f} kg/mo) but muscle preserved and fat melting."))
    elif wt > w_upper: diags.append(hud_card("c-err", "↓", "Over Upper Limit", f"Weight accumulation ({wt:.2f} kg/mo) exceeds ceiling."))
    elif wt < w_lower: diags.append(hud_card("c-err", "⚠", "Catabolic Danger", f"Losing weight too fast ({wt:.2f} kg/mo)."))
    
    if has_c and not is_muscle_driven and not is_fat_loss_driven:
        if wt >= w_lower and mmt < ideal_rates['Muscle Mass (kg)'][1]: diags.append(hud_card("c-wrn", "⚠", "Low Muscle Synthesis", f"Muscle lagging ({mmt:.2f} kg/mo)."))
        if bft > ideal_rates['Body Fat (%)'][2]: diags.append(hud_card("c-err", "⚠", "Excessive Fat Gain", f"Fat accumulation ({bft:.2f} %/mo) exceeds limits."))
            
    if not diags: diags.append(hud_card("c-ok", "✓", "Locked In", "All parameters within optimal bounds."))
    for d in diags: st.markdown(d, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# DATA TAB
# ══════════════════════════════════════════════════════════════
elif app_view == "Data":
    st.markdown('<div class="s-head" style="margin-top:0;">Record History</div>', unsafe_allow_html=True)
    st.markdown("""<div class="hist-header"><div>Date</div><div style="text-align:right;">Weight</div><div style="text-align:right;">Muscle</div><div style="text-align:right;">Fat</div><div></div></div>""", unsafe_allow_html=True)
    
    for i in range(len(df)-1, max(-1, len(df)-21), -1):
        row = df.iloc[i]
        if i > 0:
            prev = df.iloc[i-1]
            dw, dm, dbf = row['Weight (kg)'] - prev['Weight (kg)'], row['Muscle Mass (kg)'] - prev['Muscle Mass (kg)'], row['Body Fat (%)'] - prev['Body Fat (%)']
            cw = "var(--c-emerald)" if ("Cut" in active_goal and dw <= 0) or ("Bulk" in active_goal and dw >= 0) else "var(--c-rose)"
            cm = "var(--c-emerald)" if dm >= 0 else "var(--c-rose)"
            cbf = "var(--c-emerald)" if dbf <= 0 else "var(--c-rose)"
            hw = f"<div style='color:{cw}; font-size:0.58rem; margin-top:2px;'>{sgn(dw)}{dw:.1f}</div>"
            hm = f"<div style='color:{cm}; font-size:0.58rem; margin-top:2px;'>{sgn(dm)}{dm:.1f}</div>"
            hbf = f"<div style='color:{cbf}; font-size:0.58rem; margin-top:2px;'>{sgn(dbf)}{dbf:.1f}</div>"
        else: hw, hm, hbf = "", "", ""

        st.markdown(f"""
        <div class="hist-row">
            <div class="hist-grid">
                <div class="hist-date">{row['Date'].strftime('%d %b')}</div>
                <div class="hist-vals">{row['Weight (kg)']:.1f}{hw}</div>
                <div class="hist-vals">{row['Muscle Mass (kg)']:.1f}{hm}</div>
                <div class="hist-vals">{row['Body Fat (%)']:.1f}%{hbf}</div>
            </div>
        """, unsafe_allow_html=True)
        if pd.Timestamp(row['Date']) >= pd.Timestamp(datetime.now() - timedelta(days=7)):
            st.markdown("<div style='margin-left:auto;' class='del-btn'>", unsafe_allow_html=True)
            if st.button("✕", key=f"del_{i}"):
                overwrite_body_sheet(st.session_state['sheet_url'], df.drop(index=i).reset_index(drop=True))
                st.session_state['active_df'] = df.drop(index=i).reset_index(drop=True)
                load_data.clear()
                st.rerun()
            st.markdown("</div></div>", unsafe_allow_html=True)
        else: st.markdown("</div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# SETTINGS TAB
# ══════════════════════════════════════════════════════════════
elif app_view == "Settings":
    st.markdown('<div class="settings-lbl" style="margin-top:0;">Physiology (Read-Only)</div>', unsafe_allow_html=True)
    bc = st.session_state['body_constants']
    
    st.markdown(f"""
    <div style="background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:12px; display:flex; justify-content:space-between; margin-bottom:1.5rem; font-family:'DM Mono', monospace; font-size:0.8rem;">
        <div><b>Height:</b> {bc['height']} cm</div>
        <div><b>Age:</b> {bc['age']} yrs</div>
        <div><b>Gender:</b> {bc['gender'].capitalize()}</div>
    </div>
    <div style="font-size:0.6rem; color:var(--text-subtle); margin-top:-1rem; margin-bottom:1.5rem;"><i>* Edit these values directly in the 'Body' tab of your Google Sheet.</i></div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="settings-lbl" style="margin-top:0;">Nutrition Config</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1: 
        n_act = st.selectbox("Activity Level", list(ACTIVITY_MULTIPLIERS.keys()), index=list(ACTIVITY_MULTIPLIERS.keys()).index(st.session_state['activity_level']))
    with c2: 
        n_prot = st.number_input("Target Protein (g)", value=st.session_state['protein_custom'])
        
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
