"""Score diagnostics from active signals. The pack supplies every number."""

from __future__ import annotations

from typing import Any


def score_signals(
    active: set[str], rules: list[dict[str, Any]]
) -> tuple[int | float | None, list[dict[str, Any]]]:
    """First matching score rule sets the base. Every matching cap applies as min.

    Caps alone do not invent a score. No matching score rule yields null.
    """
    base: float | None = None
    base_raw: int | float | None = None
    caps: list[dict[str, Any]] = []
    for rule in rules:
        if "otherwise" in rule:
            continue
        needed = rule.get("when_all") or []
        if not all(signal in active for signal in needed):
            continue
        if "score" in rule and base is None:
            base_raw = rule["score"]
            base = float(base_raw)
        if "cap" in rule:
            caps.append({"rule": _rule_label(rule, "cap"), "cap": rule["cap"]})
    if base is None:
        return None, []
    score = base
    for cap in caps:
        score = min(score, float(cap["cap"]))
    if base_raw is not None and score == float(base_raw):
        return base_raw, caps
    return _canonical(score), caps


def status_for(score: int | float | None, green: float, amber: float) -> str:
    """Map a score to Green, Amber, Red, or No evidence."""
    if score is None:
        return "No evidence"
    if float(score) >= green:
        return "Green"
    if float(score) >= amber:
        return "Amber"
    return "Red"


def verdict_for(
    score: int | float | None,
    failed_gates: list[str],
    ready: float,
    gaps: float,
) -> str:
    """Readiness verdict. A failed gate forces Not ready."""
    if failed_gates:
        return "Not ready"
    if score is None:
        return "No evidence"
    if float(score) >= ready:
        return "Ready"
    if float(score) >= gaps:
        return "Ready with gaps"
    return "Not ready"


def maturity_for(score: int | float | None, bands: list[dict[str, Any]]) -> str | None:
    """Highest maturity band whose minimum is at or below the score."""
    if score is None:
        return None
    ordered = sorted(bands, key=lambda band: float(band.get("min", 0)), reverse=True)
    for band in ordered:
        if float(score) >= float(band.get("min", 0)):
            return str(band.get("name"))
    return None


def weighted_average(items: list[tuple[float, int | float]]) -> int | float | None:
    """Points-weighted average. Items are (points, score). Empty input is null."""
    if not items:
        return None
    total_points = sum(points for points, _score in items)
    if total_points == 0:
        return None
    total = sum(points * float(score) for points, score in items)
    return _canonical(total / total_points)


def _rule_label(rule: dict[str, Any], kind: str) -> str:
    signals = ",".join(str(signal) for signal in rule.get("when_all", []))
    return f"{kind}:{signals}"


def _canonical(value: float) -> int | float:
    rounded = round(value, 2)
    if abs(rounded - round(rounded)) < 1e-9:
        return int(round(rounded))
    return float(f"{rounded:.2f}")
