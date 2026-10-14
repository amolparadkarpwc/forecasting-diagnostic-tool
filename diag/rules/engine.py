"""Apply knowledge-pack detectors and collect evidence records."""

from __future__ import annotations

from diag.blocks import BLOCKS
from diag.blocks.common import json_safe, resolve_vocab
from diag.rules.derived import evaluate_derived
from diag.rules.review import initial_status

_HANDLER = {
    "document": "documents",
    "code": "code",
    "config": "configs",
    "log": "logs",
    "model": "models",
    "data": "data",
}

_PROVISIONAL_HANDLERS = {"code", "configs", "logs", "models"}


def _family_matches(artifact, family: str | None) -> bool:
    if not family:
        return True
    return artifact.family == family


def _record(diagnostic, signal_id, signal, detector, artifact, match, pack_version: str) -> dict:
    status = initial_status(signal.get("review"))
    if match.values.get("uncertain"):
        status = "needs_review"
    handler = _HANDLER.get(artifact.family, artifact.family)
    return {
        "diagnostic_id": diagnostic["id"],
        "signal_id": signal_id,
        "source": {
            "artifact_id": artifact.artifact_id,
            "file": artifact.rel_path,
            "location": {"kind": match.location.get("kind") or "file", "value": str(match.location.get("value") or "")},
        },
        "handler": handler,
        "block": detector.get("type"),
        "fact": match.fact,
        "values": json_safe(match.values),
        "evidence_level": detector.get("level") or "Verified",
        "match_strength": match.match_strength,
        "status": status,
        "owner_diagnostic": signal.get("owner") or diagnostic["id"],
        "model_ref": None,
        "review": {"by": None, "at": None, "decision": None, "reason": None},
        "pack_version": pack_version,
        "provisional": handler in _PROVISIONAL_HANDLERS,
    }


def build_signal_evidence(pack: dict, parsed: list) -> list[dict]:
    vocab = pack.get("vocab") or {}
    version = pack["meta"]["version"]
    records: list[dict] = []
    values_by_signal: dict[tuple[str, str], dict] = {}
    for diagnostic in pack["diagnostics"]:
        for signal_id, signal in (diagnostic.get("signals") or {}).items():
            produced = False
            for detector in signal.get("detectors") or []:
                block = BLOCKS.get(detector.get("type"))
                if block is None:
                    raise ValueError(f"{diagnostic['id']}.{signal_id} uses unknown block {detector.get('type')}")
                params = resolve_vocab(detector.get("params") or {}, vocab)
                family = detector.get("file_family")
                for artifact in parsed:
                    if not _family_matches(artifact, family):
                        continue
                    try:
                        found = block(artifact, params, vocab, {"artifacts": parsed})
                    except Exception:
                        continue
                    for match in found:
                        record = _record(diagnostic, signal_id, signal, detector, artifact, match, version)
                        records.append(record)
                        values_by_signal.setdefault((diagnostic["id"], signal_id), {}).update(record["values"])
                        produced = True
            derived = signal.get("derived")
            if derived and not produced:
                source = values_by_signal.get((diagnostic["id"], derived.get("from")), {})
                if evaluate_derived(derived, source):
                    records.append(
                        {
                            "diagnostic_id": diagnostic["id"],
                            "signal_id": signal_id,
                            "source": {
                                "artifact_id": "",
                                "file": "",
                                "location": {"kind": "derived", "value": derived.get("test") or ""},
                            },
                            "handler": "rules",
                            "block": "derived",
                            "fact": f"{signal_id} derived from {derived.get('from')}",
                            "values": {"test": derived.get("test"), "threshold": derived.get("threshold")},
                            "evidence_level": "Inferred",
                            "match_strength": "derived",
                            "status": initial_status(signal.get("review")),
                            "owner_diagnostic": signal.get("owner") or diagnostic["id"],
                            "model_ref": None,
                            "review": {"by": None, "at": None, "decision": None, "reason": None},
                            "pack_version": version,
                            "provisional": False,
                        }
                    )
    return records


def assign_record_ids(records: list[dict]) -> list[dict]:
    ordered = sorted(
        records,
        key=lambda record: (
            record.get("diagnostic_id") or "",
            record.get("signal_id") or "",
            record.get("source", {}).get("file") or "",
            record.get("source", {}).get("location", {}).get("value") or "",
            record.get("fact") or "",
        ),
    )
    for index, record in enumerate(ordered, start=1):
        record["record_id"] = f"R{index:05d}"
    return ordered
