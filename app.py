import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import random
import re
from sklearn.linear_model import LinearRegression
from datetime import datetime, timedelta
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ══════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="METRICS",
    layout="centered",
    initial_sidebar_state="collapsed"
)

def system_alert(message, kind="ok"):
    bg = "var(--c-emerald)" if kind == "ok" else "var(--c-rose)"
    ph = st.empty()
    ph.markdown(f"""
    <div style="position:fixed; top:30px; left:50%; transform:translateX(-50%);
                background:{bg}; color:#09090B; padding:15px 40px;
                border-radius:30px; font-weight:800; font-family:'Inter', sans-serif;
                z-index:99999; box-shadow: 0 10px 40px rgba(0,0,0,0.6); 
                text-transform:uppercase; letter-spacing:1.5px; font-size: 0.85rem;">
        {message}
    </div>
    """, unsafe_allow_html=True)
    time.sleep(1.2)
    ph.empty()

# ══════════════════════════════════════════════════════════════
# HARDCODED PROTOCOL TARGETS (EDIT THESE PERMANENTLY HERE)
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
        time_str = datetime.now().strftime('%H:%M:%S')
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
if 'analysis_start_date' not in st.session_state:
    default_start = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    st.session_state['analysis_start_date'] = pd.to_datetime(st.query_params.get("start", default_start)).date()

# ══════════════════════════════════════════════════════════════
# OBSIDIAN THEME CSS
# ══════════════════════════════════════════════════════════════
css = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700;800&display=swap');

:root {
    --bg-primary: #18181B; --text-main: #FFFFFF; --text-muted: rgba(255,255,255,0.5); --text-subtle: rgba(255,255,255,0.4);
    --surface: rgba(255,255,255,0.04); --surface-active: rgba(255,255,255,0.12);
    --border: rgba(255,255,255,0.08); --border-strong: rgba(255,255,255,0.2);
    --c-emerald: #10B981; --c-amber: #F59E0B; --c-rose: #EF4444; --c-blue: #3B82F6;
}

@media (prefers-color-scheme: light) {
    :root {
        --bg-primary: #F4F4F5; --text-main: #09090B; --text-muted: rgba(0,0,0,0.6); --text-subtle: rgba(0,0,0,0.5);
        --surface: #FFFFFF; --surface-active: rgba(0,0,0,0.08); --border: rgba(0,0,0,0.1); --border-strong: rgba(0,0,0,0.25);
        --c-emerald: #059669; --c-amber: #D97706; --c-rose: #DC2626; --c-blue: #2563EB;
    }
}

.stApp { background: var(--bg-primary) !important; font-family: 'Inter', sans-serif !important; }
.block-container { padding-top: 1rem !important; padding-bottom: 4rem !important; max-width: 600px !important; }
#MainMenu, footer, header { display: none !important; }

.s-head { font-family: 'Inter', sans-serif !important; font-size: 0.8rem; letter-spacing: 2px; color: var(--text-muted); margin: 2rem 0 1rem; font-weight: 700; text-transform: uppercase; }
.settings-lbl { font-family: 'Inter', sans-serif !important; font-size: 1.1rem; color: var(--text-main); font-weight: 800; text-transform: uppercase; margin-top: 1.5rem; margin-bottom: 0.8rem; letter-spacing: 0.5px;}

.app-bar { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 1.5rem; border-bottom: 1px solid var(--border); padding-bottom: 1rem; }
.wordmark { font-family: 'Inter', sans-serif; font-size: 2.2rem; font-weight: 800; color: var(--text-main); letter-spacing: -1px; line-height: 1; }
.tagline { font-family: 'JetBrains Mono', monospace; font-size: 0.65rem; color: var(--text-subtle); margin-top: 4px; }
.live-pill { display: flex; align-items: center; gap: 6px; background: rgba(16, 185, 129, 0.15); border-radius: 4px; padding: 4px 8px; font-family: 'JetBrains Mono', monospace; font-size: 0.55rem; color: var(--c-emerald); font-weight: 600; letter-spacing: 1px; }

.quote-box { text-align: center; padding: 1rem; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); margin-bottom: 1.5rem;}
.quote-text { font-family: 'Inter', sans-serif; font-size: 0.8rem; color: var(--text-main); font-style: italic; font-weight: 500; letter-spacing: 0.2px;}

div[data-testid="stSegmentedControl"] { margin-bottom: 1.5rem; }
div[data-testid="stSegmentedControl"] > div { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 8px !important; padding: 4px !important; }
div[data-testid="stSegmentedControl"] label { font-size: 0.8rem !important; font-weight: 500 !important; color: var(--text-muted) !important; }
div[data-testid="stSegmentedControl"] [aria-checked="true"] > div { background: var(--surface-active) !important; border-radius: 6px !important; }
div[data-testid="stSegmentedControl"] [aria-checked="true"] label { color: var(--text-main) !important; font-weight: 600 !important;}

.mini-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 1.5rem; }
.mini-cell { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1rem; }
.mini-lbl { font-size: 0.65rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase; margin-bottom: 4px; display: block; }
.mini-val { font-family: 'JetBrains Mono', monospace; font-size: 1.6rem; font-weight: 700; color: var(--text-main); line-height: 1; display: inline-block;}
.mini-unit { font-size: 0.7rem; color: var(--text-subtle); margin-left: 2px;}
.mini-sub { font-family: 'JetBrains Mono', monospace; font-size: 0.65rem; font-weight: 600; margin-top: 6px; display: block;}

.c-ok  { color: var(--c-emerald) !important; } .c-wrn { color: var(--c-amber) !important; } .c-err { color: var(--c-rose) !important; } .c-neu { color: var(--text-muted) !important; }

.chart-blk { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 0.8rem; margin-bottom: 0.8rem; }
.chart-meta { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0px; }
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
.tier-item.completed { background: rgba(16, 185, 129, 0.05); border: 1px solid rgba(16, 185, 129, 0.3); }
.tier-item.completed .tier-name { color: var(--c-emerald); }
.tier-item.current { background: rgba(16, 185, 129, 0.15); border: 1px solid var(--c-emerald); box-shadow: 0 4px 20px rgba(16, 185, 129, 0.15); }
.tier-item.locked { opacity: 0.3; }
.tier-emoji { font-size: 1.5rem; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; background: rgba(255,255,255,0.05); border-radius: 8px; }
.tier-details { flex-grow: 1; }
.tier-name { font-weight: 700; font-size: 0.9rem; color: var(--text-main); margin-bottom: 2px;}
.tier-req { font-family: 'JetBrains Mono', monospace; font-size: 0.65rem; color: var(--text-muted); }
.prog-tk { height: 6px; background: rgba(0,0,0,0.2); border-radius: 3px; overflow: hidden; margin-top: 8px; }
.prog-fill { height: 100%; background: var(--c-emerald); border-radius: 3px; }

div[data-testid="stSlider"] label { font-size: 0.75rem !important; color: var(--text-muted) !important; text-transform: uppercase !important; font-weight: 700 !important; letter-spacing: 1px !important; }
div[data-testid="stSlider"] > div > div > div { height: 12px !important; border-radius: 6px !important; background: var(--surface-active) !important; position: relative !important;}
div[data-testid="stSlider"] div[role="slider"] { width: 28px !important; height: 28px !important; background: #FFFFFF !important; border: 3px solid var(--c-emerald) !important; box-shadow: 0 0 15px rgba(16, 185, 129, 0.5) !important; z-index: 2 !important; }

/* Selector Controls (Centering Fix) */
div[data-testid="stSelectbox"] { margin-bottom: 0 !important; padding-bottom: 0 !important; }
div[data-testid="stSelectbox"] > div > div { background: var(--surface) !important; border: 1px solid var(--border-strong) !important; border-radius: 8px !important; color: var(--text-main) !important; display: flex !important; align-items: center !important; justify-content: center !important; min-height: 3.5rem !important; padding: 0 !important;}
div[data-testid="stSelectbox"] div[data-baseweb="select"] { width: 100% !important; justify-content: center !important; text-align: center !important;}
div[data-testid="stSelectbox"] div[class*="singleValue"] { text-align: center !important; margin: 0 auto !important; position: absolute; left: 0; right: 0; }

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
            # 1. Hyper-Anabolic (Muscle Memory): Over weight limit, but driven highly by muscle mass
            if actual > upper and mmt >= (actual * 0.4) and bft <= 0.2:
                return ('c-ok', 'bg-ok', 'MUSCLE DRIVEN', 'var(--c-emerald)')
            # 2. Hyper-Lipolytic (Fat Melting): Under weight limit, but muscle preserved and fat dropping
            if actual < lower and mmt >= -0.2 and bft < lower:
                return ('c-ok', 'bg-ok', 'FAT LOSS DRIVEN', 'var(--c-emerald)')

    # Standard Bounds
    if metric == 'Muscle Mass (kg)':
        if actual >= tgt: return ('c-ok', 'bg-ok', 'EXCEPTIONAL', 'var(--c-emerald)')
        if actual >= lower: return ('c-wrn', 'bg-wrn', 'LAGGING', 'var(--c-amber)')
        return ('c-err', 'bg-err', 'SUB-OPTIMAL', 'var(--c-rose)')
        
    if actual > upper: return ('c-err', 'bg-err', 'EXCEEDING LIMIT', 'var(--c-rose)')
    if actual < lower: return ('c-wrn', 'bg-wrn', 'BELOW TARGET', 'var(--c-amber)')
    return ('c-ok', 'bg-ok', 'OPTIMAL RANGE', 'var(--c-emerald)')

def get_gradient(metric, profile, max_mag, is_smart_override=False):
    c_g = "rgba(16, 185, 129, 0.85)"; c_o = "rgba(245, 158, 11, 0.85)"; c_r = "rgba(239, 68, 68, 0.85)"
    def to_pct(val): return max(min(((val + max_mag) / (2 * max_mag)) * 100, 100), 0)

    if metric == 'Muscle Mass (kg)':
        tgt, lower = profile[metric][:2]
        p_l = to_pct(lower); p_t = to_pct(tgt)
        return f"linear-gradient(to right, {c_r} 0%, {c_r} {p_l}%, {c_o} {p_l}%, {c_o} {p_t}%, {c_g} {p_t}%, {c_g} 100%)"
    else:
        tgt, lower, upper = profile[metric]
        p_lower = to_pct(lower); p_upper = to_pct(upper)
        
        # Adaptive Gradient Bars
        if is_smart_override == "OVER":
            return f"linear-gradient(to right, {c_o} 0%, {c_o} {p_lower}%, {c_g} {p_lower}%, {c_g} 100%)"
        elif is_smart_override == "UNDER":
            return f"linear-gradient(to right, {c_g} 0%, {c_g} {p_upper}%, {c_r} {p_upper}%, {c_r} 100%)"
            
        return f"linear-gradient(to right, {c_o} 0%, {c_o} {p_lower}%, {c_g} {p_lower}%, {c_g} {p_upper}%, {c_r} {p_upper}%, {c_r} 100%)"

def hud_card(kind, icon, title, desc):
    return f"""<div class="hud-card" style="border-left: 3px solid var(--{kind});"><div class="hud-icon {kind}">{icon}</div><div><div class="hud-title {kind}">{title}</div><div class="hud-desc">{desc}</div></div></div>"""

def traj_bar(label, actual, metric, profile, unit, mmt=None, bft=None):
    tgt = profile[metric][0]
    s = sgn(actual); ts = sgn(tgt)
    c_txt, c_bg, status, hex_col = eval_metric(metric, actual, profile, mmt, bft)
    
    is_smart_override = False
    if status == 'MUSCLE DRIVEN': is_smart_override = "OVER"
    if status == 'FAT LOSS DRIVEN': is_smart_override = "UNDER"

    if metric == 'Muscle Mass (kg)':
        max_bound = max(abs(profile[metric][1]), abs(tgt), abs(actual), 0.1) * 1.3
        bounds_html = f"<div style='display:flex; justify-content:space-between; font-family:\"JetBrains Mono\", monospace; font-size:0.6rem; color:var(--text-subtle); margin-top:6px; font-weight:600;'><span>MIN {profile[metric][1]:.2f}</span><span style='color:var(--text-main); font-weight:800;'>TARGET {tgt:.2f}</span><span>MAX ∞</span></div>"
    else:
        max_bound = max(abs(profile[metric][1]), abs(profile[metric][2]), abs(tgt), abs(actual), 0.1) * 1.3
        min_val = min(profile[metric][1], profile[metric][2])
        max_val = max(profile[metric][1], profile[metric][2])
        bounds_html = f"<div style='display:flex; justify-content:space-between; font-family:\"JetBrains Mono\", monospace; font-size:0.6rem; color:var(--text-subtle); margin-top:6px; font-weight:600;'><span>MIN {min_val:.2f}</span><span style='color:var(--text-main); font-weight:800;'>TARGET {tgt:.2f}</span><span>MAX {max_val:.2f}</span></div>"
        
    pct = ((actual + max_bound) / (2 * max_bound)) * 100
    pct = max(min(pct, 98), 2)
    bg_grad = get_gradient(metric, profile, max_bound, is_smart_override)

    return f"""
    <div class='tj-blk' style='margin-bottom: 2.5rem;'>
        <div class='tj-row' style='margin-bottom:8px;'>
            <span class='tj-nm'>{label}</span>
            <div style='text-align:right;'>
                <div style='font-family:"JetBrains Mono", monospace; font-size:1.1rem; font-weight:800; color:var(--text-main); line-height:1;'>{s}{actual:.2f} <span style='font-size:0.7rem; color:var(--text-muted);'>{unit}</span></div>
            </div>
        </div>
        <div class='bar-tk' style='background: {bg_grad};'><div class='bar-pin' style='left: {pct}%;'></div></div>
        {bounds_html}
        <div class='tj-st {c_txt}'>{status}</div>
    </div>"""


# ══════════════════════════════════════════════════════════════
# DATA LOADING
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

# ── MATHEMATICAL ENGINE (MANUAL START DATE & RAW REGRESSION) ──
analysis_start = pd.to_datetime(st.session_state['analysis_start_date'])

df_window_full = df[df['Date'] >= analysis_start].copy()

has_enough_weight_data = len(df_window_full) >= 3 or len(df) >= 3
has_enough_comp_data = len(df_window_full) >= 5 or len(df) >= 5

monthly_trends, traj_data = {}, {}
recent_dfs_for_plot = {}

if has_enough_weight_data:
    df_w = df_window_full if len(df_window_full) >= 3 else df.tail(3)
    recent_dfs_for_plot['Weight (kg)'] = df_w 
    
    X_w = df_w['Date'].map(lambda d: (d - df_w['Date'].min()).days).values.reshape(-1, 1)
    y_w = df_w['Weight (kg)'].values
    model_w = LinearRegression().fit(X_w, y_w)
    
    monthly_trends['Weight (kg)'] = model_w.coef_[0] * 30  # kg/mo
    
    start_day = (df_w['Date'].min() - df_w['Date'].min()).days
    future_days_w  = np.array([[start_day + i] for i in range(1, 91)])
    future_dates_w = [df_w['Date'].min() + timedelta(days=i) for i in range(1, 91)]
    traj_data['Weight (kg)'] = {'dates': future_dates_w, 'preds': model_w.predict(future_days_w)}

if has_enough_comp_data:
    df_c = df_window_full if len(df_window_full) >= 5 else df.tail(5)
    X_c = df_c['Date'].map(lambda d: (d - df_c['Date'].min()).days).values.reshape(-1, 1)
    start_day_c = (df_c['Date'].min() - df_c['Date'].min()).days
    future_days_c  = np.array([[start_day_c + i] for i in range(1, 91)])
    future_dates_c = [df_c['Date'].min() + timedelta(days=i) for i in range(1, 91)]
    
    for m in ['Muscle Mass (kg)', 'Body Fat (%)']:
        recent_dfs_for_plot[m] = df_c
        y_c = df_c[m].values
        model_c = LinearRegression().fit(X_c, y_c)
        monthly_trends[m] = model_c.coef_[0] * 30 # per month
        traj_data[m] = {'dates': future_dates_c, 'preds': model_c.predict(future_days_c)}

# ══════════════════════════════════════════════════════════════
# MAIN ROUTING ENGINE
# ══════════════════════════════════════════════════════════════
if "goal" in st.query_params:
    st.session_state['current_goal'] = st.query_params.get("goal")

active_goal = st.session_state.get('current_goal', 'Lean Bulk')
ideal_rates = GOAL_PROFILES.get(active_goal, GOAL_PROFILES['Lean Bulk'])

header_placeholder = st.empty()
app_view = st.segmented_control("Nav", ["Entry", "Trends", "Analysis", "Data", "Settings"],
                                default="Entry", label_visibility="collapsed")

if app_view == "Entry":
    header_placeholder.markdown(f"""
    <div class="app-bar">
        <div>
            <div class="wordmark">METRICS</div>
            <div class="tagline">Data Engine V33 | {get_display_name(st.session_state['current_user'])}</div>
        </div>
        <div class="live-pill"><span class="pdot"></span>SYNCED</div>
    </div>
    """, unsafe_allow_html=True)

    if st.session_state['enable_quotes']:
        if 'daily_quote' not in st.session_state:
            st.session_state['daily_quote'] = random.choice(st.session_state['all_quotes'])
        st.markdown(f"<div class='quote-box'><div class='quote-text'>\"{st.session_state['daily_quote']}\"</div></div>", unsafe_allow_html=True)

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
            st.markdown(f"<div style='padding:8px; border-radius:6px; background:rgba(239, 68, 68, 0.1); border:1px solid rgba(239, 68, 68, 0.2); font-size:0.7rem; color:var(--c-rose); font-weight:600; text-align:center;'>⚠️ HIGH FAT FOR BULK ({recent_bf_avg:.1f}% AVG)</div>", unsafe_allow_html=True)
        elif "Cut" in st.session_state['current_goal'] and recent_bf_avg < 10.0:
            st.markdown(f"<div style='padding:8px; border-radius:6px; background:rgba(239, 68, 68, 0.1); border:1px solid rgba(239, 68, 68, 0.2); font-size:0.7rem; color:var(--c-rose); font-weight:600; text-align:center;'>⚠️ TOO LEAN FOR CUT ({recent_bf_avg:.1f}% AVG)</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div style='padding:8px; border-radius:6px; background:rgba(16, 185, 129, 0.1); border:1px solid rgba(16, 185, 129, 0.2); font-size:0.7rem; color:var(--c-emerald); font-weight:600; text-align:center;'>✓ VALID FOR CURRENT BODY COMP ({recent_bf_avg:.1f}% AVG FAT)</div>", unsafe_allow_html=True)

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
            <span class="mini-lbl">Muscle Mass</span>
            <span class="mini-val">{last['Muscle Mass (kg)']:.1f}<span class="mini-unit">kg</span></span>
            <div class="mini-sub {dclass(delta_m)}">{sgn(delta_m)}{delta_m:.1f} kg</div>
        </div>
        <div class="mini-cell">
            <span class="mini-lbl">Body Fat</span>
            <span class="mini-val">{last['Body Fat (%)']:.1f}<span class="mini-unit">%</span></span>
            <div class="mini-sub {dclass(delta_bf, invert=True)}">{sgn(delta_bf)}{delta_bf:.1f} %</div>
        </div>
    </div>
    <div class="s-head">Record Entry</div>
    """, unsafe_allow_html=True)

    with st.form("log_form", border=False):
        w_val = float(last['Weight (kg)'])
        w = st.slider("Weight (kg)", min_value=max(0.0, w_val-2.5), max_value=w_val+2.5, value=w_val, step=0.1)
        m_val = float(last['Muscle Mass (kg)'])
        m = st.slider("Muscle Mass (kg)", min_value=max(0.0, m_val-2.5), max_value=m_val+2.5, value=m_val, step=0.1)
        bf_val = float(last['Body Fat (%)'])
        bf = st.slider("Body Fat (%)", min_value=max(3.0, bf_val-2.5), max_value=bf_val+2.5, value=bf_val, step=0.1)

        if st.form_submit_button("SAVE RECORD", use_container_width=True):
            now = datetime.now()
            date_str = now.strftime('%Y-%m-%d')
            append_to_gsheet(st.session_state['sheet_url'], date_str, w, m, bf)
            new_row = pd.DataFrame({'Date': [now], 'Weight (kg)': [w], 'Body Fat (%)': [bf], 'Muscle Mass (kg)': [m]})
            st.session_state['active_df'] = pd.concat([st.session_state['active_df'], new_row], ignore_index=True)
            load_data.clear()
            if st.session_state['enable_quotes']:
                st.session_state['daily_quote'] = random.choice(st.session_state['all_quotes'])
            system_alert("DATABANK UPDATED")
            st.rerun()

elif app_view == "Trends":
    header_placeholder.empty()
    if not has_enough_weight_data:
        st.markdown(hud_card("c-neu", "⏳", "CALIBRATING ENGINE", f"Need 3 logged measurements for trends. Currently: {len(df)}/3."), unsafe_allow_html=True)
        st.stop()
        
    if len(df_window_full) < 3:
        st.markdown(f"<div style='margin-bottom:1rem; padding:8px; border-radius:6px; background:rgba(245, 158, 11, 0.1); border:1px solid rgba(245, 158, 11, 0.2); font-size:0.7rem; color:var(--c-amber); font-weight:600; text-align:center;'>⚠️ NOT ENOUGH DATA SINCE CUSTOM START DATE. DEFAULTING TO LAST LOGS.</div>", unsafe_allow_html=True)

    wt = monthly_trends.get('Weight (kg)', 0)
    mmt = monthly_trends.get('Muscle Mass (kg)', 0)
    bft = monthly_trends.get('Body Fat (%)', 0)

    font_cfg = dict(family='JetBrains Mono, monospace', size=10, color='rgba(150,150,150,0.8)')
    for metric in METRICS:
        if metric != 'Weight (kg)' and not has_enough_comp_data:
            continue
            
        last_val = df.iloc[-1][metric]
        unit = METRIC_UNIT[metric]
        trend = monthly_trends[metric]
        target = ideal_rates[metric][0]
        c_txt, c_bg, _, hex_col = eval_metric(metric, trend, ideal_rates, mmt, bft)
        
        st.markdown(f"""
        <div class="chart-blk">
            <div class="chart-meta">
                <div style="font-size:0.75rem; color:var(--text-main); font-weight:800; letter-spacing:1px; text-transform:uppercase;">{METRIC_SHORT[metric]} <span style="font-family:'JetBrains Mono'; font-weight:700; color:var(--c-blue); margin-left:8px;">{last_val:.1f} <span style="font-size:0.6rem; color:var(--text-muted);">{unit}</span></span></div>
                <div>
                    <span class="t-chip {c_bg} {c_txt}">ACTUAL {sgn(trend)}{trend:.2f} /mo</span>
                    <span class="t-chip bg-neu c-neu" style="margin-left:4px;">TARGET {sgn(target)}{target:.2f} /mo</span>
                </div>
            </div>
        """, unsafe_allow_html=True)
        
        fig = go.Figure()
        df_hist = df[~df.index.isin(recent_dfs_for_plot[metric].index)]
        fig.add_trace(go.Scatter(x=df_hist['Date'], y=df_hist[metric], mode='lines+markers', name='History', line=dict(color='rgba(150,150,150,0.3)', width=1.5), marker=dict(size=4, color='rgba(150,150,150,0.3)'), hoverinfo='skip'))
        spec_recent = recent_dfs_for_plot[metric]
        fig.add_trace(go.Scatter(x=spec_recent['Date'], y=spec_recent[metric], mode='lines+markers', name='Active Data', line=dict(color='#3B82F6', width=2), marker=dict(size=5, color='#3B82F6'), hovertemplate='%{x|%b %d}: %{y:.1f}<extra></extra>'))
        
        epoch_date = spec_recent['Date'].min()
        fig.add_vline(x=epoch_date, line_width=1.5, line_dash="dash", line_color="var(--text-muted)", annotation_text="START", annotation_position="top left", annotation_font_size=8)
        
        fig.add_trace(go.Scatter(x=traj_data[metric]['dates'], y=traj_data[metric]['preds'], mode='lines', name='Trajectory', line=dict(color=hex_col, width=2, dash='dash'), hoverinfo='skip'))
        
        first_epoch_val = spec_recent.iloc[0][metric]
        daily_rate = ideal_rates[metric][0] / 30.0
        ideal_vals = [first_epoch_val] + [first_epoch_val + daily_rate * x for x in range(1, 91)]
        fig.add_trace(go.Scatter(x=[epoch_date] + traj_data[metric]['dates'][-90:], y=ideal_vals, mode='lines', name='Target Path', line=dict(color='gray', width=1.5, dash='dot'), opacity=0.7, hoverinfo='skip'))
        
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=0, r=0, t=20, b=5), height=140, showlegend=True,
            legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, font=dict(size=9, color='rgba(150,150,150,0.8)')),
            xaxis=dict(showgrid=False, zeroline=False, tickfont=font_cfg, tickformat='%b %d'),
            yaxis=dict(showgrid=True, gridcolor='rgba(150,150,150,0.1)', zeroline=False, tickfont=font_cfg, side='right')
        )
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        st.markdown("</div>", unsafe_allow_html=True)

elif app_view == "Analysis":
    header_placeholder.empty()
    if not has_enough_weight_data:
        st.markdown(hud_card("c-neu", "⏳", "CALIBRATING ENGINE", f"Need 3 logged measurements for basic tracking. Currently: {len(df)}/3."), unsafe_allow_html=True)
        st.stop()

    if len(df_window_full) < 3:
        st.markdown(f"<div style='margin-bottom:1rem; padding:8px; border-radius:6px; background:rgba(245, 158, 11, 0.1); border:1px solid rgba(245, 158, 11, 0.2); font-size:0.7rem; color:var(--c-amber); font-weight:600; text-align:center;'>⚠️ NOT ENOUGH DATA SINCE CUSTOM START DATE. DEFAULTING TO LAST LOGS.</div>", unsafe_allow_html=True)

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
        bf_disp = f"""<div class="mini-sub c-neu">CALIBRATING ({len(df)}/5)</div>"""
        mm_disp = f"""<div class="mini-sub c-neu">CALIBRATING ({len(df)}/5)</div>"""

    st.markdown(f"""
    <div class="s-head" style="margin-top:0;">Performance Data</div>
    <div class="mini-grid">
        <div class="mini-cell">
            <span class="mini-lbl">Weight</span>
            <span class="mini-val">{w:.1f}</span>
            <div class="mini-sub {c_w}">{sgn(wt)}{wt:.2f} kg/mo</div>
        </div>
        <div class="mini-cell">
            <span class="mini-lbl">Muscle Mass</span>
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
    
    # ── SMART RECOMPOSITION DIAGNOSTICS ──
    is_muscle_driven = (wt > w_upper) and has_enough_comp_data and (mmt > wt * 0.4) and (bft <= 0.2)
    is_fat_loss_driven = (wt < w_lower) and has_enough_comp_data and (mmt >= -0.2) and (bft < bf_lower)

    if is_muscle_driven:
        diags.append(hud_card("c-emerald", "🧬", "HYPER-ANABOLIC RESPONSE", f"Weight is increasing rapidly (+{wt:.2f} kg/mo), but it is heavily driven by muscle gain (+{mmt:.2f} kg/mo). Do not cut calories. Ride this muscle memory wave."))
    elif is_fat_loss_driven:
        diags.append(hud_card("c-emerald", "🔥", "HYPER-LIPOLYTIC RESPONSE", f"Weight is dropping fast ({wt:.2f} kg/mo), but muscle is preserved and fat is melting (-{abs(bft):.2f} %/mo). Excellent recomposition."))
    elif wt > w_upper:
        diags.append(hud_card("c-err", "↓", "OVER UPPER LIMIT", f"Weight accumulation ({wt:.2f} kg/mo) exceeds limits. Reduce caloric intake by 200-300 kcal."))
    elif wt < w_lower:
        if w_lower < 0:
            diags.append(hud_card("c-err", "⚠️", "CATABOLIC DANGER", f"Losing weight too rapidly ({wt:.2f} kg/mo). Increase caloric intake immediately."))
        else:
            diags.append(hud_card("c-wrn", "↑", "ANABOLIC STALL", f"Weight accumulation lagging below {w_lower} kg/mo. Increase daily caloric intake by 200-300 kcal."))
    
    if has_enough_comp_data and not is_muscle_driven and not is_fat_loss_driven:
        m_tgt, m_lower = ideal_rates['Muscle Mass (kg)'][:2]
        bf_tgt, bf_lower, bf_upper = ideal_rates['Body Fat (%)']
        if wt >= w_lower and mmt < m_lower:
            diags.append(hud_card("c-wrn", "⚠️", "LOW MUSCLE SYNTHESIS", f"Weight tracking properly, but muscle accumulation lagging ({mmt:.2f} kg/mo). Ensure high protein intake (1.6-2.2g/kg)."))
        if bft > bf_upper:
            diags.append(hud_card("c-err", "⚠️", "EXCESSIVE FAT GAIN", f"Body fat accumulation ({bft:.2f} %/mo) exceeds limits. Dial back carbs/fats slightly."))
            
    if not diags:
        diags.append(hud_card("c-ok", "✓", "LOCKED IN", "All tracked parameters are within optimal bounds. Stay the course."))
    for d in diags:
        st.markdown(d, unsafe_allow_html=True)

    if st.session_state['enable_achievements']:
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
            if days_elapsed >= t["days"]:
                current_tier_idx = i

        st.markdown('<div class="s-head">Achievements</div>', unsafe_allow_html=True)
        engine_html = "<div style='margin-bottom: 2rem;'>\n"
        start_idx = max(0, current_tier_idx - 3)
        for i in range(start_idx, current_tier_idx):
            t = TIERS[i]
            engine_html += f"<div class='tier-item completed'><div class='tier-emoji'>{t['emoji']}</div><div class='tier-details'><div class='tier-name'>{t['name']}</div><div class='tier-req'>UNLOCKED: {t['days']} DAYS</div></div><div style='color:var(--c-emerald); font-weight:800;'>✓</div></div>\n"
        t_curr = TIERS[current_tier_idx]
        if current_tier_idx < len(TIERS) - 1:
            t_next = TIERS[current_tier_idx + 1]
            progress = ((days_elapsed - t_curr['days']) / (t_next['days'] - t_curr['days'])) * 100
            engine_html += f"<div class='tier-item current'><div class='tier-emoji'>{t_curr['emoji']}</div><div class='tier-details'><div style='display:flex; justify-content:space-between; align-items:flex-end;'><div class='tier-name' style='color:var(--c-emerald);'>{t_curr['name']}</div><div style='font-size:0.6rem; font-weight:700;'>{days_elapsed} / {t_next['days']} D</div></div><div class='prog-tk'><div class='prog-fill' style='width:{progress}%;'></div></div></div></div>\n"
        else:
            engine_html += f"<div class='tier-item current'><div class='tier-emoji'>{t_curr['emoji']}</div><div class='tier-details'><div class='tier-name' style='color:var(--c-emerald);'>{t_curr['name']}</div><div class='tier-req'>MAXIMUM TIER REACHED</div></div></div>\n"
        end_idx = min(len(TIERS), current_tier_idx + 3)
        for i in range(current_tier_idx + 1, end_idx):
            t = TIERS[i]
            engine_html += f"<div class='tier-item locked'><div class='tier-emoji'>🔒</div><div class='tier-details'><div class='tier-name'>{t['name']}</div><div class='tier-req'>REQUIRES: {t['days']} DAYS</div></div></div>\n"
        engine_html += "</div>"
        st.markdown(engine_html, unsafe_allow_html=True)

elif app_view == "Data":
    header_placeholder.empty()
    st.markdown('<div class="s-head" style="margin-top:0;">RECORD HISTORY</div>', unsafe_allow_html=True)
    
    seven_days_ago = pd.Timestamp(datetime.now() - timedelta(days=7))
    
    for i in range(len(df)-1, max(-1, len(df)-21), -1):
        row = df.iloc[i]
        c1, c2 = st.columns([5, 1])
        with c1:
            st.markdown(f"""
            <div style="background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:16px; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
                <div style="font-family:'JetBrains Mono', monospace; font-size:0.75rem; color:var(--text-muted);">{row['Date'].strftime('%d %b %Y')}</div>
                <div style="font-family:'JetBrains Mono', monospace; font-size:0.85rem; color:var(--text-main); font-weight:700;">
                    {row['Weight (kg)']}KG <span style="color:var(--border-strong); margin: 0 4px;">|</span> {row['Muscle Mass (kg)']}MM <span style="color:var(--border-strong); margin: 0 4px;">|</span> {row['Body Fat (%)']}%
                </div>
            </div>
            """, unsafe_allow_html=True)
        with c2:
            if pd.Timestamp(row['Date']) >= seven_days_ago:
                if st.button("🗑️", key=f"del_{i}", help="Delete Record"):
                    new_df = df.drop(index=i).reset_index(drop=True)
                    overwrite_gsheet(st.session_state['sheet_url'], new_df)
                    st.session_state['active_df'] = new_df
                    load_data.clear()
                    system_alert("RECORD PURGED", "err")
                    st.rerun()

elif app_view == "Settings":
    header_placeholder.empty()

    st.markdown('<div class="settings-lbl" style="margin-top:0;">Profile</div>', unsafe_allow_html=True)
    st.markdown(f"<div style='font-size:1rem; font-weight:700; color:var(--text-main); margin-bottom: 1.5rem;'>👤 {get_display_name(st.session_state['current_user'])}</div>", unsafe_allow_html=True)

    st.markdown('<div class="settings-lbl">Features & Preferences</div>', unsafe_allow_html=True)
    st.session_state['enable_quotes'] = st.toggle("Enable Motivational Quotes", value=st.session_state['enable_quotes'])
    st.session_state['enable_achievements'] = st.toggle("Enable Achievements System", value=st.session_state['enable_achievements'])

    if st.session_state['enable_quotes']:
        with st.expander("Manage Custom Quotes"):
            for q in st.session_state['all_quotes']:
                st.markdown(f"<div style='font-size:0.7rem; color:var(--text-main); margin-bottom:5px;'>• {q}</div>", unsafe_allow_html=True)
            new_quote = st.text_input("Add New Quote", placeholder="Enter quote here...")
            if st.button("Add to Rotation"):
                if new_quote and new_quote not in st.session_state['all_quotes']:
                    st.session_state['all_quotes'].append(new_quote)
                    system_alert("QUOTE INJECTED")
                    st.rerun()

    st.markdown('<div class="settings-lbl" style="margin-top:2.5rem;">Data Analysis Limits</div>', unsafe_allow_html=True)
    new_analysis_start = st.date_input("Trend Analysis Start Date", value=st.session_state['analysis_start_date'])
    
    if st.button("SAVE DATE & RE-CALIBRATE"):
        st.session_state['analysis_start_date'] = new_analysis_start
        st.query_params.start = new_analysis_start.strftime('%Y-%m-%d')
        system_alert("ENGINE RE-CALIBRATED")
        st.rerun()

    st.markdown('<div class="settings-lbl" style="margin-top:2.5rem;">Protocol Configuration</div>', unsafe_allow_html=True)
    edit_goal = st.selectbox("Select Protocol to Modify", list(GOAL_PROFILES.keys()), index=list(GOAL_PROFILES.keys()).index(active_goal))
    p = GOAL_PROFILES[edit_goal]
    with st.form("settings_form", border=False):
        st.markdown(f"<div class='s-head'>Weight Trajectory (kg/mo)</div>", unsafe_allow_html=True)
        w_tgt = st.slider("Target", min_value=-5.0, max_value=5.0, value=float(p['Weight (kg)'][0]), step=0.1, help="Your ideal monthly goal.")
        w_min = st.slider("Lower Bound", min_value=-5.0, max_value=5.0, value=float(p['Weight (kg)'][1]), step=0.1, help="The absolute minimum acceptable monthly pace.")
        w_max = st.slider("Upper Bound", min_value=-5.0, max_value=5.0, value=float(p['Weight (kg)'][2]), step=0.1, help="The absolute maximum acceptable monthly pace.")
        st.markdown(f"<div class='s-head' style='margin-top: 1.5rem;'>Muscle Mass Trajectory (kg/mo)</div>", unsafe_allow_html=True)
        m_tgt = st.slider("Target ", min_value=-2.0, max_value=2.0, value=float(p['Muscle Mass (kg)'][0]), step=0.1)
        m_min = st.slider("Lower Bound ", min_value=-2.0, max_value=2.0, value=float(p['Muscle Mass (kg)'][1]), step=0.1)
        st.markdown(f"<div class='s-head' style='margin-top: 1.5rem;'>Body Fat Trajectory (%/mo)</div>", unsafe_allow_html=True)
        bf_tgt = st.slider("Target  ", min_value=-3.0, max_value=3.0, value=float(p['Body Fat (%)'][0]), step=0.1)
        bf_min = st.slider("Lower Bound  ", min_value=-3.0, max_value=3.0, value=float(p['Body Fat (%)'][1]), step=0.1)
        bf_max = st.slider("Upper Bound  ", min_value=-3.0, max_value=3.0, value=float(p['Body Fat (%)'][2]), step=0.1)
        st.markdown(f"<div class='s-head' style='margin-top: 1.5rem;'>Achievements Engine Start Date</div>", unsafe_allow_html=True)
        new_start = st.date_input("Start Date", value=st.session_state['gym_start_date'])
        
        if st.form_submit_button("SAVE PROTOCOL & SETTINGS", use_container_width=True):
            st.session_state['goal_profiles'][edit_goal] = {
                'Weight (kg)': [w_tgt, w_min, w_max],
                'Muscle Mass (kg)': [m_tgt, m_min],
                'Body Fat (%)': [bf_tgt, bf_min, bf_max]
            }
            st.session_state['gym_start_date'] = new_start
            system_alert("SYSTEM CONFIGURATION SAVED")
            st.rerun()

    if st.session_state.get('is_admin'):
        st.markdown('<div class="settings-lbl" style="margin-top:2.5rem; color:var(--c-rose);">Admin Control</div>', unsafe_allow_html=True)
        if st.button("LOGOUT / SWITCH PROFILE", use_container_width=True):
            st.markdown("<script>localStorage.removeItem('metrics_user');</script>", unsafe_allow_html=True)
            st.session_state['auth_status'] = False
            st.session_state['current_user'] = None
            st.session_state['sheet_url'] = ""
            if 'active_df' in st.session_state:
                del st.session_state['active_df']
            st.query_params.clear()
            st.cache_data.clear()
            st.rerun()
