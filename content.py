"""Fixed V2 customer and product data, kept separate from game logic and UI."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    key: str
    name: str
    price_sensitivity: str
    preference_summary: str


@dataclass(frozen=True)
class CafeProduct:
    key: str
    name: str
    category: str
    purchase_cost_cents: int
    reference_price_cents: int
    is_drink: bool


PERSONAS = (
    Persona("student", "Student", "Very high", "Cheap coffee, croissants, and brownies."),
    Persona("tourist", "Tourist", "Low", "Traditional pastries and premium products."),
    Persona("digital_nomad", "Digital nomad", "Medium", "Specialty coffee, matcha, and light meals."),
    Persona("healthy_plant_based", "Healthy & plant-based", "Low-to-medium", "Juice, plant-based products, and bowls."),
    Persona("local_traditional", "Local & traditional", "High", "Bica, galão, tosta mista, and traditional pastries."),
)


PRODUCT_CATALOGUE = (
    CafeProduct("bica", "Bica", "Coffee", 20, 90, True),
    CafeProduct("galao", "Galão", "Coffee", 35, 150, True),
    CafeProduct("oat_flat_white", "Oat flat white", "Coffee", 70, 320, True),
    CafeProduct("matcha_latte", "Matcha latte", "Tea & matcha", 100, 400, True),
    CafeProduct("fresh_orange_juice", "Fresh orange juice", "Juice", 90, 300, True),
    CafeProduct("tosta_mista", "Tosta mista", "Hot food", 90, 300, False),
    CafeProduct("plant_based_toastie", "Plant-based toastie", "Hot food", 140, 550, False),
    CafeProduct("pastel_de_nata", "Pastel de nata", "Pastry", 35, 130, False),
    CafeProduct("butter_croissant", "Butter croissant", "Pastry", 40, 160, False),
    CafeProduct("pistachio_croissant", "Pistachio croissant", "Pastry", 110, 400, False),
    CafeProduct("granola_bowl", "Granola bowl", "Bowls", 120, 450, False),
    CafeProduct("brownie", "Brownie", "Pastry", 50, 250, False),
)

# Columns use PERSONAS order: student, tourist, digital nomad,
# healthy & plant-based, local & traditional. Scores are 0, 1, or 3.
PRODUCT_AFFINITIES = {
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

# New V2 players start with a small valid menu. Each can replace it before a
# trading day, and menu changes are always private to that player.
DEFAULT_MENU_KEYS = ("bica", "galao", "pastel_de_nata")
MAX_MENU_SIZE = 5
