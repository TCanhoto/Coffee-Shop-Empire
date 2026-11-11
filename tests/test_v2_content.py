"""Tests for the approved static V2 personas, products, and affinities."""

from content import PERSONAS, PRODUCT_AFFINITIES, PRODUCT_CATALOGUE


def test_catalogue_contains_approved_products_and_prices():
    assert [
        (item.name, item.purchase_cost_cents, item.reference_price_cents)
        for item in PRODUCT_CATALOGUE
    ] == [
        ("Bica", 20, 90),
        ("Galão", 35, 150),
        ("Oat flat white", 70, 320),
        ("Matcha latte", 100, 400),
        ("Fresh orange juice", 90, 300),
        ("Tosta mista", 90, 300),
        ("Plant-based toastie", 140, 550),
        ("Pastel de nata", 35, 130),
        ("Butter croissant", 40, 160),
        ("Pistachio croissant", 110, 400),
        ("Granola bowl", 120, 450),
        ("Brownie", 50, 250),
    ]
    assert len({item.key for item in PRODUCT_CATALOGUE}) == 12
    assert all(item.category and isinstance(item.is_drink, bool) for item in PRODUCT_CATALOGUE)


def test_all_personas_have_approved_price_sensitivity_labels():
    assert [(persona.name, persona.price_sensitivity) for persona in PERSONAS] == [
        ("Student", "Very high"),
        ("Tourist", "Low"),
        ("Digital nomad", "Medium"),
        ("Healthy & plant-based", "Low-to-medium"),
        ("Local & traditional", "High"),
    ]


def test_affinity_matrix_is_complete_and_uses_only_approved_scores():
    product_keys = {item.key for item in PRODUCT_CATALOGUE}
    assert set(PRODUCT_AFFINITIES) == product_keys
    assert all(
        len(scores) == len(PERSONAS) and set(scores) <= {0, 1, 3}
        for scores in PRODUCT_AFFINITIES.values()
    )
    assert PRODUCT_AFFINITIES == {
        "bica": (3, 1, 1, 0, 3),
        "galao": (1, 1, 1, 0, 3),
        "oat_flat_white": (0, 1, 3, 1, 0),
        "matcha_latte": (0, 1, 3, 3, 0),
        "fresh_orange_juice": (1, 1, 1, 3, 1),
        "tosta_mista": (3, 1, 1, 0, 3),
        "plant_based_toastie": (0, 1, 1, 3, 0),
        "pastel_de_nata": (3, 3, 1, 0, 3),
        "butter_croissant": (3, 1, 1, 0, 1),
        "pistachio_croissant": (0, 3, 1, 0, 0),
        "granola_bowl": (0, 1, 1, 3, 0),
        "brownie": (3, 1, 1, 0, 0),
    }
