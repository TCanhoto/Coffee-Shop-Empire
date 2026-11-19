# Campus Tycoon V2 deterministic demand model

**Status: approved and implemented.** The group approved this model before implementation. Pure demand calculations live in `demand_engine.py`; `business_logic.py` separately calculates cash and sale results, and `v2_storage.py` applies them transactionally. The `Today` screen uses the unchanged deterministic result as an internal baseline and shows only a rounded demand range before trading. Exact daily customer and product results are saved and shown in history after the day completes. No expected-profit number is shown before trading because final purchases, sales, and rent settlement determine the realized result.

### Pre-trading estimate display

`estimate_ranges.py` converts a non-negative internal demand baseline into broad displayed bounds: the lower endpoint is rounded down from 55% of the baseline and the upper endpoint rounded up from 160%. Endpoints round outward in steps near one quarter of the baseline, with a five-unit minimum step; zero demand displays as 0–5. This asymmetric spread and coarse outward rounding mean multiple exact baselines can produce the same displayed interval. The range is a planning estimate, not a guaranteed minimum or maximum. The helper does not modify demand or saved game data.

The module also provides a pure interval conversion for signed gross-profit baselines in integer cents, using the same asymmetric spread and a minimum €5 rounding step. It is not currently used for a pre-trading profit display. Any future screen must define its profit baseline consistently: gross profit is revenue minus cost of goods sold; rent is a separate game cost and must be included if the screen claims to estimate a net result. Current UI explains that profit is available after purchases and trading; the Dashboard keeps exact historical values.

## 1. Scope and inputs

One player's trading day uses:

- The player's selected location and its daily foot traffic and persona percentages.
- The player's active menu, saved selling prices, and available stock.
- The approved product affinity score for each persona and product.
- The price-sensitivity tier assigned to each persona below.

Only active-menu products participate in demand. The current four locations are the locations in the V2 implementation. The model can apply to additional agreed locations if they are added later.

All money remains integer cents. Customer counts, product demand, and units sold are non-negative whole numbers. The model has no random values, forecasting, cross-player effects, or demand memory from previous days.

## 2. Persona order and price-sensitivity tiers

Use this fixed tie-break order, matching `content.py`:

1. Student
2. Tourist
3. Digital nomad
4. Healthy & plant-based
5. Local & traditional

The location records currently store persona percentages in a different order (nomad, healthy, tourist, local, student). Convert the named percentages to the order above before doing any allocation; do not assume the stored tuple order matches `PERSONAS`.

Proposed maximum acceptable selling price by persona:

| Persona sensitivity | Maximum acceptable price | Exact comparison |
|---|---:|---|
| Very high — Student | 1.00 × reference price | `price <= reference` |
| High — Local & traditional | 1.25 × reference price | `4 × price <= 5 × reference` |
| Medium — Digital nomad | 1.50 × reference price | `2 × price <= 3 × reference` |
| Low-to-medium — Healthy & plant-based | 1.75 × reference price | `4 × price <= 7 × reference` |
| Low — Tourist | 2.00 × reference price | `price <= 2 × reference` |

The boundary is inclusive. A product priced above a persona's limit is unsuitable for that persona. A product priced above twice its reference price is unsuitable for every persona. This gives the existing sensitivity labels a simple, ordered effect without introducing a continuous elasticity formula.

For an acceptable product, its price weight is **2** when its price is at or below its reference price, and **1** when above reference. The weight is zero when the persona's price limit is exceeded. A product's allocation weight is:

```text
affinity score × price weight
```

An affinity score of 0 always yields weight 0, even at a low price. Scores 1 and 3 contribute in that ratio. The price weight makes a below-reference product twice as attractive as an otherwise equal product priced above reference but still within that persona's limit.

## 3. Integer allocation and tie rule

Whenever a whole number of customers or demand units must be divided in proportion to weights, use the **largest-remainder method**:

1. Calculate each recipient's exact share: `total × recipient_weight / sum_of_weights`.
2. Give each recipient the whole-number floor of its share.
3. Assign the remaining units one at a time to the largest fractional remainders.
4. For equal remainders, use the fixed order for that allocation: persona order above for personas, and product catalogue order from `content.py` for products.

This guarantees the allocated whole-number shares sum to the requested total. Do not use floating-point currency or a random tie-break.

If every candidate has weight zero, allocate no customers to products; those visitors or food opportunities are unserved.

## 4. Daily demand calculation

### 4.1 Potential visitors

```text
potential visitors = floor(passers-by per day × 10 / 100)
```

Use integer arithmetic: `passers_by_per_day // 10`. The supplied traffic values are divisible by 10, so this is exact for the current locations.

### 4.2 Persona visitor counts

Divide potential visitors according to the location's persona percentages using largest remainder. The five persona counts must sum exactly to potential visitors.

### 4.3 Drink demand

Every potential visitor can request at most one drink.

For each persona separately:

1. Find active-menu drink products with affinity greater than zero and a price within that persona's limit.
2. Give each suitable drink product weight `affinity × price weight`.
3. Divide that persona's visitor count between suitable drinks in proportion to those weights using largest remainder.
4. If the persona has no suitable drink, that persona's visitors do not request a drink and are not served.

Add each persona's integer requests to get each product's daily drink demand. This allocation partitions each persona's visitor count, so no visitor can request two drinks.

### 4.4 Stock and customers served

For each drink product:

```text
drink units sold = min(drink demand, available stock)
```

Inventory cannot go below zero. If stock is less than the product's demand, assign the units sold proportionally among the persona groups that requested that product, using largest remainder and the persona tie order. This records which personas were actually served for the food step.

There is **no substitution**. A visitor assigned a drink that is out of stock is lost, even if another drink is available. This avoids a second choice pass and ensures each visitor is counted only once.

```text
customers served = total drink units sold
lost visitors = potential visitors - customers served
```

Customers served are unique people who bought a drink. A person who also buys food is still counted once as a customer.

### 4.5 Food demand and sales

The food-purchase opportunity limit is:

```text
food buyer slots = floor(customers served × 60 / 100)
```

These slots are a maximum, not a guarantee that food will sell. Divide the slots among personas in proportion to their served drink customers using largest remainder. A persona cannot receive more food slots than served customers.

For each persona, divide its food slots among active-menu food products with positive affinity and acceptable price. Use the same `affinity × price weight` and largest-remainder rules as for drinks. Each slot can request at most one food item. If the persona has no suitable active-menu food, those slots remain unused; do not move them to another persona.

For each food product:

```text
food units sold = min(food demand, available stock)
```

There is no food substitution either. A food customer assigned an out-of-stock item does not choose another item. A visitor must first have bought a drink to receive a food slot, so someone without a suitable drink cannot buy food alone.

```text
food opportunities not fulfilled = food buyer slots - food units sold
```

This number includes both slots with no suitable food and requests lost to food stockouts. It is an unfilled purchase opportunity, **not another count of lost visitors**.

## 5. Complete numerical example

Use **Carcavelos / Nova SBE**:

- Foot traffic: 1,200 per day.
- Persona mix: student 50%, tourist 5%, digital nomad 20%, healthy & plant-based 15%, local & traditional 10%.
- Active drink menu: Bica and Galão, both at their reference prices.
- Active food menu: Pastel de nata and Brownie, both at their reference prices.
- Assume enough stock of every menu item to meet all requests.

### Visitors and persona counts

```text
Potential visitors = floor(1,200 × 10 / 100) = 120
```

The persona allocation is exact for this location:

| Persona | Calculation | Visitors |
|---|---:|---:|
| Student | 120 × 50% | 60 |
| Tourist | 120 × 5% | 6 |
| Digital nomad | 120 × 20% | 24 |
| Healthy & plant-based | 120 × 15% | 18 |
| Local & traditional | 120 × 10% | 12 |
| **Total** |  | **120** |

### Drink demand

At reference price, price weight is 2. Multiplying affinities by 2 does not change the shares when both drinks have the same price tier.

- Students have Bica/Galão affinities 3/1, so their 60 visitors split 45/15.
- Tourists and digital nomads have 1/1, splitting 6 into 3/3 and 24 into 12/12.
- Healthy & plant-based visitors have 0 affinity for both drinks, so all 18 are unserved.
- Local & traditional visitors have 3/3, splitting 12 into 6/6.

| Drink | Demand | Stock | Sold |
|---|---:|---:|---:|
| Bica | 45 + 3 + 12 + 6 = **66** | 66 or more | **66** |
| Galão | 15 + 3 + 12 + 6 = **36** | 36 or more | **36** |
| **Total drinks / customers served** | **102** |  | **102** |

```text
Lost visitors = 120 - 102 = 18
```

### Food demand

```text
Food buyer slots = floor(102 × 60 / 100) = 61
```

Allocate those 61 slots among served personas in proportion to their served drink customers (60 students, 6 tourists, 24 digital nomads, 0 healthy, 12 locals). The exact shares are 35.882, 3.588, 14.353, 0, and 7.176. Floors total 59; the two remaining slots go to the largest remainders, students then tourists. The whole-number slot counts are **36, 4, 14, 0, and 7**.

- Students have affinity 3 for both foods: 36 slots split 18/18.
- Tourists have Pastel/Brownie affinities 3/1: 4 slots split 3/1.
- Digital nomads have 1/1: 14 slots split 7/7.
- Locals have affinity 3/0: all 7 slots go to Pastel de nata.

| Food | Demand | Stock | Sold |
|---|---:|---:|---:|
| Pastel de nata | 18 + 3 + 7 + 7 = **35** | 35 or more | **35** |
| Brownie | 18 + 1 + 7 + 0 = **26** | 26 or more | **26** |
| **Total food items** | **61** |  | **61** |

The day records **102 customers served**, **18 lost visitors**, and **61 food items sold**. Total item sales are 163 (102 drinks + 61 foods), but customer count stays 102 because food buyers are already included among the drink customers.

## 6. Price effect example

Use the same Carcavelos location and a menu containing only Bica. Its reference price is €0.90, its affinity is positive for students, tourists, digital nomads, and locals, and it has zero affinity for healthy & plant-based visitors.

| Bica price | Personas allowed by price tier | Drink demand before stock |
|---:|---|---:|
| €0.90 (1.00× reference) | Student, tourist, digital nomad, local | **102** |
| €1.20 (1.33×) | Tourist, digital nomad | **30** |
| €1.40 (1.56×) | Tourist | **6** |
| €1.80 (2.00×) | Tourist | **6** |
| €1.81 (>2.00×) | None | **0** |

The count at €1.20 is 6 tourists + 24 digital nomads. At €1.40 and €1.80, only the 6 tourists both have positive Bica affinity and accept that price. At €1.81, the universal twice-reference-price cap removes Bica for everyone. If another suitable drink is on the active menu, visitors may be allocated to that drink instead; they are not counted twice.

At prices above reference but within a persona's limit, the product receives half the allocation weight of an otherwise equal below-reference product. This shifts demand toward lower-priced suitable choices when the menu contains alternatives.

## 7. Location effect example

Use a Bica-only menu at reference price with enough Bica stock:

| Location | Potential visitors | Persona counts with positive Bica affinity | Bica demand | Lost visitors |
|---|---:|---|---:|---:|
| Carcavelos / Nova SBE | 120 | Student 60 + tourist 6 + nomad 24 + local 12 | **102** | **18** |
| Chiado | 300 | Student 30 + tourist 135 + nomad 45 + local 45 | **255** | **45** |

Both figures apply the same 10% conversion and affinity data. Chiado produces greater Bica demand because it has more potential visitors; its different persona mix also changes which customer groups contribute. Healthy & plant-based visitors have zero affinity for Bica at both locations.

## 8. Automated acceptance tests

The automated tests in `tests/test_v2_demand.py` cover the specified demand rules and examples. The storage integration tests also verify that demand evaluation itself leaves saved player data unchanged and that resolved customer counts persist with a completed day.

1. Potential visitors equal 10% of traffic for all four currently configured locations.
2. Persona allocation sums exactly to potential visitors at every location.
3. Hamilton rounding for Príncipe Real yields 8 students and 52 healthy & plant-based visitors (the equal-remainder tie goes to Student by persona order).
4. In the Carcavelos example, 120 potential visitors are allocated as 60/6/24/18/12 in canonical persona order.
5. A zero-affinity product receives no demand regardless of price or stock.
6. A 3-affinity product receives three times the allocation weight of a 1-affinity product at the same price tier.
7. At or below reference price, the price weight is 2; above reference but within the sensitivity cap, it is 1.
8. Each sensitivity boundary is inclusive, and a price one cent above the boundary excludes that persona's demand for the product.
9. Any product above twice reference price has zero demand for all personas; exactly twice reference is accepted only by the Low sensitivity tier under the proposed table.
10. The full Carcavelos Bica price series (€0.90, €1.20, €1.40, €1.80, €1.81) yields demand 102, 30, 6, 6, 0 before stock.
11. Product demand allocated across a persona's suitable products sums to no more than that persona's visitor count; no visitor requests two drinks.
12. A menu with no suitable drink for a persona leaves that persona's visitors unserved and gives them no food slots.
13. Drink sales never exceed stock; unsatisfied demand is counted as lost visitors and does not switch to another drink.
14. Customers served equals drink units sold, and lost visitors equals potential visitors minus customers served.
15. Food buyer slots equal floor(60% of customers served); food slots never exceed served customers.
16. Food sales never exceed food slots or stock, and no persona buys more than one food item.
17. In the complete Carcavelos example, food demand is 35 Pastéis de nata and 26 Brownies, with 61 food slots total.
18. An exact tie in product remainders resolves by catalogue order; an exact tie in persona remainders resolves by the canonical persona order.
19. Repeating the same location, menu, prices, and stock produces identical product demands and customer counts.
20. Changing location from Carcavelos to Chiado in the Bica-only example changes demand from 102 to 255.

## 9. Approved design choices and simplifications

The starting assumptions leave several choices open:

- **Meaning of “up to 60%”:** 60% is a maximum number of food opportunities, rounded down. It does not guarantee that 60% buy food.
- **Sensitivity labels:** the reference-price multipliers in Section 2 are the approved numeric interpretation of the persona labels.
- **How affinity changes demand:** affinity is a relative allocation weight, not a direct multiplier on total visitors. A 0 score means no interest; 1 and 3 divide demand in a 1:3 ratio before price adjustments.
- **Substitution:** there is no substitution after stockouts. A visitor assigned an unavailable product is lost.
- **Food customer selection:** food opportunities are allocated proportionally among customers actually served a drink. This keeps food buyers a subset of served customers and prevents double counting.
- **Location coverage:** V2 currently has four configured locations, while the broader V2 scope mentions eight. This model needs the remaining location records before their location-specific outputs can be tested.

To keep implementation small, the model uses only fixed persona price tiers, the approved affinity scores, two price-weight levels, one integer allocation routine, and a no-substitution stock rule. It does not model budgets, multiple purchases, queues, repeat visits, competitors, random variation, or elasticity curves.

## Implementation and test status

The full pytest suite exercises the deterministic calculations, the worked example, stock limits, persistence of customer counts, and the existing V2 behavior. The accepted price limits, price weights, rounding order, 60% food-slot interpretation, and no-substitution rule are implemented as specified above.
