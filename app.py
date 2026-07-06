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
    page_title="METRICS | Beta",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# ══════════════════════════════════════════════════════════════
# GLOBAL HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════
def system_alert(message, kind="ok"):
    bg = "#10B981" if kind == "ok" else "#EF4444"
    ph = st.empty()
    html_str = f"<div style='position:fixed; top:30px; left:50%; transform:translateX(-50%); background:{bg}; color:#FFFFFF; padding:14px 36px; border-radius:100px; font-weight:800; font-family:\"DM Sans\", sans-serif; z-index:99999; box-shadow: 0 8px 32px rgba(0,0,0,0.25); text-transform:uppercase; letter-spacing:2px; font-size: 0.78rem;'>{message}</div>"
    ph.markdown(html_str, unsafe_allow_html=True)
    time.sleep(1.2)
    ph.empty()

def sgn(v): 
    return "+" if v > 0 else ""

def dclass(v, invert=False): 
    if invert:
        if v < 0: return "c-ok"
        elif v > 0: return "c-err"
        else: return "c-neu"
    else:
        if v > 0: return "c-ok"
        elif v < 0: return "c-err"
        else: return "c-neu"

def eval_metric(metric, actual, profile, mmt=None, bft=None):
    tgt, lower, upper = profile[metric] if len(profile[metric]) == 3 else (profile[metric][0], profile[metric][1], float('inf'))
    
    if metric == 'Weight (kg)':
        if mmt is not None and bft is not None:
            if actual > upper and mmt >= (actual * 0.4) and bft <= 0.2:
                return ('c-ok', 'bg-ok', 'MUSCLE DRIVEN', 'var(--c-emerald)')
            bf_lower = profile.get('Body Fat (%)', [0, lower])[1] if isinstance(profile, dict) else lower
            if actual < lower and mmt >= -0.2 and bft < bf_lower:
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

def traj_bar(label, actual_rate, metric, profile, unit, mmt=None, bft=None, err_rate=0):
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

    err_pct_width = (err_rate / (2 * max_bound)) * 100 if max_bound > 0 else 0
    err_left = max(0, pct - err_pct_width)
    err_right = min(100, pct + err_pct_width)
    actual_err_width = err_right - err_left
    
    # Highly visible horizontal error bar
    err_html = f"<div style='position:absolute; top:4px; bottom:4px; left:{err_left}%; width:{actual_err_width}%; background:var(--text-main); opacity:0.85; z-index:4; border-radius:2px;'></div>"

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
        {err_html}
        <div class='bar-pin' style='left: {pct}%;'></div>
      </div>
      {bounds_html}
      <div class='tj-st {c_txt}'>{status}</div>
    </div>"""
    return html_block

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

ACTIVITY_MULTIPLIERS = {
    "Sedentary (Office job)": 1.2, 
    "Light (1-3 days/wk)": 1.375, 
    "Moderate (3-5 days/wk)": 1.55, 
    "Active (6-7 days/wk)": 1.725, 
    "Athlete (2x/day)": 1.9
}
DEFAULT_SETTINGS = {
    "goal": "Lean Bulk",
    "theme": "System",
    "activity": "Moderate (3-5 days/wk)",
    "calorie_offset": 0,
    "calorie_custom": 0,
    "protein_custom": 160,
    "analysis_start": "2026-06-26",
    "target_end": "2026-09-01",
    "gym_start": "2026-03-17",
    "muscle_mass_input_mode": "Percentage (%)",
    "enable_quotes": True,
    "enable_achievements": True,
}

MUSCLE_INPUT_MODES = ["Percentage (%)", "Kilograms (kg)"]

def parse_int_setting(value, default=0):
    try:
        if value in (None, ""): return int(default)
        return int(float(value))
    except (TypeError, ValueError): return int(default)

def parse_bool_setting(value, default=True):
    if isinstance(value, bool): return value
    if value in (None, ""): return bool(default)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"): return True
    if text in ("0", "false", "no", "n", "off"): return False
    return bool(default)

def parse_date_setting(value, default_value):
    try: return pd.to_datetime(value if value not in (None, "") else default_value).date()
    except Exception: return pd.to_datetime(default_value).date()

def scale_rate_profile(profile, factor):
    return {metric: [v * factor for v in values] for metric, values in profile.items()}

def elapsed_days(date_series):
    dates = pd.to_datetime(date_series)
    values = (dates - dates.min()).dt.total_seconds().to_numpy(dtype=float) / 86400.0
    if len(values) > 1 and np.nanmax(values) - np.nanmin(values) <= 0:
        values = np.arange(len(values), dtype=float)
    return values

# ══════════════════════════════════════════════════════════════
# AUTO‑LOGIN & PERMANENT STORAGE ENGINE
# ══════════════════════════════════════════════════════════════
st.markdown("""
<script>
(function() {
    const urlParams = new URLSearchParams(window.location.search);
    let redirect = false;
    const keys = ['user', 'goal', 'start', 'end', 'theme', 'activity', 'protein_custom', 'calorie_offset', 'calorie_custom', 'gym_start', 'mm_mode', 'enable_quotes', 'enable_achievements'];
    keys.forEach(k => {
        const sk = 'metrics_' + k;
        const val = localStorage.getItem(sk);
        if (val && !urlParams.has(k)) { urlParams.set(k, val); redirect = true; } 
        else if (urlParams.has(k)) { localStorage.setItem(sk, urlParams.get(k)); }
    });
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
    except Exception: return None

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
    except HttpError: return pd.DataFrame()

def load_body_constants(sheet_url):
    df = read_sheet_range(sheet_url, 'Body!A:C')
    if df.empty: return {'height': 180.0, 'gender': 'male', 'age': 25}
    try:
        row = df.iloc[0]
        h = float(row.iloc[0]) if len(row) > 0 else 180.0
        g = str(row.iloc[1]).lower().strip() if len(row) > 1 else 'male'
        a = int(float(row.iloc[2])) if len(row) > 2 else 25
        return {'height': h, 'gender': g, 'age': a}
    except: return {'height': 180.0, 'gender': 'male', 'age': 25}

def load_body_data(sheet_url):
    df = read_sheet_range(sheet_url, 'Data!A:E')
    if df.empty: return pd.DataFrame(columns=['Date', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)'])
    if 'Time' in df.columns: df['Date'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Time'].astype(str), format='mixed', errors='coerce')
    else: df['Date'] = pd.to_datetime(df['Date'], format='mixed', errors='coerce')
    for m in ['Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']:
        if m in df.columns: df[m] = pd.to_numeric(df[m], errors='coerce')
        else: df[m] = np.nan
    return df[['Date', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']].sort_values('Date').dropna().reset_index(drop=True)

def append_to_sheet(sheet_url, range_name, values):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id: return False
    try:
        body = {'values': values}
        service.spreadsheets().values().append(spreadsheetId=sheet_id, range=range_name, valueInputOption='USER_ENTERED', insertDataOption='INSERT_ROWS', body=body).execute()
        return True
    except HttpError: return False

def append_body_entry(sheet_url, date_str, weight, muscle_mass, body_fat):
    time_str = (datetime.utcnow() + timedelta(hours=2)).strftime('%H:%M:%S')
    return append_to_sheet(sheet_url, 'Data!A:E', [[date_str, time_str, weight, body_fat, muscle_mass]])

def overwrite_sheet_range(sheet_url, range_name, df):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id: return False
    try:
        service.spreadsheets().values().clear(spreadsheetId=sheet_id, range=range_name).execute()
        values = [df.columns.tolist()] + df.values.tolist()
        body = {'values': values}
        service.spreadsheets().values().update(spreadsheetId=sheet_id, range=range_name, valueInputOption='USER_ENTERED', body=body).execute()
        return True
    except HttpError: return False

def overwrite_body_sheet(sheet_url, df):
    values = [['Date', 'Time', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']]
    for _, row in df.iterrows():
        d = pd.Timestamp(row['Date'])
        values.append([d.strftime('%Y-%m-%d'), d.strftime('%H:%M:%S'), float(row['Weight (kg)']), float(row['Body Fat (%)']), float(row['Muscle Mass (kg)'])])
    out_df = pd.DataFrame(values[1:], columns=values[0])
    return overwrite_sheet_range(sheet_url, 'Data!A:E', out_df)

def ensure_sheet_tab(sheet_url, tab_name):
    service = get_google_sheets_service()
    sheet_id = extract_sheet_id(sheet_url)
    if not service or not sheet_id: return False
    try:
        meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        titles = [s.get('properties', {}).get('title') for s in meta.get('sheets', [])]
        if tab_name not in titles:
            service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={'requests': [{'addSheet': {'properties': {'title': tab_name}}}]}).execute()
        return True
    except HttpError: return False

def load_app_settings(sheet_url):
    df_settings = read_sheet_range(sheet_url, 'Settings!A:B')
    if df_settings.empty: return {}
    loaded = {}
    for _, row in df_settings.iterrows():
        if len(row) < 2: continue
        key = str(row.iloc[0]).strip()
        value = row.iloc[1]
        if key: loaded[key] = value
    return loaded

def write_app_settings(sheet_url, settings):
    if not ensure_sheet_tab(sheet_url, 'Settings'): return False
    settings_df = pd.DataFrame([{'Setting': key, 'Value': str(value)} for key, value in settings.items()])
    return overwrite_sheet_range(sheet_url, 'Settings!A:B', settings_df)

def collect_app_settings():
    def fmt_date(value, fallback): return parse_date_setting(value, fallback).strftime('%Y-%m-%d')
    return {
        'goal': st.session_state.get('current_goal', DEFAULT_SETTINGS['goal']),
        'theme': st.session_state.get('theme_pref', DEFAULT_SETTINGS['theme']),
        'activity': st.session_state.get('activity_level', DEFAULT_SETTINGS['activity']),
        'calorie_offset': parse_int_setting(st.session_state.get('calorie_offset'), 0),
        'calorie_custom': parse_int_setting(st.session_state.get('calorie_custom'), 0),
        'protein_custom': parse_int_setting(st.session_state.get('protein_custom'), DEFAULT_SETTINGS['protein_custom']),
        'analysis_start': fmt_date(st.session_state.get('analysis_start_date'), DEFAULT_SETTINGS['analysis_start']),
        'target_end': fmt_date(st.session_state.get('target_end_date'), DEFAULT_SETTINGS['target_end']),
        'gym_start': fmt_date(st.session_state.get('gym_start_date'), DEFAULT_SETTINGS['gym_start']),
        'muscle_mass_input_mode': st.session_state.get('muscle_mass_input_mode', DEFAULT_SETTINGS['muscle_mass_input_mode']),
        'enable_quotes': parse_bool_setting(st.session_state.get('enable_quotes'), True),
        'enable_achievements': parse_bool_setting(st.session_state.get('enable_achievements'), True),
    }

def sync_query_params_from_settings():
    settings = collect_app_settings()
    st.query_params.goal = settings['goal']
    st.query_params.theme = settings['theme']
    st.query_params.activity = settings['activity']
    st.query_params.protein_custom = str(settings['protein_custom'])
    st.query_params.calorie_offset = str(settings['calorie_offset'])
    st.query_params.calorie_custom = str(settings['calorie_custom'])
    st.query_params.start = settings['analysis_start']
    st.query_params.end = settings['target_end']
    st.query_params.gym_start = settings['gym_start']
    st.query_params.mm_mode = settings['muscle_mass_input_mode']
    st.query_params.enable_quotes = "1" if settings['enable_quotes'] else "0"
    st.query_params.enable_achievements = "1" if settings['enable_achievements'] else "0"

def persist_app_settings(sheet_url):
    sync_query_params_from_settings()
    return write_app_settings(sheet_url, collect_app_settings())

def apply_loaded_settings(settings):
    if not settings: return False
    changed = False

    def assign(key, value):
        nonlocal changed
        if st.session_state.get(key) != value:
            st.session_state[key] = value
            changed = True

    loaded_goal = settings.get('goal', settings.get('current_goal', st.session_state.get('current_goal', DEFAULT_SETTINGS['goal'])))
    if loaded_goal in st.session_state.get('goal_profiles', DEFAULT_PROFILES): assign('current_goal', loaded_goal)

    loaded_theme = settings.get('theme', st.session_state.get('theme_pref', DEFAULT_SETTINGS['theme']))
    if loaded_theme in ["System", "Dark", "Light"]: assign('theme_pref', loaded_theme)

    loaded_activity = settings.get('activity', st.session_state.get('activity_level', DEFAULT_SETTINGS['activity']))
    if loaded_activity in ACTIVITY_MULTIPLIERS: assign('activity_level', loaded_activity)

    assign('calorie_offset', parse_int_setting(settings.get('calorie_offset'), st.session_state.get('calorie_offset', 0)))
    assign('calorie_custom', parse_int_setting(settings.get('calorie_custom'), st.session_state.get('calorie_custom', 0)))
    assign('protein_custom', parse_int_setting(settings.get('protein_custom'), st.session_state.get('protein_custom', DEFAULT_SETTINGS['protein_custom'])))
    assign('analysis_start_date', parse_date_setting(settings.get('analysis_start'), st.session_state.get('analysis_start_date', DEFAULT_SETTINGS['analysis_start'])))
    assign('target_end_date', parse_date_setting(settings.get('target_end'), st.session_state.get('target_end_date', DEFAULT_SETTINGS['target_end'])))
    assign('gym_start_date', parse_date_setting(settings.get('gym_start'), st.session_state.get('gym_start_date', DEFAULT_SETTINGS['gym_start'])))

    loaded_muscle_mode = settings.get('muscle_mass_input_mode', settings.get('mm_mode', st.session_state.get('muscle_mass_input_mode', DEFAULT_SETTINGS['muscle_mass_input_mode'])))
    if loaded_muscle_mode in MUSCLE_INPUT_MODES: assign('muscle_mass_input_mode', loaded_muscle_mode)

    assign('enable_quotes', parse_bool_setting(settings.get('enable_quotes'), st.session_state.get('enable_quotes', True)))
    assign('enable_achievements', parse_bool_setting(settings.get('enable_achievements'), st.session_state.get('enable_achievements', True)))
    return changed

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
if 'enable_quotes' not in st.session_state: st.session_state['enable_quotes'] = parse_bool_setting(st.query_params.get("enable_quotes", DEFAULT_SETTINGS['enable_quotes']), DEFAULT_SETTINGS['enable_quotes'])
if 'enable_achievements' not in st.session_state: st.session_state['enable_achievements'] = parse_bool_setting(st.query_params.get("enable_achievements", DEFAULT_SETTINGS['enable_achievements']), DEFAULT_SETTINGS['enable_achievements'])
if 'goal_profiles' not in st.session_state: st.session_state['goal_profiles'] = DEFAULT_PROFILES

if 'current_goal' not in st.session_state: st.session_state['current_goal'] = st.query_params.get("goal", DEFAULT_SETTINGS['goal'])
if 'theme_pref' not in st.session_state: st.session_state['theme_pref'] = st.query_params.get("theme", DEFAULT_SETTINGS['theme'])

if 'activity_level' not in st.session_state: st.session_state['activity_level'] = st.query_params.get("activity", DEFAULT_SETTINGS['activity'])
if 'calorie_offset' not in st.session_state: st.session_state['calorie_offset'] = parse_int_setting(st.query_params.get("calorie_offset", DEFAULT_SETTINGS['calorie_offset']), DEFAULT_SETTINGS['calorie_offset'])
if 'calorie_custom' not in st.session_state: st.session_state['calorie_custom'] = parse_int_setting(st.query_params.get("calorie_custom", DEFAULT_SETTINGS['calorie_custom']), DEFAULT_SETTINGS['calorie_custom'])
if 'protein_custom' not in st.session_state: st.session_state['protein_custom'] = parse_int_setting(st.query_params.get("protein_custom", DEFAULT_SETTINGS['protein_custom']), DEFAULT_SETTINGS['protein_custom'])
if 'muscle_mass_input_mode' not in st.session_state: st.session_state['muscle_mass_input_mode'] = st.query_params.get("mm_mode", DEFAULT_SETTINGS['muscle_mass_input_mode'])
if st.session_state['muscle_mass_input_mode'] not in MUSCLE_INPUT_MODES: st.session_state['muscle_mass_input_mode'] = DEFAULT_SETTINGS['muscle_mass_input_mode']

if 'gym_start_date' not in st.session_state: st.session_state['gym_start_date'] = parse_date_setting(st.query_params.get("gym_start"), DEFAULT_SETTINGS['gym_start'])
if 'analysis_start_date' not in st.session_state: st.session_state['analysis_start_date'] = parse_date_setting(st.query_params.get("start"), DEFAULT_SETTINGS['analysis_start'])
if 'target_end_date' not in st.session_state: st.session_state['target_end_date'] = parse_date_setting(st.query_params.get("end"), DEFAULT_SETTINGS['target_end'])

if st.session_state['current_goal'] not in st.session_state['goal_profiles']: st.session_state['current_goal'] = DEFAULT_SETTINGS['goal']
if st.session_state['activity_level'] not in ACTIVITY_MULTIPLIERS: st.session_state['activity_level'] = DEFAULT_SETTINGS['activity']
if st.session_state['theme_pref'] not in ["System", "Dark", "Light"]: st.session_state['theme_pref'] = DEFAULT_SETTINGS['theme']
    
# ══════════════════════════════════════════════════════════════
# CSS — OVERHAUL
# ══════════════════════════════════════════════════════════════
css_light_vars = """
  --bg-primary: #F7F8FA;
  --bg-secondary: #EEF2F6;
  --text-main: #172033;
  --text-muted: #617087;
  --text-subtle: #98A2B3;
  --surface: #FFFFFF;
  --surface-hover: #F3F6FA;
  --surface-active: #EAF0F7;
  --border: rgba(23,32,51,0.08);
  --border-strong: rgba(23,32,51,0.16);
  --c-emerald: #059669;
  --c-emerald-bg: rgba(5, 150, 105, 0.1);
  --c-amber: #D97706;
  --c-amber-bg: rgba(217, 119, 6, 0.1);
  --c-rose: #DC2626;
  --c-rose-bg: rgba(220, 38, 38, 0.1);
  --c-blue: #2563EB;
  --c-blue-bg: rgba(37, 99, 235, 0.1);
  --c-blue-soft: rgba(37, 99, 235, 0.14);
  --shadow-sm: 0 1px 3px rgba(15,23,42,0.06), 0 1px 2px rgba(15,23,42,0.04);
  --shadow-md: 0 6px 18px rgba(15,23,42,0.08), 0 2px 6px rgba(15,23,42,0.05);
  --shadow-lg: 0 18px 44px rgba(15,23,42,0.12), 0 8px 16px rgba(15,23,42,0.06);
  --nav-bg: rgba(247, 248, 250, 0.9);
  --nav-pill: #172033;
  --nav-pill-text: #FFFFFF;
  --nav-text: #617087;
  --input-bg: #FFFFFF;
  --input-text: #172033;
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

if st.session_state['theme_pref'] == "Dark": theme_block = f":root {{{css_dark_vars}}}"
elif st.session_state['theme_pref'] == "Light": theme_block = f":root {{{css_light_vars}}}"
else: theme_block = f":root {{{css_light_vars}}} @media (prefers-color-scheme: dark) {{ :root {{{css_dark_vars}}} }}"

css = theme_block + """
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;0,9..40,800;1,9..40,400&family=DM+Mono:wght@400;500;600&display=swap');

*, *::before, *::after { box-sizing: border-box; }

.stApp { background: var(--bg-primary) !important; font-family: 'DM Sans', sans-serif !important; }
.block-container { padding-top: 1.5rem !important; padding-bottom: 6rem !important; max-width: 940px !important; }
#MainMenu, footer, header { display: none !important; }

/* ══════════════════════════════
   APP BAR & NAV
══════════════════════════════ */
.app-bar { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 2rem; }
.wordmark { font-family: 'DM Sans', sans-serif; font-size: 1.75rem; font-weight: 800; color: var(--text-main); letter-spacing: -1.5px; line-height: 1; }
.tagline { font-family: 'DM Mono', monospace; font-size: 0.6rem; color: var(--text-subtle); margin-top: 5px; letter-spacing: 0.5px; }
.live-pill { display: inline-flex; align-items: center; gap: 6px; background: var(--c-emerald-bg); border: 1px solid rgba(16, 185, 129, 0.25); border-radius: 100px; padding: 5px 12px; font-family: 'DM Mono', monospace; font-size: 0.58rem; color: var(--c-emerald); font-weight: 600; letter-spacing: 1.5px; }
.live-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--c-emerald); animation: pulse 2s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(0.7); } }

.nav-container div[role="radiogroup"] { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-bottom: 2.5rem; margin-top: -0.5rem; background: transparent !important; }
.nav-container div[role="radiogroup"] > label { background: var(--surface) !important; border: 1px solid var(--border-strong) !important; border-radius: 100px !important; padding: 8px 18px !important; margin: 0 !important; cursor: pointer; box-shadow: var(--shadow-sm); transition: all 0.2s ease; }
.nav-container div[role="radiogroup"] > label:hover { border-color: var(--text-muted) !important; transform: translateY(-1px); }
.nav-container div[role="radiogroup"] > label[data-checked="true"] { background: var(--nav-pill) !important; border-color: var(--nav-pill) !important; box-shadow: var(--shadow-md); }
.nav-container div[role="radiogroup"] > label div { color: var(--text-muted) !important; font-weight: 600 !important; font-family: 'DM Sans', sans-serif !important; font-size: 0.85rem !important; letter-spacing: 0.5px !important; }
.nav-container div[role="radiogroup"] > label[data-checked="true"] div { color: var(--nav-pill-text) !important; font-weight: 800 !important; }
.nav-container div[role="radiogroup"] span[data-baseweb="radio"] { display: none !important; }
.nav-container div[role="radiogroup"] div[data-testid="stMarkdownContainer"] p { margin: 0 !important; padding: 0 !important; }
div[data-testid="stSegmentedControl"] { display: none !important; }

.s-head { font-family: 'DM Mono', monospace !important; font-size: 0.65rem; letter-spacing: 2.5px; color: var(--text-subtle); margin: 2rem 0 1rem; font-weight: 500; text-transform: uppercase; }
.settings-lbl { font-family: 'DM Sans', sans-serif !important; font-size: 0.85rem; color: var(--text-main); font-weight: 700; text-transform: uppercase; margin-top: 2rem; margin-bottom: 1rem; letter-spacing: 1px;}
.quote-box { text-align: center; padding: 1.2rem 1.4rem; border: 1px solid var(--border); border-radius: 16px; background: var(--surface); margin-bottom: 1.75rem; box-shadow: var(--shadow-sm); }
.quote-text { font-family: 'DM Sans', sans-serif; font-size: 0.82rem; color: var(--text-muted); font-style: italic; font-weight: 400; line-height: 1.6; letter-spacing: 0.1px; }

/* ══════════════════════════════
   GRID & CARDS
══════════════════════════════ */
.mini-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 1.75rem; }
.mini-cell { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 1.1rem 1rem; box-shadow: var(--shadow-sm); transition: box-shadow 0.2s ease; }
.mini-cell:hover { box-shadow: var(--shadow-md); }
.mini-lbl { font-family: 'DM Mono', monospace; font-size: 0.58rem; color: var(--text-subtle); font-weight: 500; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 8px; display: block; }
.mini-val { font-family: 'DM Mono', monospace; font-size: 1.55rem; font-weight: 600; color: var(--text-main); line-height: 1; display: inline-block;}
.mini-unit { font-size: 0.65rem; color: var(--text-subtle); margin-left: 2px; font-weight: 400;}
.mini-sub { font-family: 'DM Mono', monospace; font-size: 0.65rem; font-weight: 600; margin-top: 8px; display: block; letter-spacing: 0.5px;}

.c-ok  { color: var(--c-emerald) !important; } .c-wrn { color: var(--c-amber) !important; } .c-err { color: var(--c-rose) !important; } .c-neu { color: var(--text-muted) !important; } .c-blue { color: var(--c-blue) !important; }

.chart-blk { background: var(--surface); border: 1px solid var(--border); border-radius: 20px; padding: 1.2rem; margin-bottom: 1rem; box-shadow: var(--shadow-sm); }
.chart-meta { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px; }
.t-chip { font-family: 'DM Mono', monospace; font-size: 0.58rem; padding: 4px 9px; border-radius: 100px; font-weight: 600; display: inline-block; letter-spacing: 0.5px;}
.t-chip.c-ok  { background: var(--c-emerald-bg); color: var(--c-emerald) !important; }
.t-chip.c-wrn { background: var(--c-amber-bg); color: var(--c-amber) !important; }
.t-chip.c-err { background: var(--c-rose-bg); color: var(--c-rose) !important; }
.t-chip.c-neu { background: var(--surface-active); color: var(--text-muted) !important; }

/* Condensed Fit Note */
.fit-note { font-family: 'DM Mono', monospace; font-size: 0.62rem; color: var(--text-subtle); border-top: 1px solid var(--border); padding-top: 8px; margin-top: 6px; line-height: 1.4; display: flex; justify-content: space-between; align-items: center;}
.fit-note-val { color: var(--text-main); font-weight: 600; }
.data-note { font-family: 'DM Mono', monospace; font-size: 0.62rem; color: var(--text-subtle); margin-top: -0.6rem; margin-bottom: 1rem; }

.hud-card { display: flex; gap: 14px; align-items: flex-start; background: var(--surface); border: 1px solid var(--border); padding: 1rem 1.1rem; border-radius: 16px; margin-bottom: 0.6rem; box-shadow: var(--shadow-sm); }
.hud-icon { font-size: 1.1rem; width: 38px; height: 38px; min-width: 38px; display: flex; align-items: center; justify-content: center; border-radius: 10px; background: var(--surface-active); flex-shrink: 0; line-height: 1; }
.hud-title { font-size: 0.78rem; color: var(--text-main); font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 3px; }
.hud-desc { font-size: 0.76rem; color: var(--text-muted); line-height: 1.5; }

.tj-blk { margin-bottom: 2.2rem; }
.tj-row { display: flex; justify-content: space-between; margin-bottom: 10px; align-items: flex-end; }
.tj-nm { font-family: 'DM Mono', monospace; font-size: 0.72rem; color: var(--text-muted); font-weight: 500; text-transform: uppercase; letter-spacing: 1.5px; }
.bar-tk { height: 20px; border-radius: 10px; overflow: hidden; margin-bottom: 8px; position: relative; }
.bar-pin { position: absolute; top: -2px; bottom: -2px; width: 3px; background: var(--text-main); box-shadow: 0 0 0 2px var(--bg-primary), 0 0 12px rgba(255,255,255,0.3); z-index: 5; transform: translateX(-50%); border-radius: 2px; }
.tj-st { font-family: 'DM Mono', monospace; font-size: 0.58rem; font-weight: 600; letter-spacing: 2px; text-transform: uppercase; display: block; margin-top: 8px; }

/* ══════════════════════════════
   ACHIEVEMENTS / TIERS
══════════════════════════════ */
.tier-item { display: flex; align-items: center; gap: 14px; padding: 12px 14px; border-radius: 14px; margin-bottom: 8px; background: var(--surface); border: 1px solid var(--border); box-shadow: var(--shadow-sm); }
.tier-item.completed { background: var(--c-blue-bg); border-color: rgba(37,99,235,0.25); }
.tier-item.completed .tier-name { color: var(--c-blue); }
.tier-item.current { background: var(--c-blue-soft); border-color: var(--c-blue); box-shadow: 0 4px 20px rgba(37,99,235,0.15); }
.tier-item.locked { opacity: 0.35; }
.tier-emoji { font-size: 1.4rem; width: 42px; height: 42px; display: flex; align-items: center; justify-content: center; background: var(--surface-active); border-radius: 10px; flex-shrink: 0; }
.tier-details { flex-grow: 1; }
.tier-name { font-weight: 700; font-size: 0.85rem; color: var(--text-main); margin-bottom: 2px; }
.tier-req { font-family: 'DM Mono', monospace; font-size: 0.6rem; color: var(--text-subtle); letter-spacing: 0.5px; }
.prog-tk { height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; margin-top: 10px; }
.prog-fill { height: 100%; background: var(--c-blue); border-radius: 3px; transition: width 0.6s ease; }

/* ══════════════════════════════
   HISTORY ROWS
══════════════════════════════ */
.hist-row { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 14px 16px; margin-bottom: 8px; display: flex; align-items: center; box-shadow: var(--shadow-sm); transition: box-shadow 0.15s ease; }
.hist-row:hover { box-shadow: var(--shadow-md); }
.del-btn button { background: transparent !important; border: none !important; color: var(--text-subtle) !important; font-family: 'DM Sans', sans-serif !important; font-weight: 600 !important; font-size: 1.2rem !important; padding: 0 !important; margin: 0 !important; box-shadow: none !important; }
.del-btn button:hover { color: var(--c-rose) !important; }

/* ══════════════════════════════
   ALERT BANNERS & INPUTS
══════════════════════════════ */
.alert-banner { padding: 10px 14px; border-radius: 10px; font-size: 0.72rem; font-weight: 600; text-align: center; margin-bottom: 1rem; letter-spacing: 0.5px; }
.alert-banner.warn { background: var(--c-amber-bg); border: 1px solid rgba(217,119,6,0.2); color: var(--c-amber); }
.alert-banner.danger { background: var(--c-rose-bg); border: 1px solid rgba(220,38,38,0.2); color: var(--c-rose); }
.alert-banner.info { background: var(--c-blue-bg); border: 1px solid rgba(37,99,235,0.2); color: var(--c-blue); }

/* Clean Sliders */
div[data-testid="stSlider"] label { font-family: 'DM Mono', monospace !important; font-size: 0.65rem !important; color: var(--text-subtle) !important; text-transform: uppercase !important; font-weight: 500 !important; letter-spacing: 1.5px !important; margin-bottom: 4px !important;}
div[data-testid="stSlider"] > div > div > div { height: 6px !important; border-radius: 3px !important; background: var(--border-strong) !important; }
div[data-testid="stSlider"] div[role="slider"] { width: 18px !important; height: 18px !important; background: var(--c-blue) !important; border: none !important; box-shadow: var(--shadow-md) !important; }
div[data-testid="stSlider"] div[data-baseweb="slider"] { margin-bottom: 0px !important; }

div[data-testid="stSelectbox"] { margin-bottom: 0 !important; }
div[data-testid="stSelectbox"] > div > div { background: var(--input-bg) !important; border: 1px solid var(--border-strong) !important; border-radius: 12px !important; color: var(--input-text) !important; min-height: 3.2rem !important; box-shadow: var(--shadow-sm) !important; }
div[data-testid="stSelectbox"] div[class*="singleValue"] { color: var(--input-text) !important; font-weight: 600 !important; font-family: 'DM Sans', sans-serif !important; }
div[data-testid="stSelectbox"] [class*="placeholder"] { color: var(--text-muted) !important; }
div[data-testid="stSelectbox"] [class*="menu"] { background: var(--surface) !important; border: 1px solid var(--border-strong) !important; border-radius: 12px !important; }
div[data-testid="stSelectbox"] [class*="option"] { color: var(--input-text) !important; background: transparent !important; }
div[data-testid="stSelectbox"] [class*="option"]:hover { background: var(--surface-active) !important; }

div[data-testid="stTextInput"] > div > div { background: var(--input-bg) !important; border: 1px solid var(--border-strong) !important; border-radius: 12px !important; min-height: 3.2rem !important; }
div[data-testid="stTextInput"] input { color: var(--input-text) !important; font-family: 'DM Mono', monospace !important; font-size: 1rem !important; text-align: center !important; background: transparent !important; }

div[data-testid="stForm"] button { background: var(--text-main) !important; color: var(--bg-primary) !important; font-family: 'DM Sans', sans-serif !important; font-weight: 700 !important; font-size: 0.82rem !important; border: none !important; border-radius: 100px !important; padding: 1rem !important; margin-top: 1.5rem !important; text-transform: uppercase !important; letter-spacing: 2px !important; box-shadow: var(--shadow-md) !important; transition: all 0.2s ease !important; }
div[data-testid="stForm"] button:hover { transform: translateY(-1px) !important; box-shadow: var(--shadow-lg) !important; }

.stButton > button { background: var(--surface) !important; color: var(--text-main) !important; font-family: 'DM Sans', sans-serif !important; font-weight: 700 !important; font-size: 0.82rem !important; border: 1px solid var(--border-strong) !important; border-radius: 100px !important; padding: 0.6rem 1.2rem !important; margin-top: 0 !important; text-transform: uppercase !important; letter-spacing: 1.5px !important; box-shadow: var(--shadow-sm) !important; transition: all 0.2s ease !important; }
.stButton > button:hover { background: var(--surface-active) !important; box-shadow: var(--shadow-md) !important; }

div[data-testid="stDateInput"] > div > div { background: var(--input-bg) !important; border: 1px solid var(--border-strong) !important; border-radius: 12px !important; color: var(--input-text) !important; }
div[data-testid="stDateInput"] input { color: var(--input-text) !important; }

div[data-testid="stToggle"] label p { color: var(--text-main) !important; font-size: 0.85rem !important; }
div[data-testid="stExpander"] { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 14px !important; overflow: hidden; }
div[data-testid="stExpander"] summary p { color: var(--text-main) !important; font-size: 0.82rem !important; font-weight: 600 !important; }
div[data-testid="stExpander"] div[data-testid="stMarkdownContainer"] p { color: var(--text-main) !important; }

button[aria-label="Step down"], button[aria-label="Step up"], button[title="Step down"], button[title="Step up"] { display: none !important; }
div[data-testid="stAlert"] { border-radius: 12px !important; }
div[data-testid="stSelectbox"] > div > div { display: flex !important; align-items: center !important; justify-content: center !important; text-align: center !important; }
div[data-testid="stSelectbox"] div[data-baseweb="select"] { width: 100% !important; justify-content: center !important; text-align: center !important; }
div[data-testid="stSelectbox"] div[class*="singleValue"] { text-align: center !important; margin: 0 auto !important; position: absolute; left: 0; right: 0; }

::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 2px; }

@media (max-width: 760px) { .block-container { padding-left: 1rem !important; padding-right: 1rem !important; } .mini-grid { grid-template-columns: 1fr; } .mini-cell[style*="grid-column"] { grid-column: span 1 !important; } .chart-meta { flex-direction: column; gap: 12px; } .chart-meta > div:last-child { align-items: flex-start !important; text-align: left !important; } .app-bar { align-items: flex-start; gap: 12px; } }
"""
st.markdown(f'<style>{css}</style>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# AUTHENTICATION
# ══════════════════════════════════════════════════════════════
saved_user = st.query_params.get("user", None)

if not st.session_state['auth_status']:
    if saved_user:
        if saved_user == admin_key:
            st.session_state['is_admin'] = True
            st.session_state['auth_status'] = False
        elif saved_user in USER_DATA:
            st.session_state['auth_status'] = True
            st.session_state['current_user'] = saved_user
            st.session_state['sheet_url'] = USER_DATA[saved_user]
            st.session_state['is_admin'] = False
            st.rerun()
        else:
            st.query_params.clear()
            st.error("🔒 Access Denied. Invalid link.")
            st.stop()
    else:
        st.error("🔒 Access Denied. Use your personal link to log in.")
        st.stop()

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

if st.session_state['auth_status']:
    settings_loaded_for = st.session_state.get('settings_loaded_for')
    current_user_key = st.session_state.get('current_user')
    if settings_loaded_for != current_user_key:
        sheet_settings = load_app_settings(st.session_state['sheet_url'])
        settings_changed = apply_loaded_settings(sheet_settings)
        st.session_state['settings_loaded_for'] = current_user_key
        if sheet_settings: sync_query_params_from_settings()
        if settings_changed: st.rerun()

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

# Isolate Data Before EMA Calculation to block ghost momentum
df_window_full = df[df['Date'] >= analysis_start].copy()

if not df_window_full.empty:
    for metric in METRICS:
        df_window_full[f'{metric}_EMA'] = df_window_full[metric].ewm(alpha=0.15, adjust=False).mean()

has_enough_weight_data = len(df_window_full) >= 3 or len(df) >= 3
has_enough_comp_data = len(df_window_full) >= 5 or len(df) >= 5

monthly_trends, weekly_trends, daily_slopes, trend_stats, traj_data = {}, {}, {}, {}, {}
recent_dfs_for_plot = {}
active_goal = st.session_state.get('current_goal', 'Lean Bulk')
ideal_rates = st.session_state['goal_profiles'].get(active_goal, st.session_state['goal_profiles']['Lean Bulk'])
ideal_weekly_rates = scale_rate_profile(ideal_rates, 7 / 30)

if has_enough_weight_data:
    df_w = df_window_full if len(df_window_full) >= 3 else df.tail(3).copy()
    recent_dfs_for_plot['Weight (kg)'] = df_w

    X_w_raw = elapsed_days(df_w['Date'])
    if 'Weight (kg)_EMA' not in df_w.columns: df_w['Weight (kg)_EMA'] = df_w['Weight (kg)'].ewm(alpha=0.15, adjust=False).mean()
        
    y_w = df_w['Weight (kg)_EMA'].values
    days_elapsed = max(float(np.nanmax(X_w_raw) - np.nanmin(X_w_raw)), 0.0)
    
    res_w = stats.linregress(X_w_raw, y_w)
    regression_stderr_w = 0 if pd.isna(res_w.stderr) else res_w.stderr

    if days_elapsed < 14 and len(y_w) >= 2:
        slope_w = (y_w[-1] - y_w[0]) / days_elapsed if days_elapsed > 0 else 0
        stderr_w = regression_stderr_w 
        fit_y_w = y_w[0] + (slope_w * X_w_raw)
        
        ss_res_w = np.sum((y_w - fit_y_w)**2)
        ss_tot_w = np.sum((y_w - np.mean(y_w))**2)
        if ss_tot_w < 0.001 and ss_res_w < 0.001: r2_w = 1.0 # Force mathematically accurate R2 for microvariance
        else: r2_w = max(0.0, 1 - (ss_res_w / ss_tot_w)) if ss_tot_w != 0 else 1.0
        
        fit_type_w = 'point-to-point'
    else:
        slope_w = res_w.slope
        stderr_w = regression_stderr_w
        r2_w = 0 if pd.isna(res_w.rvalue) else res_w.rvalue ** 2
        fit_y_w = res_w.intercept + slope_w * X_w_raw
        fit_type_w = 'linear fit'

    daily_slopes['Weight (kg)'] = slope_w
    weekly_trends['Weight (kg)'] = slope_w * 7
    monthly_trends['Weight (kg)'] = slope_w * 30
    
    trend_stats['Weight (kg)'] = {
        'n': len(df_w),
        'days': days_elapsed,
        'r2': r2_w,
        'slope': slope_w,
        'stderr': stderr_w,
        'type': fit_type_w
    }

    days_to_end_w = (target_end_date.date() - df_w['Date'].min().date()).days
    if days_to_end_w > 0:
        future_days_w  = np.array([[i] for i in range(0, days_to_end_w + 10)])
        future_dates_w = [df_w['Date'].min() + timedelta(days=i) for i in range(0, days_to_end_w + 10)]

        pred_y_w = fit_y_w[0] + slope_w * future_days_w.flatten() if days_elapsed < 14 else res_w.intercept + slope_w * future_days_w.flatten()
        
        current_day_index_w = (df_w['Date'].max() - df_w['Date'].min()).days
        days_from_current_w = np.maximum(0, future_days_w.flatten() - current_day_index_w)
        rmse_w = np.sqrt(np.mean((y_w - fit_y_w)**2)) if len(y_w) > 0 else 0.5
        
        margin_of_error_w = rmse_w + (stderr_w * days_from_current_w * 1.96)

        traj_data['Weight (kg)'] = {
            'dates': future_dates_w,
            'preds': pred_y_w,
            'upper': pred_y_w + margin_of_error_w,
            'lower': pred_y_w - margin_of_error_w,
            'final_error': margin_of_error_w[-10],
            'fit_dates': df_w['Date'].tolist(),
            'fit': fit_y_w,
        }
    else:
        traj_data['Weight (kg)'] = {'fit_dates': df_w['Date'].tolist(), 'fit': fit_y_w}

if has_enough_comp_data:
    df_c = df_window_full if len(df_window_full) >= 5 else df.tail(5).copy()
    X_c_raw = elapsed_days(df_c['Date'])
    days_elapsed_c = max(float(np.nanmax(X_c_raw) - np.nanmin(X_c_raw)), 0.0)

    days_to_end_c = (target_end_date.date() - df_c['Date'].min().date()).days
    future_days_c, future_dates_c = None, None
    if days_to_end_c > 0:
        future_days_c = np.array([[i] for i in range(0, days_to_end_c + 10)])
        future_dates_c = [df_c['Date'].min() + timedelta(days=i) for i in range(0, days_to_end_c + 10)]

    for m in ['Muscle Mass (kg)', 'Body Fat (%)']:
        if f'{m}_EMA' not in df_c.columns: df_c[f'{m}_EMA'] = df_c[m].ewm(alpha=0.15, adjust=False).mean()
            
        recent_dfs_for_plot[m] = df_c
        y_c = df_c[f'{m}_EMA'].values

        res_c = stats.linregress(X_c_raw, y_c)
        regression_stderr_c = 0 if pd.isna(res_c.stderr) else res_c.stderr

        if days_elapsed_c < 14 and len(y_c) >= 2:
            slope_c = (y_c[-1] - y_c[0]) / days_elapsed_c if days_elapsed_c > 0 else 0
            stderr_c = regression_stderr_c 
            fit_y_c = y_c[0] + (slope_c * X_c_raw)
            
            ss_res_c = np.sum((y_c - fit_y_c)**2)
            ss_tot_c = np.sum((y_c - np.mean(y_c))**2)
            if ss_tot_c < 0.001 and ss_res_c < 0.001: r2_c = 1.0 # Force mathematically accurate R2 for microvariance
            else: r2_c = max(0.0, 1 - (ss_res_c / ss_tot_c)) if ss_tot_c != 0 else 1.0
            fit_type_c = 'point-to-point'
        else:
            slope_c = res_c.slope
            stderr_c = regression_stderr_c
            r2_c = 0 if pd.isna(res_c.rvalue) else res_c.rvalue ** 2
            fit_y_c = res_c.intercept + slope_c * X_c_raw
            fit_type_c = 'linear fit'

        daily_slopes[m] = slope_c
        weekly_trends[m] = slope_c * 7
        monthly_trends[m] = slope_c * 30
        
        trend_stats[m] = {
            'n': len(df_c),
            'days': days_elapsed_c,
            'r2': r2_c,
            'slope': slope_c,
            'stderr': stderr_c,
            'type': fit_type_c
        }

        if future_days_c is not None:
            pred_y_c = fit_y_c[0] + slope_c * future_days_c.flatten() if days_elapsed_c < 14 else res_c.intercept + slope_c * future_days_c.flatten()
            
            current_day_index_c = (df_c['Date'].max() - df_c['Date'].min()).days
            days_from_current_c = np.maximum(0, future_days_c.flatten() - current_day_index_c)
            rmse_c = np.sqrt(np.mean((y_c - fit_y_c)**2)) if len(y_c) > 0 else 0.5
            margin_of_error_c = rmse_c + (stderr_c * days_from_current_c * 1.96)

            traj_data[m] = {
                'dates': future_dates_c,
                'preds': pred_y_c,
                'upper': pred_y_c + margin_of_error_c,
                'lower': pred_y_c - margin_of_error_c,
                'final_error': margin_of_error_c[-10],
                'fit_dates': df_c['Date'].tolist(),
                'fit': fit_y_c,
            }
        else:
            traj_data[m] = {'fit_dates': df_c['Date'].tolist(), 'fit': fit_y_c}

# ══════════════════════════════════════════════════════════════
# MAIN ROUTING ENGINE
# ══════════════════════════════════════════════════════════════
active_goal = st.session_state.get('current_goal', 'Lean Bulk')
ideal_rates = st.session_state['goal_profiles'].get(active_goal, st.session_state['goal_profiles']['Lean Bulk'])

header_placeholder = st.empty()

# Navigation wrapped in scoped container
st.markdown('<div class="nav-container">', unsafe_allow_html=True)
app_view = st.radio("Nav", ["Entry", "Nutrition", "Trends", "Analysis", "Data", "Settings"], horizontal=True, label_visibility="collapsed")
st.markdown('</div>', unsafe_allow_html=True)

header_placeholder.markdown(f"""
<div class="app-bar">
    <div>
        <div class="wordmark">Metrics</div>
        <div class="tagline">{get_display_name(st.session_state['current_user'])} · Beta 8</div>
    </div>
    <div class="live-pill"><div class="live-dot"></div>SYNCED</div>
</div>
""", unsafe_allow_html=True)

days_elapsed_since_start = max(0, (datetime.now().date() - analysis_start.date()).days)

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
        persist_app_settings(st.session_state['sheet_url'])
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

    # UI Sliders (Callbacks ensure calculation works perfectly)
    if 'entry_w' not in st.session_state: st.session_state.entry_w = float(last['Weight (kg)'])
    if 'entry_bf' not in st.session_state: st.session_state.entry_bf = float(last['Body Fat (%)'])
    if 'entry_m' not in st.session_state: st.session_state.entry_m = float(last['Muscle Mass (kg)'])
    if 'entry_m_pct' not in st.session_state: st.session_state.entry_m_pct = (st.session_state.entry_m / st.session_state.entry_w) * 100 if st.session_state.entry_w > 0 else 45.0

    def sync_m_from_pct():
        st.session_state.entry_m = st.session_state.entry_w * (st.session_state.entry_m_pct / 100.0)
        
    def sync_m_from_w():
        st.session_state.entry_m = st.session_state.entry_w * (st.session_state.entry_m_pct / 100.0)

    st.slider("Weight (kg)", min_value=max(0.0, float(last['Weight (kg)'])-2.5), max_value=float(last['Weight (kg)'])+2.5, step=0.1, key="entry_w", on_change=sync_m_from_w)
    
    mm_mode = st.session_state.get('muscle_mass_input_mode', 'Percentage (%)')
    if mm_mode == "Kilograms (kg)":
        st.slider("Muscle Mass (kg)", min_value=max(0.0, float(last['Muscle Mass (kg)'])-2.5), max_value=float(last['Muscle Mass (kg)'])+2.5, step=0.1, key="entry_m")
    else:
        st.slider("Muscle Mass (%)", min_value=max(0.0, st.session_state.entry_m_pct-5.0), max_value=min(100.0, st.session_state.entry_m_pct+5.0), step=0.1, key="entry_m_pct", on_change=sync_m_from_pct)
        st.markdown(f"<div class='data-note' style='text-align:right; margin-top:6px;'>Calculated: {st.session_state.entry_m:.1f} kg</div>", unsafe_allow_html=True)

    st.slider("Body Fat (%)", min_value=max(3.0, float(last['Body Fat (%)'])-2.5), max_value=float(last['Body Fat (%)'])+2.5, step=0.1, key="entry_bf")

    with st.form("log_form", border=False):
        if st.form_submit_button("Save Record", use_container_width=True):
            now_str = datetime.now().strftime('%Y-%m-%d')
            append_body_entry(st.session_state['sheet_url'], now_str, st.session_state.entry_w, st.session_state.entry_m, st.session_state.entry_bf)
            st.session_state['active_df'] = pd.concat([st.session_state['active_df'], pd.DataFrame({'Date': [datetime.now()], 'Weight (kg)': [st.session_state.entry_w], 'Body Fat (%)': [st.session_state.entry_bf], 'Muscle Mass (kg)': [st.session_state.entry_m]})], ignore_index=True)
            load_data.clear()
            if st.session_state['enable_quotes']: st.session_state['daily_quote'] = random.choice(st.session_state['all_quotes'])
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
    
    if g_curr == "male": bmr = (10 * w_curr) + (6.25 * h_curr) - (5 * a_curr) + 5
    else: bmr = (10 * w_curr) + (6.25 * h_curr) - (5 * a_curr) - 161
        
    tdee = bmr * ACTIVITY_MULTIPLIERS.get(act_lvl, 1.55)
    
    if "Aggressive Cut" in active_goal: cal_adj, pro_min, pro_max = -750, 2.0, 2.4
    elif "Lean Cut" in active_goal: cal_adj, pro_min, pro_max = -400, 2.0, 2.3
    elif "Recomposition" in active_goal: cal_adj, pro_min, pro_max = -100, 1.8, 2.1
    elif "Lean Bulk" in active_goal: cal_adj, pro_min, pro_max = +300, 1.8, 2.2
    else: cal_adj, pro_min, pro_max = +500, 1.6, 1.9
    
    calc_cals = int(tdee + cal_adj)
    manual_cals = parse_int_setting(st.session_state.get('calorie_custom'), 0)
    target_cals = manual_cals if manual_cals > 0 else calc_cals + cal_offset
    calorie_sub = f"Manual target · recommendation {calc_cals} kcal" if manual_cals > 0 else f"Baseline Estimate: {calc_cals} kcal"

    st.markdown(f"""
    <div class="mini-grid">
        <div class="mini-cell" style="grid-column: span 3; text-align:center;">
            <span class="mini-lbl">Daily Caloric Target</span>
            <span class="mini-val">{target_cals}<span class="mini-unit">kcal</span></span>
            <div class="mini-sub c-neu">{calorie_sub}</div>
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
    mmt = monthly_trends.get('Muscle Mass (kg)', 0)
    bft = monthly_trends.get('Body Fat (%)', 0)
    w_t, w_min, w_max = ideal_rates['Weight (kg)']
    
    is_muscle_driven = (wt_trend > w_max) and has_enough_comp_data and (mmt >= (wt_trend * 0.4)) and (bft <= 0.2)
    bf_lower = ideal_rates['Body Fat (%)'][1] if len(ideal_rates['Body Fat (%)']) > 1 else -99
    is_fat_loss_driven = (wt_trend < w_min) and has_enough_comp_data and (mmt >= -0.2) and (bft < bf_lower)

    if days_elapsed_since_start < 21:
        st.markdown(hud_card("c-neu", "⏳", "Phase Lock Active", f"Goal locked for the first 3-4 weeks to stabilize water noise. No calorie adjustments recommended yet. (Day {days_elapsed_since_start}/21)"), unsafe_allow_html=True)
    elif len(df_window_full) < 5:
        st.markdown(hud_card("c-neu", "⏳", "Calibrating", "Need more data points since the Start Date to provide adaptive calorie adjustments."), unsafe_allow_html=True)
    else:
        if is_muscle_driven:
            st.markdown(hud_card("c-ok", "🧬", "Hyper-Anabolic Response", f"Weight is increasing rapidly (+{wt_trend:.2f} kg/mo), but it is heavily driven by muscle gain (+{mmt:.2f} kg/mo). Do not cut calories. Ride this muscle memory wave."), unsafe_allow_html=True)
        elif is_fat_loss_driven:
            st.markdown(hud_card("c-ok", "🔥", "Hyper-Lipolytic Response", f"Weight is dropping fast ({wt_trend:.2f} kg/mo), but muscle is preserved and fat is melting (-{abs(bft):.2f} %/mo). Excellent recomposition. Maintain current intake."), unsafe_allow_html=True)
        elif wt_trend > w_max:
            st.markdown(hud_card("c-err", "↓", "Pace Diverging Over Expected", f"Gaining {wt_trend:.2f} kg/mo (Limit: {w_max} kg). Recommend lowering intake by 200 kcal."), unsafe_allow_html=True)
            if st.button("Accept & Lower Calories by 200", use_container_width=True):
                if parse_int_setting(st.session_state.get('calorie_custom'), 0) > 0:
                    st.session_state['calorie_custom'] = max(1000, parse_int_setting(st.session_state.get('calorie_custom'), 0) - 200)
                else:
                    st.session_state['calorie_offset'] -= 200
                st.session_state['analysis_start_date'] = datetime.now().date()
                persist_app_settings(st.session_state['sheet_url'])
                system_alert("Phase Reset")
                st.rerun()
        elif wt_trend < w_min:
            st.markdown(hud_card("c-wrn", "↑", "Pace Diverging Under Expected", f"Tracking at {wt_trend:.2f} kg/mo (Minimum: {w_min} kg). Recommend increasing intake by 200 kcal."), unsafe_allow_html=True)
            if st.button("Accept & Increase Calories by 200", use_container_width=True):
                if parse_int_setting(st.session_state.get('calorie_custom'), 0) > 0:
                    st.session_state['calorie_custom'] = parse_int_setting(st.session_state.get('calorie_custom'), 0) + 200
                else:
                    st.session_state['calorie_offset'] += 200
                st.session_state['analysis_start_date'] = datetime.now().date()
                persist_app_settings(st.session_state['sheet_url'])
                system_alert("Phase Reset")
                st.rerun()
        else:
            st.markdown(hud_card("c-ok", "✓", "Pace Locked In", f"Moving Average ({wt_trend:.2f} kg/mo) is exactly within protocol bounds. Maintain current intake."), unsafe_allow_html=True)

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
        if metric != 'Weight (kg)' and not has_enough_comp_data: continue

        last_val = df.iloc[-1][metric]
        unit = METRIC_UNIT[metric]
        weekly_trend = weekly_trends.get(metric, 0)
        monthly_trend = monthly_trends.get(metric, 0)
        weekly_target = ideal_weekly_rates[metric][0]
        c_txt, c_bg, _, hex_col = eval_metric(metric, weekly_trend, ideal_weekly_rates)

        if metric == 'Weight (kg)': err_pct = 1.0
        elif metric == 'Muscle Mass (kg)': err_pct = 1.0
        elif metric == 'Body Fat (%)': err_pct = 5.0
        else: err_pct = 1.0

        if 'preds' in traj_data.get(metric, {}):
            final_pred = traj_data[metric]['preds'][-10] 
            final_error = traj_data[metric]['final_error']
            lower_proj = final_pred - final_error
            upper_proj = final_pred + final_error
            proj_html = f"<div style='font-family:\"Inter\", sans-serif; font-size:0.75rem; color:var(--text-subtle); margin-top:4px;'>{end_label} PROJ: <span style='color:var(--text-main); font-weight:700;'>{lower_proj:.1f} - {upper_proj:.1f} {unit}</span></div>"
        else:
            proj_html = ""
        
        st.markdown(f"""
        <div class="chart-blk">
            <div class="chart-meta" style="align-items: flex-start;">
                <div>
                    <div style="font-size:0.9rem; color:var(--text-main); font-weight:800; letter-spacing:1px; text-transform:uppercase;">
                        {METRIC_SHORT[metric]} 
                        <span style="font-family:'Inter', sans-serif; font-weight:800; color:var(--text-main); margin-left:8px; font-size:1.5rem;">
                            {last_val:.1f} <span style="font-size:0.9rem; color:var(--text-muted);">{unit}</span>
                        </span>
                    </div>
                    {proj_html}
                </div>
                <div style="text-align: right;">
                    <span class="t-chip {c_bg} {c_txt}" style="margin-bottom:4px;">ACTUAL {sgn(weekly_trend)}{weekly_trend:.2f} /wk</span><br>
                    <span class="t-chip bg-neu c-neu">TARGET {sgn(weekly_target)}{weekly_target:.2f} /wk</span>
                </div>
            </div>
        """, unsafe_allow_html=True)
        
        fig = go.Figure()
        
        df_hist = df[~df.index.isin(recent_dfs_for_plot[metric].index)]
        fig.add_trace(go.Scatter(
            x=df_hist['Date'], y=df_hist[metric],
            mode='lines+markers', name='History',
            line=dict(color='rgba(150,150,150,0.4)', width=1.5),
            marker=dict(size=4, color='rgba(150,150,150,0.4)'),
            error_y=dict(type='percent', value=err_pct, color='rgba(128,128,128,0.1)', thickness=1, width=2),
            hoverinfo='skip'
        ))
        
        spec_recent = recent_dfs_for_plot[metric]
        ema_col = f'{metric}_EMA'

        fig.add_trace(go.Scatter(
            x=spec_recent['Date'], y=spec_recent[metric],
            mode='markers', name='Raw log',
            marker=dict(size=6, color='rgba(128,128,128,0.45)', line=dict(width=0)),
            error_y=dict(type='percent', value=err_pct, color='rgba(128,128,128,0.3)', thickness=1.5, width=3),
            hovertemplate='%{x|%b %d}: %{y:.1f} {unit} ±'+str(err_pct)+'%<extra></extra>'.replace('{unit}', unit)
        ))
        
        if ema_col in spec_recent.columns:
            fig.add_trace(go.Scatter(
                x=spec_recent['Date'], y=spec_recent[ema_col],
                mode='lines', name='EMA smoothing',
                line=dict(color='#3B82F6', width=3),
                hovertemplate='EMA: %{y:.1f} {unit}<extra></extra>'.replace('{unit}', unit)
            ))

        if 'fit_dates' in traj_data.get(metric, {}):
            fig.add_trace(go.Scatter(
                x=traj_data[metric]['fit_dates'], y=traj_data[metric]['fit'],
                mode='lines', name='Linear fit',
                line=dict(color='#F59E0B', width=2, dash='dot'),
                hovertemplate='Fit: %{y:.1f} {unit}<extra></extra>'.replace('{unit}', unit)
            ))

        if 'dates' in traj_data.get(metric, {}):
            x_vals = traj_data[metric]['dates']
            y_upper = traj_data[metric]['upper']
            y_lower = traj_data[metric]['lower']
            
            fig.add_trace(go.Scatter(
                x=list(x_vals) + list(x_vals)[::-1],
                y=list(y_upper) + list(y_lower)[::-1],
                fill='toself', fillcolor='rgba(59,130,246,0.08)',
                line=dict(color='rgba(255,255,255,0)'),
                hoverinfo="skip", showlegend=False
            ))
            
            fig.add_trace(go.Scatter(
                x=x_vals, y=traj_data[metric]['preds'],
                mode='lines', name='Forecast',
                line=dict(color='#3B82F6', width=1.5, dash='dash'),
                hoverinfo='skip'
            ))
        
        epoch_date = spec_recent['Date'].min()
        fig.add_vline(x=epoch_date, line_width=2, line_dash="solid", line_color="#888888", annotation_text="START", annotation_position="bottom right", annotation_font_size=10, annotation_font_color="#888888")
        
        current_date = spec_recent['Date'].max()
        daily_rate = ideal_rates[metric][0] / 30.0
        
        days_span = (target_end_date.date() - current_date.date()).days
        if days_span > 0 and ema_col in spec_recent.columns:
            latest_ema = spec_recent[ema_col].iloc[-1]
            goal_val = latest_ema + daily_rate * days_span
            
            fig.add_vline(x=target_end_date, line_width=1.5, line_dash="dash", line_color="#10B981", annotation_text=end_label, annotation_position="top left", annotation_font_size=10, annotation_font_color="#10B981")
            fig.add_trace(go.Scatter(x=[target_end_date], y=[goal_val], mode='markers+text', name=f'{end_label} Goal', marker=dict(size=8, color='#10B981', symbol='diamond'), text=[f"{goal_val:.1f}{unit}"], textposition="middle right", textfont=dict(color="#10B981", size=10, family="Inter"), hoverinfo='skip'))
            fig.add_trace(go.Scatter(x=[current_date, target_end_date], y=[latest_ema, goal_val], mode='lines', name='Target Path', line=dict(color='gray', width=1.5, dash='dot'), opacity=0.7, hoverinfo='skip'))

        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=0, r=0, t=20, b=45), height=320, showlegend=True,
            legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="center", x=0.5, font=dict(size=9, color='gray')),
            xaxis=dict(showgrid=False, zeroline=False, tickfont=font_cfg, tickformat='%b %d', range=[df['Date'].min(), target_end_date + timedelta(days=10)]),
            yaxis=dict(showgrid=True, gridcolor='rgba(150,150,150,0.1)', zeroline=False, tickfont=font_cfg, side='right')
        )
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

        fit = trend_stats.get(metric, {'n': 0, 'days': 0, 'r2': 0, 'slope': 0, 'type': 'linear fit'})
        st.markdown(
            f"""<div style="display:flex; justify-content:space-between; align-items:center; border-top: 1px solid var(--border); padding-top: 10px; margin-top: 2px;">
                <div style="font-family: 'DM Mono', monospace; font-size: 0.62rem; color: var(--text-subtle); line-height: 1.4;">
                    <b>Algorithm:</b> EMA smoothed → {fit['type'].title()}<br>
                    <b>Horizon:</b> {fit['n']} logs over {fit['days']:.1f} days
                </div>
                <div style="font-family: 'DM Mono', monospace; font-size: 0.62rem; color: var(--text-subtle); line-height: 1.4; text-align:right;">
                    <b>Variance (R²):</b> {fit['r2']:.2f}<br>
                    <b>Error Margins:</b> ±{err_pct}% BIA spec
                </div>
            </div>""",
            unsafe_allow_html=True
        )
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
    wt = weekly_trends.get('Weight (kg)', 0)
    mmt = weekly_trends.get('Muscle Mass (kg)', 0)
    bft = weekly_trends.get('Body Fat (%)', 0)
    wt_month = monthly_trends.get('Weight (kg)', 0)
    mmt_month = monthly_trends.get('Muscle Mass (kg)', 0)
    bft_month = monthly_trends.get('Body Fat (%)', 0)

    wt_err = trend_stats.get('Weight (kg)', {}).get('stderr', 0) * 7
    mmt_err = trend_stats.get('Muscle Mass (kg)', {}).get('stderr', 0) * 7
    bft_err = trend_stats.get('Body Fat (%)', {}).get('stderr', 0) * 7

    c_w, _, _, _ = eval_metric('Weight (kg)', wt, ideal_weekly_rates, mmt, bft)

    if has_enough_comp_data:
        c_bf, _, _, _ = eval_metric('Body Fat (%)', bft, ideal_weekly_rates, mmt, bft)
        c_mm, _, _, _ = eval_metric('Muscle Mass (kg)', mmt, ideal_weekly_rates, mmt, bft)
        bf_disp = f"""<div class="mini-sub {c_bf}">{sgn(bft)}{bft:.2f} %/wk <span style='color:var(--text-subtle);'>({sgn(bft_month)}{bft_month:.2f}/mo)</span></div>"""
        mm_disp = f"""<div class="mini-sub {c_mm}">{sgn(mmt)}{mmt:.2f} kg/wk <span style='color:var(--text-subtle);'>({sgn(mmt_month)}{mmt_month:.2f}/mo)</span></div>"""
    else:
        bf_disp = f"""<div class="mini-sub c-neu">Calibrating ({len(df)}/5)</div>"""
        mm_disp = f"""<div class="mini-sub c-neu">Calibrating ({len(df)}/5)</div>"""

    st.markdown(f"""
    <div class="s-head" style="margin-top:0;">Performance Data</div>
    <div class="mini-grid">
        <div class="mini-cell">
            <span class="mini-lbl">Weight</span>
            <span class="mini-val">{w:.1f}</span>
            <div class="mini-sub {c_w}">{sgn(wt)}{wt:.2f} kg/wk <span style='color:var(--text-subtle);'>({sgn(wt_month)}{wt_month:.2f}/mo)</span></div>
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

    st.markdown(traj_bar("BODY WEIGHT", wt, 'Weight (kg)', ideal_weekly_rates, "kg/wk", mmt, bft, wt_err), unsafe_allow_html=True)
    if has_enough_comp_data:
        st.markdown(
            traj_bar("MUSCLE MASS", mmt, 'Muscle Mass (kg)', ideal_weekly_rates, "kg/wk", mmt, bft, mmt_err) +
            traj_bar("BODY FAT", bft, 'Body Fat (%)', ideal_weekly_rates, "%/wk", mmt, bft, bft_err),
            unsafe_allow_html=True
        )

    st.markdown('<div class="s-head">System Diagnostics</div>', unsafe_allow_html=True)
    w_tgt, w_lower, w_upper = ideal_weekly_rates['Weight (kg)']
    diags = []

    recent_std = df_window_full['Weight (kg)'].tail(7).std()
    if pd.isna(recent_std) or len(df_window_full) < 7:
        diags.append(hud_card("c-neu", "📊", "Trend Confidence: Calibrating", "Need at least 7 days of data for stable noise filtering."))
    elif recent_std > 0.6:
        diags.append(hud_card("c-err", "⚠️", "Trend Confidence: LOW", f"High weight variance ({recent_std:.2f} kg std dev). Water noise heavily present. Do not adjust calories yet."))
    else:
        diags.append(hud_card("c-ok", "📊", "Trend Confidence: HIGH", f"Low variance ({recent_std:.2f} kg std dev). Trend line is stable and reliable."))

    is_muscle_driven = (wt > w_upper) and has_enough_comp_data and (mmt >= (wt * 0.4)) and (bft <= (0.2 * 7 / 30))
    bf_lower = ideal_weekly_rates['Body Fat (%)'][1] if len(ideal_weekly_rates['Body Fat (%)']) > 1 else -99
    is_fat_loss_driven = (wt < w_lower) and has_enough_comp_data and (mmt >= (-0.2 * 7 / 30)) and (bft < bf_lower)

    if days_elapsed_since_start < 21:
        diags.append(hud_card("c-neu", "⏳", "Phase Lock", f"Goal locked for first 3 weeks to stabilize water noise. No adjustments advised. (Day {days_elapsed_since_start}/21)"))
    elif is_muscle_driven:
        diags.append(hud_card("c-ok", "🧬", "Hyper-Anabolic Response", f"Weight is increasing quickly (+{wt:.2f} kg/wk), but it is heavily driven by muscle gain (+{mmt:.2f} kg/wk). Do not cut calories yet."))
    elif is_fat_loss_driven:
        diags.append(hud_card("c-ok", "🔥", "Hyper-Lipolytic Response", f"Weight is dropping fast ({wt:.2f} kg/wk), but muscle is preserved and fat is dropping ({bft:.2f} %/wk). Excellent recomposition."))
    elif wt > w_upper:
        diags.append(hud_card("c-err", "↓", "Over Weekly Limit", f"Weight accumulation ({wt:.2f} kg/wk) exceeds the weekly protocol range. Review the fit line and consider reducing caloric intake by 200 kcal."))
    elif wt < w_lower:
        if w_lower < 0:
            diags.append(hud_card("c-err", "⚠", "Catabolic Danger", f"Losing weight too rapidly ({wt:.2f} kg/wk). Increase caloric intake immediately."))
        else:
            diags.append(hud_card("c-wrn", "↑", "Anabolic Stall", f"Weight accumulation is below {w_lower:.2f} kg/wk. Consider increasing daily caloric intake by 200 kcal."))

    if has_enough_comp_data and not is_muscle_driven and not is_fat_loss_driven:
        m_tgt, m_lower = ideal_weekly_rates['Muscle Mass (kg)'][:2]
        bf_tgt, bf_lower_v, bf_upper = ideal_weekly_rates['Body Fat (%)']
        if wt >= w_lower and mmt < m_lower:
            diags.append(hud_card("c-wrn", "⚠", "Low Muscle Synthesis", f"Weight is tracking, but muscle accumulation is lagging ({mmt:.2f} kg/wk). Keep protein high and watch training recovery."))
        if bft > bf_upper:
            diags.append(hud_card("c-err", "⚠", "Excessive Fat Gain", f"Body fat accumulation ({bft:.2f} %/wk) exceeds limits. Dial back carbs/fats slightly."))

    if len(diags) <= 1:
        diags.append(hud_card("c-ok", "✓", "Locked In", "All tracked parameters are within the weekly protocol range. Stay the course."))

    for d in diags:
        st.markdown(d, unsafe_allow_html=True)

    if st.session_state.get('enable_achievements', True):
        start_gym_time = st.session_state.get('gym_start_date', datetime(2026, 3, 17).date())
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

    if df.empty:
        st.markdown(hud_card("c-neu", "⏳", "No Records Yet", "Log your first measurement from the Entry tab."), unsafe_allow_html=True)
    else:
        data_view = df.sort_values('Date').copy()
        data_view['Weight Δ'] = data_view['Weight (kg)'].diff()
        data_view['Muscle Δ'] = data_view['Muscle Mass (kg)'].diff()
        data_view['Fat Δ'] = data_view['Body Fat (%)'].diff()
        data_view = data_view.sort_values('Date', ascending=False).reset_index().rename(columns={'index': '_row_id'})

        c1, c2, c3 = st.columns(3)
        c1.markdown(f"<div class='mini-cell'><span class='mini-lbl'>Records</span><span class='mini-val'>{len(df)}</span><div class='mini-sub c-neu'>total logs</div></div>", unsafe_allow_html=True)
        c2.markdown(f"<div class='mini-cell'><span class='mini-lbl'>First Log</span><span class='mini-val' style='font-size:1.15rem;'>{df['Date'].min().strftime('%d %b')}</span><div class='mini-sub c-neu'>{df['Date'].min().strftime('%Y')}</div></div>", unsafe_allow_html=True)
        c3.markdown(f"<div class='mini-cell'><span class='mini-lbl'>Latest Log</span><span class='mini-val' style='font-size:1.15rem;'>{df['Date'].max().strftime('%d %b')}</span><div class='mini-sub c-neu'>{df['Date'].max().strftime('%H:%M')}</div></div>", unsafe_allow_html=True)

        display_count = st.selectbox("Rows shown", [14, 30, 60, "All"], index=1)
        if display_count != "All":
            shown = data_view.head(int(display_count)).copy()
        else:
            shown = data_view.copy()

        table_df = shown[['Date', 'Weight (kg)', 'Weight Δ', 'Muscle Mass (kg)', 'Muscle Δ', 'Body Fat (%)', 'Fat Δ']].copy()
        table_df['Date'] = table_df['Date'].dt.strftime('%d %b %Y %H:%M')
        st.dataframe(
            table_df,
            use_container_width=True,
            hide_index=True,
            height=min(620, 88 + 35 * len(table_df)),
            column_config={
                'Date': st.column_config.TextColumn('Date', width='medium'),
                'Weight (kg)': st.column_config.NumberColumn('Weight', format='%.1f kg'),
                'Weight Δ': st.column_config.NumberColumn('Δ Weight', format='%+.1f'),
                'Muscle Mass (kg)': st.column_config.NumberColumn('Muscle', format='%.1f kg'),
                'Muscle Δ': st.column_config.NumberColumn('Δ Muscle', format='%+.1f'),
                'Body Fat (%)': st.column_config.NumberColumn('Fat', format='%.1f%%'),
                'Fat Δ': st.column_config.NumberColumn('Δ Fat', format='%+.1f'),
            }
        )
        st.markdown("<div class='data-note'>Deletion is limited to records from the last 7 days so older history stays protected.</div>", unsafe_allow_html=True)

        seven_days_ago = pd.Timestamp(datetime.now() - timedelta(days=7))
        recent_deletable = data_view[pd.to_datetime(data_view['Date']) >= seven_days_ago].copy()
        if not recent_deletable.empty:
            delete_options = {
                f"{row['Date'].strftime('%d %b %Y %H:%M')} · {row['Weight (kg)']:.1f} kg · {row['Body Fat (%)']:.1f}% fat": int(row['_row_id'])
                for _, row in recent_deletable.iterrows()
            }
            selected_delete = st.selectbox("Delete recent record", list(delete_options.keys()))
            if st.button("Delete Selected Record", use_container_width=True):
                new_df = df.drop(index=delete_options[selected_delete]).reset_index(drop=True)
                overwrite_body_sheet(st.session_state['sheet_url'], new_df)
                st.session_state['active_df'] = new_df
                load_data.clear()
                system_alert("Deleted", "err")
                st.rerun()
        else:
            st.markdown(hud_card("c-neu", "🔒", "History Protected", "No records from the last 7 days are available to delete."), unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# SETTINGS TAB
# ══════════════════════════════════════════════════════════════
elif app_view == "Settings":
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
        w_w, w_min_w, w_max_w = ideal_weekly_rates['Weight (kg)']
        m_w, m_min_w = ideal_weekly_rates['Muscle Mass (kg)'][:2]
        bf_w, bf_min_w, bf_max_w = ideal_weekly_rates['Body Fat (%)']

        st.markdown(f"""
        <div style="font-size:0.75rem; color:var(--text-muted); line-height:1.8; font-family: 'DM Mono', monospace;">
        <b style="color:var(--text-main);">WEIGHT</b>  {w_w:+.2f} kg/wk · Monthly {w_t:+.2f} kg/mo · Range [{w_min:+.2f}, {w_max:+.2f}]<br>
        <b style="color:var(--text-main);">MUSCLE</b>  {m_w:+.2f} kg/wk · Monthly {m_t:+.2f} kg/mo · Min {m_min:+.2f}<br>
        <b style="color:var(--text-main);">FAT</b>     {bf_w:+.2f} %/wk · Monthly {bf_t:+.2f} %/mo · Range [{bf_min:+.2f}, {bf_max:+.2f}]<br>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('<div class="settings-lbl">Nutrition Goals</div>', unsafe_allow_html=True)
    manual_mode_default = parse_int_setting(st.session_state.get('calorie_custom'), 0) > 0
    cal_mode = st.selectbox("Calorie Target Mode", ["Use recommendation", "Manual target"], index=1 if manual_mode_default else 0)
    n1, n2 = st.columns(2)
    with n1:
        n_act = st.selectbox("Activity Level", list(ACTIVITY_MULTIPLIERS.keys()), index=list(ACTIVITY_MULTIPLIERS.keys()).index(st.session_state.get('activity_level', DEFAULT_SETTINGS['activity'])))
    with n2:
        n_prot = st.number_input("Target Protein (g)", min_value=60, max_value=350, value=parse_int_setting(st.session_state.get('protein_custom'), DEFAULT_SETTINGS['protein_custom']), step=5)

    manual_default = parse_int_setting(st.session_state.get('calorie_custom'), 0)
    if manual_default <= 0:
        manual_default = 2600
    n_calories = st.number_input("Manual Calories (kcal)", min_value=1000, max_value=6000, value=manual_default, step=25, disabled=(cal_mode == "Use recommendation"))
    st.markdown("<div class='data-note'>Manual calories override the recommendation. Protein is always your chosen target.</div>", unsafe_allow_html=True)

    st.markdown('<div class="settings-lbl">Tracking Window</div>', unsafe_allow_html=True)
    d1, d2 = st.columns(2)
    with d1:
        new_analysis_start = st.date_input("Tracking Start Date", value=st.session_state['analysis_start_date'])
    with d2:
        new_target_end = st.date_input("Target End Date", value=st.session_state['target_end_date'])
    new_gym_start = st.date_input("Gym Start Date (Achievements)", value=st.session_state['gym_start_date'])
    
    valid_dates = new_target_end > new_analysis_start
    if not valid_dates:
        st.markdown("<div class='alert-banner danger'>Target end date must be after the tracking start date.</div>", unsafe_allow_html=True)

    st.markdown('<div class="settings-lbl">Entry Preferences</div>', unsafe_allow_html=True)
    muscle_mode = st.selectbox("Muscle Mass Input", MUSCLE_INPUT_MODES, index=MUSCLE_INPUT_MODES.index(st.session_state.get('muscle_mass_input_mode', DEFAULT_SETTINGS['muscle_mass_input_mode'])))

    st.markdown('<div class="settings-lbl">System Preferences</div>', unsafe_allow_html=True)
    new_theme = st.selectbox("Theme", ["System", "Dark", "Light"], index=["System", "Dark", "Light"].index(st.session_state['theme_pref']))

    st.markdown('<div class="settings-lbl">Features</div>', unsafe_allow_html=True)
    new_enable_quotes = st.toggle("Motivational Quotes", value=st.session_state.get('enable_quotes', True))
    new_enable_achievements = st.toggle("Achievements System", value=st.session_state.get('enable_achievements', True))

    if st.button("Save Settings to Google Sheets", use_container_width=True, disabled=not valid_dates):
        st.session_state['activity_level'] = n_act
        st.session_state['protein_custom'] = int(n_prot)
        st.session_state['calorie_custom'] = int(n_calories) if cal_mode == "Manual target" else 0
        st.session_state['analysis_start_date'] = new_analysis_start
        st.session_state['target_end_date'] = new_target_end
        st.session_state['gym_start_date'] = new_gym_start
        st.session_state['muscle_mass_input_mode'] = muscle_mode
        st.session_state['theme_pref'] = new_theme
        st.session_state['enable_quotes'] = new_enable_quotes
        st.session_state['enable_achievements'] = new_enable_achievements
        
        ok = persist_app_settings(st.session_state['sheet_url'])
        system_alert("Saved to Sheets" if ok else "Local Save Only", "ok" if ok else "err")
        st.rerun()

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
        st.markdown('<div class="settings-lbl" style="color:var(--c-rose);">Admin Console</div>', unsafe_allow_html=True)
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
