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


def area_rollup(diagnostics: list[dict], area_order: list[str]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for item in diagnostics:
        if item.get("tier") == "synthesis" or not item.get("applicable", True):
            continue
        grouped.setdefault(item["area"], []).append(item)
    names = [name for name in area_order if name in grouped]
    for name in grouped:
        if name not in names:
            names.append(name)
    areas = []
    for name in names:
        items = grouped[name]
        points = sum(item["points"] for item in items)
        score = _weighted(items)
        areas.append(
            {
                "name": name,
                "points": points,
                "score": score,
                "status": status_for(score) if score is not None else "No evidence",
            }
        )
    return areas


def overall_score(diagnostics: list[dict]) -> float | None:
    return _weighted(diagnostics)
