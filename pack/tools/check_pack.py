"""Consistency checks for the knowledge pack (data area).

Run:  python tools/check_pack.py   (from the pack/ folder)
Exits non-zero if any check fails. Intended to run in CI before a pack version is released.
"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
errors: list[str] = []
warnings: list[str] = []


def load(rel: str) -> dict:
    try:
        return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - report every parse failure
        errors.append(f"{rel}: YAML does not parse ({exc})")
        return {}


pack = load("pack.yaml")
vocab = {}
for v in pack.get("vocabularies", []):
    vocab.update(load(v))
shared = {Path(s).stem: load(s) for s in pack.get("shared_steps", [])}
library = {}
for lib in pack.get("library", []):
    for rec in load(lib).get("recommendations", []):
        library[rec["id"]] = rec

zero_classes = {c["id"] for c in shared.get("zero_classification", {}).get("classes", [])}
VALID_LEVELS = {"Verified", "Inferred", "Attested"}
VALID_RELEASES = set(pack.get("releases", []))


def check_vocab_refs(node, where: str) -> None:
    """Every '@name' or '@name.key' must resolve in vocab (pack.* and data_stage.* are engine refs)."""
    if isinstance(node, dict):
        for k, v in node.items():
            check_vocab_refs(v, f"{where}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            check_vocab_refs(v, f"{where}[{i}]")
    elif isinstance(node, str) and node.startswith("@"):
        path = node[1:].split(".")
        if path[0] in {"pack", "data_stage"}:
            return
        cur = vocab
        for part in path:
            if not isinstance(cur, dict) or part not in cur:
                errors.append(f"{where}: vocabulary reference {node} does not resolve")
                return
            cur = cur[part]


def check_curve(curve, where: str) -> None:
    xs = [p[0] for p in curve]
    ys = [p[1] for p in curve]
    if xs != sorted(xs):
        errors.append(f"{where}: curve x values are not increasing")
    if any(b > a for a, b in zip(ys, ys[1:])):
        errors.append(f"{where}: curve scores rise as the problem grows")
    if any(not 0 <= y <= 100 for y in ys):
        errors.append(f"{where}: curve score outside 0-100")


entries = {}
for rel in pack.get("diagnostics", []):
    e = load(rel)
    entries[e.get("id", rel)] = e
floor = pack.get("gates", {}).get("floor", 40)

for did, entry in entries.items():
    measures = entry.get("data_route", {}).get("measures", {})
    signals = entry.get("signals", {})
    known = set(signals) | set(measures)

    for name, m in measures.items():
        w = f"{did}.measures.{name}"
        if m.get("release") not in VALID_RELEASES:
            errors.append(f"{w}: release missing or invalid")
        if m.get("owner") != did:
            errors.append(f"{w}: owner must be {did}")
        if "curve" in m:
            check_curve(m["curve"], w)
        elif "score_map" in m:
            if any(not 0 <= v <= 100 for v in m["score_map"].values()):
                errors.append(f"{w}: score_map value outside 0-100")
        else:
            errors.append(f"{w}: needs a curve or a score_map")
        for ref in m.get("handled_by", []) + m.get("never_handled_by", []):
            if ref not in signals:
                errors.append(f"{w}: handled_by refers to unknown signal {ref}")
        rec = m.get("recommendation")
        if rec and rec not in library:
            errors.append(f"{w}: recommendation {rec} not in library")
        if "level" in m and m["level"] not in VALID_LEVELS:
            errors.append(f"{w}: invalid level {m['level']}")

    if not any(m.get("critical") for m in measures.values()):
        errors.append(f"{did}: no critical measure, so the condition score is never capped")

    for name, s in signals.items():
        w = f"{did}.signals.{name}"
        if s.get("owner") != did:
            errors.append(f"{w}: every signal needs exactly one owner ({did})")
        if s.get("release") not in VALID_RELEASES:
            errors.append(f"{w}: release missing or invalid")
        for det in s.get("detectors", []):
            if det.get("level") not in VALID_LEVELS:
                errors.append(f"{w}: detector level missing or invalid")
            if det.get("file_family") == "document" and det.get("level") != "Attested":
                errors.append(f"{w}: document detectors must be Attested")
        if "detectors" not in s and "derived" not in s:
            errors.append(f"{w}: neither detectors nor derived")
        derived = s.get("derived") or {}
        sources = derived.get("from", [])
        sources = [sources] if isinstance(sources, str) else sources
        for src in sources + derived.get("of", []):
            if src.startswith("@"):
                continue
            if src.startswith("zero."):
                if src[5:] not in zero_classes:
                    errors.append(f"{w}: unknown zero class {src}")
            elif src not in known:
                errors.append(f"{w}: derived from unknown signal {src}")

    for rule in entry.get("scoring", []):
        for ref in rule.get("when_all", []):
            if ref not in signals:
                errors.append(f"{did}.scoring: unknown signal {ref}")
        if "score" in rule and "cap" in rule:
            errors.append(f"{did}.scoring: a rule sets score or cap, not both")
    if entry.get("scoring") and "otherwise" not in entry["scoring"][-1]:
        errors.append(f"{did}.scoring: last rule must be 'otherwise'")
    score_rules = [r for r in entry.get("scoring", []) if "score" in r]
    if [r["score"] for r in score_rules] != sorted((r["score"] for r in score_rules), reverse=True):
        errors.append(f"{did}.scoring: score rules not ordered strongest first")

    for key in list(entry.get("insights", {})) + list(entry.get("recommendations", {})):
        if key not in known:
            errors.append(f"{did}: template or recommendation key {key} matches no signal or measure")
    for rec in entry.get("recommendations", {}).values():
        if rec not in library:
            errors.append(f"{did}: recommendation {rec} not in library")

    for name, tmpl in entry.get("insights", {}).items():
        allowed = set(signals.get(name, {}).get("values", [])) | set(measures.get(name, {}).get("outputs", []))
        for ph in re.findall(r"{(\w+)}", tmpl):
            base = ph[:-4] if ph.endswith("_pct") else ph
            if ph not in allowed and base not in allowed:
                errors.append(f"{did}.insights.{name}: placeholder {{{ph}}} is not produced by the signal")

    for name, m in measures.items():
        allowed = set(m.get("outputs", []))
        for ph in re.findall(r"{(\w+)}", m.get("insight", "")):
            stem = ph[:-4] if ph.endswith("_pct") else ph
            if ph not in allowed and stem not in allowed and f"{stem}_share" not in allowed:
                errors.append(f"{did}.measures.{name}.insight: placeholder {{{ph}}} is not an output")

    for name, sig in signals.items():
        src = (sig.get("derived") or {}).get("from", [])
        if name in ([src] if isinstance(src, str) else src):
            errors.append(f"{did}.signals.{name}: derived from itself (use pass_when for a threshold)")

    if entry.get("gate"):
        policy = entry.get("gate_policy")
        if not policy:
            errors.append(f"{did}: gate diagnostic without gate_policy")
        else:
            for t in policy.get("triggers", []):
                tid, kind = t.get("id"), t.get("kind")
                if kind == "signal":
                    sig = signals.get(tid)
                    if not sig:
                        errors.append(f"{did}.gate_policy: unknown trigger signal {tid}")
                        continue
                    if not sig.get("gate_trigger"):
                        errors.append(f"{did}.gate_policy: {tid} is not marked gate_trigger")
                    lows = [r.get("cap", r.get("score")) for r in entry.get("scoring", []) if r.get("when_all") == [tid]]
                    if not lows or min(lows) >= floor:
                        errors.append(f"{did}.gate_policy: trigger {tid} can never take the score below the floor ({floor})")
                elif kind == "measure":
                    m = measures.get(tid)
                    if not m:
                        errors.append(f"{did}.gate_policy: unknown trigger measure {tid}")
                        continue
                    if not m.get("critical"):
                        errors.append(f"{did}.gate_policy: trigger measure {tid} must be critical to cap the condition score")
                    vals = [m["score_map"][v] for v in t.get("values", [])] if "score_map" in m else [p[1] for p in m.get("curve", [])]
                    if not vals or min(vals) >= floor:
                        errors.append(f"{did}.gate_policy: trigger {tid} can never fall below the floor ({floor})")
                else:
                    errors.append(f"{did}.gate_policy: trigger {tid} has no valid kind")
            trigger_ids = {t["id"] for t in policy.get("triggers", [])}
            for name, sig in signals.items():
                if sig.get("gate_trigger") and name not in trigger_ids:
                    errors.append(f"{did}: {name} is marked gate_trigger but not listed in gate_policy")
            non_trigger_low = [r for r in entry.get("scoring", []) if "cap" in r and r["cap"] < floor
                               and not set(r["when_all"]) <= trigger_ids]
            for r in non_trigger_low:
                warnings.append(f"{did}: cap {r['cap']} on {r['when_all']} is below the floor but not a trigger (lowers the score, can't fail the gate)")

    for sup in entry.get("supporting", []):
        ref = sup.get("ref", "")
        target_id, _, rest = ref.partition(".")
        if target_id not in entries:
            warnings.append(f"{did}: supporting ref {ref} points to an entry not written yet")
            continue
        other = entries[target_id]
        if rest.startswith("zero."):
            ok = rest[5:] in zero_classes
        else:
            ok = rest in other.get("signals", {}) or rest in other.get("data_route", {}).get("measures", {})
        if not ok:
            errors.append(f"{did}: supporting ref {ref} does not exist in {target_id}")

    check_vocab_refs(entry, did)

for name, step in shared.items():
    check_vocab_refs(step, name)

for w_ in warnings:
    print("note:", w_)
if errors:
    print(f"FAILED: {len(errors)} problem(s)")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print(f"OK: pack {pack.get('version')}, {len(entries)} entries, "
      f"{len(library)} recommendations, {len(zero_classes)} zero classes")
