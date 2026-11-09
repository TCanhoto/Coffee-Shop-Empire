"""Streamlit dashboard for the Campus Tycoon starter version."""

import streamlit as st

from business_logic import (
    TOTAL_TRADING_DAYS,
    calculate_demand,
    format_euros,
    price_to_cents,
)
from storage import (
    DATABASE_PATH,
    get_final_results,
    load_run,
    load_trade_history,
    purchase_stock,
    reset_run,
    set_selling_price,
    trade_day,
)


st.set_page_config(page_title="Campus Tycoon", page_icon="☕", layout="centered")
experience = st.sidebar.radio(
    "Game version",
    ["Campus Tycoon 1.0", "Campus Tycoon 2.0 · Multiplayer"],
)
if experience == "Campus Tycoon 2.0 · Multiplayer":
    from v2_interface import render as render_v2

    render_v2()
    st.stop()

run = load_run()
trade_history = load_trade_history()
final_results = get_final_results()

# Clear Streamlit's remembered price inputs before rebuilding widgets after a
# confirmed reset, so the screen reflects the restored database prices.
if st.session_state.pop("reset_price_widgets", False):
    for product in run["products"]:
        st.session_state.pop(f"selling_price_{product['product_key']}", None)

if "purchase_message" in st.session_state:
    st.success(st.session_state.pop("purchase_message"))

st.title("☕ Campus Tycoon")
st.caption("Run your campus cafe for five trading days.")

cash_column, day_column = st.columns(2)
cash_column.metric("Available cash", format_euros(run["cash_cents"]))
day_label = (
    f"Day {run['current_day']} of {TOTAL_TRADING_DAYS}"
    if run["current_day"] <= TOTAL_TRADING_DAYS
    else f"Complete ({TOTAL_TRADING_DAYS} days)"
)
day_column.metric("Current day", day_label)
days_completed = min(run["current_day"] - 1, TOTAL_TRADING_DAYS)
st.progress(
    days_completed / TOTAL_TRADING_DAYS,
    text=f"{days_completed} of {TOTAL_TRADING_DAYS} trading days completed",
)

st.subheader("Products and stock")
for product in run["products"]:
    with st.container(border=True):
        name_column, stock_column, cost_column, price_column = st.columns(4)
        name_column.markdown(f"**{product['name']}**")
        stock_column.metric("In stock", product["quantity"])
        cost_column.metric("Purchase cost", format_euros(product["purchase_cost_cents"]))
        price_column.metric("Reference price", format_euros(product["reference_price_cents"]))

st.subheader("Set selling prices")
st.caption(
    "Demand rule: at or below the reference price = 10 units; above the reference "
    "price and up to twice that price = 5 units; above twice the reference price = 0 units."
)
for product in run["products"]:
    with st.container(border=True):
        st.markdown(f"**{product['name']}** — reference price "
                    f"{format_euros(product['reference_price_cents'])}")
        price_text = st.text_input(
            f"Selling price for {product['name']} (€)",
            value=format_euros(product["selected_price_cents"])[1:],
            key=f"selling_price_{product['product_key']}",
            disabled=run["current_day"] > TOTAL_TRADING_DAYS,
        )
        try:
            preview_price_cents = price_to_cents(price_text)
        except ValueError as error:
            st.error(str(error))
        else:
            expected_demand = calculate_demand(
                preview_price_cents, product["reference_price_cents"]
            )
            st.write(f"Demand at this price: **{expected_demand} units**")

        if st.button(
            "Save selling price",
            key=f"save_price_{product['product_key']}",
            disabled=run["current_day"] > TOTAL_TRADING_DAYS,
        ):
            try:
                saved_price_cents = set_selling_price(
                    DATABASE_PATH, product["product_key"], price_text
                )
            except ValueError as error:
                st.error(str(error))
            else:
                st.session_state["price_message"] = (
                    f"{product['name']} selling price saved as "
                    f"{format_euros(saved_price_cents)}."
                )
                st.rerun()

if "price_message" in st.session_state:
    st.success(st.session_state.pop("price_message"))

st.subheader("Trade one day")
if run["current_day"] <= TOTAL_TRADING_DAYS:
    if st.button("Trade Day", type="primary"):
        try:
            completed_trade = trade_day(DATABASE_PATH)
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state["trade_message"] = (
                f"Day {completed_trade['day']} is complete."
            )
            st.rerun()
else:
    st.info("This run is complete. No more trading days are available.")

if "trade_message" in st.session_state:
    st.success(st.session_state.pop("trade_message"))

if trade_history:
    st.subheader("Trading history")
    history_rows = [
        {
            "Day": entry["day"],
            "Units sold": entry["totals"]["units_sold"],
            "Revenue": format_euros(entry["totals"]["revenue_cents"]),
            "Cost of goods sold": format_euros(
                entry["totals"]["cost_of_goods_sold_cents"]
            ),
            "Gross profit": format_euros(entry["totals"]["gross_profit_cents"]),
            "Cash after trading": format_euros(entry["cash_cents_after"]),
        }
        for entry in trade_history
    ]
    st.dataframe(history_rows, hide_index=True, use_container_width=True)

    for entry in trade_history:
        st.markdown(f"**Day {entry['day']} product results**")
        result_rows = [
            {
                "Product": product["name"],
                "Demand": product["demand"],
                "Units sold": product["units_sold"],
                "Revenue": format_euros(product["revenue_cents"]),
                "Cost of goods sold": format_euros(
                    product["cost_of_goods_sold_cents"]
                ),
                "Gross profit": format_euros(product["gross_profit_cents"]),
            }
            for product in entry["products"]
        ]
        totals = entry["totals"]
        result_rows.append(
            {
                "Product": "Total",
                "Demand": totals["demand"],
                "Units sold": totals["units_sold"],
                "Revenue": format_euros(totals["revenue_cents"]),
                "Cost of goods sold": format_euros(
                    totals["cost_of_goods_sold_cents"]
                ),
                "Gross profit": format_euros(totals["gross_profit_cents"]),
            }
        )
        st.dataframe(result_rows, hide_index=True, use_container_width=True)

if final_results is not None:
    st.subheader("Final results")
    final_cash_column, stock_value_column, gain_loss_column = st.columns(3)
    final_cash_column.metric("Final cash", format_euros(final_results["cash_cents"]))
    stock_value_column.metric(
        "Remaining stock at purchase cost",
        format_euros(final_results["remaining_stock_value_cents"]),
    )
    gain_loss_column.metric(
        "Overall gain / loss",
        format_euros(final_results["overall_gain_loss_cents"]),
    )

st.subheader("Purchase stock")
product_by_key = {product["product_key"]: product for product in run["products"]}
selected_product_key = st.selectbox(
    "Choose a product",
    options=list(product_by_key),
    format_func=lambda key: product_by_key[key]["name"],
    disabled=run["current_day"] > TOTAL_TRADING_DAYS,
)
selected_product = product_by_key[selected_product_key]
quantity = st.number_input(
    "Number of units",
    min_value=1,
    step=1,
    value=1,
    disabled=run["current_day"] > TOTAL_TRADING_DAYS,
)
total_cost_cents = quantity * selected_product["purchase_cost_cents"]
st.write(f"Unit purchase cost: {format_euros(selected_product['purchase_cost_cents'])}")
st.write(f"Total purchase cost: **{format_euros(total_cost_cents)}**")

if st.button(
    "Buy",
    type="primary",
    disabled=run["current_day"] > TOTAL_TRADING_DAYS,
):
    try:
        paid_cents = purchase_stock(DATABASE_PATH, selected_product_key, quantity)
    except ValueError as error:
        st.error(str(error))
    else:
        st.session_state["purchase_message"] = (
            f"Purchased {quantity} {selected_product['name'].lower()} unit(s) "
            f"for {format_euros(paid_cents)}."
        )
        st.rerun()

st.subheader("Manage run")
if st.button("New Run", disabled=st.session_state.get("confirm_new_run", False)):
    st.session_state["confirm_new_run"] = True
    st.rerun()

if st.session_state.get("confirm_new_run", False):
    st.warning("Start a new run? Your current cash, stock, prices, and history will be replaced.")
    confirm_column, cancel_column = st.columns(2)
    if confirm_column.button("Confirm New Run", type="primary"):
        reset_run(DATABASE_PATH, confirmed=True)
        st.session_state["confirm_new_run"] = False
        st.session_state["reset_price_widgets"] = True
        st.rerun()
    if cancel_column.button("Cancel", key="cancel_new_run"):
        st.session_state["confirm_new_run"] = False
        st.rerun()
