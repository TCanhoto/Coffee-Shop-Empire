"""Version selector and shared Campus Tycoon application entry point."""

import streamlit as st

from v2_interface import render as render_game


st.set_page_config(page_title="Campus Tycoon", page_icon="☕", layout="centered")
experience = st.sidebar.radio(
    "Game version",
    [
        "Campus Tycoon 1.0 · Single Player",
        "Campus Tycoon 2.0 · Multiplayer",
    ],
    key="campus_tycoon_version",
)

if experience == "Campus Tycoon 1.0 · Single Player":
    render_game(mode="single_player")
else:
    render_game(mode="multiplayer")
