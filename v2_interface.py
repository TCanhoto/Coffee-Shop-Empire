"""Small Streamlit screens for creating, joining, and resuming V2 sessions."""

import streamlit as st

import v2_storage
from business_logic import calculate_demand, format_euros, price_to_cents


def _save_player_identity(progress: dict, recovery_credential: str) -> None:
    st.session_state["v2_player"] = {
        "session_id": progress["session_id"],
        "player_id": progress["player_id"],
        "nickname": progress["nickname"],
        "recovery_credential": recovery_credential,
    }


def _session_summary(session: dict) -> None:
    st.write(f"**Game code:** `{session['join_code']}`")
    st.write(f"Trading days: {session['trading_days']}")
    st.write(f"Starting cash: {format_euros(session['starting_budget_cents'])}")
    st.write(f"Status: **{session['status'].title()}**")


def _show_player_cafe(session: dict, player: dict) -> None:
    database = v2_storage.V2_DATABASE_PATH
    progress = v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    history = v2_storage.load_player_trade_history(
        database, session["session_id"], player["player_id"]
    )
    action_message = st.session_state.pop("v2_player_action_message", None)
    if action_message:
        st.success(action_message)
    st.subheader(f"{progress['nickname']}'s café")
    st.metric("Available cash", format_euros(progress["cash_cents"]))
    last_day = session["trading_days"]
    if progress["current_day"] <= last_day:
        st.metric("Trading day", f"{progress['current_day']} of {last_day}")
    else:
        st.metric("Trading day", f"Complete ({last_day} days)")
        st.success("You completed all trading days for this game.")

    if session["status"] != "active":
        st.info("This game is not active yet. Wait for the host to start it.")
        return

    can_trade = progress["current_day"] <= last_day
    st.caption(
        "Demand follows the V1 rule: at or below the reference price, 10 units; "
        "above it and up to twice the reference price, 5 units; above twice the "
        "reference price, 0 units."
    )
    for product in progress["products"]:
        key = product["product_key"]
        with st.container(border=True):
            st.markdown(f"**{product['name']}**")
            st.write(
                f"In stock: **{product['quantity']}** · Purchase cost: "
                f"{format_euros(product['purchase_cost_cents'])} · Reference price: "
                f"{format_euros(product['reference_price_cents'])}"
            )
            price_field = st.text_input(
                f"Selling price for {product['name']} (€)",
                value=(
                    f"{product['selected_price_cents'] // 100}."
                    f"{product['selected_price_cents'] % 100:02d}"
                ),
                key=f"v2_price_{player['player_id']}_{key}",
                disabled=not can_trade,
            )
            try:
                preview_price = price_to_cents(price_field)
            except ValueError as error:
                st.error(str(error))
            else:
                demand = calculate_demand(
                    preview_price, product["reference_price_cents"]
                )
                st.write(f"Expected daily demand at this price: **{demand} units**")
            if st.button(
                f"Save price for {product['name']}",
                key=f"v2_save_price_{player['player_id']}_{key}",
                disabled=not can_trade,
            ):
                try:
                    saved = v2_storage.set_player_selling_price(
                        database,
                        session["session_id"],
                        player["player_id"],
                        key,
                        price_field,
                    )
                except ValueError as error:
                    st.error(str(error))
                else:
                    st.session_state["v2_player_action_message"] = (
                        f"{product['name']} selling price saved as {format_euros(saved)}."
                    )
                    st.rerun()

            quantity = st.number_input(
                f"Units to buy ({product['name']})",
                min_value=1,
                value=1,
                step=1,
                key=f"v2_quantity_{player['player_id']}_{key}",
                disabled=not can_trade,
            )
            if st.button(
                f"Buy {product['name']}",
                key=f"v2_buy_{player['player_id']}_{key}",
                disabled=not can_trade,
            ):
                try:
                    total = v2_storage.purchase_player_stock(
                        database,
                        session["session_id"],
                        player["player_id"],
                        key,
                        int(quantity),
                    )
                except ValueError as error:
                    st.error(str(error))
                else:
                    st.session_state["v2_player_action_message"] = (
                        f"Bought {int(quantity)} {product['name'].lower()} unit(s) "
                        f"for {format_euros(total)}."
                    )
                    st.rerun()

    if can_trade and st.button(
        f"Complete Day {progress['current_day']}",
        type="primary",
        key=f"v2_complete_day_{player['player_id']}_{progress['current_day']}",
    ):
        try:
            result = v2_storage.trade_player_day(
                database,
                session["session_id"],
                player["player_id"],
                expected_day=progress["current_day"],
            )
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state["v2_last_trade_message"] = (
                f"Day {result['day']} completed. Revenue: "
                f"{format_euros(result['totals']['revenue_cents'])}."
            )
            st.rerun()

    trade_message = st.session_state.pop("v2_last_trade_message", None)
    if trade_message:
        st.success(trade_message)
    if history:
        st.subheader("Trading history")
        rows = [
            {
                "Day": item["day"],
                "Units sold": item["totals"]["units_sold"],
                "Revenue": format_euros(item["totals"]["revenue_cents"]),
                "Gross profit": format_euros(item["totals"]["gross_profit_cents"]),
                "Cash after trading": format_euros(item["cash_cents_after"]),
            }
            for item in history
        ]
        st.dataframe(rows, hide_index=True, use_container_width=True)


def _show_waiting_room(
    session_id: str, *, host: bool, player_id: str | None = None
) -> None:
    session = v2_storage.get_game_session(v2_storage.V2_DATABASE_PATH, session_id)
    st.subheader("Waiting room" if session["status"] == "waiting" else "Game status")
    _session_summary(session)
    players = v2_storage.list_session_players(
        v2_storage.V2_DATABASE_PATH, session_id
    )
    st.markdown("**Players who have joined**")
    if players:
        for index, player in enumerate(players, start=1):
            st.write(f"{index}. {player['nickname']}")
    else:
        st.caption("No players have joined yet.")

    if host and session["status"] == "waiting":
        host_credential = st.session_state.get("v2_host_credential")
        if st.button(
            "Start Game",
            type="primary",
            key="v2_start_game",
            disabled=not players or not host_credential,
        ):
            try:
                v2_storage.start_game_session(
                    v2_storage.V2_DATABASE_PATH, session_id, host_credential
                )
            except ValueError as error:
                st.error(str(error))
            else:
                st.rerun()
        st.caption("You can start once at least one player has joined.")
    elif session["status"] == "waiting":
        st.info("The host has not started the game yet. Refresh to check again.")
    elif session["status"] == "active":
        st.success("The game has started.")
        if player_id:
            _show_player_cafe(
                session, {"session_id": session_id, "player_id": player_id}
            )
        else:
            st.info("Join as a player to manage a café in this game.")
    else:
        st.info("This game is finished.")

    if session["status"] == "waiting" and st.button(
        "Refresh waiting room", key=f"refresh_{session_id}"
    ):
        st.rerun()


def _host_page() -> None:
    st.header("Host Game")
    existing_session_id = st.session_state.get("v2_host_session_id")
    if existing_session_id:
        st.write("Share this six-character code with the other players:")
        st.code(st.session_state["v2_host_code"])
        credential = st.session_state.pop("v2_new_host_credential", None)
        if credential:
            st.warning("Save this private host credential. It is shown only once.")
            st.code(credential)
        player = st.session_state.get("v2_player", {})
        player_id = (
            player.get("player_id")
            if player.get("session_id") == existing_session_id
            else None
        )
        _show_waiting_room(existing_session_id, host=True, player_id=player_id)
        return

    st.caption("Choose the game length and starting cash. Allowed ranges: 1–30 days and €1–€10,000.")
    with st.expander("Resume host controls"):
        with st.form("v2_resume_host_form"):
            resume_code = st.text_input("Six-character game code", max_chars=6).strip().upper()
            host_credential = st.text_input("Private host credential", type="password")
            resume_submitted = st.form_submit_button("Resume Host Controls")
        if resume_submitted:
            try:
                session = v2_storage.authenticate_host(
                    v2_storage.V2_DATABASE_PATH, resume_code, host_credential
                )
            except ValueError as error:
                st.error(str(error))
            else:
                st.session_state["v2_host_session_id"] = session["session_id"]
                st.session_state["v2_host_code"] = session["join_code"]
                st.session_state["v2_host_credential"] = host_credential
                st.rerun()

    with st.form("v2_create_game_form"):
        trading_days = st.number_input(
            "Trading days", min_value=1, max_value=30, value=7, step=1
        )
        starting_budget = st.text_input("Starting cash (€)", value="2000.00")
        submitted = st.form_submit_button("Create Game", type="primary", use_container_width=True)

    if submitted:
        try:
            session = v2_storage.create_game_session(
                v2_storage.V2_DATABASE_PATH,
                trading_days=int(trading_days),
                starting_budget=starting_budget,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state["v2_host_session_id"] = session["session_id"]
            st.session_state["v2_host_code"] = session["join_code"]
            st.session_state["v2_host_credential"] = session["host_credential"]
            st.session_state["v2_new_host_credential"] = session["host_credential"]
            st.rerun()


def _join_page() -> None:
    st.header("Join Game")
    player = st.session_state.get("v2_player")
    if player:
        new_credential = st.session_state.pop("v2_new_player_credential", None)
        if new_credential:
            st.warning("Save this private recovery credential. It is shown only once.")
            st.code(new_credential)
        st.write(f"You joined as **{player['nickname']}**.")
        _show_waiting_room(
            player["session_id"], host=False, player_id=player["player_id"]
        )
        return

    st.caption("Enter the code shared by the host and choose a nickname.")
    with st.form("v2_join_game_form"):
        join_code = st.text_input("Six-character game code", max_chars=6).strip().upper()
        nickname = st.text_input("Nickname", max_chars=30)
        submitted = st.form_submit_button("Join Game", type="primary", use_container_width=True)

    if submitted:
        try:
            player = v2_storage.join_game_session(
                v2_storage.V2_DATABASE_PATH, join_code, nickname
            )
        except ValueError as error:
            st.error(str(error))
        else:
            _save_player_identity(player, player["recovery_credential"])
            st.session_state["v2_new_player_credential"] = player["recovery_credential"]
            st.rerun()

def _resume_page() -> None:
    st.header("Resume Game")
    player = st.session_state.get("v2_player")
    if player:
        st.success(f"Resumed as {player['nickname']}.")
        _show_waiting_room(
            player["session_id"], host=False, player_id=player["player_id"]
        )
        if st.button("Sign out of this player", key="v2_sign_out"):
            st.session_state.pop("v2_player", None)
            st.rerun()
        return

    with st.form("v2_resume_game_form"):
        join_code = st.text_input("Six-character game code", max_chars=6).strip().upper()
        nickname = st.text_input("Nickname", max_chars=30)
        recovery_credential = st.text_input(
            "Private recovery credential", type="password"
        )
        submitted = st.form_submit_button("Resume Game", type="primary", use_container_width=True)

    if submitted:
        try:
            progress = v2_storage.resume_player_by_credentials(
                v2_storage.V2_DATABASE_PATH,
                join_code,
                nickname,
                recovery_credential,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            _save_player_identity(progress, recovery_credential)
            st.rerun()


def render() -> None:
    """Render V2 lobby navigation and the selected screen."""

    v2_storage.initialize_v2_database(v2_storage.V2_DATABASE_PATH)
    st.title("Campus Tycoon 2.0")
    st.caption("Create a multiplayer game, join with a code, or securely resume.")
    page = st.selectbox(
        "Multiplayer pages",
        ["Host Game", "Join Game", "Resume Game"],
    )
    if page == "Host Game":
        _host_page()
    elif page == "Join Game":
        _join_page()
    else:
        _resume_page()
