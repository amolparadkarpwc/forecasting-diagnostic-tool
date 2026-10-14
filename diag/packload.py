"""Load and validate the knowledge pack."""

from __future__ import annotations

from pathlib import Path

import yaml

from diag.blocks import BLOCKS
from diag.rules.ownership import validate_ownership
from diag.rules.review import POLICIES

REQUIRED = ["id", "name", "area", "tier", "points", "gate", "question"]


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"missing knowledge pack file: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.name} must be a mapping")
    return loaded


def load_pack(path: str | Path) -> dict:
    root = Path(path)
    if root.is_file():
        root = root.parent
    meta = _load_yaml(root / "pack.yaml")
    for field in ("name", "version", "diagnostics", "gate_floor", "maturity_bands", "area_weights", "gates"):
        if field not in meta:
            raise ValueError(f"pack.yaml missing {field}")
    vocab = {}
    for name in meta.get("vocabularies") or []:
        vocab[name] = _load_yaml(root / "vocab" / f"{name}.yaml")
    diagnostics = []
    known_ids = set()
    for diag_id in meta["diagnostics"]:
        entry = _load_yaml(root / "diagnostics" / f"{diag_id}.yaml")
        if entry.get("id") != diag_id:
            raise ValueError(f"{diag_id}.yaml id does not match the file name")
        missing = [field for field in REQUIRED if field not in entry]
        if missing:
            raise ValueError(f"{diag_id} missing {', '.join(missing)}")
        _validate_entry(entry, vocab)
        diagnostics.append(entry)
        known_ids.add(diag_id)
    for gate in meta.get("gates") or []:
        if gate not in known_ids:
            raise ValueError(f"gate {gate} is not in this pack")
    validate_ownership(diagnostics)
    library = _load_yaml(root / "library" / "recommendations.yaml")
    recommendations = library.get("recommendations") or []
    known_recs = {item.get("id") for item in recommendations}
    for entry in diagnostics:
        for signal_id, recommendation in (entry.get("recommendations") or {}).items():
            if recommendation not in known_recs:
                raise ValueError(f"{entry['id']}.{signal_id} references unknown recommendation {recommendation}")
    return {
        "meta": meta,
        "vocab": vocab,
        "diagnostics": diagnostics,
        "recommendations": recommendations,
        "root": str(root),
    }


def _validate_entry(entry: dict, vocab: dict) -> None:
    for signal_id, signal in (entry.get("signals") or {}).items():
        if not isinstance(signal, dict):
            raise ValueError(f"{entry['id']}.{signal_id} must be a mapping")
        policy = signal.get("review") or "none"
        if policy not in POLICIES:
            raise ValueError(f"{entry['id']}.{signal_id} has unknown review policy {policy}")
        for detector in signal.get("detectors") or []:
            block = detector.get("type")
            if block not in BLOCKS and block != "data_calc":
                raise ValueError(f"{entry['id']}.{signal_id} uses unknown block {block}")
            if detector.get("file_family") == "document" and detector.get("level") != "Attested":
                raise ValueError(f"{entry['id']}.{signal_id} document detector must be Attested")
            _check_refs(detector.get("params") or {}, vocab, f"{entry['id']}.{signal_id}")


def _check_refs(value, vocab: dict, label: str) -> None:
    if isinstance(value, str) and value.startswith("@"):
        if value[1:] not in vocab:
            raise ValueError(f"{label} references unknown vocabulary {value}")
    elif isinstance(value, list):
        for item in value:
            _check_refs(item, vocab, label)
    elif isinstance(value, dict):
        for item in value.values():
            _check_refs(item, vocab, label)
