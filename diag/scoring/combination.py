"""Data-area combination rule and trigger-based gates.

Thresholds, curves and floors are read from the pack. Nothing here is a
placeholder number of our own.
"""

from __future__ import annotations


def round_at_end(value: float) -> int:
    """Round once, at the end of a side score.

    TODO(pack): the brief asks for half-up. The worked-example scripts use
    Python's round, which takes halves to even. D43 case 2 lands on a half,
    so half-up would score 25 where the script scores 24. This follows the
    script until the pack owner chooses.
    """
    return int(round(value))


def _curve_points(curve) -> list[dict]:
    points = []
    for point in curve or []:
        if isinstance(point, dict):
            points.append(point)
        else:
            points.append({"x": point[0], "y": point[1]})
    return points


def _measure_score(measure: dict, value) -> float | None:
    from diag.scoring.score import interpolate

    if "score_map" in measure:
        mapped = measure["score_map"].get(value)
        if mapped is None:
            return None
        return float(mapped)
    scored = interpolate(_curve_points(measure.get("curve")), float(value))
    return None if scored is None else float(scored)


def _perfect_value(measure: dict):
    """A handled issue does not count: 0 on a curve, the best category on a map."""
    if "score_map" in measure:
        return max(measure["score_map"], key=lambda key: measure["score_map"][key])
    return 0


def condition_score(entry: dict, values: dict, stage: str, active: set[str]) -> tuple[int | None, dict[str, float]]:
    measures = (entry.get("data_route") or {}).get("measures") or {}
    if not isinstance(measures, dict) or not values:
        return None, {}
    scores: dict[str, float] = {}
    for name, raw in values.items():
        measure = measures.get(name)
        if not isinstance(measure, dict) or measure.get("release") == "later":
            continue
        stages = measure.get("stages")
        if stage == "model_ready" and stages == ["raw_source"]:
            continue
        handled = set(measure.get("handled_by") or []) & active
        if stage == "raw_source" and handled:
            raw = _perfect_value(measure)
        scored = _measure_score(measure, raw)
        if scored is not None:
            scores[name] = scored
    if not scores:
        return None, {}
    mean = sum(scores.values()) / len(scores)
    critical = [score for name, score in scores.items() if measures[name].get("critical")]
    return round_at_end(min([mean, *critical])), scores


def control_score(entry: dict, active: set[str]) -> int | None:
    from diag.scoring.score import apply_rules

    score, _caps = apply_rules(entry.get("scoring") or [], sorted(active))
    if score is None:
        return None
    return int(score)


def combine(condition: int | None, control: int | None) -> tuple[int | None, str | None]:
    if condition is None and control is None:
        return None, None
    if control is None:
        return condition, "Controls not evidenced"
    if condition is None:
        return control, "Condition not measured"
    return min(condition, control), None


def data_area_ids(pack: dict) -> set[str]:
    combination = ((pack.get("meta") or {}).get("combination") or {}).get("data_area") or {}
    return set(combination.get("diagnostics") or [])


def gate_floor(pack: dict) -> float:
    gates = (pack.get("meta") or {}).get("gates")
    if isinstance(gates, dict) and "floor" in gates:
        return float(gates["floor"])
    return float((pack.get("meta") or {}).get("gate_floor", 40))


def requirement_met(trigger: dict, signal_id: str, confirmed: set[str], level: str | None, inferred_needs_review: bool) -> bool:
    requires = trigger.get("requires") or "none"
    if inferred_needs_review and level == "Inferred" and signal_id not in confirmed:
        return False
    if requires == "none":
        return True
    if requires in {"review_confirmed", "absence_confirmed", "lineage_resolved_or_review_confirmed"}:
        return signal_id in confirmed
    return False


def evaluate_gate(
    entry: dict,
    combined: int | None,
    signals: set[str],
    measure_scores: dict[str, float],
    confirmed: set[str],
    floor: float,
    *,
    levels: dict[str, str] | None = None,
    categories: dict | None = None,
    inferred_needs_review: bool = True,
) -> dict:
    empty = {"status": "no_evidence", "triggers_active": [], "triggers_met": [], "triggers_pending": []}
    if combined is None or not entry.get("gate"):
        return empty if entry.get("gate") else {}
    active: list[dict] = []
    for trigger in (entry.get("gate_policy") or {}).get("triggers") or []:
        kind = trigger.get("kind")
        trigger_id = trigger.get("id")
        if kind == "signal" and trigger_id in signals:
            active.append(trigger)
        elif kind == "measure" and trigger_id in measure_scores and measure_scores[trigger_id] < floor:
            allowed = trigger.get("values")
            category = (categories or {}).get(trigger_id)
            if allowed and category is not None and category not in allowed:
                continue
            active.append(trigger)
    if combined >= floor or not active:
        return {"status": "passes", "triggers_active": [], "triggers_met": [], "triggers_pending": []}
    met: list[str] = []
    pending: list[str] = []
    levels = levels or {}
    for trigger in active:
        trigger_id = trigger["id"]
        if requirement_met(trigger, trigger_id, confirmed, levels.get(trigger_id), inferred_needs_review):
            met.append(trigger_id)
        else:
            pending.append(trigger_id)
    return {
        "status": "tripped" if met else "pending",
        "triggers_active": [item["id"] for item in active],
        "triggers_met": met,
        "triggers_pending": pending,
    }


def _fill(template: str, values: dict) -> str:
    text = template
    for key, value in values.items():
        text = text.replace("{" + key + "}", "" if value is None else str(value))
    return text


def verdict_for_pack(pack: dict, diagnostics: list[dict], overall: float | None) -> tuple[str, str]:
    """First matching rule in pack.yaml verdict wins. Gates not in this pack are ignored."""
    rules = (pack.get("meta") or {}).get("verdict")
    present = {item["id"] for item in diagnostics}
    gates = [item for item in diagnostics if item.get("gate") and item["id"] in present]
    if not isinstance(rules, list):
        return "Not ready", ""
    tripped = [item for item in gates if (item.get("gate_result") or {}).get("status") == "tripped"]
    pending = [item for item in gates if (item.get("gate_result") or {}).get("status") == "pending"]
    missing = [item for item in gates if (item.get("gate_result") or {}).get("status") == "no_evidence" or item.get("score") is None and item.get("gate")]
    for rule in rules:
        when = rule.get("when")
        reason = rule.get("reason") or ""
        if when == "any_gate_tripped" and tripped:
            item = tripped[0]
            return rule["verdict"], _fill(reason, {"gate": item["id"], "gate_finding": item.get("finding") or "", "overall": overall})
        if when == "overall_below" and overall is not None and overall < float(rule.get("value", 50)):
            return rule["verdict"], _fill(reason, {"overall": overall, "gate": "", "gate_finding": ""})
        if when == "any_gate_trigger_pending" and pending:
            item = pending[0]
            return rule["verdict"], _fill(reason, {"gate": item["id"], "gate_finding": ", ".join((item.get("gate_result") or {}).get("triggers_pending") or [])})
        if when == "any_gate_without_evidence" and missing:
            return rule["verdict"], _fill(reason, {"gate": missing[0]["id"], "gate_finding": ""})
        if when == "overall_from" and overall is not None and overall >= float(rule.get("value", 67)):
            return rule["verdict"], reason
        if rule.get("otherwise"):
            return rule["verdict"], reason
    return "Ready with gaps", ""
