"""Area and overall roll-up. Missing evidence counts as zero."""

from __future__ import annotations

from diag.scoring.readiness import status_for
from diag.util import round_score


def _weighted(diagnostics: list[dict]) -> float | None:
    applicable = [item for item in diagnostics if item.get("applicable", True) and item.get("tier") != "synthesis"]
    points = sum(item["points"] for item in applicable)
    if not points:
        return None
    total = sum(item["points"] * (0 if item.get("score") is None else item["score"]) for item in applicable)
    return round_score(total / points)


def area_rollup(diagnostics: list[dict], area_weights: dict) -> list[dict]:
    """Score every pack area. An area with no diagnostics scores 0."""
    grouped: dict[str, list[dict]] = {}
    for item in diagnostics:
        if item.get("tier") == "synthesis" or not item.get("applicable", True):
            continue
        grouped.setdefault(item["area"], []).append(item)
    names = list(area_weights)
    for name in grouped:
        if name not in names:
            names.append(name)
    areas = []
    for name in names:
        items = grouped.get(name) or []
        weight = area_weights.get(name)
        points = float(weight) if weight is not None else float(sum(item["points"] for item in items))
        if not items:
            areas.append({"name": name, "points": points, "score": 0.0, "status": "No evidence"})
            continue
        score = _weighted(items)
        if score is None:
            score = 0.0
        all_missing = all(item.get("score") is None for item in items)
        areas.append(
            {
                "name": name,
                "points": points,
                "score": score,
                "status": "No evidence" if all_missing else status_for(score),
            }
        )
    return areas


def overall_score(diagnostics: list[dict], area_weights: dict | None = None) -> float | None:
    """Area-weighted score. An area with no evidence contributes zero."""
    weights = area_weights or {}
    if not weights:
        return _weighted(diagnostics)
    areas = area_rollup(diagnostics, weights)
    points = sum(float(area["points"]) for area in areas)
    if not points:
        return _weighted(diagnostics)
    total = sum(float(area["points"]) * (0 if area.get("score") is None else area["score"]) for area in areas)
    return round_score(total / points)
