import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import random
import re
from sklearn.linear_model import LinearRegression
from datetime import datetime, timedelta
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

# ══════════════════════════════════════════════════════════════
# AUTO‑LOGIN FROM HOME SCREEN (localStorage)
# ══════════════════════════════════════════════════════════════
st.markdown("""
<script>
(function() {
    const urlParams = new URLSearchParams(window.location.search);
    if (!urlParams.has('user')) {
        const savedUser = localStorage.getItem('metrics_user');
        if (savedUser) {
            const newUrl = window.location.origin + window.location.pathname + '?user=' + savedUser;
            window.location.replace(newUrl);
        }
    } else {
        localStorage.setItem('metrics_user', urlParams.get('user'));
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
        creds = service_account.Credentials.from_service_account_info(
            credentials_dict,
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        return build('sheets', 'v4', credentials=creds)
    except Exception:
        return None

def extract_sheet_id(url):
    if not url:
        return None
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
    if match:
        return match.group(1)
    if re.match(r'^[a-zA-Z0-9-_]{20,}$', url):
        return url
    return None

def read_gsheet(sheet_url):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id:
        return read_gsheet_csv(sheet_url)
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range='A:E').execute()
        values = result.get('values', [])
        if not values or len(values) < 2:
            return pd.DataFrame(columns=['Date', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)'])
        headers = values[0]
        data = values[1:]
        df = pd.DataFrame(data, columns=headers)
        if 'Time' in df.columns:
            df['DateTime'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Time'].astype(str),
                                            format='mixed', errors='coerce')
            df['Date'] = df['DateTime']
            df = df.drop(columns=['Time', 'DateTime'])
        else:
            df['Date'] = pd.to_datetime(df['Date'], format='mixed', errors='coerce')
        for m in ['Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']:
            if m in df.columns:
                df[m] = pd.to_numeric(df[m], errors='coerce')
            else:
                df[m] = np.nan
        df = df[['Date', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']]
        return df.sort_values('Date').dropna().reset_index(drop=True)
    except HttpError as e:
        st.error(f"Google Sheets API error: {e}")
        st.info("💡 Did you share the sheet with the service account email?")
        return pd.DataFrame(columns=['Date', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)'])

def read_gsheet_csv(sheet_url):
    csv_url = f"https://docs.google.com/spreadsheets/d/{extract_sheet_id(sheet_url)}/export?format=csv"
    try:
        df = pd.read_csv(csv_url)
        df['Date'] = pd.to_datetime(df['Date'], format='mixed')
        for m in ['Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']:
            if m in df.columns:
                df[m] = pd.to_numeric(df[m], errors='coerce')
        return df.sort_values('Date').dropna().reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=['Date', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)'])

def append_to_gsheet(sheet_url, date_str, weight, muscle_mass, body_fat):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id:
        return False
    try:
        time_str = datetime.now().strftime('%H:%M:%S')
        values = [[date_str, time_str, weight, body_fat, muscle_mass]]
        body = {'values': values}
        service.spreadsheets().values().append(
            spreadsheetId=sheet_id, range='A:E',
            valueInputOption='USER_ENTERED', insertDataOption='INSERT_ROWS',
            body=body).execute()
        return True
    except HttpError as e:
        st.error(f"Failed to save to Google Sheets: {e}")
        return False

def overwrite_gsheet(sheet_url, df):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id:
        return False
    try:
        service.spreadsheets().values().clear(spreadsheetId=sheet_id, range='A:Z').execute()
        headers = ['Date', 'Time', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']
        values = [headers]
        for _, row in df.iterrows():
            date_val = pd.Timestamp(row['Date'])
            values.append([
                date_val.strftime('%Y-%m-%d'),
                date_val.strftime('%H:%M:%S'),
                float(row['Weight (kg)']),
                float(row['Body Fat (%)']),
                float(row['Muscle Mass (kg)'])
            ])
        body = {'values': values}
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id, range='A:E',
            valueInputOption='USER_ENTERED', body=body).execute()
        return True
    except HttpError as e:
        st.error(f"Failed to update Google Sheets: {e}")
        return False

# ══════════════════════════════════════════════════════════════
# USER SETUP (WITH OPTIONAL SECRET USER KEYS)
# ══════════════════════════════════════════════════════════════
dan_url = st.secrets.get("daniel_gsheets_url", "")
bram_url = st.secrets.get("bram_gsheets_url", "")
LOGOUT_PASSWORD = st.secrets.get("switch_password", "")

if not dan_url or not bram_url:
    st.error("❌ Missing sheet URLs in secrets. Add `daniel_gsheets_url` and `bram_gsheets_url`.")
    st.stop()

# Optional complex keys – if not set, fall back to "Daniel" / "Bram"
dan_key = st.secrets.get("daniel_user_key", "Daniel")
bram_key = st.secrets.get("bram_user_key", "Bram")

# Build mappings
USER_DATA = {
    dan_key: dan_url,
    bram_key: bram_url
}
LABEL_TO_KEY = {
    "Daniel": dan_key,
    "Bram": bram_key
}
KEY_TO_LABEL = {v: k for k, v in LABEL_TO_KEY.items()}

def get_display_name(user_key):
    return KEY_TO_LABEL.get(user_key, user_key)

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
# INITIALIZE SESSION STATE
# ══════════════════════════════════════════════════════════════
if 'users' not in st.session_state: st.session_state['users'] = USER_DATA
if 'auth_status' not in st.session_state: st.session_state['auth_status'] = False
if 'current_user' not in st.session_state: st.session_state['current_user'] = None
if 'sheet_url' not in st.session_state: st.session_state['sheet_url'] = ""
if 'gsheets_available' not in st.session_state:
    st.session_state['gsheets_available'] = get_google_sheets_service() is not None

if 'all_quotes' not in st.session_state: st.session_state['all_quotes'] = DEFAULT_QUOTES
if 'enable_quotes' not in st.session_state: st.session_state['enable_quotes'] = True
if 'enable_achievements' not in st.session_state: st.session_state['enable_achievements'] = True
if 'gym_start_date' not in st.session_state: st.session_state['gym_start_date'] = datetime(2026, 3, 17).date()

if 'goal_profiles' not in st.session_state:
    st.session_state['goal_profiles'] = {
        "Aggressive Cut":  {'Weight (kg)': [-3.0, -4.0, -2.0], 'Muscle Mass (kg)': [-0.2, -0.5], 'Body Fat (%)': [-1.2, -1.8, -0.6]},
        "Lean Cut":        {'Weight (kg)': [-1.5, -2.0, -1.0], 'Muscle Mass (kg)': [0.0, -0.1],  'Body Fat (%)': [-0.6, -1.0, -0.3]},
        "Recomposition":   {'Weight (kg)': [0.0, -0.5, 0.5],   'Muscle Mass (kg)': [0.3, 0.1],   'Body Fat (%)': [-0.4, -0.8, -0.1]},
        "Lean Bulk":       {'Weight (kg)': [1.0, 0.5, 1.5],    'Muscle Mass (kg)': [0.6, 0.3],   'Body Fat (%)': [0.1, -0.1, 0.4]},
        "Aggressive Bulk": {'Weight (kg)': [2.5, 2.0, 3.5],    'Muscle Mass (kg)': [0.8, 0.5],   'Body Fat (%)': [0.6, 0.3, 1.0]},
    }

# ══════════════════════════════════════════════════════════════
# OBSIDIAN THEME CSS (unchanged)
# ══════════════════════════════════════════════════════════════
css = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700;800&display=swap');

:root {
    --bg-primary: #18181B; --text-main: #FFFFFF; --text-muted: rgba(255,255,255,0.5); --text-subtle: rgba(255,255,255,0.4);
    --surface: rgba(255,255,255,0.04); --surface-active: rgba(255,255,255,0.12);
    --border: rgba(255,255,255,0.08); --border-strong: rgba(255,255,255,0.2);
    --c-emerald: #10B981; --c-amber: #F59E0B; --c-rose: #EF4444; --c-blue: #3B82F6;
    --bg-emerald: rgba(16, 185, 129, 0.15); --bg-amber: rgba(245, 158, 11, 0.15); --bg-rose: rgba(239, 68, 68, 0.15);
}

@media (prefers-color-scheme: light) {
    :root {
        --bg-primary: #F4F4F5; --text-main: #09090B; --text-muted: rgba(0,0,0,0.6); --text-subtle: rgba(0,0,0,0.5);
        --surface: #FFFFFF; --surface-active: rgba(0,0,0,0.08); --border: rgba(0,0,0,0.1); --border-strong: rgba(0,0,0,0.25);
        --c-emerald: #059669; --c-amber: #D97706; --c-rose: #DC2626; --c-blue: #2563EB;
        --bg-emerald: rgba(5, 150, 105, 0.1); --bg-amber: rgba(217, 119, 6, 0.1); --bg-rose: rgba(220, 38, 38, 0.1);
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
.live-pill { display: flex; align-items: center; gap: 6px; background: var(--bg-emerald); border-radius: 4px; padding: 4px 8px; font-family: 'JetBrains Mono', monospace; font-size: 0.55rem; color: var(--c-emerald); font-weight: 600; letter-spacing: 1px; }
.pdot { width: 4px; height: 4px; border-radius: 50%; background: var(--c-emerald); animation: pulse 2s infinite; }
@keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.3; } 100% { opacity: 1; } }

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
.bg-ok  { background: var(--bg-emerald) !important; border: 1px solid rgba(16, 185, 129, 0.2) !important; }
.bg-wrn { background: var(--bg-amber) !important; border: 1px solid rgba(245, 158, 11, 0.2) !important; }
.bg-err { background: var(--bg-rose) !important; border: 1px solid rgba(239, 68, 68, 0.2) !important; }

.chart-blk { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 0.6rem 0.8rem; margin-bottom: 0.6rem; }
.chart-meta { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 0.2rem; }
.chart-val { font-family: 'JetBrains Mono', monospace; font-size: 1.4rem; font-weight: 700; color: var(--text-main); line-height: 1; margin-top: 2px;}
.chart-unit { font-size: 0.7rem; color: var(--text-subtle); font-weight: 500; }
.t-chip { font-family: 'JetBrains Mono', monospace; font-size: 0.55rem; padding: 3px 6px; border-radius: 4px; font-weight: 600; display: inline-block; }

.hud-card { display: flex; gap: 12px; align-items: center; background: var(--surface); border: 1px solid var(--border); padding: 1rem; border-radius: 10px; margin-bottom: 0.5rem; }
.hud-icon { font-size: 1.2rem; width: 35px; height: 35px; display: flex; align-items: center; justify-content: center; border-radius: 8px; background: var(--surface-active); flex-shrink: 0; line-height: 1; }
.hud-title { font-size: 0.85rem; color: var(--text-main); font-weight: 700; text-transform: uppercase; }
.hud-desc { font-size: 0.75rem; color: var(--text-muted); line-height: 1.4; margin-top: 2px;}

.tj-row { display: flex; justify-content: space-between; margin-bottom: 6px; align-items: flex-end; }
.tj-nm { font-size: 0.85rem; color: var(--text-main); font-weight: 600; text-transform: uppercase; }
.tj-nn { font-family: 'JetBrains Mono', monospace; font-size: 0.6rem; color: var(--text-muted); }
.bar-tk { height: 18px; border-radius: 9px; overflow: hidden; margin-bottom: 4px; position: relative; border: 1px solid rgba(255,255,255,0.05);}
.bar-pin { position: absolute; top: 0; bottom: 0; width: 4px; background: #FFFFFF; box-shadow: 0 0 8px #FFFFFF; z-index: 5; transform: translateX(-50%); border-radius: 2px;}
.tj-st { font-family: 'JetBrains Mono', monospace; font-size: 0.55rem; font-weight: 700; letter-spacing: 0.5px; text-transform: uppercase; display: block; margin-top:10px;}

.tier-item { display: flex; align-items: center; gap: 15px; padding: 12px; border-radius: 12px; margin-bottom: 8px; background: var(--surface); border: 1px solid var(--border); }
.tier-item.completed { background: rgba(16, 185, 129, 0.05); border: 1px solid rgba(16, 185, 129, 0.3); }
.tier-item.completed .tier-name { color: var(--c-emerald); }
.tier-item.current { background: var(--bg-emerald); border: 1px solid var(--c-emerald); box-shadow: 0 4px 20px rgba(16, 185, 129, 0.15); }
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

div[data-testid="stSelectbox"] > div > div { background: var(--surface) !important; border: 1px solid var(--border-strong) !important; border-radius: 8px !important; color: var(--text-main) !important; display: flex !important; align-items: center !important; justify-content: center !important; min-height: 3.5rem !important; padding: 0 !important;}

div[data-testid="stForm"] button, .stButton>button {
    background: var(--text-main) !important; color: var(--bg-primary) !important; 
    font-family: 'Inter', sans-serif !important; font-weight: 800 !important; font-size: 0.95rem !important; 
    border: none !important; border-radius: 12px !important; padding: 1rem !important; margin-top: 1.5rem !important;
    transition: transform 0.1s ease !important; text-transform: uppercase !important; letter-spacing: 1px !important;
}
.stButton>button { border: 2px solid var(--border-strong) !important; background: var(--surface) !important; color: var(--text-main) !important; padding: 2.5rem 1rem !important; font-size: 1.5rem !important; margin-top: 0 !important; }
div[data-testid="stDateInput"] > div > div { background: var(--surface) !important; border: 1px solid var(--border-strong) !important; border-radius: 8px !important; color: var(--text-main) !important; height: 3rem !important; }
[data-testid="stDataFrame"] { border-radius: 8px; border: 1px solid var(--border); }
div[data-testid="stForm"] { margin-bottom: 1rem !important; }
</style>
"""
st.markdown(f'<style>{css}</style>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# AUTO‑LOGIN via URL parameter (uses complex keys if set)
# ══════════════════════════════════════════════════════════════
if not st.session_state['auth_status']:
    saved_user = st.query_params.get("user", None)
    if saved_user and saved_user in USER_DATA:
        st.session_state['auth_status'] = True
        st.session_state['current_user'] = saved_user
        st.session_state['sheet_url'] = USER_DATA[saved_user]
    elif saved_user and saved_user not in USER_DATA:
        st.query_params.clear()
        st.rerun()

# ══════════════════════════════════════════════════════════════
# PROFILE SELECTION (buttons use display names, URL uses complex key)
# ══════════════════════════════════════════════════════════════
if not st.session_state['auth_status']:
    st.markdown("""
    <div class="app-bar" style="border:none; justify-content:center; margin-top:3rem;">
        <div style="text-align:center;">
            <div class="wordmark">METRICS</div>
            <div class="tagline">Data Engine V23</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div class='s-head' style='text-align:center; margin-bottom: 2rem;'>SELECT PROFILE</div>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("DANIEL", key="btn_dan", use_container_width=True):
            key = LABEL_TO_KEY["Daniel"]
            st.session_state['auth_status'] = True
            st.session_state['current_user'] = key
            st.session_state['sheet_url'] = USER_DATA[key]
            st.query_params.user = key
            st.rerun()
    with col2:
        if st.button("BRAM", key="btn_bram", use_container_width=True):
            key = LABEL_TO_KEY["Bram"]
            st.session_state['auth_status'] = True
            st.session_state['current_user'] = key
            st.session_state['sheet_url'] = USER_DATA[key]
            st.query_params.user = key
            st.rerun()
    st.stop()

# ══════════════════════════════════════════════════════════════
# MATH ENGINE & GLOBAL HELPERS (unchanged)
# ══════════════════════════════════════════════════════════════
def sgn(v): return "+" if v > 0 else ""
def dclass(v, invert=False):
    if invert: v = -v
    return "c-ok" if v > 0 else ("c-err" if v < 0 else "c-neu")
def eval_metric(metric, actual, profile):
    if metric == 'Muscle Mass (kg)':
        tgt, lower = profile[metric][:2]
        if actual >= tgt: return ('c-ok', 'bg-ok', 'EXCEPTIONAL', 'var(--c-emerald)')
        if actual >= lower: return ('c-wrn', 'bg-wrn', 'LAGGING', 'var(--c-amber)')
        return ('c-err', 'bg-err', 'SUB-OPTIMAL', 'var(--c-rose)')
    tgt, lower, upper = profile[metric]
    if actual > upper: return ('c-err', 'bg-err', 'EXCEEDING LIMIT', 'var(--c-rose)')
    if actual < lower: return ('c-wrn', 'bg-wrn', 'BELOW TARGET', 'var(--c-amber)')
    return ('c-ok', 'bg-ok', 'OPTIMAL RANGE', 'var(--c-emerald)')

def get_gradient(metric, profile, max_mag):
    c_g = "rgba(16, 185, 129, 0.85)"; c_o = "rgba(245, 158, 11, 0.85)"; c_r = "rgba(239, 68, 68, 0.85)"
    if metric == 'Muscle Mass (kg)':
        tgt, lower = profile[metric][:2]
        p_l = min(abs(lower) / max_mag * 100, 100)
        p_t = min(abs(tgt) / max_mag * 100, 100)
        return f"linear-gradient(to right, {c_r} 0%, {c_r} {p_l}%, {c_o} {p_l}%, {c_o} {p_t}%, {c_g} {p_t}%, {c_g} 100%)"
    else:
        tgt, lower, upper = profile[metric]
        if tgt == 0.0:
            p_max = max(abs(lower), abs(upper)) / max_mag * 100
            return f"linear-gradient(to right, {c_g} 0%, {c_g} {p_max}%, {c_r} {p_max}%, {c_r} 100%)"
        p_min = min(abs(lower), abs(upper)) / max_mag * 100
        p_max = max(abs(lower), abs(upper)) / max_mag * 100
        return f"linear-gradient(to right, {c_o} 0%, {c_o} {p_min}%, {c_g} {p_min}%, {c_g} {p_max}%, {c_r} {p_max}%, {c_r} 100%)"

def hud_card(kind, icon, title, desc):
    return f"""<div class="hud-card" style="border-left: 3px solid var(--{kind});"><div class="hud-icon {kind}">{icon}</div><div><div class="hud-title {kind}">{title}</div><div class="hud-desc">{desc}</div></div></div>"""

def traj_bar(label, actual, metric, profile, unit):
    tgt = profile[metric][0]
    s = sgn(actual); ts = sgn(tgt)
    c_txt, c_bg, status, hex_col = eval_metric(metric, actual, profile)
    if metric == 'Muscle Mass (kg)':
        max_bound = max(abs(profile[metric][1]), abs(tgt), 0.1) * 2.5
        pos_min = min((abs(profile[metric][1]) / max_bound) * 100, 95)
        pos_tgt = min((abs(tgt) / max_bound) * 100, 95)
        bounds_html = f"<div style='position:relative; height:12px; font-family:\"JetBrains Mono\", monospace; font-size:0.55rem; color:var(--text-subtle); margin-top:2px;'><span style='position:absolute; left:{pos_min}%; transform:translateX(-50%);'>MIN {profile[metric][1]:.1f}</span><span style='position:absolute; left:{pos_tgt}%; transform:translateX(-50%); color:var(--text-main); font-weight:700;'>TARGET {tgt:.1f}</span><span style='position:absolute; right:0;'>MAX ∞</span></div>"
    else:
        max_bound = max(abs(profile[metric][1]), abs(profile[metric][2]), abs(tgt), 0.1) * 2.5
        pos_b1 = min((abs(profile[metric][1]) / max_bound) * 100, 95)
        pos_tgt = min((abs(tgt) / max_bound) * 100, 95)
        pos_b2 = min((abs(profile[metric][2]) / max_bound) * 100, 95)
        bounds_html = f"<div style='position:relative; height:12px; font-family:\"JetBrains Mono\", monospace; font-size:0.55rem; color:var(--text-subtle); margin-top:2px;'><span style='position:absolute; left:{pos_b1}%; transform:translateX(-50%);'>MIN {profile[metric][1]:.1f}</span><span style='position:absolute; left:{pos_tgt}%; transform:translateX(-50%); color:var(--text-main); font-weight:700;'>TARGET {tgt:.1f}</span><span style='position:absolute; left:{pos_b2}%; transform:translateX(-50%);'>MAX {profile[metric][2]:.1f}</span></div>"
    pct = min((abs(actual) / max_bound) * 100, 100)
    pct = max(pct, 2)
    bg_grad = get_gradient(metric, profile, max_bound)
    return f"<div class='tj-blk' style='margin-bottom: 1.5rem;'><div class='tj-row'><span class='tj-nm'>{label}</span><span class='tj-nn'>ACTUAL {s}{actual:.2f} | TARGET {ts}{tgt:.2f} {unit}</span></div><div class='bar-tk' style='background: {bg_grad};'><div class='bar-pin' style='left: {pct}%;'></div></div>{bounds_html}<div class='tj-st {c_txt}'>{status}</div></div>"

# ══════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=60, show_spinner=False)
def load_data(url):
    if not url:
        raise Exception("URL Missing")
    df = read_gsheet(url)
    if df.empty:
        raise Exception("No data found in sheet – check sharing permissions and URL.")
    return df

try:
    df = load_data(st.session_state['sheet_url'])
    if 'active_df' not in st.session_state:
        st.session_state['active_df'] = df
except Exception as e:
    st.error(f"System Error: Could not load data. {str(e)}")
    if st.button("Reset Login"):
        st.session_state['auth_status'] = False
        st.query_params.clear()
        st.cache_data.clear()
        st.rerun()
    st.stop()

df = st.session_state['active_df']
GOAL_PROFILES = st.session_state['goal_profiles']
METRICS = ['Weight (kg)', 'Muscle Mass (kg)', 'Body Fat (%)']
METRIC_SHORT = {'Weight (kg)': 'BODY WEIGHT', 'Muscle Mass (kg)': 'MUSCLE MASS', 'Body Fat (%)': 'BODY FAT'}
METRIC_UNIT  = {'Weight (kg)': 'kg', 'Muscle Mass (kg)': 'kg', 'Body Fat (%)': '%'}

has_enough_data = len(df) >= 3
if has_enough_data:
    cutoff = df['Date'].max() - timedelta(days=45)
    recent_df = df[df['Date'] >= cutoff]
    if len(recent_df) < 4: recent_df = df.tail(5)
    recent_days  = recent_df['Date'].map(lambda d: (d - df['Date'].min()).days).values.reshape(-1, 1)
    future_days  = np.array([[(df['Date'].max() - df['Date'].min()).days + i] for i in range(1, 61)])
    future_dates = [df['Date'].max() + timedelta(days=i) for i in range(1, 61)]
    monthly_trends, traj_data = {}, {}
    for m in METRICS:
        model = LinearRegression().fit(recent_days, recent_df[m].values)
        monthly_trends[m] = model.coef_[0] * 30
        traj_data[m] = {'dates': list(recent_df['Date']) + future_dates,
                        'preds': model.predict(np.vstack((recent_days, future_days)))}

# ══════════════════════════════════════════════════════════════
# MAIN ROUTING ENGINE
# ══════════════════════════════════════════════════════════════
active_goal = st.session_state.get('current_goal', 'Lean Bulk')
ideal_rates = GOAL_PROFILES[active_goal]

header_placeholder = st.empty()
app_view = st.segmented_control("Nav", ["Entry", "Analysis", "Trends", "Data", "Settings"],
                                default="Entry", label_visibility="collapsed")

if app_view == "Entry":
    header_placeholder.markdown(f"""
    <div class="app-bar">
        <div>
            <div class="wordmark">METRICS</div>
            <div class="tagline">Data Engine V23 | {get_display_name(st.session_state['current_user'])}</div>
        </div>
        <div class="live-pill"><span class="pdot"></span>SYNCED</div>
    </div>
    """, unsafe_allow_html=True)

    if st.session_state['enable_quotes']:
        if 'daily_quote' not in st.session_state:
            st.session_state['daily_quote'] = random.choice(st.session_state['all_quotes'])
        st.markdown(f"<div class='quote-box'><div class='quote-text'>\"{st.session_state['daily_quote']}\"</div></div>", unsafe_allow_html=True)

    st.session_state['current_goal'] = st.selectbox("Protocol", list(GOAL_PROFILES.keys()),
                                                    index=list(GOAL_PROFILES.keys()).index(active_goal))
    if len(df) > 0:
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last
    else:
        last = pd.Series({'Weight (kg)': 70.0, 'Body Fat (%)': 15.0, 'Muscle Mass (kg)': 35.0})
        prev = last

    if len(df) > 0:
        recent_bf_avg = df.tail(7)['Body Fat (%)'].mean()
        if "Bulk" in st.session_state['current_goal'] and recent_bf_avg > 18.0:
            st.markdown(f"<div style='margin-top:-10px; margin-bottom:15px; font-size:0.7rem; color:var(--c-rose); font-weight:600;'><span>⚠️</span> WARNING: HIGH FAT FOR BULK ({recent_bf_avg:.1f}% AVG)</div>", unsafe_allow_html=True)
        elif "Cut" in st.session_state['current_goal'] and recent_bf_avg < 10.0:
            st.markdown(f"<div style='margin-top:-10px; margin-bottom:15px; font-size:0.7rem; color:var(--c-rose); font-weight:600;'><span>⚠️</span> WARNING: TOO LEAN FOR CUT ({recent_bf_avg:.1f}% AVG)</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div style='margin-top:-10px; margin-bottom:15px; font-size:0.7rem; color:var(--c-emerald); font-weight:600;'><span>✓</span> VALID FOR CURRENT BODY COMPOSITION ({recent_bf_avg:.1f}% AVG FAT)</div>", unsafe_allow_html=True)

    delta_w = last['Weight (kg)'] - prev['Weight (kg)']
    delta_bf = last['Body Fat (%)'] - prev['Body Fat (%)']
    delta_m = last['Muscle Mass (kg)'] - prev['Muscle Mass (kg)']

    st.markdown(f"""
    <div class="mini-grid">
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
            success = append_to_gsheet(st.session_state['sheet_url'], date_str, w, m, bf)
            new_row = pd.DataFrame({'Date': [now], 'Weight (kg)': [w], 'Body Fat (%)': [bf], 'Muscle Mass (kg)': [m]})
            st.session_state['active_df'] = pd.concat([st.session_state['active_df'], new_row], ignore_index=True)
            load_data.clear()
            if success:
                st.success("✅ Record saved to Google Sheets!")
            else:
                st.warning("⚠️ Record saved locally only.")
            if st.session_state['enable_quotes']:
                st.session_state['daily_quote'] = random.choice(st.session_state['all_quotes'])
            st.rerun()

# (Analysis, Trends, Data tabs are identical to previous complete versions – no login changes)

elif app_view == "Settings":
    header_placeholder.empty()

    # ── TEMPORARY DEBUG ──
    st.write(f"🔍 Debug: LOGOUT_PASSWORD is set: {bool(LOGOUT_PASSWORD)}")
    # ─────────────────────

    if st.session_state['gsheets_available']:
        st.markdown(f"<div style='font-size:0.7rem; color:var(--c-emerald); margin-bottom:1rem;'>🟢 Google Sheets API Connected</div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<div style='font-size:0.7rem; color:var(--c-amber); margin-bottom:1rem;'>🟡 Google Sheets API Not Connected</div>", unsafe_allow_html=True)

    st.markdown('<div class="settings-lbl" style="margin-top:0;">Profile</div>', unsafe_allow_html=True)
    st.markdown(f"**Current User:** {get_display_name(st.session_state['current_user'])}")

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
                    st.rerun()

    st.markdown('<div class="settings-lbl" style="margin-top:2.5rem;">Protocol Configuration</div>', unsafe_allow_html=True)
    edit_goal = st.selectbox("Select Protocol to Modify", list(GOAL_PROFILES.keys()), index=list(GOAL_PROFILES.keys()).index(active_goal))
    p = GOAL_PROFILES[edit_goal]
    with st.form("settings_form", border=False):
        st.markdown(f"<div class='s-head'>Weight Trajectory (kg/mo)</div>", unsafe_allow_html=True)
        w_tgt = st.slider("Target", min_value=-5.0, max_value=5.0, value=float(p['Weight (kg)'][0]), step=0.1)
        w_min = st.slider("Lower Bound", min_value=-5.0, max_value=5.0, value=float(p['Weight (kg)'][1]), step=0.1)
        w_max = st.slider("Upper Bound", min_value=-5.0, max_value=5.0, value=float(p['Weight (kg)'][2]), step=0.1)
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
            st.success("✅ Protocol updated!")
            st.rerun()

    # ── PASSWORD‑PROTECTED LOGOUT (FIXED) ──
    st.markdown('<div class="settings-lbl" style="margin-top:2.5rem; color:var(--c-rose);">System Control</div>', unsafe_allow_html=True)

    if st.session_state['current_user'] != dan_key:
        if not LOGOUT_PASSWORD:
            st.error("❌ Logout password is missing in secrets. Contact the admin.")
            st.stop()
        logout_password = st.text_input("Enter password to switch user", type="password")
    else:
        logout_password = None

    if st.button("LOGOUT / SWITCH PROFILE", use_container_width=True):
        if st.session_state['current_user'] != dan_key:
            if logout_password != LOGOUT_PASSWORD:
                st.error("Incorrect password. Access denied.")
            else:
                # Password correct – proceed with logout
                st.markdown("<script>localStorage.removeItem('metrics_user');</script>", unsafe_allow_html=True)
                st.session_state['auth_status'] = False
                st.session_state['current_user'] = None
                if 'active_df' in st.session_state:
                    del st.session_state['active_df']
                st.query_params.clear()
                st.cache_data.clear()
                st.rerun()
        else:
            # Daniel – logout directly
            st.markdown("<script>localStorage.removeItem('metrics_user');</script>", unsafe_allow_html=True)
            st.session_state['auth_status'] = False
            st.session_state['current_user'] = None
            if 'active_df' in st.session_state:
                del st.session_state['active_df']
            st.query_params.clear()
            st.cache_data.clear()
            st.rerun()
