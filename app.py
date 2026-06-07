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
    sync('activity'); sync('protein_custom'); sync('calorie_offset');
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
# SHEET‑SPECIFIC HELPERS – TAB STRUCTURE:
#   Body   → constants (height, gender, age, weight optional)
#   Data   → time‑series body measurements
#   Workout → per‑set logs (Date, Workout Type, Exercise, Weight, Set, Reps)
# ══════════════════════════════════════════════════════════════

def load_body_constants(sheet_url):
    """Read height, gender, age from 'Body' tab (A1:C2)."""
    df = read_sheet_range(sheet_url, 'Body!A1:C2')
    if df.empty:
        return {'height': 180, 'gender': 'male', 'age': 25}
    try:
        h = int(float(df.iloc[0,0])) if not df.empty else 180
        g = df.iloc[0,1].strip().lower() if df.shape[1]>1 else 'male'
        a = int(float(df.iloc[0,2])) if df.shape[1]>2 else 25
        return {'height': h, 'gender': g, 'age': a}
    except:
        return {'height': 180, 'gender': 'male', 'age': 25}

def load_body_data(sheet_url):
    """Read time‑series body metrics from 'Data' tab (A:E)."""
    df = read_sheet_range(sheet_url, 'Data!A:E')
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
    return append_to_sheet(sheet_url, 'Data!A:E', [[date_str, time_str, weight, body_fat, muscle_mass]])

def overwrite_body_sheet(sheet_url, df):
    values = [['Date', 'Time', 'Weight (kg)', 'Body Fat (%)', 'Muscle Mass (kg)']]
    for _, row in df.iterrows():
        d = pd.Timestamp(row['Date'])
        values.append([d.strftime('%Y-%m-%d'), d.strftime('%H:%M:%S'), float(row['Weight (kg)']), float(row['Body Fat (%)']), float(row['Muscle Mass (kg)'])])
    return overwrite_sheet_range(sheet_url, 'Data!A:E', pd.DataFrame(values[1:], columns=values[0]))

def load_workout_data(sheet_url):
    """Read Workout sheet: Date, Workout Type, Exercise, Weight, Set, Reps."""
    df = read_sheet_range(sheet_url, 'Workout!A:F')
    if df.empty:
        return pd.DataFrame(columns=['Date','Workout Type','Exercise','Weight','Set','Reps'])
    # Ensure columns exist
    expected = ['Date','Workout Type','Exercise','Weight','Set','Reps']
    for c in expected:
        if c not in df.columns:
            df[c] = '' if c == 'Exercise' else np.nan
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df['Weight'] = pd.to_numeric(df['Weight'], errors='coerce')
    df['Set'] = pd.to_numeric(df['Set'], errors='coerce').fillna(1).astype(int)
    df['Reps'] = pd.to_numeric(df['Reps'], errors='coerce').fillna(0).astype(int)
    return df[expected].dropna(subset=['Date','Exercise']).reset_index(drop=True)

def append_workout_rows(sheet_url, rows):
    """rows: list of lists [date, workout_type, exercise, weight, set_number, reps]"""
    for r in rows:
        append_to_sheet(sheet_url, 'Workout!A:F', [r])

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

# Body constants (source of truth: 'Body' sheet)
if 'body_constants' not in st.session_state:
    st.session_state['body_constants'] = load_body_constants(st.session_state['sheet_url'])

# Nutrition state
if 'activity_level' not in st.session_state:
    st.session_state['activity_level'] = st.query_params.get("activity", "moderate")
if 'calorie_offset' not in st.session_state:
    st.session_state['calorie_offset'] = int(st.query_params.get("calorie_offset", 0))
if 'protein_custom' not in st.session_state:
    st.session_state['protein_custom'] = int(st.query_params.get("protein_custom", 150))
if 'nutrition_phase_start' not in st.session_state:
    st.session_state['nutrition_phase_start'] = datetime.now().date()

# Workout exercises (predefined, with default weight & sets)
if 'exercises' not in st.session_state:
    st.session_state['exercises'] = [
        {"Name": "DB Press (45°)", "Category": "Chest", "Muscle Group": "Upper Chest"},
        # ... (same full list as before)
    ]

# ══════════════════════════════════════════════════════════════
# CSS THEME & STYLES (identical to previous version, omitted for brevity)
# ... (paste the entire CSS block from earlier correct answer)
# ══════════════════════════════════════════════════════════════

# AUTO‑LOGIN & ADMIN (unchanged)
# ...

# ══════════════════════════════════════════════════════════════
# MATH & EVALUATION FUNCTIONS (unchanged)
# ══════════════════════════════════════════════════════════════
def sgn(v): return "+" if v > 0 else ""
def dclass(v, invert=False):
    if invert: v = -v
    return "c-ok" if v > 0 else ("c-err" if v < 0 else "c-neu")
# ... eval_metric, get_gradient, hud_card, traj_bar (same as before)

# ══════════════════════════════════════════════════════════════
# NUTRITION CALCULATIONS (NEW – TDEE BASED)
# ══════════════════════════════════════════════════════════════
def calculate_bmr(weight_kg, height_cm, age, gender):
    if gender == "male":
        return 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    else:
        return 10 * weight_kg + 6.25 * height_cm - 5 * age - 161

def calculate_tdee(bmr, activity_level):
    factors = {
        "sedentary": 1.2,
        "lightly_active": 1.375,
        "moderate": 1.55,
        "very_active": 1.725,
        "athlete": 1.9
    }
    return bmr * factors.get(activity_level, 1.55)

def get_protocol_calorie_adjustment(protocol):
    """Return daily kcal surplus/deficit based on monthly weight change target.
       Uses 7700 kcal ≈ 1 kg body weight change."""
    target_rate = DEFAULT_PROFILES[protocol]['Weight (kg)'][0]  # kg/month
    return (target_rate * 7700) / 30  # daily kcal adjustment

def get_nutrition_targets(protocol, weight, height_cm, age, gender, activity_level, offset=0):
    bmr = calculate_bmr(weight, height_cm, age, gender)
    tdee = calculate_tdee(bmr, activity_level)
    daily_adjustment = get_protocol_calorie_adjustment(protocol)
    base_calories = round(tdee + daily_adjustment)
    final_calories = base_calories + offset
    protein_range = (round(weight * 1.6), round(weight * 2.2))
    return final_calories, protein_range

def get_context_adaptive_recommendation(protocol, weight_trend, bf_trend, current_offset, current_calories):
    # same logic as before, just messages adjusted
    w_lower, w_upper = DEFAULT_PROFILES[protocol]['Weight (kg)'][1], DEFAULT_PROFILES[protocol]['Weight (kg)'][2]
    bf_target, bf_lower, bf_upper = DEFAULT_PROFILES[protocol]['Body Fat (%)']

    if weight_trend > w_upper and bf_trend > bf_upper:
        return (f"Fat gain detected – weight +{weight_trend:.1f} kg/mo, fat +{bf_trend:.1f}%/mo. Consider reducing calories.",
                current_offset - 200)
    if weight_trend > w_upper and bf_trend <= bf_target:
        return (f"Lean mass progression – weight +{weight_trend:.1f} kg/mo, fat trend good. Maintain current intake.",
                current_offset)
    if weight_trend < w_lower:
        if "Cut" in protocol:
            return (f"Weight loss too fast ({weight_trend:.1f} kg/mo). Increase calories to preserve muscle.",
                    current_offset + 200)
        else:
            return (f"Weight gain below target ({weight_trend:.1f} kg/mo). Increase calories.",
                    current_offset + 250)
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

# ... (trends calculation identical)

# ══════════════════════════════════════════════════════════════
# MAIN ROUTING
# ══════════════════════════════════════════════════════════════
active_goal = st.session_state.get('current_goal', 'Lean Bulk')
ideal_rates = GOAL_PROFILES.get(active_goal, GOAL_PROFILES['Lean Bulk'])
header_placeholder = st.empty()
app_view = st.radio("Nav", ["Entry", "Trends", "Analysis", "Data", "Nutrition", "Workout", "Settings"],
                    horizontal=True, label_visibility="collapsed")

# ══════════════════════════════════════════════════════════════
# ENTRY TAB (unchanged)
# ══════════════════════════════════════════════════════════════
# (identical to previous version, uses append_body_entry etc.)

# ══════════════════════════════════════════════════════════════
# TRENDS / ANALYSIS / DATA tabs (unchanged)
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════
# NUTRITION TAB (REWRITTEN)
# ══════════════════════════════════════════════════════════════
elif app_view == "Nutrition":
    header_placeholder.empty()
    # Use latest weight (or a fallback)
    if len(df) > 0:
        current_weight = df.iloc[-1]['Weight (kg)']
    else:
        current_weight = 70.0

    bc = st.session_state['body_constants']
    height, gender, age = bc['height'], bc['gender'], bc['age']

    # Activity level is a setting, but we can allow changing it here or in Settings
    activity = st.session_state['activity_level']

    # Calculate base target
    final_cals, prot_range = get_nutrition_targets(
        active_goal, current_weight, height, age, gender, activity,
        offset=st.session_state['calorie_offset']
    )

    st.markdown(f"""
    <div class="s-head" style="margin-top:0;">Daily Targets</div>
    <div style="display:flex; gap:20px; margin-bottom:1.5rem;">
        <div style="flex:1; background:var(--surface); border:1px solid var(--border); border-radius:16px; padding:1.2rem; text-align:center;">
            <div style="font-family:'DM Mono',monospace; font-size:0.65rem; color:var(--text-subtle); letter-spacing:2px;">CALORIES</div>
            <div style="font-size:2.5rem; font-weight:700; color:var(--text-main); font-family:'DM Mono',monospace;">{final_cals}</div>
            <div style="font-size:0.7rem; color:var(--text-muted);">kcal/day (TDEE + protocol)</div>
        </div>
        <div style="flex:1; background:var(--surface); border:1px solid var(--border); border-radius:16px; padding:1.2rem; text-align:center;">
            <div style="font-family:'DM Mono',monospace; font-size:0.65rem; color:var(--text-subtle); letter-spacing:2px;">PROTEIN</div>
            <div style="font-size:2.5rem; font-weight:700; color:var(--text-main); font-family:'DM Mono',monospace;">{st.session_state['protein_custom']}</div>
            <div style="font-size:0.7rem; color:var(--text-muted);">g/day (custom · rec {prot_range[0]}–{prot_range[1]})</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    new_prot = st.number_input("Custom Protein Target (g)", min_value=50, max_value=300,
                               value=st.session_state['protein_custom'], step=5)
    if new_prot != st.session_state['protein_custom']:
        st.session_state['protein_custom'] = new_prot
        st.query_params.protein_custom = str(new_prot)
        st.rerun()

    # Adaptive recommendation
    if has_enough_weight_data and has_enough_comp_data:
        wt_trend = monthly_trends.get('Weight (kg)', 0)
        bf_trend = monthly_trends.get('Body Fat (%)', 0)
        msg, new_offset = get_context_adaptive_recommendation(
            active_goal, wt_trend, bf_trend,
            st.session_state['calorie_offset'], final_cals
        )
        st.markdown(f"<div class='alert-banner info'>{msg}</div>", unsafe_allow_html=True)
        if new_offset != st.session_state['calorie_offset'] and st.button("Accept Adjustment", use_container_width=True):
            st.session_state['calorie_offset'] = new_offset
            st.query_params.calorie_offset = str(new_offset)
            st.session_state['nutrition_phase_start'] = datetime.now().date()
            system_alert(f"Offset set to {new_offset:+d}")
            st.rerun()
    else:
        st.info("Need at least 3 body weight + 5 composition entries for adaptive feedback.")

# ══════════════════════════════════════════════════════════════
# WORKOUT TAB (REDESIGNED)
# ══════════════════════════════════════════════════════════════
elif app_view == "Workout":
    header_placeholder.empty()

    # Templates: (exercise, default_weight, default_sets)
    UPPER1 = [
        ("DB Press (45°)", 20, 2),
        ("Incline Chest Press Machine", 22.5, 2),
        ("Assisted Pullup", -18, 2),
        ("Single Hand Seated Row", 20, 2),
        ("Side Delt Flys", 2.3, 2),
        ("Cross-Body Cable Tricep Ext", 6.8, 2)
    ]
    LOWER1 = [
        ("Barbell Squat", 70, 2),
        ("Leg Press", 0, 2),
        ("Leg Extensions", -39, 2),
        ("Leg Curls", 52, 2),
        ("Standing Calf Raises", 10, 2),
        ("Abs Rope", 30, 2)
    ]
    UPPER2 = [
        ("Lat Pulldown", 45, 2),
        ("Shoulder Press Machine", 10, 2),
        ("Upper Back Row", 10, 2),
        ("Pec Deck Fly", None, 2),
        ("Brachialis Rope Curl", 11.3, 2),
        ("Overhead Tricep Ext", 9, 2)
    ]
    LOWER2 = [
        ("RDLs", 40, 2),
        ("Barbell Squat", 75, 2),
        ("Seated or Lying Hamstring Curls", 59, 2),
        ("45° Hyperextension", 10, 2),
        ("Calf Raises", 35, 2),
        ("Abs Rope", 45, 2)
    ]
    templates = {
        "Upper 1": UPPER1,
        "Lower 1": LOWER1,
        "Upper 2": UPPER2,
        "Lower 2": LOWER2
    }

    workout_type = st.selectbox("Workout", list(templates.keys()))
    exercises = templates[workout_type]

    # Load previous data for weight auto-fill
    w_df = load_workout_data(st.session_state['sheet_url'])
    if not w_df.empty:
        last_date = w_df['Date'].max().strftime('%d %b %Y')
    else:
        last_date = "never"
    st.markdown(f"**Last recorded workout:** {last_date}")
    st.markdown("---")

    with st.form("workout_form", clear_on_submit=False):
        data_to_log = []
        for ex_name, def_weight, def_sets in exercises:
            st.markdown(f"**{ex_name}**")
            # Pre-fill weight from history
            if not w_df.empty:
                ex_hist = w_df[w_df['Exercise'] == ex_name]
                last_weight = ex_hist['Weight'].values[0] if not ex_hist.empty else def_weight
                if last_weight is None or last_weight == 0:
                    last_weight = def_weight if def_weight else 0.0
            else:
                last_weight = def_weight if def_weight else 0.0

            weight = st.number_input(f"{ex_name} Weight (kg)", value=float(last_weight),
                                     step=0.5, key=f"w_{ex_name}_{workout_type}")
            sets = st.number_input(f"Number of sets", min_value=1, max_value=8, value=def_sets,
                                   key=f"nsets_{ex_name}_{workout_type}")
            reps = []
            for s in range(sets):
                rep_val = st.number_input(f"Set {s+1} reps", min_value=0, value=0,
                                          key=f"rep_{ex_name}_{s}_{workout_type}")
                reps.append(rep_val)
            data_to_log.append((ex_name, weight, reps))
            st.markdown("---")

        workout_date = st.date_input("Workout Date", datetime.now().date())
        if st.form_submit_button("Log Workout"):
            rows = []
            for ex_name, weight, reps in data_to_log:
                for set_idx, r in enumerate(reps):
                    if r > 0:
                        rows.append([
                            workout_date.strftime('%Y-%m-%d'),
                            workout_type,
                            ex_name,
                            weight,
                            set_idx+1,
                            r
                        ])
            if rows:
                append_workout_rows(st.session_state['sheet_url'], rows)
                system_alert("Workout saved")
            st.rerun()

# ══════════════════════════════════════════════════════════════
# SETTINGS TAB (no body profile editing)
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

    st.markdown('<div class="settings-lbl">Activity Level</div>', unsafe_allow_html=True)
    new_activity = st.selectbox("Activity Level", ["sedentary", "lightly_active", "moderate", "very_active", "athlete"],
                                index=["sedentary", "lightly_active", "moderate", "very_active", "athlete"].index(
                                    st.session_state['activity_level']))
    if new_activity != st.session_state['activity_level']:
        st.session_state['activity_level'] = new_activity
        st.query_params.activity = new_activity
        # Recalculate nutrition targets immediately? Not necessary, next visit to Nutrition tab will use it.
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
