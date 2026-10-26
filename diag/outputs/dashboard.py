"""Render the prototype dashboard from results.json.

The page is the v4 prototype: same tabs, layout, and interactions. Scores,
findings, and evidence come from the results file. Checks the pack did not
score stay on the prototype list as not assessed.
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

_TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "dashboard.html"
_CATALOG = Path(__file__).resolve().parents[1] / "templates" / "catalog.json"

PHASES = [
    {"k": "DA", "name": "Data", "short": "Data", "w": 25},
    {"k": "FE", "name": "Feature engineering", "short": "Features", "w": 25},
    {"k": "MT", "name": "Model training", "short": "Training", "w": 15},
    {"k": "VB", "name": "Validation & backtesting", "short": "Validation", "w": 20},
    {"k": "DM", "name": "Deployment & monitoring", "short": "Deploy & monitor", "w": 15},
]
_PHASE_BY_NAME = {item["name"]: item["k"] for item in PHASES}
_PHASE_ROOT = {"DA": "Data", "FE": "Inputs", "MT": "Model", "VB": "Model", "DM": "Process"}
_ROOT_LABEL = {"data": "Data", "inputs": "Inputs", "model": "Model", "process": "Process"}
_VERDICT = {
    "Ready": "ready",
    "Ready with gaps": "gaps",
    "Not ready": "not",
    "Readiness not confirmed": "hold",
}
_LEVELS = ((0, 25), (25, 50), (50, 67), (67, 85), (85, 101))
_EFFORT_RANK = {"L": 0, "M": 1, "H": 2}

_ARTIFACT_KINDS = (
    ("Code", {"python", "sql", "code"}),
    ("Configs", {"config", "yaml", "json", "toml", "ini"}),
    ("Data", {"sales_history", "event_calendar", "stockout_flags", "data"}),
    ("Run outputs", {"past_forecasts"}),
    ("Documents", {"document", "markdown", "pdf", "docx", "text"}),
    ("Logs", {"log"}),
    ("Model files", {"model", "pickle", "joblib", "onnx"}),
)
_MISSING_LABELS = {
    "sales_history": "Sales data",
    "past_forecasts": "Run outputs",
    "event_calendar": "Event calendar",
    "stockout_flags": "Stockout flags",
    "python": "Code",
    "sql": "SQL",
    "config": "Configs",
    "log": "Logs",
    "model": "Model files",
}


def _load_catalog() -> dict:
    return json.loads(_CATALOG.read_text(encoding="utf-8"))


def _esc_title(value: str) -> str:
    return html.escape(value, quote=True)


def _effort(value: object) -> str:
    text = str(value or "").strip().lower()
    return {"l": "L", "low": "L", "m": "M", "medium": "M", "h": "H", "high": "H"}.get(text, "")


def _tier(value: object, fallback: str) -> str:
    text = str(value or fallback or "S").strip().lower()
    if text in {"c", "core"}:
        return "C"
    return "S"


def _evidence(score, level, applicable: bool = True) -> str:
    if not applicable:
        return "NA"
    if score is None:
        return "NE"
    return {"Verified": "V", "Inferred": "I", "Attested": "A"}.get(str(level or ""), "V")


def _level_index(score) -> int:
    if score is None:
        return -1
    value = float(score)
    for index, (low, high) in enumerate(_LEVELS):
        if low <= value < high:
            return index
    return len(_LEVELS) - 1


def _dated(value: object) -> str:
    text = str(value or "")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return text
    return f"{parsed.day} {parsed.strftime('%B %Y')}"


def _why(overall: dict, diagnostics: list[dict]) -> str:
    reason = str(overall.get("verdict_reason") or "").strip()
    if reason:
        return reason
    by_id = {item["id"]: item for item in diagnostics}
    failed = overall.get("failed_gates") or []
    score = overall.get("score")
    verdict = overall.get("verdict") or "Not ready"
    if failed:
        bits = []
        for item in failed:
            diagnostic = by_id.get(item["id"]) or {}
            name = str(diagnostic.get("name") or item["id"]).lower()
            reason = item.get("reason") or "gate"
            if item.get("score") is None:
                bits.append(f"{item['id']} {name} has no evidence ({reason})")
            else:
                bits.append(f"{item['id']} {name} scored {item.get('score')} ({reason})")
        text = "Not ready because a gate failed: " + "; ".join(bits) + "."
        finding = str((by_id.get(failed[0]["id"]) or {}).get("finding") or "").strip()
        if finding:
            text = f"{text} {finding}"
        return text
    if score is None:
        return "Not ready. No scored diagnostics."
    if verdict == "Ready":
        return "Score is above the ready line and every gate passed."
    if verdict == "Ready with gaps":
        return "Score is between 50 and 66 and every gate passed."
    return "Score is below 50."


def _segments(rows: list[dict]) -> dict:
    denom = sum(row["points"] for row in rows) or 1.0
    measured = attested = lost = missing = 0.0
    for row in rows:
        share = row["points"] / denom * 100
        score = row["score"]
        if score is None:
            missing += share
            continue
        earned = share * float(score) / 100
        if row.get("evidence_level") == "Attested":
            attested += earned
        else:
            measured += earned
        lost += share - earned
    return {"ev": measured, "ans": attested, "lost": lost, "ne": missing, "score": measured + attested}


def _rows_for(diagnostics: list[dict], measured: dict | None) -> list[dict]:
    rows = []
    for item in diagnostics:
        if item.get("tier") == "synthesis" or item.get("applicable") is False:
            continue
        score = item.get("score")
        level = item.get("evidence_level")
        if measured is not None:
            slot = measured.get(item["id"]) or {}
            score = slot.get("score")
            level = slot.get("evidence_level")
        rows.append(
            {
                "id": item["id"],
                "area": item.get("area"),
                "points": float(item.get("points") or 0),
                "score": score,
                "evidence_level": level,
            }
        )
    return rows


def _area_snapshot(areas: list[dict], rows: list[dict]) -> dict:
    by_name = {area.get("name"): area for area in areas or []}
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["area"], []).append(row)
    snapshot = {}
    for phase in PHASES:
        area = by_name.get(phase["name"])
        items = grouped.get(phase["name"]) or []
        if area is None or area.get("score") is None:
            snapshot[phase["k"]] = {"score": None, "assessedShare": 0, "points": 0}
            continue
        points = sum(item["points"] for item in items)
        assessed = sum(item["points"] for item in items if item["score"] is not None)
        snapshot[phase["k"]] = {
            "score": area.get("score"),
            "assessedShare": (assessed / points) if points else 0,
            "points": float(area.get("points") or 0),
        }
    return snapshot


def _engine_view(overall: dict, areas: list[dict], rows: list[dict], diagnostics: list[dict]) -> dict:
    score = overall.get("score")
    segments = _segments(rows)
    segments["score"] = score
    return {
        "score": score,
        "maturity": overall.get("maturity") or "Initial",
        "levelIndex": _level_index(score),
        "verdict": overall.get("verdict") or "Not ready",
        "v": _VERDICT.get(overall.get("verdict") or "", "not"),
        "why": _why(overall, diagnostics),
        "headline": overall.get("headline") or "",
        "totals": segments,
        "areas": _area_snapshot(areas, rows),
    }


def _artifacts(results: dict) -> tuple[list[str], list[str], list[dict]]:
    counts = {label: 0 for label, _types in _ARTIFACT_KINDS}
    other = 0
    for row in results.get("artifacts_shared") or []:
        if row.get("status") == "duplicate":
            continue
        keys = {str(row.get("type") or ""), str(row.get("family") or "")}
        count = int(row.get("count") or 0)
        matched = False
        for label, types in _ARTIFACT_KINDS:
            if keys & types:
                counts[label] += count
                matched = True
                break
        if not matched and count:
            other += count
    shared = [f"{label} ({count})" for label, count in counts.items() if count]
    if other:
        shared.append(f"Other ({other})")
    missing_names = []
    for name in results.get("artifacts_not_shared") or []:
        label = _MISSING_LABELS.get(str(name), str(name).replace("_", " "))
        if label not in missing_names:
            missing_names.append(label)
    coverage = []
    for label, _types in _ARTIFACT_KINDS:
        count = counts[label]
        if count:
            noun = "file" if count == 1 else "files"
            informs = f"{count} {noun} shared with this assessment"
        else:
            informs = "Not shared"
        coverage.append({"kind": label, "shared": bool(count), "informs": informs})
    if other:
        noun = "file" if other == 1 else "files"
        coverage.append({"kind": "Other", "shared": True, "informs": f"{other} other {noun} shared"})
    return shared, missing_names, coverage


def _actions(results: dict) -> list[dict]:
    actions = []
    for action in results.get("actions") or []:
        targets = action.get("targets") or {}
        if not targets:
            continue
        actions.append(
            {
                "id": action.get("id") or "",
                "title": action.get("text") or "",
                "effort": _effort(action.get("effort")),
                "root": _ROOT_LABEL.get(str(action.get("root_cause") or ""), str(action.get("root_cause") or "")),
                "targets": targets,
            }
        )
    return actions


def _root_causes(results: dict) -> list[dict]:
    causes = []
    for cause in results.get("root_causes") or []:
        causes.append(
            {
                "title": cause.get("summary") or cause.get("title") or "",
                "root": cause.get("title") or "",
                "text": "",
                "checks": list(cause.get("diagnostics") or []),
            }
        )
    return causes


def _footer(results: dict) -> str:
    versions = results.get("versions") or {}
    pack = versions.get("pack") or "—"
    engine = versions.get("engine") or "—"
    python = versions.get("python") or "—"
    return (
        f"Pack {pack} · engine {engine} · Python {python}. "
        "Overall score weights each pack area by its points. "
        "An area with no diagnostics, and a diagnostic with no evidence, counts as zero. "
        "Checks outside the pack are shown as not assessed and are not scored. "
        "Thresholds are placeholders until the SME workshop. "
        "Measured evidence only excludes attested records."
    )


def _gate_floor(results: dict) -> float:
    for item in (results.get("overall") or {}).get("failed_gates") or []:
        if item.get("floor") is not None:
            return float(item["floor"])
    return 40.0


def _checks(results: dict, catalog: dict, actions: list[dict]) -> tuple[list[dict], dict, dict]:
    diagnostics = [item for item in results.get("diagnostics") or [] if item.get("tier") != "synthesis"]
    by_id = {item["id"]: item for item in diagnostics}
    measured = ((results.get("measured_view") or {}).get("diagnostics") or {})
    targeted: dict[str, list[tuple[dict, object]]] = {}
    for action in actions:
        for diagnostic_id, target in (action.get("targets") or {}).items():
            targeted.setdefault(diagnostic_id, []).append((action, target))
    desc = dict(catalog.get("desc") or {})
    src: dict[str, str] = {}
    checks = []
    seen = set()

    def add(spec: dict, diagnostic: dict | None) -> None:
        diagnostic_id = spec["id"]
        if diagnostic_id in seen:
            return
        seen.add(diagnostic_id)
        applicable = True if diagnostic is None else diagnostic.get("applicable") is not False
        in_pack = diagnostic is not None and applicable
        if diagnostic is None:
            score = None
            level = None
            phase = spec["ph"]
            name = spec["name"]
            points = spec["pts"]
            tier = spec["tier"]
            gate = bool(spec.get("gate"))
            finding = "Not assessed. This check is outside the MVP knowledge pack, so it has no score."
            source = "Not assessed"
            question = ""
        else:
            score = diagnostic.get("score")
            level = diagnostic.get("evidence_level")
            phase = _PHASE_BY_NAME.get(diagnostic.get("area") or "", spec["ph"])
            name = diagnostic.get("name") or spec["name"]
            points = diagnostic.get("points") if diagnostic.get("points") is not None else spec["pts"]
            tier = _tier(diagnostic.get("tier"), spec["tier"])
            gate_field = diagnostic.get("gate")
            gate = True if isinstance(gate_field, dict) else bool(gate_field)
            finding = diagnostic.get("finding") or "No evidence was found for this diagnostic in the files shared."
            source = diagnostic.get("source_summary") or "No evidence in the files shared."
            question = diagnostic.get("question") or ""
        if question:
            desc[diagnostic_id] = question
        src[diagnostic_id] = source
        slot = measured.get(diagnostic_id) or {}
        if in_pack:
            m_score = slot.get("score") if diagnostic_id in measured else score
            m_level = slot.get("evidence_level") if diagnostic_id in measured else level
        else:
            m_score = None
            m_level = None
        offers = targeted.get(diagnostic_id) or []
        recommendation = " ".join(action["title"] for action, _target in offers if action.get("title")) or "—"
        targets = [value for _action, value in offers if isinstance(value, (int, float))]
        efforts = [action["effort"] for action, _target in offers if action.get("effort")]
        effort = min(efforts, key=lambda item: _EFFORT_RANK.get(item, 9)) if efforts else ""
        checks.append(
            {
                "id": diagnostic_id,
                "ph": phase,
                "name": name,
                "tier": tier,
                "pts": points,
                "gate": gate,
                "gateStatus": (diagnostic or {}).get("gate_result", {}).get("status") if diagnostic else None,
                "conditionScore": (diagnostic or {}).get("condition_score") if diagnostic else None,
                "controlScore": (diagnostic or {}).get("control_score") if diagnostic else None,
                "combinedLabel": (diagnostic or {}).get("combined_label") if diagnostic else None,
                "cap": bool(spec.get("cap")),
                "ev": _evidence(score, level, applicable),
                "score": score,
                "mEv": _evidence(m_score, m_level, applicable),
                "mScore": m_score,
                "eff": effort,
                "root": _PHASE_ROOT.get(phase, ""),
                "target": max(targets) if targets else None,
                "f": finding,
                "detail": (diagnostic or {}).get("detail") or [],
                "review": (diagnostic or {}).get("review_checklist") or [],
                "rec": recommendation,
                "inPack": in_pack,
            }
        )

    for spec in catalog.get("checks") or []:
        add(spec, by_id.get(spec["id"]))
    for diagnostic in diagnostics:
        if diagnostic["id"] in seen:
            continue
        phase = _PHASE_BY_NAME.get(diagnostic.get("area") or "", "DM")
        add(
            {
                "id": diagnostic["id"],
                "ph": phase,
                "name": diagnostic.get("name") or diagnostic["id"],
                "tier": "C",
                "pts": diagnostic.get("points") or 0,
                "gate": bool(diagnostic.get("gate")),
                "cap": False,
            },
            diagnostic,
        )
    return checks, desc, src


def _payload(results: dict) -> dict:
    catalog = _load_catalog()
    diagnostics = list(results.get("diagnostics") or [])
    engagement = results.get("engagement") or {}
    overall = results.get("overall") or {}
    measured_view = results.get("measured_view") or {}
    actions = _actions(results)
    checks, desc, src = _checks(results, catalog, actions)
    shared, missing, coverage_rows = _artifacts(results)
    final_rows = _rows_for(diagnostics, None)
    measured_rows = _rows_for(diagnostics, measured_view.get("diagnostics") or {})
    request = []
    for row in results.get("targeted_request") or []:
        diagnostic_id = row.get("diagnostic_id")
        ask = row.get("request") or ""
        if not diagnostic_id or not ask:
            continue
        request.append({"ask": ask, "checks": [diagnostic_id]})
    stage = "Final" if results.get("stage") == "final" else "Provisional"
    final = _engine_view(overall, results.get("areas") or [], final_rows, diagnostics)
    measured_overall = measured_view.get("overall") or overall
    measured = _engine_view(measured_overall, measured_view.get("areas") or [], measured_rows, diagnostics)
    client_name = engagement.get("client_alias") or engagement.get("id") or "Engagement"
    return {
        "client": {
            "name": client_name,
            "solution": engagement.get("solution") or "",
            "assessed": _dated(engagement.get("assessed_date")),
        },
        "stage": stage,
        "shared": shared,
        "notShared": missing,
        "phases": PHASES,
        "coverage": {"artifacts": coverage_rows, "request": request},
        "gateFloor": _gate_floor(results),
        "checks": checks,
        "headline": final["headline"],
        "rootCauses": _root_causes(results),
        "actions": actions,
        "engine": {"final": final, "measured": measured},
        "desc": desc,
        "src": src,
        "footer": _footer(results),
    }


def render_dashboard(results: dict) -> str:
    template = _TEMPLATE.read_text(encoding="utf-8")
    payload = _payload(results)
    blob = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    engagement = results.get("engagement") or {}
    title = _esc_title(
        "Forecast health assessment – " + str(engagement.get("client_alias") or engagement.get("id") or "Engagement")
    )
    return template.replace("__TITLE__", title).replace("__RESULTS_JSON__", blob)
