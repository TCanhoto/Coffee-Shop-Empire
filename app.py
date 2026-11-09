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
    load_latest_trade,
    load_run,
    purchase_stock,
    set_selling_price,
    trade_day,
)


st.set_page_config(page_title="Campus Tycoon", page_icon="☕", layout="centered")
run = load_run()
latest_trade = load_latest_trade()

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

        if st.button("Save selling price", key=f"save_price_{product['product_key']}"):
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

if latest_trade is not None:
    st.subheader(f"Results for Day {latest_trade['day']}")
    result_rows = [
        {
            "Product": product["name"],
            "Demand": product["demand"],
            "Units sold": product["units_sold"],
            "Revenue": format_euros(product["revenue_cents"]),
            "Cost of goods sold": format_euros(product["cost_of_goods_sold_cents"]),
            "Gross profit": format_euros(product["gross_profit_cents"]),
        }
        for product in latest_trade["products"]
    ]
    totals = latest_trade["totals"]
    result_rows.append(
        {
            "Product": "Total",
            "Demand": totals["demand"],
            "Units sold": totals["units_sold"],
            "Revenue": format_euros(totals["revenue_cents"]),
            "Cost of goods sold": format_euros(totals["cost_of_goods_sold_cents"]),
            "Gross profit": format_euros(totals["gross_profit_cents"]),
        }
    )
    st.dataframe(result_rows, hide_index=True, use_container_width=True)

st.subheader("Purchase stock")
product_by_key = {product["product_key"]: product for product in run["products"]}
selected_product_key = st.selectbox(
    "Choose a product",
    options=list(product_by_key),
    format_func=lambda key: product_by_key[key]["name"],
)
selected_product = product_by_key[selected_product_key]
quantity = st.number_input(
    "Number of units",
    min_value=1,
    step=1,
    value=1,
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
