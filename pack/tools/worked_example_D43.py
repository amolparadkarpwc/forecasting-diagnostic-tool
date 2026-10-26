"""Reference calculation of D43 and its gate for README section 3b.

Reads curves, score maps, control rules and the gate policy from the YAML. A demonstration of the
rules, not the engine.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
D43 = yaml.safe_load((ROOT / "diagnostics/D43.yaml").read_text())
FLOOR = yaml.safe_load((ROOT / "pack.yaml").read_text())["gates"]["floor"]
MEASURES = D43["data_route"]["measures"]
TRIGGERS = {t["id"]: t for t in D43["gate_policy"]["triggers"]}


def curve(points, x):
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0)
    return points[-1][1]


def measure_score(name, value):
    m = MEASURES[name]
    return m["score_map"][value] if "score_map" in m else curve(m["curve"], value)


def condition(values, handled):
    if not values:
        return None, {}
    scores = {n: (100 if set(MEASURES[n].get("handled_by", [])) & handled else measure_score(n, v)) for n, v in values.items()}
    mean = sum(scores.values()) / len(scores)
    return round(min([mean] + [s for n, s in scores.items() if MEASURES[n]["critical"]])), scores


def control(active):
    base, caps = None, []
    for rule in D43["scoring"]:
        if "otherwise" in rule:
            break
        if set(rule["when_all"]) <= active:
            if "score" in rule and base is None:
                base = rule["score"]
            if "cap" in rule:
                caps.append(rule["cap"])
    return None if base is None else min([base] + caps)


def gate(combined, signals, measure_scores, confirmed):
    """Trips only if the score is below the floor AND a listed trigger is below the floor with its requirement met."""
    if combined is None:
        return "no evidence -> Readiness not confirmed"
    active = []
    for tid, t in TRIGGERS.items():
        if t["kind"] == "signal" and tid in signals:
            active.append(tid)
        if t["kind"] == "measure" and tid in measure_scores and measure_scores[tid] < FLOOR:
            active.append(tid)
    if combined >= FLOOR or not active:
        return "passes"
    met = [t for t in active if TRIGGERS[t]["requires"] == "none" or t in confirmed]
    if met:
        return f"TRIPPED by {', '.join(met)} -> Not ready"
    return f"pending review of {', '.join(active)} -> Readiness not confirmed"


aligned = {"grain_alignment": "aligned", "unit_alignment": "aligned"}
good_code = {"training_code_present", "target_identified", "target_definition_stated",
             "evaluation_actuals_traced", "target_same_in_training_and_evaluation"}

cases = [
    ("1 Clean; 4% returns netted", {**aligned, "target_reconciliation": 0.005, "returns_share": 0.04}, good_code, set()),
    ("2 Accuracy measured on shipments", {**aligned, "target_reconciliation": 0.08},
     {"training_code_present", "target_identified", "evaluation_actuals_traced", "target_mismatch_training_evaluation"},
     {"target_mismatch_training_evaluation"}),          # lineage resolved both columns
    ("3 20% returns, net sales clipped", {**aligned, "target_reconciliation": 0.005, "returns_share": 0.20},
     good_code | {"target_clipped_at_zero"}, set()),
    ("4 Column 'qty', nothing defines it", {}, {"training_code_present", "target_identified", "target_ambiguous"}, set()),
    ("5a Deck says till sales, code shipments", {}, {"training_code_present", "target_identified", "target_definition_stated", "definitions_conflict"}, set()),
    ("5b Same, after practitioner confirms", {}, {"training_code_present", "target_identified", "target_definition_stated", "definitions_conflict"}, {"definitions_conflict"}),
    ("6 Nothing about the target shared", {}, set(), set()),
]
for label, values, signals, confirmed in cases:
    cond, mscores = condition(values, signals)
    ctrl = control(signals)
    sides = [x for x in (cond, ctrl) if x is not None]
    combined = min(sides) if sides else None
    label_side = "" if cond is not None and ctrl is not None else (" (condition not measured)" if ctrl is not None else (" (controls not evidenced)" if cond is not None else ""))
    print(f"{label:40s} cond {str(cond):>4}  ctrl {str(ctrl):>4}  D43 {str(combined):>4}{label_side:26s} gate: {gate(combined, signals, mscores, confirmed)}")
