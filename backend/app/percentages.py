from math import isfinite


INITIAL_CLOSE_PROBABILITY = 10


def canonical_percentage(value: object) -> float:
    """Return a finite percentage on the canonical 0-100 scale.

    Older property-workspace records stored fractional values such as 0.10,
    while the operating system stores whole percentages such as 61. Preserve
    whole percentages and translate only legacy fractional values.
    """
    try:
        percentage = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if not isfinite(percentage):
        return 0.0
    if 0 < percentage < 1:
        percentage *= 100
    return max(0.0, min(100.0, percentage))
