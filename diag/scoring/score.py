"""Score diagnostics from evidence and data measures."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone

from diag import __version__
from diag.outputs.findings import (
    actions_for,
    check_details,
    d42_finding,
    finding_text,
    recommendation_ids,
    root_causes,
    source_summary,
)
from diag.rules.review import COUNTED
from diag.scoring.combination import (
    combine,
    condition_score,
    control_score,
    data_area_ids,
    evaluate_gate,
    gate_floor,
    verdict_for_pack,
)
from diag.scoring.coverage import summarise
from diag.scoring.readiness import gate_failures, maturity_for, status_for, verdict_for
from diag.scoring.routes import best_level, choose_route
from diag.scoring.family import detect_family
from diag.scoring.rollup import area_rollup, overall_score
from diag.util import round_score


def interpolate(curve: list[dict], value: float) -> float | None:
    points = sorted((float(point["x"]), float(point["y"])) for point in curve)
    if not points:
        return None
    if value <= points[0][0]:
        return points[0][1]
    if value >= points[-1][0]:
        return points[-1][1]
    for (left_x, left_y), (right_x, right_y) in zip(points, points[1:]):
        if left_x <= value <= right_x:
            if right_x == left_x:
                return left_y
            weight = (value - left_x) / (right_x - left_x)
            return left_y + weight * (right_y - left_y)
    return points[-1][1]


def _matches(rule: dict, active: set[str]) -> bool:
    if "otherwise" in rule:
        return False
    if "when_all" in rule and not all(signal in active for signal in rule["when_all"]):
        return False
    if "when_any" in rule and not any(signal in active for signal in rule["when_any"]):
        return False
    if "when_none" in rule and any(signal in active for signal in rule["when_none"]):
        return False
    return any(key in rule for key in ("when_all", "when_any", "when_none"))


def apply_rules(rules: list[dict], active: list[str]) -> tuple[float | None, list[dict]]:
    active_set = set(active)
    score = None
    for rule in rules:
        if _matches(rule, active_set) and "score" in rule:
            score = float(rule["score"])
            break
    caps = []
    for rule in rules:
        if _matches(rule, active_set) and "cap" in rule:
            label = ",".join(rule.get("when_all") or rule.get("when_any") or [])
            caps.append({"rule": label or "cap", "cap": rule["cap"]})
            if score is not None:
                score = min(score, float(rule["cap"]))
    return score, caps


def data_score(diagnostic: dict, measure_values: dict) -> float | None:
    slot = measure_values.get(diagnostic["id"]) or {}
    if not slot:
        return None
    scored = []
    for measure in (diagnostic.get("data_route") or {}).get("measures") or []:
        if measure["name"] not in slot:
            continue
        value = interpolate(measure.get("curve") or [], slot[measure["name"]])
        if value is not None:
            scored.append((measure, value))
    if not scored:
        return None
    average = sum(score for _, score in scored) / len(scored)
    critical = [score for measure, score in scored if measure.get("critical")]
    if critical:
        average = min(average, min(critical))
    return average


def _is_provisional(diagnostic: dict, records: list[dict], route: str) -> bool:
    polarity = {
        signal_id: (signal.get("polarity") or "")
        for signal_id, signal in (diagnostic.get("signals") or {}).items()
    }
    for record in records:
        if record["status"] in {"counted_flagged", "needs_review"} and polarity.get(record["signal_id"]) == "negative":
            return True
    if route == "inspected":
        return any(record.get("provisional") and record["status"] in COUNTED for record in records)
    return False


def _stockout_signals(pack: dict) -> set[str]:
    stockouts = (pack.get("meta") or {}).get("stockouts") or {}
    if stockouts.get("in_scope", True):
        return set()
    classes = ((pack.get("shared") or {}).get("zero_classification") or {}).get("classes") or []
    return {f"zero.{item['id']}" for item in classes if str(item.get("id") or "").startswith("stockout")}


def _plain_measures(slot: dict) -> tuple[dict, dict]:
    values: dict = {}
    detail: dict = {}
    for name, raw in (slot or {}).items():
        if isinstance(raw, dict):
            detail[name] = raw
            if raw.get("computed") and raw.get("value") is not None:
                values[name] = raw["value"]
        else:
            values[name] = raw
    return values, detail


def _measure_report(diagnostic: dict, values: dict, detail: dict, scores: dict, stage: str, active: set[str]) -> list[dict]:
    measures = (diagnostic.get("data_route") or {}).get("measures") or {}
    if not isinstance(measures, dict):
        return []
    rows = []
    for name, spec in measures.items():
        if not isinstance(spec, dict):
            continue
        extra = detail.get(name) or {}
        handled_by = sorted(set(spec.get("handled_by") or []) & active)
        handled = stage == "raw_source" and bool(handled_by)
        later = spec.get("release") == "later"
        computed = name in scores and not later
        rows.append(
            {
                "id": name,
                "value": None if later else values.get(name, extra.get("value")),
                "score": None if not computed else scores.get(name),
                "computed": computed,
                "critical": bool(spec.get("critical")),
                "level": extra.get("level"),
                "data_stage": stage,
                "handled": handled,
                "handled_by": handled_by,
                "reason_not_computed": "not_implemented" if later else (None if computed else extra.get("reason") or "not_computable"),
            }
        )
    return rows


def _confirmed(records: list[dict]) -> tuple[set[str], dict[str, str]]:
    confirmed: set[str] = set()
    levels: dict[str, str] = {}
    rank = {"Attested": 1, "Inferred": 2, "Verified": 3}
    for record in records:
        signal_id = record.get("signal_id") or ""
        if record.get("status") == "confirmed":
            confirmed.add(signal_id)
        level = record.get("evidence_level") or ""
        if rank.get(level, 0) and (signal_id not in levels or rank[level] < rank.get(levels[signal_id], 9)):
            # The weakest counted level decides whether inferred evidence can meet a gate.
            levels[signal_id] = level
    return confirmed, levels


def _score_data_area(pack: dict, diagnostic: dict, counted: list[dict], slot: dict, stage: str) -> dict:
    active = {record["signal_id"] for record in counted}
    values, detail = _plain_measures(slot)
    condition, scores = condition_score(diagnostic, values, stage, active)
    control = control_score(diagnostic, active)
    score, label = combine(condition, control)
    confirmed, levels = _confirmed(counted)
    categories = {name: value for name, value in values.items() if isinstance(value, str)}
    gates = pack["meta"].get("gates") if isinstance(pack["meta"].get("gates"), dict) else {}
    gate_result = {}
    if diagnostic.get("gate"):
        gate_result = evaluate_gate(
            diagnostic,
            score,
            active,
            scores,
            confirmed,
            gate_floor(pack),
            levels=levels,
            categories=categories,
            inferred_needs_review=bool(gates.get("inferred_trip_requires_review", True)),
        )
    route = "data" if condition is not None else choose_route(counted, False)
    return {
        "score": score,
        "route": route if score is not None else "none",
        "caps": [],
        "label": label,
        "condition": condition,
        "control": control,
        "measures": _measure_report(diagnostic, values, detail, scores, stage, active),
        "gate_result": gate_result,
    }


def score_diagnostics(pack: dict, evidence: list[dict], measure_values: dict, *, include_attested: bool = True) -> list[dict]:
    red = float((pack["meta"].get("status_bands") or {}).get("red_below", 50))
    amber = float((pack["meta"].get("status_bands") or {}).get("amber_below", 67))
    data_ids = data_area_ids(pack)
    ignored = _stockout_signals(pack)
    stage = "model_ready"
    results = []
    for diagnostic in pack["diagnostics"]:
        records = [record for record in evidence if record["diagnostic_id"] == diagnostic["id"]]
        if not include_attested:
            records = [record for record in records if record.get("evidence_level") != "Attested"]
        counted = [
            record
            for record in records
            if record["status"] in COUNTED
            and record.get("signal_id") not in ignored
            and record.get("owner_diagnostic") is not None
        ]
        active = sorted({record["signal_id"] for record in counted})
        synthesis = diagnostic.get("tier") == "synthesis" or diagnostic.get("synthesis")
        if synthesis:
            results.append(_blank(diagnostic, status="Not scored", route="none"))
            continue
        slot = measure_values.get(diagnostic["id"]) or {}
        caps: list[dict] = []
        label = None
        condition = None
        control = None
        measure_rows: list[dict] = []
        gate_result: dict = {}
        if diagnostic["id"] in data_ids and isinstance((diagnostic.get("data_route") or {}).get("measures"), dict):
            scored = _score_data_area(pack, diagnostic, counted, slot, stage)
            score = scored["score"]
            route = scored["route"]
            label = scored["label"]
            condition = scored["condition"]
            control = scored["control"]
            measure_rows = scored["measures"]
            gate_result = scored["gate_result"]
        else:
            measured = data_score(diagnostic, measure_values)
            if measured is not None:
                score = measured
                route = "data"
            else:
                score, caps = apply_rules(diagnostic.get("scoring") or [], active)
                route = choose_route(counted, False)
        score = round_score(score)
        status = status_for(score, red, amber)
        level = best_level(counted)
        counted_route = route if score is not None else "none"
        # Sub-checks see every record, including ones held for review.
        # The score itself still uses only counted records.
        row = {
            "id": diagnostic["id"],
            "name": diagnostic["name"],
            "area": diagnostic["area"],
            "tier": diagnostic["tier"],
            "points": diagnostic["points"],
            "gate": bool(diagnostic.get("gate")),
            "question": diagnostic.get("question") or "",
            "gap_request": diagnostic.get("gap_request") or "",
            "applicable": True,
            "route": counted_route,
            "evidence_level": level,
            "score": score,
            "status": status,
            "caps_applied": caps,
            "provisional": _is_provisional(diagnostic, records, counted_route),
            "signals": active,
            "records": [record["record_id"] for record in counted if record.get("record_id")],
            "finding": finding_text(diagnostic, score, counted_route, slot if isinstance(slot, dict) else {}, records),
            "detail": check_details(diagnostic, slot if not any(isinstance(item, dict) for item in (slot or {}).values()) else {}, records),
            "review_checklist": list(diagnostic.get("review_checklist") or []),
            "recommendation_ids": recommendation_ids(diagnostic, active),
            "source_summary": source_summary(counted),
        }
        if diagnostic["id"] in data_ids:
            row["condition_score"] = condition
            row["control_score"] = control
            row["combined_label"] = label
            row["measures"] = measure_rows
            if diagnostic.get("gate"):
                row["gate_result"] = gate_result
        results.append(row)
    return results


def _blank(diagnostic: dict, status: str, route: str) -> dict:
    return {
        "id": diagnostic["id"],
        "name": diagnostic["name"],
        "area": diagnostic["area"],
        "tier": diagnostic["tier"],
        "points": diagnostic["points"],
        "gate": bool(diagnostic.get("gate")),
        "question": diagnostic.get("question") or "",
        "gap_request": diagnostic.get("gap_request") or "",
        "applicable": True,
        "route": route,
        "evidence_level": None,
        "score": None,
        "status": status,
        "caps_applied": [],
        "provisional": False,
        "signals": [],
        "records": [],
        "finding": "",
        "detail": [],
        "review_checklist": list(diagnostic.get("review_checklist") or []),
        "recommendation_ids": [],
        "source_summary": "",
    }


def _library_versions() -> dict:
    from importlib.metadata import PackageNotFoundError, version

    libraries = {}
    for dist, label in (("pandas", "pandas"), ("PyYAML", "pyyaml"), ("python-docx", "python-docx")):
        try:
            libraries[label] = version(dist)
        except PackageNotFoundError:
            continue
    return libraries


def _artifact_lists(inventory: list[dict], parsed: list) -> tuple[list[dict], list[str]]:
    counts: dict[tuple, int] = {}
    present = set()
    for record in inventory:
        present.add(record.get("detected_type"))
        present.add(record.get("family"))
        if record.get("status") == "duplicate":
            continue
        key = (record.get("detected_type"), record.get("family"), record.get("status"))
        counts[key] = counts.get(key, 0) + 1
    for artifact in parsed:
        if artifact.data_format:
            present.add(artifact.data_format)
    shared = [
        {"type": detected, "family": family, "status": status, "count": count}
        for (detected, family, status), count in sorted(counts.items(), key=lambda item: (item[0][0] or "", item[0][2] or ""))
    ]
    watch = [
        ("sales_history", {"sales_history"}),
        ("past_forecasts", {"past_forecasts"}),
        ("event_calendar", {"event_calendar"}),
        ("stockout_flags", {"stockout_flags"}),
        ("python", {"python"}),
        ("sql", {"sql"}),
        ("config", {"config", "yaml", "json", "toml", "ini"}),
        ("log", {"log"}),
        ("model", {"model", "pickle", "joblib", "onnx"}),
    ]
    missing = [name for name, options in watch if present.isdisjoint(options)]
    return shared, missing


def _gap_text(diagnostic: dict) -> str:
    request = diagnostic.get("gap_request") or ""
    if not isinstance(request, dict):
        return str(request or "")
    label = diagnostic.get("combined_label")
    if diagnostic.get("score") is None:
        parts = [request.get("condition") or "", request.get("control") or ""]
        return " ".join(part.strip() for part in parts if part.strip())
    if label == "Controls not evidenced":
        return str(request.get("control") or "").strip()
    if label == "Condition not measured":
        return str(request.get("condition") or "").strip()
    return ""


def _targeted(diagnostics: list[dict]) -> list[dict]:
    rows = []
    for diagnostic in diagnostics:
        if diagnostic["tier"] == "synthesis":
            continue
        request = _gap_text(diagnostic)
        if not request:
            score = diagnostic["score"]
            legacy = diagnostic.get("gap_request") or ""
            if score is None or score >= 50 or isinstance(legacy, dict) or not legacy:
                continue
            request = str(legacy)
        rows.append((diagnostic["points"], diagnostic["id"], request))
    rows.sort(key=lambda row: (-row[0], row[1]))
    return [
        {"rank": index, "diagnostic_id": diag_id, "request": request}
        for index, (_points, diag_id, request) in enumerate(rows, start=1)
    ]


def _headline(verdict: str, score, failed: list[dict], reason: str = "") -> str:
    if reason:
        return f"{verdict}. {reason}"
    if failed:
        detail = ", ".join(
            f"{item['id']} ({item['reason']})" for item in failed
        )
        return f"{verdict}. Gate diagnostics failed: {detail}."
    if score is None:
        return f"{verdict}. No scored diagnostics."
    return f"{verdict}. Overall score {score}."


def _overall(diagnostics: list[dict], pack: dict) -> dict:
    meta = pack["meta"]
    score = overall_score(diagnostics)
    reason = ""
    if isinstance(meta.get("verdict"), list):
        verdict, reason = verdict_for_pack(pack, diagnostics, score)
        floor = gate_floor(pack)
        failed = [
            {
                "id": item["id"],
                "score": item.get("score"),
                "reason": "trigger met",
                "floor": floor,
            }
            for item in diagnostics
            if (item.get("gate_result") or {}).get("status") == "tripped"
        ]
    else:
        gate_ids = meta.get("gates") if isinstance(meta.get("gates"), list) else []
        failed = gate_failures(diagnostics, list(gate_ids), float(meta.get("gate_floor", 40)))
        bands = meta.get("verdict_bands") or {}
        verdict = verdict_for(score, failed, float(bands.get("ready", 67)), float(bands.get("ready_with_gaps", 50)))
    return {
        "score": score,
        "maturity": maturity_for(score, meta.get("maturity_bands") or []),
        "verdict": verdict,
        "verdict_reason": reason,
        "failed_gates": failed,
        "provisional": any(item["provisional"] for item in diagnostics),
        "headline": _headline(verdict, score, failed, reason),
    }


def assemble_results(cfg: dict, pack: dict, inventory: list[dict], parsed: list, evidence: list[dict], measure_values: dict, *, stage: str) -> dict:
    diagnostics = score_diagnostics(pack, evidence, measure_values, include_attested=True)
    area_order = list((pack["meta"].get("area_weights") or {}).keys())
    causes = root_causes(diagnostics)
    for diagnostic in diagnostics:
        if diagnostic["id"] == "D42":
            diagnostic["finding"] = d42_finding(causes)
    measured = score_diagnostics(pack, evidence, measure_values, include_attested=False)
    measured_overall = _overall(measured, pack)
    measured_overall["provisional"] = False
    shared, missing = _artifact_lists(inventory, parsed)
    overall = _overall(diagnostics, pack)
    return {
        "stage": stage,
        "engagement": {
            "id": cfg.get("engagement_id") or "",
            "client_alias": cfg.get("client_alias") or "",
            "solution": cfg.get("solution") or "",
            "assessed_date": date.today().isoformat(),
        },
        "versions": {
            "pack": pack["meta"]["version"],
            "engine": __version__,
            "python": sys.version.split()[0],
            "libraries": _library_versions(),
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        },
        "model_family": detect_family(parsed),
        "artifacts_shared": shared,
        "artifacts_not_shared": missing,
        "diagnostics": diagnostics,
        "areas": area_rollup(diagnostics, area_order),
        "overall": overall,
        "coverage": summarise(diagnostics),
        "measured_view": {
            "overall": measured_overall,
            "areas": area_rollup(measured, area_order),
            "diagnostics": {
                item["id"]: {
                    "score": item["score"],
                    "status": item["status"],
                    "route": item["route"],
                    "evidence_level": item["evidence_level"],
                }
                for item in measured
            },
        },
        "targeted_request": _targeted(diagnostics),
        "root_causes": causes,
        "actions": actions_for(diagnostics, pack.get("recommendations") or []),
        "sign_off": {
            "by": None,
            "at": None,
            "decision": "finalised_pending_signoff" if stage == "final" else None,
        },
    }
