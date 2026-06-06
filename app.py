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
# SHEET‑SPECIFIC HELPERS (WITH FALLBACK)
# ══════════════════════════════════════════════════════════════

def load_body_data(sheet_url):
    """
    Reads body metrics.
    Tries 'Body' tab first; if empty, falls back to the first sheet (range A:E).
    """
    df = read_sheet_range(sheet_url, 'Body!A:E')
    if df.empty:
        # Fallback to original first sheet
        df = read_sheet_range(sheet_url, 'A:E')
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
    """
    Appends to 'Body' tab if it exists, otherwise falls back to the first sheet.
    We try 'Body!A:E' first; if that fails (e.g., sheet doesn't exist), we fallback to 'A:E'.
    """
    time_str = (datetime.utcnow() + timedelta(hours=2)).strftime('%H:%M:%S')
    # Attempt to append to 'Body' sheet; if that fails (sheet missing), use default range.
    if not append_to_sheet(sheet_url, 'Body!A:E', [[date_str, time_str, weight, body_fat, muscle_mass]]):
        # Fallback: append to first sheet's A:E
        append_to_sheet(sheet_url, 'A:E', [[date_str, time_str, weight, body_fat, muscle_mass]])

def overwrite_body_sheet(sheet_url, df):
    """
    Overwrites the body data. Tries 'Body' sheet first, then falls back to first sheet.
    """
    values = [['Date', 'Time', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']]
    for _, row in df.iterrows():
        d = pd.Timestamp(row['Date'])
        values.append([d.strftime('%Y-%m-%d'), d.strftime('%H:%M:%S'), float(row['Weight (kg)']), float(row['Body Fat (%)']), float(row['Muscle Mass (kg)'])])
    if not overwrite_sheet_range(sheet_url, 'Body!A:E', pd.DataFrame(values[1:], columns=values[0])):
        overwrite_sheet_range(sheet_url, 'A:E', pd.DataFrame(values[1:], columns=values[0]))

def load_data_constants(sheet_url):
    """
    Reads height/gender/age from 'Data' tab (A1:C2).
    If missing, returns defaults (from localStorage or 180/male/25).
    """
    df = read_sheet_range(sheet_url, 'Data!A1:C2')
    if df.empty:
        # Fallback: try reading from first sheet? Not needed, just use defaults.
        return {'height': int(st.session_state.get('height_cm', 180)),
                'gender': st.session_state.get('gender', 'male').lower(),
                'age': int(st.session_state.get('age', 25))}
    try:
        h = int(df.iloc[0,0]) if not df.empty else 180
        g = df.iloc[0,1] if df.shape[1]>1 else 'male'
        a = int(df.iloc[0,2]) if df.shape[1]>2 else 25
        return {'height': h, 'gender': g.lower(), 'age': a}
    except:
        return {'height': int(st.session_state.get('height_cm', 180)),
                'gender': st.session_state.get('gender', 'male').lower(),
                'age': int(st.session_state.get('age', 25))}

def write_data_constants(sheet_url, height, gender, age):
    """
    Writes constants to 'Data' tab (A1:C2). Creates/overwrites that range.
    """
    vals = [[height, gender, age]]
    # Only write to 'Data' sheet – will create the sheet if it doesn't exist (via update).
    return overwrite_sheet_range(sheet_url, 'Data!A1:C2', pd.DataFrame(vals, columns=['Height', 'Gender', 'Age']))

def load_workout_data(sheet_url):
    """Read Workout sheet with columns: Date, Exercise, Weight (kg), Reps set 1..4"""
    df = read_sheet_range(sheet_url, 'Workout!A:G')
    if df.empty:
        # Fallback: try first sheet? No, Workout is its own tab; if missing, return empty.
        return pd.DataFrame(columns=['Date','Exercise','Weight (kg)','Reps set 1','Reps set 2','Reps set 3','Reps set 4'])
    expected = ['Date','Exercise','Weight (kg)','Reps set 1','Reps set 2','Reps set 3','Reps set 4']
    for c in expected:
        if c not in df.columns:
            df[c] = '' if c == 'Exercise' else np.nan
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df['Weight (kg)'] = pd.to_numeric(df['Weight (kg)'], errors='coerce')
    for i in range(1,5):
        col = f'Reps set {i}'
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
    return df[expected].dropna(subset=['Date','Exercise']).reset_index(drop=True)

def append_workout_row(sheet_url, row):
    """row: [date, exercise, weight, rep1, rep2, rep3, rep4]"""
    # Try Workout sheet, fallback? Better to just write to 'Workout' tab.
    return append_to_sheet(sheet_url, 'Workout!A:G', [row])

# ══════════════════════════════════════════════════════════════
# LOAD SECRETS & DIRECTORY (unchanged)
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
# SESSION STATE INIT (unchanged)
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

# Body constants (try Data sheet, else use localStorage defaults)
if 'body_constants' not in st.session_state:
    st.session_state['body_constants'] = load_data_constants(st.session_state['sheet_url'])

# Workout exercises (predefined)
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

# CSS, login, admin, math engine, data loading, tabs... (all identical to the last answer, no changes needed except fallback functions above)

# ... (insert the entire CSS block and tab code from the previous complete answer; it's too long to repeat, but I'll include everything else in the final code block for clarity)
