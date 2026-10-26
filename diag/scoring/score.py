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


def score_diagnostics(pack: dict, evidence: list[dict], measure_values: dict, *, include_attested: bool = True) -> list[dict]:
    red = float((pack["meta"].get("status_bands") or {}).get("red_below", 50))
    amber = float((pack["meta"].get("status_bands") or {}).get("amber_below", 67))
    results = []
    for diagnostic in pack["diagnostics"]:
        records = [record for record in evidence if record["diagnostic_id"] == diagnostic["id"]]
        if not include_attested:
            records = [record for record in records if record.get("evidence_level") != "Attested"]
        counted = [record for record in records if record["status"] in COUNTED]
        active = sorted({record["signal_id"] for record in counted})
        synthesis = diagnostic.get("tier") == "synthesis" or diagnostic.get("synthesis")
        if synthesis:
            results.append(_blank(diagnostic, status="Not scored", route="none"))
            continue
        measured = data_score(diagnostic, measure_values)
        caps: list[dict] = []
        if measured is not None:
            score = measured
            route = "data"
        else:
            score, caps = apply_rules(diagnostic.get("scoring") or [], active)
            route = choose_route(counted, False)
        score = round_score(score)
        status = status_for(score, red, amber)
        level = best_level(counted)
        slot = measure_values.get(diagnostic["id"]) or {}
        counted_route = route if score is not None else "none"
        # Sub-checks see every record, including ones held for review.
        # The score itself still uses only counted records.
        results.append(
            {
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
                "finding": finding_text(diagnostic, score, counted_route, slot, records),
                "detail": check_details(diagnostic, slot, records),
                "review_checklist": list(diagnostic.get("review_checklist") or []),
                "recommendation_ids": recommendation_ids(diagnostic, active),
                "source_summary": source_summary(counted),
            }
        )
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


def _targeted(diagnostics: list[dict]) -> list[dict]:
    rows = []
    for diagnostic in diagnostics:
        if diagnostic["tier"] == "synthesis":
            continue
        score = diagnostic["score"]
        if score is not None and score >= 50:
            continue
        request = diagnostic.get("gap_request") or ""
        if not request:
            continue
        rows.append((diagnostic["points"], diagnostic["id"], request))
    rows.sort(key=lambda row: (-row[0], row[1]))
    return [
        {"rank": index, "diagnostic_id": diag_id, "request": request}
        for index, (_points, diag_id, request) in enumerate(rows, start=1)
    ]


def _headline(verdict: str, score, failed: list[dict]) -> str:
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
    failed = gate_failures(diagnostics, list(meta.get("gates") or []), float(meta.get("gate_floor", 40)))
    bands = meta.get("verdict_bands") or {}
    verdict = verdict_for(score, failed, float(bands.get("ready", 67)), float(bands.get("ready_with_gaps", 50)))
    return {
        "score": score,
        "maturity": maturity_for(score, meta.get("maturity_bands") or []),
        "verdict": verdict,
        "failed_gates": failed,
        "provisional": any(item["provisional"] for item in diagnostics),
        "headline": _headline(verdict, score, failed),
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
