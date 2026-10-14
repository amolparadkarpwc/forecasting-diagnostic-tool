"""Detect one model family from imports, calls, and config values."""

_ML = (
    "lightgbm",
    "lgbm",
    "xgboost",
    "xgb",
    "sklearn",
    "gradientboosting",
    "gradient_boosting",
    "randomforest",
    "random_forest",
    "n_estimators",
)
_STAT = ("arima", "sarimax", "exponential_smoothing", "prophet", "statsmodels", "auto_arima")
_INTER = ("croston", "tsb", "adida")
_BASE = ("seasonal_naive", "seasonal naive", "moving_average")


def detect_family(parsed: list) -> str:
    parts: list[str] = []
    for artifact in parsed:
        for item in artifact.imports:
            parts.append(str(item.get("module") or ""))
            parts.extend(str(name) for name in item.get("names") or [])
        for call in artifact.calls:
            parts.append(str(call.get("name") or ""))
        for key, value in artifact.keys.items():
            parts.append(str(key))
            parts.append(str(value))
    text = " ".join(parts).lower()
    if any(token in text for token in _ML):
        return "ml"
    if any(token in text for token in _STAT):
        return "statistical"
    if any(token in text for token in _INTER):
        return "intermittent"
    if any(token in text for token in _BASE):
        return "baseline"
    return "unknown"
