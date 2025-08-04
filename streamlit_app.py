import streamlit as st
import pandas as pd
import requests
import time
import hashlib
from datetime import datetime

st.set_page_config(page_title="AI Sports Betting Dashboard", layout="wide")

if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False

def login():
    st.subheader("🔐 Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        hashed = hashlib.sha256(password.encode()).hexdigest()
        if username == "demo" and hashed == hashlib.sha256("demo123".encode()).hexdigest():
            st.session_state['logged_in'] = True
            st.success("Logged in successfully")
        else:
            st.error("Invalid credentials")

def roi_tracker():
    st.header("📈 ROI Tracker")
    if 'bet_log' not in st.session_state:
        st.session_state['bet_log'] = []

    st.subheader("Record Outcome")
    match = st.text_input("Match")
    odds = st.number_input("Odds", min_value=1.0, step=0.01)
    result = st.selectbox("Result", ["Win", "Loss"])
    if st.button("Add Record"):
        st.session_state['bet_log'].append({
            'match': match,
            'odds': odds,
            'result': result,
            'timestamp': datetime.now()
        })
        st.success("Record added")

    df = pd.DataFrame(st.session_state['bet_log'])
    if not df.empty:
        df['payout'] = df.apply(lambda x: x['odds'] if x['result'] == 'Win' else 0, axis=1)
        df['net'] = df['payout'] - 1
        roi = df['net'].sum()
        win_rate = (df['result'] == 'Win').mean() * 100
        st.metric("Total ROI", f"{roi:.2f} units")
        st.metric("Win Rate", f"{win_rate:.1f}%")
        df['type'] = df['match'].apply(lambda x: 'Over 2.5' if 'Over' in x else ('BTTS' if 'BTTS' in x else 'Other'))
        st.dataframe(df[['match', 'type', 'odds', 'result', 'net', 'timestamp']])
        type_stats = df.groupby('type').agg({'net': 'sum', 'result': lambda x: (x == 'Win').mean() * 100}).rename(columns={'net': 'ROI', 'result': 'Win Rate (%)'})
        st.subheader("Performance by Bet Type")
        st.dataframe(type_stats.reset_index())

if not st.session_state['logged_in']:
    login()
else:
    st.sidebar.button("Logout", on_click=lambda: st.session_state.update({'logged_in': False}))
    roi_tracker()
    st.success("✅ Logged in. Full betting features go here…")