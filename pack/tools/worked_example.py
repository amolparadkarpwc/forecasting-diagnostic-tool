"""Reference calculation of D08 for the Retailer X scenarios (README section 3).

Reads the curves and control rules from diagnostics/D08.yaml, so the README numbers stay
true to the pack. This is a demonstration of the combination rule, not the engine.
"""
from pathlib import Path

import yaml

D08 = yaml.safe_load((Path(__file__).resolve().parent.parent / "diagnostics/D08.yaml").read_text())
MEASURES = D08["data_route"]["measures"]


def curve(points, x):
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0)
    return points[-1][1]


def condition(values, stage, handled):
    """values: measure -> raw value. On raw data, handled issues are set to 0 before scoring."""
    scores = {}
    for name, x in values.items():
        m = MEASURES[name]
        if stage == "model_ready" and m.get("stages") == ["raw_source"]:
            continue
        if stage == "raw_source" and set(m.get("handled_by", [])) & handled:
            x = 0
        scores[name] = curve(m["curve"], x)
    mean = sum(scores.values()) / len(scores)
    critical = [s for n, s in scores.items() if MEASURES[n]["critical"]]
    return round(min([mean] + critical)), scores


def control(active):
    base, caps = None, []
    for rule in D08["scoring"]:
        if "otherwise" in rule:
            break
        if set(rule["when_all"]) <= active:
            if "score" in rule and base is None:
                base = rule["score"]
            if "cap" in rule:
                caps.append(rule["cap"])
    return None if base is None else min([base] + caps)


def combine(cond, ctrl):
    if cond is None and ctrl is None:
        return "No evidence"
    if ctrl is None:
        return f"{cond} (controls not evidenced)"
    if cond is None:
        return f"{ctrl} (condition not measured)"
    return min(cond, ctrl)


clean = {"duplicate_rows": 0, "conflicting_records": 0, "out_of_range": 0, "calendar_consistency": 0}
prep_py = {"data_prep_code_present", "dedupe_exact", "zero_fill_gaps", "zero_fill_hides_missing_data", "no_validation_found"}
better = {"data_prep_code_present", "dedupe_exact", "explicit_gap_handling", "validation_framework_used"}

scenarios = {
    "A  model-ready table only": ("model_ready", {**clean, "gap_share": 0.018}, None),
    "B  model-ready table + prep.py": ("model_ready", {**clean, "gap_share": 0.018}, prep_py),
    "C  raw extract + prep.py": ("raw_source", {**clean, "gap_share": 0.018, "duplicate_rows": 0.003, "parse_errors": 0}, prep_py),
    "D  raw extract + better pipeline": ("raw_source", {**clean, "gap_share": 0.018, "duplicate_rows": 0.003, "parse_errors": 0}, better),
}
for label, (stage, values, signals) in scenarios.items():
    handled = signals or set()
    cond, detail = condition(values, stage, handled)
    ctrl = control(signals) if signals else None
    print(f"{label:36s} condition {cond:>3}  control {str(ctrl):>4}  ->  D08 = {combine(cond, ctrl)}")
