"""Generic derived tests. Thresholds come from the knowledge pack."""


def rate_above(value, threshold) -> bool:
    try:
        return float(value) > float(threshold)
    except (TypeError, ValueError):
        return False


def count_above(value, threshold) -> bool:
    try:
        return float(value) > float(threshold)
    except (TypeError, ValueError):
        return False


def evaluate_derived(spec: dict, source_values: dict) -> bool:
    test = spec.get("test")
    field = spec.get("field") or "value"
    threshold = spec.get("threshold")
    value = source_values.get(field)
    if test in {"rate_above", "threshold_above"}:
        return rate_above(value, threshold)
    if test == "count_above":
        return count_above(value, threshold)
    return False
