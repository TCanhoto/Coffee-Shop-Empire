"""Small Streamlit screens for creating, joining, and resuming V2 sessions."""

import sqlite3

import streamlit as st

import v2_storage
from content import MAX_MENU_SIZE
from business_logic import format_euros, price_to_cents
from demand_engine import calculate_v2_demand
from estimate_ranges import demand_estimate_range
from v2_ui_components import render_sticky_business_header


def _save_player_identity(progress: dict, recovery_credential: str) -> None:
    st.session_state["v2_player"] = {
        "session_id": progress["session_id"],
        "player_id": progress["player_id"],
        "nickname": progress["nickname"],
        "recovery_credential": recovery_credential,
    }


def _navigate_to(section: str) -> None:
    # The selectbox already exists in this run. Apply the new choice on rerun.
    st.session_state["v2_next_section"] = section
    st.rerun()


def _player_destination(progress: dict) -> str:
    if progress["location"] is None:
        return "Café Setup"
    if progress["current_day"] > 1:
        return "Dashboard"
    return "Today"


def _session_summary(session: dict) -> None:
    st.write(f"**Game code:** `{session['join_code']}`")
    st.write(f"Trading days: {session['trading_days']}")
    st.write(f"Starting cash: {format_euros(session['starting_budget_cents'])}")
    st.write(f"Status: **{session['status'].title()}**")


def _show_management_dashboard(
    progress: dict, history: list[dict], total_days: int, can_trade: bool
) -> None:
    """Render current player metrics and charts from saved results only."""

    accumulated_revenue_cents = sum(
        item["totals"]["revenue_cents"] for item in history
    )
    accumulated_customers = sum(item["customers_served"] for item in history)
    accumulated_result_cents = (
        progress["cash_cents"] - progress["starting_cash_cents"]
    )
    if progress["is_bankrupt"]:
        day_value = f"Ended on Day {progress['current_day'] - 1}"
    elif progress["current_day"] > total_days:
        day_value = f"Complete ({total_days} days)"
    else:
        day_value = f"{progress['current_day']} of {total_days}"

    st.subheader("Management Dashboard")
    if history:
        _show_day_results(history[-1])
        if can_trade:
            if st.button(f"Continue to Day {progress['current_day']}", type="primary"):
                _navigate_to("Today")
        elif st.button("View Final Report", type="primary"):
            _navigate_to("Final Report")
    first_row = st.columns(2, gap="small")
    first_row[0].metric("Available cash", format_euros(progress["cash_cents"]))
    first_row[1].metric("Current day", day_value)
    second_row = st.columns(2, gap="small")
    second_row[0].metric(
        "Accumulated revenue", format_euros(accumulated_revenue_cents)
    )
    second_row[1].metric(
        "Accumulated game result", format_euros(accumulated_result_cents)
    )
    third_row = st.columns(2, gap="small")
    third_row[0].metric("Customers served", f"{accumulated_customers:,}")
    third_row[1].metric(
        "Inventory units",
        f"{sum(product['quantity'] for product in progress['products']):,}",
    )
    st.caption(
        "Game result is current cash minus starting cash. Inventory has no recovery "
        "value at the end of the game."
    )

    st.subheader("Current inventory")
    st.dataframe(
        [
            {
                "Product": product["name"],
                "Units in stock": product["quantity"],
                "Menu": "Active" if product["is_active"] else "Off menu",
            }
            for product in progress["products"]
        ],
        hide_index=True,
        width="stretch",
    )

    st.subheader("Daily results history")
    if not history:
        st.info(
            "No trading days have been completed yet. Complete your first day to "
            "see revenue, cash, customer, and product-sales charts here."
        )
        return

    day_numbers = [item["day"] for item in history]
    st.subheader("Revenue by completed day")
    st.line_chart(
        {
            "Day": day_numbers,
            "Revenue (€)": [
                item["totals"]["revenue_cents"] / 100 for item in history
            ],
        },
        x="Day",
        y="Revenue (€)",
        height=240,
        width="stretch",
    )

    st.subheader("Cash balance over time")
    st.caption("Closing cash after each completed day, with starting cash at Day 0.")
    cash_days = [0, *day_numbers]
    cash_values = [progress["starting_cash_cents"] / 100] + [
        item["cash_cents_after"] / 100 for item in history
    ]
    st.line_chart(
        {"Day": cash_days, "Cash (€)": cash_values},
        x="Day",
        y="Cash (€)",
        height=240,
        width="stretch",
    )

    units_by_product = {item["product_key"]: 0 for item in progress["products"]}
    names_by_product = {
        item["product_key"]: item["name"] for item in progress["products"]
    }
    for day in history:
        for product in day["products"]:
            units_by_product[product["product_key"]] = (
                units_by_product.get(product["product_key"], 0)
                + product["units_sold"]
            )
            names_by_product[product["product_key"]] = product["name"]
    ranked_products = sorted(
        units_by_product.items(),
        key=lambda item: (-item[1], names_by_product[item[0]].casefold()),
    )
    product_rows = [
        {"Product": names_by_product[key], "Units sold": units}
        for key, units in ranked_products
    ]
    st.subheader("Units sold by product")
    st.bar_chart(
        product_rows,
        x="Product",
        y="Units sold",
        horizontal=True,
        height=max(250, min(420, 28 * len(product_rows))),
        width="stretch",
    )
    st.subheader("Best-selling products")
    st.dataframe(
        [
            {"Rank": rank, **row}
            for rank, row in enumerate(product_rows, start=1)
        ],
        hide_index=True,
        width="stretch",
    )

    st.dataframe(
        [
            {
                "Day": item["day"],
                "Customers served": item["customers_served"],
                "Units sold": item["totals"]["units_sold"],
                "Revenue": format_euros(item["totals"]["revenue_cents"]),
                "Rent paid": format_euros(item["rent_paid_cents"]),
                "Cash after day": format_euros(item["cash_cents_after"]),
            }
            for item in history
        ],
        hide_index=True,
        width="stretch",
    )


def _show_final_performance_report(report: dict) -> None:
    """Display a finished player's saved-data report and evidence-based advice."""

    st.subheader("Final Performance Report")
    st.metric("Final game result", format_euros(report["final_game_result_cents"]))
    if report["ranking_is_final"]:
        st.metric("Final ranking", f"#{report['ranking_position']}")
    else:
        st.metric("Provisional ranking", f"#{report['ranking_position']}")
        st.info("This ranking is provisional because other players are still playing.")

    metrics = st.columns(2, gap="small")
    metrics[0].metric("Total revenue", format_euros(report["total_revenue_cents"]))
    metrics[1].metric("Total customers served", f"{report['total_customers_served']:,}")

    st.caption("Best and worst products are ranked by total gross profit.")
    best = report["best_product"]
    worst = report["worst_product"]
    if best is None:
        st.write("**Best-performing product:** No product sales were recorded.")
        st.write("**Worst-performing offered product:** No product sales were recorded.")
    else:
        st.write(
            f"**Best-performing product:** {best['name']} "
            f"(gross profit {format_euros(best['gross_profit_cents'])})"
        )
        st.write(
            f"**Worst-performing offered product:** {worst['name']} "
            f"(gross profit {format_euros(worst['gross_profit_cents'])})"
        )

    st.write(
        f"**Remaining unsold inventory:** {report['remaining_inventory_units']:,} "
        f"units · purchase-cost value {format_euros(report['remaining_inventory_value_cents'])}. "
        "This value is informational and is not added to the final game result."
    )
    st.metric("Lost product-demand units due to stock limits", f"{report['lost_sales_units']:,}")
    st.caption(
        "Calculated from recorded product demand minus units sold; it excludes visitors "
        "who had no suitable drink on the menu."
    )

    persona = report["most_served_persona"]
    if persona:
        st.write(
            f"**Most successfully served persona:** {persona['name']} "
            f"({persona['customers_served']:,} customers)"
        )
    else:
        st.info("Most-served persona is unavailable because no customers were served or persona data is missing.")

    st.markdown("**Recommendations based on your saved results**")
    if report["recommendations"]:
        for recommendation in report["recommendations"]:
            st.write(f"- {recommendation['text']}")
            st.caption(f"Evidence: {recommendation['evidence']}")
    else:
        st.write("No recommendation rules were triggered by the recorded results.")

    if report["missing_data"]:
        with st.expander("Data limitations"):
            for note in report["missing_data"]:
                st.write(f"- {note}")


def _show_menu_setup(
    database: str, session: dict, player: dict, progress: dict, can_trade: bool
) -> None:
    menu_products = [
        product for product in progress["products"] if product["category"] != "Legacy"
    ]
    menu_by_key = {product["product_key"]: product for product in menu_products}
    active_menu_keys = [
        product["product_key"] for product in menu_products if product["is_active"]
    ]
    legacy_menu = len(active_menu_keys) > MAX_MENU_SIZE
    st.subheader("Build your menu")
    selected_menu = st.multiselect(
        "Choose products",
        options=list(menu_by_key),
        default=active_menu_keys,
        format_func=lambda key: (
            f"{menu_by_key[key]['name']} · {menu_by_key[key]['category']} · "
            f"reference {format_euros(menu_by_key[key]['reference_price_cents'])}"
        ),
        # Legacy saves may already exceed the new cap. Let players remove items
        # from those menus without hiding any saved selections; saving stays blocked.
        max_selections=None if legacy_menu else MAX_MENU_SIZE,
        key=f"v2_menu_select_{player['player_id']}_{progress['current_day']}",
        disabled=not can_trade,
    )
    st.caption(f"{len(selected_menu)} of {MAX_MENU_SIZE} products selected")
    if not selected_menu:
        st.info("Select at least one product for your menu.")
    if len(selected_menu) >= MAX_MENU_SIZE:
        st.info(f"Maximum reached: you can select up to {MAX_MENU_SIZE} products.")
    if legacy_menu:
        st.warning(
            f"This saved menu has {len(active_menu_keys)} products. Its data is preserved; "
            f"reduce it to {MAX_MENU_SIZE} or fewer before saving the menu again."
        )
    st.caption(
        "A menu needs at least one drink. Changes apply to the upcoming day. "
        "Removing a product keeps its unsold stock."
    )
    st.dataframe(
        [
            {
                "Product": product["name"],
                "Category": product["category"],
                "Reference price": format_euros(product["reference_price_cents"]),
            }
            for product in menu_products
        ],
        hide_index=True,
        width="stretch",
    )
    if not can_trade:
        st.info("Menu editing is disabled because your game has ended or is waiting to start.")
    if st.button(
        "Save menu",
        key=f"v2_save_menu_{player['player_id']}_{progress['current_day']}",
        disabled=not can_trade or not selected_menu or len(selected_menu) > MAX_MENU_SIZE,
        use_container_width=True,
    ):
        try:
            v2_storage.set_player_menu(
                database,
                session["session_id"],
                player["player_id"],
                selected_menu,
                expected_day=progress["current_day"],
            )
        except ValueError as error:
            st.error(str(error))
        except sqlite3.Error:
            st.error("The menu could not be saved. Please try again.")
        else:
            st.session_state["v2_player_action_message"] = "Your café menu was saved."
            _navigate_to("Today")

    if progress["location"]:
        st.subheader("Signed location")
        location = progress["location"]
        st.markdown(f"### 📍 {location['name']}")
        st.write(location["description"])
        st.write(
            f"Daily foot traffic: **{location['passers_by_per_day']:,}** · "
            f"Daily rent: **{format_euros(location['rent_per_day_cents'])}**"
        )


def _show_player_cafe(
    session: dict, player: dict, section: str = "Today"
) -> None:
    database = v2_storage.V2_DATABASE_PATH
    progress = v2_storage.get_player_progress(
        database, session["session_id"], player["player_id"]
    )
    history = v2_storage.load_player_trade_history(
        database, session["session_id"], player["player_id"]
    )
    _show_new_player_credential()
    action_message = st.session_state.pop("v2_player_action_message", None)
    if action_message:
        st.success(action_message)
    last_day = session["trading_days"]
    render_sticky_business_header(progress, last_day)
    if session["status"] == "waiting":
        st.info("This game is not active yet. Wait for the host to start it.")
        return

    if progress["location"] is None:
        if section == "Café Setup":
            _show_location_setup(database, session, player)
        else:
            st.info("Complete Café Setup first: choose a location and sign the lease.")
        return

    st.subheader(f"☕ {progress['nickname']}'s café")
    if progress["is_bankrupt"]:
        st.error("Your café could not pay its full rent. Your game has ended.")
    elif progress["current_day"] > last_day:
        st.success("You completed all trading days for this game.")

    can_trade = (
        session["status"] == "active"
        and not progress["is_bankrupt"]
        and progress["current_day"] <= last_day
    )
    if section == "Today":
        st.info(
            "Plan today's menu in Café Setup, then set prices and buy stock here. "
            "When you're ready, Complete Day will show a confirmation before trading."
        )
        st.progress(
            min(progress["current_day"] - 1, last_day) / last_day,
            text=f"{min(progress['current_day'] - 1, last_day)} of {last_day} days completed",
        )
    if section == "Dashboard":
        _show_management_dashboard(progress, history, last_day, can_trade)
        return
    if section == "Café Setup":
        _show_menu_setup(database, session, player, progress, can_trade)
        return
    if section == "Final Report":
        if can_trade:
            st.info("Your Final Report will be available after you finish all trading days.")
            st.caption(f"Progress: {min(progress['current_day'] - 1, last_day)} of {last_day} days.")
        else:
            _show_final_performance_report(
                v2_storage.get_player_final_report(
                    database, session["session_id"], player["player_id"]
                )
            )
        return
    if not can_trade:
        report = v2_storage.get_player_final_report(
            database, session["session_id"], player["player_id"]
        )
        st.success("Your game is complete. Open Final Report to review your results.")
        return
    menu_products = [product for product in progress["products"] if product["category"] != "Legacy"]
    menu_by_key = {product["product_key"]: product for product in menu_products}
    active_menu_keys = [
        product["product_key"] for product in menu_products if product["is_active"]
    ]
    st.info(
        "Demand is deterministic: 10% of passers-by become potential visitors. "
        "Each visitor can request one suitable drink. Persona preferences and "
        "price limits split demand across your menu; a price above twice the "
        "reference price gets no demand. Up to 60% of drink customers receive "
        "one food opportunity. Sales cannot exceed stock, and customers do not "
        "substitute when an item is unavailable."
    )
    with st.expander("How persona prices affect demand"):
        st.write(
            "Maximum prices by persona: Student 1.00× reference; Local & "
            "traditional 1.25×; Digital nomad 1.50×; Healthy & plant-based "
            "1.75×; Tourist 2.00×. The limits include the exact boundary. "
            "At or below reference price, a product gets twice the allocation "
            "weight it gets above reference but within the persona's limit. "
            "Affinity scores 0, 1, and 3 mean no interest, likes, and strong "
            "preference. When whole visitors must be split, largest remainders "
            "are assigned using the documented fixed persona and product order."
        )
    st.caption(
        "Profit is not forecast before your final purchases and trading. "
        "Completed-day results, including profit and rent, appear on Dashboard."
    )
    for product in progress["products"]:
        if not product["is_active"]:
            continue
        key = product["product_key"]
        with st.container(border=True):
            icon = "🥤" if product.get("is_drink") else "🥐"
            st.markdown(f"### {icon} {product['name']}")
            st.write(
                f"Category: **{product['category']}** · Reference price: "
                f"{format_euros(product['reference_price_cents'])} · "
                f"In stock: **{product['quantity']}** · Purchase cost: "
                f"{format_euros(product['purchase_cost_cents'])}"
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
                preview_products = [
                    {
                        **item,
                        "selected_price_cents": (
                            preview_price
                            if item["product_key"] == key
                            else item["selected_price_cents"]
                        ),
                    }
                    for item in menu_products
                    if item["is_active"]
                ]
                preview = calculate_v2_demand(
                    progress["location"], preview_products
                )
                demand = preview["products"][key]["demand"]
                demand_low, demand_high = demand_estimate_range(demand)
                st.write(
                    f"Estimated demand range at this price: **{demand_low:,}–"
                    f"{demand_high:,} units/day** before applying stock limits. "
                    "This is a planning range, not a guaranteed minimum or maximum."
                )
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
            # A successful purchase changes stock and invalidates the old form.
            day = progress["current_day"]
            stock = product["quantity"]
            form_key = f"v2_purchase_{player['player_id']}_{key}_{day}_{stock}"
            with st.form(form_key, enter_to_submit=False, border=False):
                quantity = st.number_input(
                    f"Units to buy ({product['name']})",
                    min_value=1,
                    value=1,
                    step=1,
                    key=f"{form_key}_quantity",
                )
                buy = st.form_submit_button(f"Buy {product['name']}")
            if buy:
                try:
                    total = v2_storage.purchase_player_stock(
                        database,
                        session["session_id"],
                        player["player_id"],
                        key,
                        int(quantity),
                        expected_day=day,
                        expected_stock=stock,
                    )
                except ValueError as error:
                    st.error(str(error))
                else:
                    st.session_state["v2_player_action_message"] = (
                        f"Bought {int(quantity)} {product['name'].lower()} unit(s) "
                        f"for {format_euros(total)}."
                    )
                    st.rerun()

    off_menu_stock = [
        product
        for product in progress["products"]
        if not product["is_active"] and product["quantity"] > 0
    ]
    if off_menu_stock:
        st.subheader("Stock from removed menu items")
        st.caption("This stock is preserved and is excluded from purchases and trading while off-menu.")
        st.dataframe(
            [
                {
                    "Product": product["name"],
                    "Units kept in stock": product["quantity"],
                    "Category": product["category"],
                }
                for product in off_menu_stock
            ],
            hide_index=True,
            use_container_width=True,
        )

    confirm_key = f"v2_confirm_day_{player['player_id']}_{progress['current_day']}"
    if can_trade and st.button(
        f"Complete Day {progress['current_day']}",
        type="primary",
        key=f"v2_complete_day_{player['player_id']}_{progress['current_day']}",
        use_container_width=True,
    ):
        st.session_state[confirm_key] = True
        st.rerun()

    if can_trade and st.session_state.get(confirm_key):
        st.warning(
            f"Complete Day {progress['current_day']} now? This records sales, "
            "charges rent, and advances your game by one day."
        )
        confirm_col, cancel_col = st.columns(2, gap="small")
        if confirm_col.button(
            "Confirm Complete Day",
            type="primary",
            key=f"v2_confirm_complete_{player['player_id']}_{progress['current_day']}",
            use_container_width=True,
        ):
            st.session_state.pop(confirm_key, None)
            try:
                result = v2_storage.trade_player_day(
                    database,
                    session["session_id"],
                    player["player_id"],
                    expected_day=progress["current_day"],
                )
            except ValueError as error:
                st.error(str(error))
            except sqlite3.Error:
                st.error("The day could not be completed. Please try again.")
            else:
                st.session_state["v2_player_action_message"] = (
                    f"Day {result['day']} completed. Revenue: "
                    f"{format_euros(result['totals']['revenue_cents'])}. "
                    f"Rent paid: {format_euros(result['rent_paid_cents'])} of "
                    f"{format_euros(result['rent_due_cents'])}. "
                    f"Customers served: {result['customers_served']}; "
                    f"visitors lost: {result['lost_visitors']}."
                    + (" Your café is bankrupt and your game has ended."
                       if result["bankrupt"] else "")
                )
                _navigate_to("Dashboard")
        if cancel_col.button(
            "Cancel",
            key=f"v2_cancel_complete_{player['player_id']}_{progress['current_day']}",
            use_container_width=True,
        ):
            st.session_state.pop(confirm_key, None)
            st.rerun()

    if history:
        _show_day_results(history[-1])


def _show_day_results(latest: dict) -> None:
    st.subheader(f"Day {latest['day']} results")
    st.dataframe(
        [
            {
                "Product": item["name"],
                "Demand": item["demand"],
                "Units sold": item["units_sold"],
                "Revenue": format_euros(item["revenue_cents"]),
                "Cost of goods sold": format_euros(
                    item["cost_of_goods_sold_cents"]
                ),
                "Gross profit": format_euros(item["gross_profit_cents"]),
            }
            for item in latest["products"]
        ]
        + [
            {
                "Product": "TOTAL",
                "Demand": latest["totals"]["demand"],
                "Units sold": latest["totals"]["units_sold"],
                "Revenue": format_euros(latest["totals"]["revenue_cents"]),
                "Cost of goods sold": format_euros(
                    latest["totals"]["cost_of_goods_sold_cents"]
                ),
                "Gross profit": format_euros(
                    latest["totals"]["gross_profit_cents"]
                ),
            }
        ],
        hide_index=True,
        use_container_width=True,
    )
    st.caption(
        f"Rent: {format_euros(latest['rent_paid_cents'])} paid of "
        f"{format_euros(latest['rent_due_cents'])} due; "
        f"{format_euros(latest['rent_shortfall_cents'])} forgiven."
    )


@st.dialog("Confirm your café lease", width="small", dismissible=False)
def _confirm_location_lease(
    database: str, session: dict, player: dict, location: dict
) -> None:
    """Confirm and persist one player's selected lease from a modal dialog."""

    st.write(f"Sign a lease for **{location['name']}**?")
    st.write(f"Daily rent: **{format_euros(location['rent_per_day_cents'])}**")
    st.warning("Once signed, this lease cannot be changed for the rest of the game.")

    if st.button(
        "Sign the lease",
        type="primary",
        key=f"v2_dialog_sign_lease_{player['player_id']}",
        use_container_width=True,
    ):
        try:
            confirmed = v2_storage.select_player_location(
                database,
                session["session_id"],
                player["player_id"],
                location["location_key"],
            )
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state.pop(f"v2_pending_location_{player['player_id']}", None)
            st.session_state["v2_player_action_message"] = (
                f"Lease signed for {confirmed['name']}. Your location is locked."
            )
            st.rerun()

    if st.button(
        "Cancel",
        key=f"v2_dialog_cancel_lease_{player['player_id']}",
        use_container_width=True,
    ):
        st.session_state.pop(f"v2_pending_location_{player['player_id']}", None)
        st.rerun()


def _show_location_setup(database: str, session: dict, player: dict) -> None:
    """Render Day 0 cards; only signing writes the selected location to SQLite."""

    st.header("📍 Day 0 — Choose your café location")
    st.write("Review the locations, choose one, then confirm your lease.")
    locations = v2_storage.list_locations(database)
    pending_key = f"v2_pending_location_{player['player_id']}"
    pending_location = st.session_state.get(pending_key)

    for location in locations:
        with st.container(border=True):
            st.subheader(f"☕ {location['name']}")
            st.write(location["description"])
            st.write(f"Daily foot traffic: **{location['passers_by_per_day']:,} people**")
            st.write(f"Daily rent: **{format_euros(location['rent_per_day_cents'])}**")
            if st.button(
                "Choose this location",
                key=f"v2_choose_location_{player['player_id']}_{location['location_key']}",
            ):
                st.session_state[pending_key] = location["location_key"]
                st.rerun()

    selected = next(
        (location for location in locations if location["location_key"] == pending_location),
        None,
    )
    if selected:
        _confirm_location_lease(database, session, player, selected)


def _leave_player_lobby(session_id: str, player_id: str) -> None:
    progress = v2_storage.get_player_progress(
        v2_storage.V2_DATABASE_PATH, session_id, player_id
    )
    st.session_state.pop("v2_waiting_player", None)
    _navigate_to(_player_destination(progress))


@st.fragment(run_every=2.5)
def _watch_for_game_start(session_id: str, player_id: str) -> None:
    if v2_storage.get_game_session_status(v2_storage.V2_DATABASE_PATH, session_id) != "waiting":
        _leave_player_lobby(session_id, player_id)


def _show_waiting_room(
    session_id: str, *, host: bool, player_id: str | None = None
) -> None:
    session = v2_storage.get_game_session(v2_storage.V2_DATABASE_PATH, session_id)
    if player_id and session["status"] != "waiting" and st.session_state.get(
        "v2_waiting_player"
    ) == (session_id, player_id):
        _leave_player_lobby(session_id, player_id)
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
                if player_id:
                    _leave_player_lobby(session_id, player_id)
                st.rerun()
        st.caption("You can start once at least one player has joined.")
    elif session["status"] == "waiting":
        st.info("The host has not started the game yet. This page will update automatically.")
        if player_id:
            st.session_state["v2_waiting_player"] = (session_id, player_id)
            _watch_for_game_start(session_id, player_id)
    elif session["status"] == "active":
        st.success("The game has started.")
        if player_id:
            st.info("Choose Today, Café Setup, Dashboard, or Final Report from navigation.")
        else:
            st.info("Join as a player to manage a café in this game.")
    else:
        st.info("This game is finished.")
        if player_id:
            _show_player_cafe(
                session, {"session_id": session_id, "player_id": player_id}
            )

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


def _show_new_player_credential() -> None:
    credential = st.session_state.pop("v2_new_player_credential", None)
    if credential:
        st.warning("Save this private recovery credential. It is shown only once.")
        st.code(credential)


def _join_page() -> None:
    st.header("Join Game")
    player = st.session_state.get("v2_player")
    if player:
        st.write(f"You joined as **{player['nickname']}**.")
        _show_waiting_room(
            player["session_id"], host=False, player_id=player["player_id"]
        )
        _show_new_player_credential()
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
            st.session_state["v2_waiting_player"] = (player["session_id"], player["player_id"])
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
            st.session_state.pop("v2_waiting_player", None)
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
            status = v2_storage.get_game_session_status(
                v2_storage.V2_DATABASE_PATH, progress["session_id"]
            )
            if status != "waiting":
                st.session_state["v2_player_action_message"] = f"Resumed as {progress['nickname']}."
                _navigate_to(_player_destination(progress))
            st.session_state["v2_waiting_player"] = (progress["session_id"], progress["player_id"])
            st.rerun()


def _host_join_page() -> None:
    flow = st.radio(
        "Choose an action",
        ["Host Game", "Join Game", "Resume Game"],
        horizontal=True,
        key="v2_access_flow",
    )
    if flow == "Host Game":
        st.session_state.pop("v2_waiting_player", None)
        _host_page()
    elif flow == "Join Game":
        _join_page()
    else:
        _resume_page()


def _leaderboard_page() -> None:
    st.header("Multiplayer Leaderboard")
    player = st.session_state.get("v2_player") or {}
    host_session_id = st.session_state.get("v2_host_session_id")
    session_id = player.get("session_id") or host_session_id
    if not session_id:
        st.info("Join or resume a game, or host a game, to view its leaderboard.")
        return

    if st.button("Refresh leaderboard", key="v2_leaderboard_refresh"):
        st.rerun()

    try:
        session = v2_storage.get_game_session(
            v2_storage.V2_DATABASE_PATH, session_id
        )
        standings = v2_storage.get_session_leaderboard(
            v2_storage.V2_DATABASE_PATH, session_id
        )
    except ValueError as error:
        st.error(str(error))
        return

    if standings["is_final"]:
        st.success("Final leaderboard — every player has finished.")
    else:
        st.info("Provisional leaderboard — at least one player is still playing.")
    if session["status"] == "waiting":
        st.caption("The host has not started this game yet.")
    if not standings["players"]:
        st.info("No players have joined this game yet.")
        return

    st.dataframe(
        [
            {
                "Rank": item["rank"],
                "Player": item["nickname"],
                "Café location": item["location"],
                "Completed days": f"{item['completed_days']} / {session['trading_days']}",
                "Game result": format_euros(item["game_result_cents"]),
                "Status": item["status"],
            }
            for item in standings["players"]
        ],
        hide_index=True,
        use_container_width=True,
    )


def render() -> None:
    """Render the six main areas of the multiplayer game."""

    v2_storage.initialize_v2_database(v2_storage.V2_DATABASE_PATH)
    st.markdown(
        """
        <style>
        :root { color-scheme: light; }
        [data-testid="stAppViewContainer"] { background: #fbf5ea; }
        [data-testid="stHeader"] { background: rgba(251, 245, 234, .92); }
        [data-testid="stSidebar"] { background: #efe1cc; }
        [data-testid="stMetric"] {
          background: #fffaf1; border: 1px solid #e4d2b8;
          border-radius: 14px; padding: .8rem;
        }
        .stButton > button, [data-testid="stFormSubmitButton"] button {
          background: #a64f35; color: #fffaf1; border: 0;
          border-radius: 10px; min-height: 2.7rem; font-weight: 650;
        }
        .stButton > button:hover, [data-testid="stFormSubmitButton"] button:hover {
          background: #853b28; color: #fff;
        }
        [data-testid="stVerticalBlockBorderWrapper"] {
          background: #fffaf1; border-radius: 14px;
        }
        @media (max-width: 640px) {
          .block-container { padding: 1rem .8rem 2rem; }
          [data-testid="stMetricValue"] { font-size: 1.35rem; }
          .stButton > button { min-height: 3rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("☕ Campus Tycoon 2.0")
    st.caption("A Lisbon café game. Plan your menu, serve your customers, grow your result.")
    next_section = st.session_state.pop("v2_next_section", None)
    if next_section is not None:
        st.session_state["v2_main_navigation"] = next_section

    page = st.selectbox(
        "Game section",
        [
            "Host / Join Game",
            "Café Setup",
            "Today",
            "Dashboard",
            "Leaderboard",
            "Final Report",
        ],
        key="v2_main_navigation",
    )
    if page == "Host / Join Game":
        _host_join_page()
        return
    st.session_state.pop("v2_waiting_player", None)
    if page == "Leaderboard":
        _leaderboard_page()
        return

    player = st.session_state.get("v2_player")
    if not player:
        st.info("Join or resume a game before opening your café pages.")
        st.caption("Use **Host / Join Game** to get started.")
        return
    try:
        session = v2_storage.get_game_session(
            v2_storage.V2_DATABASE_PATH, player["session_id"]
        )
    except ValueError as error:
        st.error(str(error))
        return

    if page in {"Café Setup", "Today", "Dashboard", "Final Report"}:
        if session["status"] == "waiting":
            if st.button("Refresh game status", key="v2_refresh_game_status", use_container_width=True):
                st.rerun()
        _show_player_cafe(session, player, section=page)
