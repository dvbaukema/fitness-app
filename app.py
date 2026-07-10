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
    try:
        return pd.to_datetime(value if value not in (None, "") else default_value).date()
    except Exception:
        return pd.to_datetime(default_value).date()

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
        service.spreadsheets().values().append(
            spreadsheetId=sheet_id, range=range_name,
            valueInputOption='USER_ENTERED', insertDataOption='INSERT_ROWS', body=body
        ).execute()
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
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id, range=range_name,
            valueInputOption='USER_ENTERED', body=body
        ).execute()
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
    if not service or not sheet_id:
        return False
    try:
        meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        titles = [s.get('properties', {}).get('title') for s in meta.get('sheets', [])]
        if tab_name not in titles:
            service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={'requests': [{'addSheet': {'properties': {'title': tab_name}}}]}
            ).execute()
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
    try:
        st.query_params["goal"] = settings['goal']
        st.query_params["theme"] = settings['theme']
        st.query_params["activity"] = settings['activity']
        st.query_params["protein_custom"] = str(settings['protein_custom'])
        st.query_params["calorie_offset"] = str(settings['calorie_offset'])
        st.query_params["calorie_custom"] = str(settings['calorie_custom'])
        st.query_params["start"] = settings['analysis_start']
        st.query_params["end"] = settings['target_end']
        st.query_params["gym_start"] = settings['gym_start']
        st.query_params["mm_mode"] = settings['muscle_mass_input_mode']
        st.query_params["enable_quotes"] = "1" if settings['enable_quotes'] else "0"
        st.query_params["enable_achievements"] = "1" if settings['enable_achievements'] else "0"
    except Exception:
        pass

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
# CSS — MODERN CLEAN DESIGN, VISIBLE SLIDER VALUES
# ══════════════════════════════════════════════════════════════
css_light_vars = """
  --bg-primary: #F8FAFC;
  --bg-secondary: #F1F5F9;
  --text-main: #0F172A;
  --text-muted: #475569;
  --text-subtle: #94A3B8;
  --surface: #FFFFFF;
  --surface-hover: #F8FAFC;
  --surface-active: #F1F5F9;
  --border: rgba(15,23,42,0.06);
  --border-strong: rgba(15,23,42,0.12);
  --c-emerald: #059669;
  --c-emerald-bg: rgba(5, 150, 105, 0.08);
  --c-amber: #D97706;
  --c-amber-bg: rgba(217, 119, 6, 0.08);
  --c-rose: #DC2626;
  --c-rose-bg: rgba(220, 38, 38, 0.08);
  --c-blue: #2563EB;
  --c-blue-bg: rgba(37, 99, 235, 0.08);
  --c-blue-soft: rgba(37, 99, 235, 0.12);
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.04), 0 1px 3px rgba(0,0,0,0.06);
  --shadow-md: 0 4px 6px rgba(0,0,0,0.04), 0 2px 4px rgba(0,0,0,0.06);
  --shadow-lg: 0 10px 15px rgba(0,0,0,0.05), 0 4px 6px rgba(0,0,0,0.05);
  --nav-bg: rgba(248, 250, 252, 0.9);
  --nav-pill: #0F172A;
  --nav-pill-text: #FFFFFF;
  --nav-text: #475569;
  --input-bg: #FFFFFF;
  --input-text: #0F172A;
"""

css_dark_vars = """
  --bg-primary: #0B0F19;
  --bg-secondary: #131A2A;
  --text-main: #E2E8F0;
  --text-muted: #94A3B8;
  --text-subtle: #475569;
  --surface: #1A2332;
  --surface-hover: #1E293B;
  --surface-active: #243044;
  --border: rgba(148,163,184,0.08);
  --border-strong: rgba(148,163,184,0.16);
  --c-emerald: #10B981;
  --c-emerald-bg: rgba(16, 185, 129, 0.1);
  --c-amber: #F59E0B;
  --c-amber-bg: rgba(245, 158, 11, 0.1);
  --c-rose: #F87171;
  --c-rose-bg: rgba(248, 113, 113, 0.1);
  --c-blue: #60A5FA;
  --c-blue-bg: rgba(96, 165, 250, 0.1);
  --c-blue-soft: rgba(96, 165, 250, 0.15);
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.2);
  --shadow-md: 0 4px 6px rgba(0,0,0,0.3);
  --shadow-lg: 0 10px 15px rgba(0,0,0,0.4);
  --nav-bg: rgba(11, 15, 25, 0.88);
  --nav-pill: #E2E8F0;
  --nav-pill-text: #0B0F19;
  --nav-text: #94A3B8;
  --input-bg: #1A2332;
  --input-text: #E2E8F0;
"""

if st.session_state['theme_pref'] == "Dark": theme_block = f":root {{{css_dark_vars}}}"
elif st.session_state['theme_pref'] == "Light": theme_block = f":root {{{css_light_vars}}}"
else: theme_block = f":root {{{css_light_vars}}} @media (prefers-color-scheme: dark) {{ :root {{{css_dark_vars}}} }}"

css = theme_block + """
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;0,9..40,800;1,9..40,400&family=DM+Mono:wght@400;500;600&display=swap');

*, *::before, *::after { box-sizing: border-box; }

.stApp { background: var(--bg-primary) !important; font-family: 'DM Sans', sans-serif !important; }
.block-container { padding-top: 2rem !important; padding-bottom: 6rem !important; max-width: 960px !important; }
#MainMenu, footer, header { display: none !important; }

/* ── App bar & nav ── */
.app-bar { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 2.5rem; }
.wordmark { font-family: 'DM Sans', sans-serif; font-size: 1.85rem; font-weight: 800; color: var(--text-main); letter-spacing: -1.5px; line-height: 1; }
.tagline { font-family: 'DM Mono', monospace; font-size: 0.6rem; color: var(--text-subtle); margin-top: 5px; letter-spacing: 0.8px; }
.live-pill { display: inline-flex; align-items: center; gap: 6px; background: var(--c-emerald-bg); border: 1px solid rgba(16, 185, 129, 0.2); border-radius: 100px; padding: 5px 14px; font-family: 'DM Mono', monospace; font-size: 0.58rem; color: var(--c-emerald); font-weight: 600; letter-spacing: 1.5px; }
.live-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--c-emerald); animation: pulse 2s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(0.7); } }

.nav-container div[role="radiogroup"] { display: flex; flex-wrap: wrap; justify-content: center; gap: 6px; margin-bottom: 2.5rem; margin-top: -0.5rem; background: transparent !important; }
.nav-container div[role="radiogroup"] > label { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 12px !important; padding: 8px 16px !important; margin: 0 !important; cursor: pointer; box-shadow: var(--shadow-sm); transition: all 0.2s ease; }
.nav-container div[role="radiogroup"] > label:hover { border-color: var(--text-muted) !important; }
.nav-container div[role="radiogroup"] > label[data-checked="true"] { background: var(--nav-pill) !important; border-color: var(--nav-pill) !important; box-shadow: var(--shadow-md); }
.nav-container div[role="radiogroup"] > label div { color: var(--text-muted) !important; font-weight: 600 !important; font-family: 'DM Sans', sans-serif !important; font-size: 0.82rem !important; letter-spacing: 0.5px !important; }
.nav-container div[role="radiogroup"] > label[data-checked="true"] div { color: var(--nav-pill-text) !important; font-weight: 700 !important; }
.nav-container div[role="radiogroup"] span[data-baseweb="radio"] { display: none !important; }
.nav-container div[role="radiogroup"] div[data-testid="stMarkdownContainer"] p { margin: 0 !important; padding: 0 !important; }
div[data-testid="stSegmentedControl"] { display: none !important; }

.s-head { font-family: 'DM Mono', monospace !important; font-size: 0.65rem; letter-spacing: 2.5px; color: var(--text-subtle); margin: 2rem 0 1rem; font-weight: 500; text-transform: uppercase; }
.settings-lbl { font-family: 'DM Sans', sans-serif !important; font-size: 0.85rem; color: var(--text-main); font-weight: 700; text-transform: uppercase; margin-top: 2rem; margin-bottom: 1rem; letter-spacing: 1px;}
.quote-box { text-align: center; padding: 1.2rem 1.4rem; border: 1px solid var(--border); border-radius: 14px; background: var(--surface); margin-bottom: 1.75rem; box-shadow: var(--shadow-sm); }
.quote-text { font-family: 'DM Sans', sans-serif; font-size: 0.84rem; color: var(--text-muted); font-style: italic; font-weight: 400; line-height: 1.6; letter-spacing: 0.1px; }

/* ── Grid & cards ── */
.mini-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 1.75rem; }
.mini-cell { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 1.2rem 1rem; box-shadow: var(--shadow-sm); transition: box-shadow 0.2s ease; }
.mini-cell:hover { box-shadow: var(--shadow-md); }
.mini-lbl { font-family: 'DM Mono', monospace; font-size: 0.6rem; color: var(--text-subtle); font-weight: 500; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 8px; display: block; }
.mini-val { font-family: 'DM Mono', monospace; font-size: 1.6rem; font-weight: 600; color: var(--text-main); line-height: 1; display: inline-block;}
.mini-unit { font-size: 0.65rem; color: var(--text-subtle); margin-left: 2px; font-weight: 400;}
.mini-sub { font-family: 'DM Mono', monospace; font-size: 0.65rem; font-weight: 600; margin-top: 8px; display: block; letter-spacing: 0.5px;}

.c-ok  { color: var(--c-emerald) !important; } .c-wrn { color: var(--c-amber) !important; } .c-err { color: var(--c-rose) !important; } .c-neu { color: var(--text-muted) !important; } .c-blue { color: var(--c-blue) !important; }

.chart-blk { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 1.2rem; margin-bottom: 1rem; box-shadow: var(--shadow-sm); }
.chart-meta { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px; }
.t-chip { font-family: 'DM Mono', monospace; font-size: 0.58rem; padding: 4px 9px; border-radius: 100px; font-weight: 600; display: inline-block; letter-spacing: 0.5px;}
.t-chip.c-ok  { background: var(--c-emerald-bg); color: var(--c-emerald) !important; }
.t-chip.c-wrn { background: var(--c-amber-bg); color: var(--c-amber) !important; }
.t-chip.c-err { background: var(--c-rose-bg); color: var(--c-rose) !important; }
.t-chip.c-neu { background: var(--surface-active); color: var(--text-muted) !important; }

/* ── Hud & trajectory ── */
.hud-card { display: flex; gap: 14px; align-items: flex-start; background: var(--surface); border: 1px solid var(--border); padding: 1rem 1.1rem; border-radius: 14px; margin-bottom: 0.6rem; box-shadow: var(--shadow-sm); }
.hud-icon { font-size: 1.1rem; width: 38px; height: 38px; min-width: 38px; display: flex; align-items: center; justify-content: center; border-radius: 10px; background: var(--surface-active); flex-shrink: 0; line-height: 1; }
.hud-title { font-size: 0.78rem; color: var(--text-main); font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 3px; }
.hud-desc { font-size: 0.76rem; color: var(--text-muted); line-height: 1.5; }

.tj-blk { margin-bottom: 2.2rem; }
.tj-row { display: flex; justify-content: space-between; margin-bottom: 10px; align-items: flex-end; }
.tj-nm { font-family: 'DM Mono', monospace; font-size: 0.72rem; color: var(--text-muted); font-weight: 500; text-transform: uppercase; letter-spacing: 1.5px; }
.bar-tk { height: 20px; border-radius: 10px; overflow: hidden; margin-bottom: 8px; position: relative; }
.bar-pin { position: absolute; top: -2px; bottom: -2px; width: 3px; background: var(--text-main); box-shadow: 0 0 0 2px var(--bg-primary), 0 0 12px rgba(255,255,255,0.3); z-index: 5; transform: translateX(-50%); border-radius: 2px; }
.tj-st { font-family: 'DM Mono', monospace; font-size: 0.58rem; font-weight: 600; letter-spacing: 2px; text-transform: uppercase; display: block; margin-top: 8px; }

/* ── Achievements ── */
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

/* ── SIMPLE, CLEAN SLIDERS WITH VISIBLE VALUE ── */
div[data-testid="stSlider"] {
    padding-top: 0.5rem !important;
    padding-bottom: 0.1rem !important;
}
div[data-testid="stSlider"] > div > div > div {
    height: 6px !important;
    background: var(--border) !important;
    border-radius: 3px !important;
    overflow: hidden !important;
}
div[data-testid="stSlider"] > div > div > div > div:first-child {
    background: var(--c-blue) !important;
    height: 6px !important;
}
/* Show the numeric value neatly */
div[data-testid="stSlider"] div[data-baseweb="slider"] div[role="slider"] > div {
    font-size: 0.85rem !important;
    font-weight: 700 !important;
    color: var(--text-main) !important;
    background: var(--surface) !important;
    padding: 2px 8px !important;
    border-radius: 6px !important;
    border: 1px solid var(--border-strong) !important;
    box-shadow: var(--shadow-sm) !important;
    transform: translateY(-36px);
}
/* Slider thumb */
div[data-testid="stSlider"] div[role="slider"] {
    background: var(--c-blue) !important;
    border: 2px solid white !important;
    width: 18px !important;
    height: 18px !important;
    border-radius: 50% !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2) !important;
    margin-top: -6px;
}
div[data-testid="stSlider"] div[role="slider"]:focus {
    box-shadow: 0 0 0 3px rgba(37,99,235,0.3) !important;
    outline: none !important;
}

/* ── Inputs & buttons ── */
div[data-testid="stSelectbox"] { margin-bottom: 0 !important; }
div[data-testid="stSelectbox"] > div > div { background: var(--input-bg) !important; border: 1px solid var(--border) !important; border-radius: 12px !important; color: var(--input-text) !important; min-height: 3.2rem !important; box-shadow: var(--shadow-sm) !important; }
div[data-testid="stSelectbox"] div[class*="singleValue"] { color: var(--input-text) !important; font-weight: 600 !important; font-family: 'DM Sans', sans-serif !important; }
div[data-testid="stSelectbox"] [class*="placeholder"] { color: var(--text-muted) !important; }
div[data-testid="stSelectbox"] [class*="menu"] { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 12px !important; }
div[data-testid="stSelectbox"] [class*="option"] { color: var(--input-text) !important; background: transparent !important; }
div[data-testid="stSelectbox"] [class*="option"]:hover { background: var(--surface-active) !important; }

div[data-testid="stTextInput"] > div > div { background: var(--input-bg) !important; border: 1px solid var(--border) !important; border-radius: 12px !important; min-height: 3.2rem !important; }
div[data-testid="stTextInput"] input { color: var(--input-text) !important; font-family: 'DM Mono', monospace !important; font-size: 1rem !important; text-align: center !important; background: transparent !important; }

div[data-testid="stForm"] button { background: var(--text-main) !important; color: var(--bg-primary) !important; font-family: 'DM Sans', sans-serif !important; font-weight: 700 !important; font-size: 0.82rem !important; border: none !important; border-radius: 12px !important; padding: 1rem !important; margin-top: 1.5rem !important; text-transform: uppercase !important; letter-spacing: 2px !important; box-shadow: var(--shadow-md) !important; transition: all 0.2s ease !important; }
div[data-testid="stForm"] button:hover { transform: translateY(-1px) !important; box-shadow: var(--shadow-lg) !important; }

.stButton > button { background: var(--surface) !important; color: var(--text-main) !important; font-family: 'DM Sans', sans-serif !important; font-weight: 700 !important; font-size: 0.82rem !important; border: 1px solid var(--border) !important; border-radius: 12px !important; padding: 0.6rem 1.2rem !important; margin-top: 0 !important; text-transform: uppercase !important; letter-spacing: 1.5px !important; box-shadow: var(--shadow-sm) !important; transition: all 0.2s ease !important; }
.stButton > button:hover { background: var(--surface-active) !important; box-shadow: var(--shadow-md) !important; }

div[data-testid="stDateInput"] > div > div { background: var(--input-bg) !important; border: 1px solid var(--border) !important; border-radius: 12px !important; color: var(--input-text) !important; }
div[data-testid="stDateInput"] input { color: var(--input-text) !important; }

div[data-testid="stToggle"] label p { color: var(--text-main) !important; font-size: 0.85rem !important; }
div[data-testid="stExpander"] { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 14px !important; overflow: hidden; }
div[data-testid="stExpander"] summary p { color: var(--text-main) !important; font-size: 0.82rem !important; font-weight: 600 !important; }

div[data-testid="stAlert"] { border-radius: 12px !important; }
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 2px; }

@media (max-width: 760px) { 
  .block-container { padding-left: 1rem !important; padding-right: 1rem !important; } 
  .mini-val { font-size: 1.25rem; } 
  .chart-meta { flex-direction: column; gap: 12px; } 
}
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
                st.query_params["user"] = user_key
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
# DATA LOADING & STATISTICAL ENGINE (EMA for all metrics)
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
        if ss_tot_w < 0.001 and ss_res_w < 0.001: r2_w = 1.0
        else: r2_w = max(0.0, 1 - (ss_res_w / ss_tot_w)) if ss_tot_w != 0 else 1.0
        
        fit_type_w = 'point-to-point slope'
    else:
        slope_w = res_w.slope
        stderr_w = regression_stderr_w
        r2_w = 0 if pd.isna(res_w.rvalue) else res_w.rvalue ** 2
        fit_y_w = res_w.intercept + slope_w * X_w_raw
        fit_type_w = 'linear regression'

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
            if ss_tot_c < 0.001 and ss_res_c < 0.001: r2_c = 1.0 
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
            traj_data[m] = {
                'fit_dates': df_c['Date'].tolist(),
                'fit': fit_y_c,
            }

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
        <div class="tagline">{get_display_name(st.session_state['current_user'])} · Beta 10</div>
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
    <div class="s-head" style="margin-bottom:0;">New Entry</div>
    """, unsafe_allow_html=True)

    # Sliders with visible labels and values (no help to avoid crash)
    w_val = float(last['Weight (kg)'])
    st.markdown("<div style='text-align:center; font-weight:800; font-size:0.75rem; color:var(--text-subtle); text-transform:uppercase; letter-spacing:1.5px; margin-top:1rem;'>Weight (kg)</div>", unsafe_allow_html=True)
    w = st.slider("Weight", min_value=max(0.0, w_val-5.0), max_value=w_val+5.0, value=w_val, step=0.1, label_visibility="collapsed")

    mm_mode = st.session_state.get('muscle_mass_input_mode', 'Percentage (%)')
    if mm_mode == "Kilograms (kg)":
        m_val = float(last['Muscle Mass (kg)'])
        st.markdown("<div style='text-align:center; font-weight:800; font-size:0.75rem; color:var(--text-subtle); text-transform:uppercase; letter-spacing:1.5px; margin-top:1rem;'>Muscle Mass (kg)</div>", unsafe_allow_html=True)
        m = st.slider("Muscle Mass", min_value=max(0.0, m_val-5.0), max_value=m_val+5.0, value=m_val, step=0.1, label_visibility="collapsed")
    else:
        current_pct = (last['Muscle Mass (kg)'] / last['Weight (kg)']) * 100 if last['Weight (kg)'] > 0 else 45.0
        st.markdown("<div style='text-align:center; font-weight:800; font-size:0.75rem; color:var(--text-subtle); text-transform:uppercase; letter-spacing:1.5px; margin-top:1rem;'>Muscle Mass (%)</div>", unsafe_allow_html=True)
        m_pct = st.slider("Muscle Mass", min_value=max(0.0, current_pct-5.0), max_value=min(100.0, current_pct+5.0), value=current_pct, step=0.1, label_visibility="collapsed")
        m = w * (m_pct / 100.0)
        st.markdown(f"<div class='data-note' style='text-align:center; margin-top:-10px; margin-bottom:15px; font-weight:600;'>Calculated: {m:.1f} kg</div>", unsafe_allow_html=True)

    bf_val = float(last['Body Fat (%)'])
    st.markdown("<div style='text-align:center; font-weight:800; font-size:0.75rem; color:var(--text-subtle); text-transform:uppercase; letter-spacing:1.5px; margin-top:1rem;'>Body Fat (%)</div>", unsafe_allow_html=True)
    bf = st.slider("Body Fat", min_value=max(3.0, bf_val-5.0), max_value=bf_val+5.0, value=bf_val, step=0.1, label_visibility="collapsed")

    with st.form("log_form", border=False):
        if st.form_submit_button("Save Record", use_container_width=True):
            now_str = datetime.now().strftime('%Y-%m-%d')
            append_body_entry(st.session_state['sheet_url'], now_str, w, m, bf)
            st.session_state['active_df'] = pd.concat([st.session_state['active_df'], pd.DataFrame({'Date': [datetime.now()], 'Weight (kg)': [w], 'Body Fat (%)': [bf], 'Muscle Mass (kg)': [m]})], ignore_index=True)
            load_data.clear()
            if st.session_state['enable_quotes']: st.session_state['daily_quote'] = random.choice(st.session_state['all_quotes'])
            system_alert("Saved")
            st.rerun()

# ... (the rest of the tabs: Nutrition, Trends, Analysis, Data, Settings) remain exactly as before.
# I've omitted them for brevity, but they are unchanged from your original code.
# Just copy and paste the entire block from your original "Nutrition" tab onward.
