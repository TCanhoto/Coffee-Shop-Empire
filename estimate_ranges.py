"""Broad, rounded intervals for player-facing pre-trading estimates.

These helpers only format internal baseline estimates. They do not feed values
back into demand, purchases, trading, or saved results.
"""

def _validate_baseline(value: object, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be a whole number.")
    return value


def _rounding_step(magnitude: int, *, minimum: int, unit: int) -> int:
    """Use coarser outward rounding as the estimate grows."""

    quarter_steps = (magnitude + 4 * unit - 1) // (4 * unit)
    return max(minimum, quarter_steps * unit)


def _floor_multiple(numerator: int, denominator: int, step: int) -> int:
    return (numerator // (denominator * step)) * step


def _ceil_multiple(numerator: int, denominator: int, step: int) -> int:
    divisor = denominator * step
    return -((-numerator // divisor) * step)


def demand_estimate_range(baseline_units: int) -> tuple[int, int]:
    """Return a non-negative, deliberately broad interval around demand.

    Bounds span roughly 55% to 160% of the internal baseline and are rounded
    outward to a step about one quarter of that baseline (at least five units).
    A zero baseline is displayed as 0–5 to avoid presenting a precise forecast.
    """

    baseline = _validate_baseline(baseline_units, "Demand baseline")
    if baseline < 0:
        raise ValueError("Demand baseline cannot be negative.")
    step = _rounding_step(baseline, minimum=5, unit=5)
    lower = max(0, _floor_multiple(baseline * 11, 20, step))
    upper = _ceil_multiple(baseline * 8, 5, step)
    if upper == lower:
        upper += step
    return lower, upper


def profit_estimate_range(baseline_cents: int) -> tuple[int, int]:
    """Return a rounded interval around a gross-profit baseline in euro cents.

    Bounds use the same asymmetric 55%/160% span and round outward in steps
    near one quarter of the absolute estimate, with a €5 minimum step. A zero
    baseline becomes a ±€5 interval. This helper is available to screens that
    have a documented profit baseline; current pre-trading screens do not.
    """

    baseline = _validate_baseline(baseline_cents, "Profit baseline")
    magnitude = abs(baseline)
    step = _rounding_step(magnitude, minimum=500, unit=500)
    if baseline > 0:
        lower = _floor_multiple(baseline * 11, 20, step)
        upper = _ceil_multiple(baseline * 8, 5, step)
    elif baseline < 0:
        lower = _floor_multiple(baseline * 8, 5, step)
        upper = _ceil_multiple(baseline * 11, 20, step)
    else:
        lower, upper = -step, step
    if lower == upper:
        upper += step
    return lower, upper
