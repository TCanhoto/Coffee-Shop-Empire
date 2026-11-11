"""Pure calculations for each finished player's performance report."""

from content import PERSONAS


def build_final_report(
    progress: dict,
    history: list[dict],
    *,
    ranking_position: int | None,
    ranking_is_final: bool,
) -> dict:
    """Summarize only saved player results and current inventory."""

    totals_by_product: dict[str, dict] = {}
    lost_sales_units = 0
    for day in history:
        for product in day["products"]:
            key = product["product_key"]
            totals = totals_by_product.setdefault(
                key,
                {
                    "product_key": key,
                    "name": product["name"],
                    "demand": 0,
                    "units_sold": 0,
                    "revenue_cents": 0,
                    "cost_of_goods_sold_cents": 0,
                    "gross_profit_cents": 0,
                    "offered_days": 0,
                    "stockout_days": 0,
                },
            )
            totals["demand"] += product["demand"]
            totals["units_sold"] += product["units_sold"]
            totals["revenue_cents"] += product["revenue_cents"]
            totals["cost_of_goods_sold_cents"] += product[
                "cost_of_goods_sold_cents"
            ]
            totals["gross_profit_cents"] += product["gross_profit_cents"]
            totals["offered_days"] += 1
            lost_units = max(0, product["demand"] - product["units_sold"])
            lost_sales_units += lost_units
            if lost_units:
                totals["stockout_days"] += 1

    offered_products = list(totals_by_product.values())
    sold_products = [product for product in offered_products if product["units_sold"]]
    best_product = None
    worst_product = None
    if sold_products:
        best_product = dict(
            sorted(
                sold_products,
                key=lambda item: (
                    -item["gross_profit_cents"],
                    -item["revenue_cents"],
                    -item["units_sold"],
                    item["name"].casefold(),
                ),
            )[0]
        )
        worst_product = dict(
            sorted(
                offered_products,
                key=lambda item: (
                    item["gross_profit_cents"],
                    item["revenue_cents"],
                    item["units_sold"],
                    item["name"].casefold(),
                ),
            )[0]
        )

    inventory = [
        {
            "product_key": product["product_key"],
            "name": product["name"],
            "units": product["quantity"],
            "purchase_cost_value_cents": (
                product["quantity"] * product["purchase_cost_cents"]
            ),
        }
        for product in progress["products"]
        if product["quantity"] > 0
    ]
    remaining_inventory_units = sum(item["units"] for item in inventory)
    remaining_inventory_value_cents = sum(
        item["purchase_cost_value_cents"] for item in inventory
    )

    persona_days = [day.get("served_customers_by_persona") for day in history]
    persona_keys = {persona.key for persona in PERSONAS}
    persona_data_complete = bool(history) and all(
        isinstance(day_data, dict)
        and set(day_data) == persona_keys
        and all(type(value) is int and value >= 0 for value in day_data.values())
        and sum(day_data.values()) == day["customers_served"]
        for day, day_data in zip(history, persona_days)
    )
    most_served_persona = None
    if persona_data_complete:
        persona_totals = {
            persona.key: sum(day_data.get(persona.key, 0) for day_data in persona_days)
            for persona in PERSONAS
        }
        served_count = sum(persona_totals.values())
        if served_count:
            persona_order = {persona.key: index for index, persona in enumerate(PERSONAS)}
            winning_key = min(
                persona_totals,
                key=lambda key: (-persona_totals[key], persona_order[key]),
            )
            winning_persona = next(
                persona for persona in PERSONAS if persona.key == winning_key
            )
            most_served_persona = {
                "key": winning_key,
                "name": winning_persona.name,
                "customers_served": persona_totals[winning_key],
            }

    recommendations = []
    starting_cash_cents = progress["starting_cash_cents"]
    if remaining_inventory_value_cents * 10 >= starting_cash_cents:
        recommendations.append(
            {
                "rule": "unsold_inventory",
                "text": (
                    "Consider buying less next time: remaining stock costs "
                    f"€{remaining_inventory_value_cents // 100:,}."
                ),
                "evidence": "Unsold stock purchase cost is at least 10% of starting cash.",
            }
        )

    repeated_stockouts = sorted(
        (
            product
            for product in offered_products
            if product["stockout_days"] >= 2
        ),
        key=lambda item: (
            -(item["demand"] - item["units_sold"]),
            item["name"].casefold(),
        ),
    )
    if repeated_stockouts:
        product = repeated_stockouts[0]
        lost_units = product["demand"] - product["units_sold"]
        recommendations.append(
            {
                "rule": "repeated_stockouts",
                "text": f"Consider increasing stock of {product['name']}.",
                "evidence": (
                    f"Demand exceeded stock on {product['stockout_days']} days, "
                    f"leaving {lost_units} units of recorded demand unsold."
                ),
            }
        )

    zero_demand_products = [
        product
        for product in offered_products
        if product["offered_days"] >= 2 and product["demand"] == 0
    ]
    if zero_demand_products:
        names = ", ".join(
            product["name"]
            for product in sorted(
                zero_demand_products, key=lambda item: item["name"].casefold()
            )[:3]
        )
        recommendations.append(
            {
                "rule": "zero_demand_product",
                "text": f"Review the menu fit or price for {names}.",
                "evidence": (
                    "These offered products recorded zero demand on at least two days."
                ),
            }
        )

    total_revenue_cents = sum(day["totals"]["revenue_cents"] for day in history)
    total_customers_served = sum(day["customers_served"] for day in history)
    if len(recommendations) < 2 and best_product is not None:
        recommendations.append(
            {
                "rule": "retain_top_seller",
                "text": f"Keep {best_product['name']} in mind when planning your next menu.",
                "evidence": (
                    f"It was the strongest offered product by gross profit, "
                    f"with {best_product['units_sold']} units sold."
                ),
            }
        )
    elif len(recommendations) < 2 and history and total_customers_served == 0:
        recommendations.append(
            {
                "rule": "no_customers_served",
                "text": "Start the next game with a small test purchase before building stock.",
                "evidence": "No customers were served during the completed trading days.",
            }
        )

    missing_data = [
        "Selling prices by day were not saved, so price-driven demand reduction "
        "cannot be isolated from the recorded results.",
        "Product-level demand by persona was not saved, so low-affinity menu "
        "recommendations cannot be verified from the history.",
    ]
    if history and not persona_data_complete:
        missing_data.append(
            "Persona service counts are missing for one or more completed days; "
            "the most-served persona is unavailable."
        )
    elif not history:
        missing_data.append("There are no completed trading days to summarize.")
    elif persona_data_complete and total_customers_served == 0:
        missing_data.append("No customers were served, so no persona can be ranked.")

    return {
        "session_id": progress["session_id"],
        "player_id": progress["player_id"],
        "nickname": progress["nickname"],
        "final_cash_cents": progress["cash_cents"],
        "final_game_result_cents": (
            progress["cash_cents"] - progress["starting_cash_cents"]
        ),
        "ranking_position": ranking_position,
        "ranking_is_final": ranking_is_final,
        "total_revenue_cents": total_revenue_cents,
        "total_customers_served": total_customers_served,
        "best_product": best_product,
        "worst_product": worst_product,
        "remaining_inventory_units": remaining_inventory_units,
        "remaining_inventory_value_cents": remaining_inventory_value_cents,
        "remaining_inventory": inventory,
        "lost_sales_units": lost_sales_units,
        "most_served_persona": most_served_persona,
        "persona_data_complete": persona_data_complete,
        "recommendations": recommendations[:3],
        "missing_data": missing_data,
    }
