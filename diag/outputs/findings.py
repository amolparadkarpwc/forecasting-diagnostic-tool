"""Turn evidence into findings, root causes, and actions."""

from __future__ import annotations

CAUSE_FOR_AREA = {
    "Data": "data",
    "Feature engineering": "inputs",
    "Model training": "model",
    "Validation & backtesting": "model",
    "Deployment & monitoring": "process",
}

CAUSE_TITLE = {"data": "Data", "inputs": "Inputs", "model": "Model", "process": "Process"}

CAUSE_SUMMARY = {
    "data": "History quality or the definition of demand is weakening the forecast.",
    "inputs": "Features appear to use information that would not have been known at forecast time.",
    "model": "Accuracy is not yet shown to be measured and ahead of a simple baseline.",
    "process": "Pipeline runs fail or swallow errors, so a forecast may silently go stale.",
}

_WEAK = {"Red", "Amber", "No evidence"}


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return "n/a"


def _display_values(measures: dict, records: list[dict]) -> dict:
    raw: dict = {}
    for record in records:
        for key, value in (record.get("values") or {}).items():
            raw.setdefault(key, value)
        raw.setdefault("fact", record.get("fact") or "")
    raw.update(measures or {})
    display = dict(raw)
    for key, value in list(raw.items()):
        if isinstance(value, float):
            display[f"{key}_pct"] = f"{value * 100:.1f}%"
            display[f"{key}_num"] = f"{value:.3f}"
    display.setdefault("fact", "")
    return display


def fill_template(template: str, values: dict) -> str:
    try:
        return template.format_map(_Safe(values))
    except (IndexError, ValueError):
        return template


def finding_text(diagnostic: dict, score, route: str, measures: dict, records: list[dict]) -> str:
    if diagnostic.get("tier") == "synthesis":
        return ""
    values = _display_values(measures, records)
    template = diagnostic.get("finding_template")
    if template and (score is not None or records):
        return fill_template(template, values)
    if score is None:
        return "No evidence was found for this diagnostic in the files shared."
    return f"Score {score} from the {route} route."


def recommendation_ids(diagnostic: dict, active: list[str]) -> list[str]:
    mapping = diagnostic.get("recommendations") or {}
    found: list[str] = []
    for signal in active:
        recommendation = mapping.get(signal)
        if recommendation and recommendation not in found:
            found.append(recommendation)
    if not found:
        for recommendation in mapping.values():
            if recommendation and recommendation not in found:
                found.append(recommendation)
            break
    return found


def source_summary(records: list[dict]) -> str:
    if not records:
        return ""
    record = records[0]
    location = record["source"]["location"]
    return f"{record['source']['file']} ({location['kind']} {location['value']})"


def root_causes(diagnostics: list[dict]) -> list[dict]:
    grouped: dict[str, list[str]] = {}
    for diagnostic in diagnostics:
        if diagnostic.get("tier") == "synthesis":
            continue
        if diagnostic.get("status") not in _WEAK:
            continue
        cause = CAUSE_FOR_AREA.get(diagnostic.get("area"), "process")
        grouped.setdefault(cause, []).append(diagnostic["id"])
    causes = []
    for cause in ("data", "inputs", "model", "process"):
        if cause not in grouped:
            continue
        causes.append(
            {
                "id": cause,
                "title": CAUSE_TITLE[cause],
                "summary": CAUSE_SUMMARY[cause],
                "diagnostics": grouped[cause],
            }
        )
    return causes


def d42_finding(causes: list[dict]) -> str:
    if not causes:
        return "No weak diagnostics to group. Root-cause attribution is a synthesis step and is not scored."
    parts = [f"{cause['title'].lower()} ({', '.join(cause['diagnostics'])})" for cause in causes]
    return "Root causes group under " + "; ".join(parts) + "."


def actions_for(diagnostics: list[dict], library: list[dict]) -> list[dict]:
    by_id = {item["id"]: item for item in library}
    points_by_diag = {item["id"]: item["points"] for item in diagnostics}
    wanted: list[str] = []
    for diagnostic in diagnostics:
        if diagnostic.get("tier") == "synthesis":
            continue
        score = diagnostic.get("score")
        if score is not None and score >= 67:
            continue
        for recommendation in diagnostic.get("recommendation_ids") or []:
            if recommendation not in wanted:
                wanted.append(recommendation)
    ranked = []
    for recommendation_id in wanted:
        item = by_id.get(recommendation_id)
        if item is None:
            continue
        targets = item.get("targets") or {}
        weight = sum(points_by_diag.get(diag_id, 0) for diag_id in targets)
        ranked.append((weight, recommendation_id, item, targets))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    actions = []
    for _weight, recommendation_id, item, targets in ranked:
        actions.append(
            {
                "id": recommendation_id,
                "text": item.get("text") or "",
                "effort": item.get("effort") or "",
                "root_cause": item.get("root_cause") or "",
                "targets": targets,
                "diagnostics": sorted(targets),
            }
        )
    return actions
