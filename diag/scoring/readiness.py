"""Gate floor and readiness verdict."""

from __future__ import annotations


def gate_failures(diagnostics: list[dict], gate_ids: list[str], floor: float) -> list[dict]:
    by_id = {item["id"]: item for item in diagnostics}
    failed = []
    for gate_id in gate_ids:
        diagnostic = by_id.get(gate_id)
        if diagnostic is None:
            failed.append({"id": gate_id, "score": None, "reason": "not in pack", "floor": floor})
            continue
        score = diagnostic.get("score")
        if score is None:
            failed.append({"id": gate_id, "score": None, "reason": "no evidence", "floor": floor})
        elif score < floor:
            failed.append({"id": gate_id, "score": score, "reason": "below gate floor", "floor": floor})
    return failed


def verdict_for(score: float | None, failed: list[dict], ready: float, ready_with_gaps: float) -> str:
    if failed or score is None:
        return "Not ready"
    if score >= ready:
        return "Ready"
    if score >= ready_with_gaps:
        return "Ready with gaps"
    return "Not ready"


def maturity_for(score: float | None, bands: list[dict]) -> str:
    if score is None or not bands:
        return bands[0]["name"] if bands else "Initial"
    chosen = bands[0]["name"]
    for band in bands:
        if score >= float(band["min"]):
            chosen = band["name"]
    return chosen


def status_for(score: float | None, red_below: float = 50, amber_below: float = 67) -> str:
    if score is None:
        return "No evidence"
    if score < red_below:
        return "Red"
    if score < amber_below:
        return "Amber"
    return "Green"
