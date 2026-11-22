"""Version selector and shared Coffee Shop Empire application entry point."""

import streamlit as st

from v2_interface import render as render_game


st.set_page_config(page_title="Coffee Shop Empire", page_icon="☕", layout="centered")
experience = st.sidebar.radio(
    "Game version",
    [
        "Coffee Shop Empire 1.0 · Single Player",
        "Coffee Shop Empire 2.0 · Multiplayer",
    ],
    key="campus_tycoon_version",
)

if experience == "Coffee Shop Empire 1.0 · Single Player":
    render_game(mode="single_player")
else:
    render_game(mode="multiplayer")
