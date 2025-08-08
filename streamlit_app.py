
import streamlit as st
import pandas as pd
import requests
import hashlib
import time as _time
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

st.set_page_config(page_title="AI Sports Betting Assistant", layout="wide")

# -------- AUTH --------
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

def login():
    st.subheader("Login")
    with st.form("login_form"):
        u = st.text_input("Username", key="u")
        p = st.text_input("Password", type="password", key="p")
        ok = st.form_submit_button("Login")
    if ok:
        if u == "demo" and hashlib.sha256(p.encode()).hexdigest() == hashlib.sha256("demo123".encode()).hexdigest():
            st.session_state["logged_in"] = True
            st.success("Logged in")
            st.rerun()
        else:
            st.error("Invalid credentials")

def logout():
    st.session_state.clear()
    st.session_state["logged_in"] = False
    st.rerun()

# -------- KEYS: Secrets-preferred, Sidebar fallback --------
def get_secret(name: str) -> str:
    try:
        return st.secrets[name]
    except Exception:
        return ""

ODDS_API_KEY = get_secret("ODDS_API_KEY")
FOOTBALL_API_KEY = get_secret("FOOTBALL_API_KEY")

with st.sidebar:
    st.header("Configuration")
    if not ODDS_API_KEY:
        ODDS_API_KEY = st.text_input("OddsAPI Key (fallback)", type="password")
    if not FOOTBALL_API_KEY:
        FOOTBALL_API_KEY = st.text_input("API-Football Key (fallback)", type="password")
    st.button("Logout", on_click=logout)

if not st.session_state["logged_in"]:
    login()
    st.stop()

if not ODDS_API_KEY or not FOOTBALL_API_KEY:
    st.error("Missing API keys. Set them as Streamlit Secrets or paste in the sidebar.\n\nSecrets keys:\n- ODDS_API_KEY\n- FOOTBALL_API_KEY")
    st.stop()

# -------- CONFIG --------
LEAGUE_CODES = {
    "EPL": "soccer_epl",
    "La Liga": "soccer_spain_la_liga",
    "Bundesliga": "soccer_germany_bundesliga",
    "Serie A": "soccer_italy_serie_a",
    "Ligue 1": "soccer_france_ligue_one",
}
SEASON = 2024

# -------- THROTTLE --------
def throttle(min_gap: float = 2.0):
    if "last_call" not in st.session_state:
        st.session_state["last_call"] = 0.0
    now = _time.time()
    if now - st.session_state["last_call"] < min_gap:
        st.info("Throttled to protect API usage. Please wait a moment and try again.")
        st.stop()
    st.session_state["last_call"] = now

# -------- CACHED HTTP --------
@st.cache_data(ttl=120, show_spinner=False)
def http_get(url: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        r = requests.get(url, headers=headers or {}, params=params or {}, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

# -------- HELPERS --------
def implied_prob(odds):
    try:
        return round((1/float(odds))*100, 2) if odds and float(odds) > 0 else None
    except Exception:
        return None

@st.cache_data(ttl=600, show_spinner=False)
def football_search_team_id(name: str) -> Optional[int]:
    url = "https://v3.football.api-sports.io/teams"
    data = http_get(url, headers={"x-apisports-key": FOOTBALL_API_KEY}, params={"search": name})
    try:
        for item in data.get("response", []):
            if name.lower() in item["team"]["name"].lower():
                return item["team"]["id"]
    except Exception:
        pass
    return None

@st.cache_data(ttl=600, show_spinner=False)
def football_player_summary(team_id: Optional[int]) -> Dict[str, Any]:
    if not team_id:
        return {"avg_rating":0.0,"avg_shots":0.0,"att_boost":0.0,"def_boost":0.0,"elite":False,"gk_saves":0,"clean_sheets":0}
    url = "https://v3.football.api-sports.io/players"
    data = http_get(url, headers={"x-apisports-key": FOOTBALL_API_KEY}, params={"team": team_id, "season": SEASON})
    rating_sum = 0.0
    shots_sum = 0.0
    n = 0
    att_boost = 0.0
    def_boost = 0.0
    gk_saves = 0
    clean_sheets = 0
    elite = False
    try:
        for p in data.get("response", []):
            stats = p.get("statistics", [{}])[0] or {}
            games = stats.get("games", {}) or {}
            position = games.get("position", "") or p.get("player", {}).get("position","")
            rating = float(games.get("rating", 0) or 0)
            shots = (stats.get("shots", {}) or {}).get("total", 0) or 0
            saves = (stats.get("goals", {}) or {}).get("saves", 0) or 0
            conceded = (stats.get("goals", {}) or {}).get("conceded", 0) or 0
            if position in ("Attacker","Forward"):
                att_boost += (rating*1.5) + (shots*0.5)
                if rating >= 7.5 and shots >= 3:
                    elite = True
            elif position in ("Defender",):
                def_boost += rating
            elif position in ("Goalkeeper",):
                def_boost += rating
                gk_saves += saves
                if conceded == 0:
                    clean_sheets += 1
            rating_sum += rating
            shots_sum += shots
            n += 1
    except Exception:
        pass
    avg_rating = round(rating_sum/n,2) if n else 0.0
    avg_shots = round(shots_sum/n,2) if n else 0.0
    return {"avg_rating":avg_rating,"avg_shots":avg_shots,"att_boost":att_boost,"def_boost":def_boost,"elite":elite,"gk_saves":gk_saves,"clean_sheets":clean_sheets}

@st.cache_data(ttl=120, show_spinner=False)
def fetch_odds(selected_leagues: Tuple[str, ...]) -> pd.DataFrame:
    throttle(0.5)
    rows = []
    for lname, lcode in LEAGUE_CODES.items():
        if lname not in selected_leagues:
            continue
        url = f"https://api.the-odds-api.com/v4/sports/{lcode}/odds/"
        params = {"regions":"eu", "markets":"h2h,totals,btts", "apiKey": ODDS_API_KEY}
        data = http_get(url, params=params)
        for m in data if isinstance(data, list) else []:
            home = m.get("home_team")
            away = m.get("away_team")
            commence = (m.get("commence_time","") or "").replace("T"," ").replace("Z","")
            home_odds = None; away_odds = None
            over25 = None; btts = None
            bookmakers = m.get("bookmakers", []) or []
            if bookmakers:
                markets = bookmakers[0].get("markets", []) or []
                for market in markets:
                    key = market.get("key")
                    outcomes = market.get("outcomes", []) or []
                    if key == "h2h":
                        for o in outcomes:
                            if o.get("name") == home:
                                home_odds = o.get("price")
                            elif o.get("name") == away:
                                away_odds = o.get("price")
                    elif key == "totals":
                        for o in outcomes:
                            name = str(o.get("name","")).lower()
                            if "over" in name and "2.5" in name:
                                over25 = o.get("price")
                    elif key == "btts":
                        for o in outcomes:
                            if o.get("name") in ("Yes","No"):
                                btts = f"{o.get('name')} @ {o.get('price')}"
            if not (home and away and home_odds and away_odds):
                continue

            def ip(x):
                try:
                    return round((1/float(x))*100,2)
                except Exception:
                    return None

            home_prob = ip(home_odds)
            away_prob = ip(away_odds)

            team_id_home = football_search_team_id(home)
            team_id_away = football_search_team_id(away)
            ph = football_player_summary(team_id_home)
            pa = football_player_summary(team_id_away)

            boost_home = ph["att_boost"] - pa["def_boost"]
            boost_away = pa["att_boost"] - ph["def_boost"]
            model_home = min(max((home_prob or 0) + boost_home*0.5, 0), 99.9)
            model_away = min(max((away_prob or 0) + boost_away*0.5, 0), 99.9)
            home_value = (model_home - (home_prob or 0))
            away_value = (model_away - (away_prob or 0))

            rows.append({
                "league": lname,
                "match": f"{home} vs {away}",
                "start_time": commence[:16],
                "home_odds": home_odds,
                "away_odds": away_odds,
                "home_prob": home_prob,
                "away_prob": away_prob,
                "over_2_5": over25,
                "btts": btts,
                "gk_saves": ph["gk_saves"] + pa["gk_saves"],
                "clean_sheets": ph["clean_sheets"] + pa["clean_sheets"],
                "elite_attacker": ph["elite"] or pa["elite"],
                "model_home": round(model_home,2),
                "model_away": round(model_away,2),
                "home_value": round(home_value,2),
                "away_value": round(away_value,2),
            })
    return pd.DataFrame(rows)

# -------- UI --------
st.title("AI Sports Betting Assistant")
st.caption("Live odds + value detection + player metrics + parlay suggestions")

# Last updated banner + refresh
if "last_updated" not in st.session_state:
    st.session_state["last_updated"] = None

col1, col2 = st.columns([0.8, 0.2])
with col1:
    last = st.session_state["last_updated"]
    msg = f"Data last updated: {last}" if last else "Data not loaded yet."
    st.info(msg)
with col2:
    if st.button("Refresh data"):
        http_get.clear()
        football_search_team_id.clear()
        football_player_summary.clear()
        fetch_odds.clear()
        st.session_state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.success("Cache cleared. Re-loading...")
        st.rerun()

selected = st.multiselect(
    "Leagues", list(LEAGUE_CODES.keys()),
    default=list(LEAGUE_CODES.keys())
)

st.header("Live Odds + Value Detection")
df = fetch_odds(tuple(selected))
if st.session_state["last_updated"] is None:
    st.session_state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

if df.empty:
    st.warning("No odds found. Try again later or change leagues.")
else:
    df["Edge"] = df[["home_value","away_value"]].abs().max(axis=1).round(2)
    df["Confidence Index"] = df.apply(lambda r: (
        (max(r.get("home_prob",0) or 0, r.get("away_prob",0) or 0))*0.4 +
        (r.get("gk_saves",0) or 0)*0.2 +
        (r.get("clean_sheets",0) or 0)*0.2 +
        abs(r.get("home_value",0) or 0)*0.1 +
        abs(r.get("away_value",0) or 0)*0.1
    ), axis=1).round(2)
    df["Star"] = df["elite_attacker"].apply(lambda x: "STAR" if x else "")

    threshold = st.slider("Minimum Confidence Index", 0, 100, 70)
    high_only = st.checkbox("Only High-Confidence & High-Edge (CI >= 80 & Edge >= 10)")
    show_cols = ["Star","match","league","start_time","home_odds","away_odds","over_2_5","btts","home_prob","away_prob","home_value","away_value","Edge","Confidence Index"]
    if high_only:
        view = df[(df["Confidence Index"]>=80) & (df["Edge"]>=10)].copy()
    else:
        view = df[df["Confidence Index"]>=threshold].copy()

    st.dataframe(view[show_cols], use_container_width=True)

    st.header("Market-Based Parlay Suggestions")
    st.subheader("Over 2.5 Parlay")
    o25 = view[view["over_2_5"].notna()].sort_values("Confidence Index", ascending=False).head(3)
    if o25.empty:
        st.write("No Over 2.5 selections available.")
    else:
        for _, r in o25.iterrows():
            st.markdown(f"- **{r['match']}** → Over 2.5 @ `{r['over_2_5']}` | CI: `{r['Confidence Index']}` | GK Saves: `{r['gk_saves']}` | Clean Sheets: `{r['clean_sheets']}`")

    st.subheader("BTTS Parlay")
    btts_df = view[view["btts"].notna()].sort_values("Confidence Index", ascending=False).head(3)
    if btts_df.empty:
        st.write("No BTTS selections available.")
    else:
        for _, r in btts_df.iterrows():
            st.markdown(f"- **{r['match']}** → BTTS `{r['btts']}` | CI: `{r['Confidence Index']}` | GK Saves: `{r['gk_saves']}` | Clean Sheets: `{r['clean_sheets']}`")

    st.subheader("Top 10 Matches by Confidence Index")
    top10 = view.sort_values("Confidence Index", ascending=False).head(10)
    st.dataframe(top10[["match","league","Confidence Index","home_odds","away_odds","gk_saves","clean_sheets"]], use_container_width=True)

# -------- ROI TRACKER --------
st.markdown("---")
st.header("ROI Tracker (Manual Entry)")
if "bet_log" not in st.session_state:
    st.session_state["bet_log"] = []

c1, c2, c3, c4 = st.columns(4)
with c1:
    bet_match = st.text_input("Match (e.g., Team A vs Team B Over 2.5)")
with c2:
    bet_odds = st.number_input("Odds", min_value=1.0, step=0.01)
with c3:
    bet_result = st.selectbox("Result", ["Win","Loss"])
with c4:
    if st.button("Add Record"):
        st.session_state["bet_log"].append({"match":bet_match,"odds":bet_odds,"result":bet_result,"timestamp":datetime.now()})
        st.success("Record added")

hist = pd.DataFrame(st.session_state["bet_log"])
if not hist.empty:
    hist["payout"] = hist.apply(lambda x: x["odds"] if x["result"]=="Win" else 0, axis=1)
    hist["net"] = hist["payout"] - 1
    roi = hist["net"].sum()
    win_rate = (hist["result"]=="Win").mean()*100
    st.metric("Total ROI", f"{roi:.2f} units")
    st.metric("Win Rate", f"{win_rate:.1f}%")
    hist["type"] = hist["match"].apply(lambda x: "Over 2.5" if "Over" in x else ("BTTS" if "BTTS" in x else "Other"))
    st.dataframe(hist[["match","type","odds","result","net","timestamp"]], use_container_width=True)
    grp = hist.groupby("type").agg({"net":"sum","result":lambda s:(s=="Win").mean()*100}).rename(columns={"net":"ROI","result":"Win Rate (%)"})
    st.subheader("Performance by Bet Type")
    st.dataframe(grp.reset_index(), use_container_width=True)
