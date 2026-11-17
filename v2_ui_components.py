"""Small reusable UI components for the V2 player interface."""

import streamlit as st

from business_logic import format_euros


def business_header_values(progress: dict, total_days: int) -> dict[str, str]:
    """Format the signed-in player's compact business indicators.

    The profit/loss calculation intentionally matches the Dashboard:
    current cash minus the player's starting cash.
    """

    if total_days < 1:
        raise ValueError("total_days must be a positive whole number")

    if progress.get("location") is None:
        displayed_day = 0
    elif progress.get("is_bankrupt"):
        displayed_day = max(progress["current_day"] - 1, 0)
    else:
        displayed_day = min(progress["current_day"], total_days)

    inventory_units = sum(product["quantity"] for product in progress["products"])
    return {
        "day": f"{displayed_day} / {total_days}",
        "cash": format_euros(progress["cash_cents"]),
        "profit_loss": format_euros(
            progress["cash_cents"] - progress["starting_cash_cents"]
        ),
        "inventory_units": f"{inventory_units:,}",
    }


def render_sticky_business_header(progress: dict, total_days: int) -> None:
    """Render compact metrics in a CSS-scoped, sticky Streamlit container."""

    values = business_header_values(progress, total_days)
    st.markdown(
        """
        <style>
        .st-key-v2-sticky-business-header {
          position: sticky;
          top: 3.5rem;
          z-index: 90;
          background: #fbf5ea;
          border: 1px solid #e4d2b8;
          border-radius: 12px;
          padding: .25rem .45rem;
          margin: .15rem 0 .8rem;
          box-shadow: 0 2px 8px rgba(62, 39, 28, .10);
        }
        .st-key-v2-sticky-business-header [data-testid="stHorizontalBlock"] {
          display: grid !important;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: .35rem;
        }
        .st-key-v2-sticky-business-header [data-testid="stColumn"] {
          width: auto !important;
          min-width: 0 !important;
          flex: initial !important;
        }
        .st-key-v2-sticky-business-header [data-testid="stMetric"] {
          background: transparent;
          border: 0;
          border-radius: 0;
          padding: .15rem .25rem;
        }
        .st-key-v2-sticky-business-header [data-testid="stMetricLabel"] {
          font-size: .68rem;
          line-height: 1.1;
        }
        .st-key-v2-sticky-business-header [data-testid="stMetricValue"] {
          font-size: clamp(.86rem, 1.7vw, 1.12rem);
          line-height: 1.2;
          overflow-wrap: anywhere;
        }
        @media (max-width: 640px) {
          .st-key-v2-sticky-business-header {
            top: 3.5rem;
            padding: .15rem .3rem;
          }
          .st-key-v2-sticky-business-header [data-testid="stHorizontalBlock"] {
            grid-template-columns: repeat(2, minmax(0, 1fr));
            column-gap: .2rem;
            row-gap: 0;
          }
          .st-key-v2-sticky-business-header [data-testid="stMetricLabel"] {
            font-size: .64rem;
          }
          .st-key-v2-sticky-business-header [data-testid="stMetricValue"] {
            font-size: .94rem;
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Streamlit 1.67 supports keyed containers, which give the style rules a
    # local class rather than changing every metric or column in the app.
    with st.container(key="v2-sticky-business-header"):
        columns = st.columns(4, gap="small")
        columns[0].metric("Day / days", values["day"])
        columns[1].metric("Available cash", values["cash"])
        columns[2].metric("Profit / loss", values["profit_loss"])
        columns[3].metric("Inventory units", values["inventory_units"])
