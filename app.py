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
    page_title="METRICS | Alpha 2",
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
# HARDCODED PROTOCOL TARGETS
# ══════════════════════════════════════════════════════════════
DEFAULT_PROFILES = {
    "Aggressive Cut":  {'Weight (kg)': [-3.0, -4.0, -2.0], 'Muscle Mass (kg)': [-0.2, -0.5], 'Body Fat (%)': [-1.2, -1.8, -0.6]},
    "Lean Cut":        {'Weight (kg)': [-1.5, -2.0, -1.0], 'Muscle Mass (kg)': [0.0, -0.1],  'Body Fat (%)': [-0.6, -1.0, -0.3]},
    "Recomposition":   {'Weight (kg)': [0.0, -0.5, 0.5],   'Muscle Mass (kg)': [0.3, 0.1],   'Body Fat (%)': [-0.4, -0.8, -0.1]},
    "Lean Bulk":       {'Weight (kg)': [1.0, 0.5, 1.5],    'Muscle Mass (kg)': [0.6, 0.3],   'Body Fat (%)': [0.1, -0.1, 0.4]},
    "Aggressive Bulk": {'Weight (kg)': [2.5, 2.0, 3.5],    'Muscle Mass (kg)': [0.8, 0.5],   'Body Fat (%)': [0.6, 0.3, 1.0]},
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

def read_gsheet(sheet_url):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id: return read_gsheet_csv(sheet_url)
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

def read_gsheet_csv(sheet_url):
    csv_url = f"https://docs.google.com/spreadsheets/d/{extract_sheet_id(sheet_url)}/export?format=csv"
    try:
        df = pd.read_csv(csv_url)
        df['Date'] = pd.to_datetime(df['Date'], format='mixed')
        for m in ['Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']:
            if m in df.columns: df[m] = pd.to_numeric(df[m], errors='coerce')
        return df.sort_values('Date').dropna().reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=['Date', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)'])

def append_to_gsheet(sheet_url, date_str, weight, muscle_mass, body_fat):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id: return False
    try:
        # Timezone Fix: Server is UTC, Netherlands is CEST (+2 Hours)
        time_now = datetime.utcnow() + timedelta(hours=2)
        time_str = time_now.strftime('%H:%M:%S')
        values = [[date_str, time_str, weight, body_fat, muscle_mass]]
        body = {'values': values}
        service.spreadsheets().values().append(spreadsheetId=sheet_id, range='A:E', valueInputOption='USER_ENTERED', insertDataOption='INSERT_ROWS', body=body).execute()
        return True
    except HttpError:
        return False

def delete_row_from_gsheet(sheet_url, row_index_to_delete):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id: return False
    try:
        sheet_row_index = row_index_to_delete + 1 
        sheet_metadata = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        tab_id = sheet_metadata.get('sheets', [])[0].get('properties', {}).get('sheetId', 0)
        requests = [{"deleteDimension": {"range": {"sheetId": tab_id, "dimension": "ROWS", "startIndex": sheet_row_index, "endIndex": sheet_row_index + 1}}}]
        body = {'requests': requests}
        service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body=body).execute()
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
dan_key = st.secrets.get("daniel_user_key", "Daniel")
bram_key = st.secrets.get("bram_user_key", "Bram")
admin_key = st.secrets.get("admin_user_key", "Admin")

USER_DATA = {dan_key: dan_url, bram_key: bram_url}
KEY_TO_LABEL = {dan_key: "Daniel", bram_key: "Bram"}
def get_display_name(user_key): return KEY_TO_LABEL.get(user_key, "Unknown User")

DEFAULT_QUOTES = [
    "The man who loves walking will walk further than the man who loves the destination.",
    "Intensity > Volume.",
    "No man has the right to be an amateur in the matter of physical training. - Socrates",
    "Discipline equals freedom. - Jocko Willink",
    "It's not about perfect. It's about effort.",
    "The iron never lies. - Henry Rollins",
    "We are what we repeatedly do. Excellence, then, is not an act, but a habit. - Aristotle",
    "There is no reason to be alive and not be strong. - Socrates",
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

if 'analysis_start_date' not in st.session_state:
    default_start = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    st.session_state['analysis_start_date'] = pd.to_datetime(st.query_params.get("start", default_start)).date()
if 'target_end_date' not in st.session_state:
    default_end = '2026-09-01'
    st.session_state['target_end_date'] = pd.to_datetime(st.query_params.get("end", default_end)).date()

# ══════════════════════════════════════════════════════════════
# CSS THEMES (TRUE SPOTIFY TABS & BRUTE FORCE LIGHT MODE)
# ══════════════════════════════════════════════════════════════
css_light = """
    :root {
        --bg-primary: #F4F4F5; --text-main: #09090B; --text-muted: rgba(0,0,0,0.6); --text-subtle: rgba(0,0,0,0.5);
        --surface: #FFFFFF; --surface-active: rgba(0,0,0,0.08); --border: rgba(0,0,0,0.1); --border-strong: rgba(0,0,0,0.25);
        --c-emerald: #10B981; --c-amber: #F59E0B; --c-rose: #EF4444; --c-blue: #3B82F6;
    }
"""
css_dark = """
    :root {
        --bg-primary: #121212; --text-main: #FDFDFD; --text-muted: rgba(253, 253, 253, 0.65); --text-subtle: rgba(253, 253, 253, 0.4);
        --surface: #1E1E1E; --surface-active: #2C2C2C; --border: #2A2A2A; --border-strong: #444444;
        --c-emerald: #10B981; --c-amber: #F59E0B; --c-rose: #EF4444; --c-blue: #3B82F6;
    }
"""

if st.session_state['theme_pref'] == "Dark":
    theme_vars = css_dark
elif st.session_state['theme_pref'] == "Light":
    theme_vars = css_light
else:
    theme_vars = css_light + "\n@media (prefers-color-scheme: dark) {\n" + css_dark + "\n}"

css = theme_vars + """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700;800&display=swap');

/* BRUTE FORCE THEME OVERRIDES FOR NATIVE STREAMLIT BUGS */
[data-testid="stAppViewContainer"], [data-testid="stHeader"] { background-color: var(--bg-primary) !important; }
.stMarkdown p, .stWidgetLabel, .stCheckbox label, .stToggle label, .stSelectbox label, .stDateInput label, .stTextInput label, .stSlider label { color: var(--text-main) !important; }
[data-testid="stExpander"] { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 8px !important; }
[data-testid="stExpander"] summary p { color: var(--text-main) !important; font-weight: 600 !important; }

.stApp { background: var(--bg-primary) !important; font-family: 'Inter', sans-serif !important; }
.block-container { padding-top: 1rem !important; padding-bottom: 4rem !important; max-width: 600px !important; }
#MainMenu, footer, header { display: none !important; }

.s-head { font-family: 'Inter', sans-serif !important; font-size: 0.8rem; letter-spacing: 2px; color: var(--text-muted); margin: 2rem 0 1rem; font-weight: 700; text-transform: uppercase; }
.settings-lbl { font-family: 'Inter', sans-serif !important; font-size: 1.1rem; color: var(--text-main); font-weight: 800; text-transform: uppercase; margin-top: 1.5rem; margin-bottom: 0.8rem; letter-spacing: 0.5px;}

.app-bar { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 1.5rem; border-bottom: 1px solid var(--border); padding-bottom: 1rem; }
.wordmark { font-family: 'Inter', sans-serif; font-size: 2.2rem; font-weight: 800; color: var(--text-main); letter-spacing: -1px; line-height: 1; }
.tagline { font-family: 'JetBrains Mono', monospace; font-size: 0.65rem; color: var(--text-subtle); margin-top: 4px; }
.live-pill { display: flex; align-items: center; gap: 6px; background: rgba(59, 130, 246, 0.15); border-radius: 4px; padding: 4px 8px; font-family: 'JetBrains Mono', monospace; font-size: 0.55rem; color: var(--c-blue); font-weight: 600; letter-spacing: 1px; }

.quote-box { text-align: center; padding: 1rem; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); margin-bottom: 1.5rem;}
.quote-text { font-family: 'Inter', sans-serif; font-size: 0.8rem; color: var(--text-main); font-style: italic; font-weight: 500; letter-spacing: 0.2px;}

/* ── SPOTIFY ISLAND TABS ── */
div[data-testid="stSegmentedControl"] { 
    display: flex; justify-content: center; margin-bottom: 2rem; 
}
div[data-testid="stSegmentedControl"] > div {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    gap: 12px !important;
    padding: 0 !important;
}
div[data-testid="stSegmentedControl"] > div > div:first-child { display: none !important; }
div[data-testid="stSegmentedControl"] label {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 50px !important; 
    padding: 8px 16px !important;
    margin: 0 !important;
    box-shadow: none !important;
}
div[data-testid="stSegmentedControl"] label p { 
    color: var(--text-muted) !important; 
    font-weight: 600 !important; 
    font-size: 0.85rem !important; 
}
div[data-testid="stSegmentedControl"] label[aria-checked="true"] {
    background: var(--text-main) !important;
    border-color: var(--text-main) !important;
}
div[data-testid="stSegmentedControl"] label[aria-checked="true"] p { 
    color: var(--bg-primary) !important; 
    font-weight: 800 !important; 
}

.mini-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 1.5rem; }
.mini-cell { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1rem; }
.mini-lbl { font-size: 0.65rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase; margin-bottom: 4px; display: block; }
.mini-val { font-family: 'JetBrains Mono', monospace; font-size: 1.6rem; font-weight: 700; color: var(--text-main); line-height: 1; display: inline-block;}
.mini-unit { font-size: 0.7rem; color: var(--text-subtle); margin-left: 2px;}
.mini-sub { font-family: 'JetBrains Mono', monospace; font-size: 0.65rem; font-weight: 600; margin-top: 6px; display: block;}

.c-ok  { color: var(--c-emerald) !important; } .c-wrn { color: var(--c-amber) !important; } .c-err { color: var(--c-rose) !important; } .c-neu { color: var(--text-muted) !important; }

.chart-blk { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 0.8rem; margin-bottom: 0.8rem; }
.chart-meta { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0px; }
.t-chip { font-family: 'JetBrains Mono', monospace; font-size: 0.6rem; padding: 4px 6px; border-radius: 4px; font-weight: 700; display: inline-block; letter-spacing: 0.5px;}

.hud-card { display: flex; gap: 12px; align-items: center; background: var(--surface); border: 1px solid var(--border); padding: 1rem; border-radius: 10px; margin-bottom: 0.5rem; }
.hud-icon { font-size: 1.2rem; width: 35px; height: 35px; display: flex; align-items: center; justify-content: center; border-radius: 8px; background: var(--surface-active); flex-shrink: 0; line-height: 1; }
.hud-title { font-size: 0.85rem; color: var(--text-main); font-weight: 700; text-transform: uppercase; }
.hud-desc { font-size: 0.75rem; color: var(--text-muted); line-height: 1.4; margin-top: 2px;}

.tj-row { display: flex; justify-content: space-between; margin-bottom: 12px; align-items: flex-end; }
.tj-nm { font-size: 0.85rem; color: var(--text-main); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;}
.bar-tk { height: 22px; border-radius: 11px; overflow: hidden; margin-bottom: 6px; position: relative; border: 1px solid rgba(255,255,255,0.05);}
.bar-pin { position: absolute; top: 0; bottom: 0; width: 4px; background: #FFFFFF; box-shadow: 0 0 10px #FFFFFF; z-index: 5; transform: translateX(-50%); border-radius: 2px;}
.tj-st { font-family: 'JetBrains Mono', monospace; font-size: 0.6rem; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; display: block; margin-top:10px;}

.tier-item { display: flex; align-items: center; gap: 15px; padding: 12px; border-radius: 12px; margin-bottom: 8px; background: var(--surface); border: 1px solid var(--border); }
.tier-item.completed { background: rgba(59, 130, 246, 0.05); border: 1px solid rgba(59, 130, 246, 0.3); }
.tier-item.completed .tier-name { color: var(--c-blue); }
.tier-item.current { background: rgba(59, 130, 246, 0.15); border: 1px solid var(--c-blue); box-shadow: 0 4px 20px rgba(59, 130, 246, 0.15); }
.tier-item.locked { opacity: 0.3; }
.tier-emoji { font-size: 1.5rem; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; background: rgba(255,255,255,0.05); border-radius: 8px; }
.tier-details { flex-grow: 1; }
.tier-name { font-weight: 700; font-size: 0.9rem; color: var(--text-main); margin-bottom: 2px;}
.tier-req { font-family: 'JetBrains Mono', monospace; font-size: 0.65rem; color: var(--text-muted); }
.prog-tk { height: 6px; background: rgba(0,0,0,0.2); border-radius: 3px; overflow: hidden; margin-top: 8px; }
.prog-fill { height: 100%; background: var(--c-blue); border-radius: 3px; }

div[data-testid="stSlider"] label { font-size: 0.75rem !important; color: var(--text-muted) !important; text-transform: uppercase !important; font-weight: 700 !important; letter-spacing: 1px !important; }
div[data-testid="stSlider"] > div > div > div { height: 12px !important; border-radius: 6px !important; background: var(--surface-active) !important; position: relative !important;}
div[data-testid="stSlider"] div[role="slider"] { width: 24px !important; height: 24px !important; background: #3B82F6 !important; border: 2px solid #FFFFFF !important; box-shadow: 0 4px 10px rgba(59, 130, 246, 0.4) !important; z-index: 2 !important; }

/* Input Selectors */
div[data-testid="stSelectbox"] { margin-bottom: 0 !important; padding-bottom: 0 !important; }
div[data-testid="stSelectbox"] > div > div { background: var(--surface) !important; border: 1px solid var(--border-strong) !important; border-radius: 8px !important; color: var(--text-main) !important; display: flex !important; align-items: center !important; justify-content: center !important; min-height: 3.5rem !important; padding: 0 !important;}
div[data-testid="stSelectbox"] div[data-baseweb="select"] { width: 100% !important; justify-content: center !important; text-align: center !important;}
div[data-testid="stSelectbox"] div[class*="singleValue"] { text-align: center !important; margin: 0 auto !important; position: absolute; left: 0; right: 0; color: var(--text-main) !important;}

div[data-testid="stTextInput"] > div > div { background: var(--surface) !important; border: 1px solid var(--border-strong) !important; border-radius: 8px !important; color: var(--text-main) !important; display: flex !important; align-items: center !important; min-height: 3.5rem !important; overflow: hidden !important; padding: 0 !important;}
div[data-testid="stTextInput"] input { color: var(--text-main) !important; font-family: 'JetBrains Mono', monospace !important; font-size: 1.2rem !important; text-align: center !important; margin-bottom: 0 !important; border: none !important;}
div[data-testid="stTextInput"] button { background: transparent !important; border: none !important; box-shadow: none !important; height: 2.5rem !important; width: 2.5rem !important; margin-right: 0.2rem !important; padding: 0 !important; display: flex !important; align-items: center !important; justify-content: center !important; }
div[data-testid="stTextInput"] button svg { width: 1.3rem !important; height: 1.3rem !important; fill: var(--text-subtle) !important; }

div[data-testid="stForm"] button, .stButton>button { background: var(--text-main) !important; color: var(--bg-primary) !important; font-family: 'Inter', sans-serif !important; font-weight: 800 !important; font-size: 0.95rem !important; border: none !important; border-radius: 12px !important; padding: 1rem !important; margin-top: 1.5rem !important; transition: transform 0.1s ease !important; text-transform: uppercase !important; letter-spacing: 1px !important; }
.stButton>button { border: 2px solid var(--border-strong) !important; background: var(--surface) !important; color: var(--text-main) !important; padding: 2.5rem 1rem !important; font-size: 1.5rem !important; margin-top: 0 !important; }
div[data-testid="stDateInput"] > div > div { background: var(--surface) !important; border: 1px solid var(--border-strong) !important; border-radius: 8px !important; color: var(--text-main) !important; height: 3rem !important; }

button[aria-label="Step down"], button[aria-label="Step up"], button[title="Step down"], button[title="Step up"] { display: none !important; }
</style>
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
    <div class="app-bar" style="border:none; justify-content:center; margin-top:3rem;">
        <div style="text-align:center;">
            <div class="wordmark">METRICS</div>
            <div class="tagline">Admin Control</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div class='s-head' style='text-align:center; margin-bottom: 2rem;'>SELECT PROFILE</div>", unsafe_allow_html=True)
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
# RECOMPOSITION MATH ENGINE & GLOBAL HELPERS
# ══════════════════════════════════════════════════════════════
def sgn(v): return "+" if v > 0 else ""

def dclass(v, invert=False):
    if invert: v = -v
    return "c-ok" if v > 0 else ("c-err" if v < 0 else "c-neu")

def eval_metric(metric, actual, profile, mmt=None, bft=None):
    tgt, lower, upper = profile[metric] if len(profile[metric]) == 3 else (profile[metric][0], profile[metric][1], float('inf'))
    
    # ── SMART BODY RECOMPOSITION OVERRIDES ──
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
    return f"<div class='hud-card' style='border-left: 3px solid var(--{kind});'><div class='hud-icon {kind}'>{icon}</div><div><div class='hud-title {kind}'>{title}</div><div class='hud-desc'>{desc}</div></div></div>"

def traj_bar(label, actual_rate, metric, profile, unit, mmt=None, bft=None):
    tgt_rate = profile[metric][0]
    s = sgn(actual_rate); ts = sgn(tgt_rate)
    c_txt, c_bg, status, hex_col = eval_metric(metric, actual_rate, profile, mmt, bft)
    
    is_smart_override = False
    if status == 'MUSCLE DRIVEN': is_smart_override = "OVER"
    if status == 'FAT LOSS DRIVEN': is_smart_override = "UNDER"

    if metric == 'Muscle Mass (kg)':
        max_bound = max(abs(profile[metric][1]), abs(tgt_rate), abs(actual_rate), 0.1) * 1.3
        bounds_html = f"<div style='display:grid; grid-template-columns: 1fr 1fr 1fr; text-align:center; font-family:\"JetBrains Mono\", monospace; font-size:0.6rem; color:var(--text-subtle); margin-top:6px; font-weight:600;'><span style='text-align:left;'>MIN {profile[metric][1]:.2f}</span><span style='color:var(--text-main); font-weight:800;'>TGT {tgt_rate:.2f}</span><span style='text-align:right;'>MAX ∞</span></div>"
    else:
        max_bound = max(abs(profile[metric][1]), abs(profile[metric][2]), abs(tgt_rate), abs(actual_rate), 0.1) * 1.3
        min_val = min(profile[metric][1], profile[metric][2])
        max_val = max(profile[metric][1], profile[metric][2])
        bounds_html = f"<div style='display:grid; grid-template-columns: 1fr 1fr 1fr; text-align:center; font-family:\"JetBrains Mono\", monospace; font-size:0.6rem; color:var(--text-subtle); margin-top:6px; font-weight:600;'><span style='text-align:left;'>MIN {min_val:.2f}</span><span style='color:var(--text-main); font-weight:800;'>TGT {tgt_rate:.2f}</span><span style='text-align:right;'>MAX {max_val:.2f}</span></div>"
        
    pct = ((actual_rate + max_bound) / (2 * max_bound)) * 100
    pct = max(min(pct, 98), 2)
    bg_grad = get_gradient(metric, profile, max_bound, is_smart_override)

    html_block = f"<div class='tj-blk' style='margin-bottom: 2.5rem;'><div class='tj-row' style='margin-bottom:8px;'><span class='tj-nm'>{label}</span><div style='text-align:right;'><div style='font-family:\"JetBrains Mono\", monospace; font-size:1.1rem; font-weight:800; color:var(--text-main); line-height:1;'>{s}{actual_rate:.2f} <span style='font-size:0.7rem; color:var(--text-muted);'>{unit}</span></div></div></div><div class='bar-tk' style='background: {bg_grad};'><div class='bar-pin' style='left: {pct}%;'></div></div>{bounds_html}<div class='tj-st {c_txt}'>{status}</div></div>"
    return html_block


# ══════════════════════════════════════════════════════════════
# DATA LOADING & STATISTICAL ENGINE
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=60, show_spinner=False)
def load_data(url):
    if not url: raise Exception("URL Missing")
    df = read_gsheet(url)
    if df.empty: raise Exception("No data found in sheet – check sharing permissions and URL.")
    return df

try:
    df = load_data(st.session_state['sheet_url'])
    if 'active_df' not in st.session_state:
        st.session_state['active_df'] = df
except Exception as e:
    st.error(f"System Error: Could not load data. {str(e)}")
    st.stop()

df = st.session_state['active_df']
GOAL_PROFILES = st.session_state['goal_profiles']
METRICS = ['Weight (kg)', 'Muscle Mass (kg)', 'Body Fat (%)']
METRIC_SHORT = {'Weight (kg)': 'BODY WEIGHT', 'Muscle Mass (kg)': 'MUSCLE MASS', 'Body Fat (%)': 'BODY FAT'}
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
    
    # Regression & Confidence Intervals
    res_w = stats.linregress(X_w_raw, y_w)
    slope_w = res_w.slope
    stderr_w = res_w.stderr
    
    monthly_trends['Weight (kg)'] = slope_w * 30 
    
    start_day_w = (df_w['Date'].min() - df_w['Date'].min()).days
    days_to_end_w = (target_end_date.date() - df_w['Date'].min().date()).days
    if days_to_end_w > 0:
        future_days_w  = np.array([[start_day_w + i] for i in range(0, days_to_end_w + 10)])
        future_dates_w = [df_w['Date'].min() + timedelta(days=i) for i in range(0, days_to_end_w + 10)]
        
        # Calculate Error Range
        pred_y_w = res_w.intercept + slope_w * future_days_w.flatten()
        margin_of_error_w = stderr_w * future_days_w.flatten() * 1.96 # 95% CI
        
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
if "goal" in st.query_params: st.session_state['current_goal'] = st.query_params.get("goal")

active_goal = st.session_state.get('current_goal', 'Lean Bulk')
ideal_rates = GOAL_PROFILES.get(active_goal, GOAL_PROFILES['Lean Bulk'])

header_placeholder = st.empty()
app_view = st.segmented_control("Nav", ["Entry", "Trends", "Analysis", "Data", "Settings"], default="Entry", label_visibility="collapsed")

if app_view == "Entry":
    header_placeholder.markdown(f"""
    <div class="app-bar">
        <div>
            <div class="wordmark">METRICS</div>
            <div class="tagline">Data Engine Alpha 1 | {get_display_name(st.session_state['current_user'])}</div>
        </div>
        <div class="live-pill"><span class="pdot"></span>SYNCED</div>
    </div>
    """, unsafe_allow_html=True)

    if st.session_state['enable_quotes']:
        if 'daily_quote' not in st.session_state:
            st.session_state['daily_quote'] = random.choice(st.session_state['all_quotes'])
        st.markdown(f"<div class='quote-box'><div class='quote-text'>\"{st.session_state['
