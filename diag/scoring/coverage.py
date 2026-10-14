"""Coverage of points and diagnostics that have evidence."""

from __future__ import annotations

from diag.util import round_measure


def summarise(diagnostics: list[dict]) -> dict:
    scored = [item for item in diagnostics if item.get("tier") != "synthesis" and item.get("applicable", True)]
    evidenced = [item for item in scored if item.get("score") is not None]
    points_total = sum(item["points"] for item in scored)
    points_with = sum(item["points"] for item in evidenced)
    by_level = {"Verified": 0, "Inferred": 0, "Attested": 0}
    for item in evidenced:
        level = item.get("evidence_level") or "Verified"
        if level in by_level:
            by_level[level] += item["points"]
    return {
        "points_with_evidence": points_with,
        "points_total": points_total,
        "points_coverage": round_measure(points_with / points_total) if points_total else 0.0,
        "diagnostics_with_evidence": len(evidenced),
        "diagnostics_total": len(scored),
        "points_by_evidence_level": by_level,
    }
