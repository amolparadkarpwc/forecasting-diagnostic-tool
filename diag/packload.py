"""Load and validate the knowledge pack."""

from __future__ import annotations

import subprocess
import sys
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


def _vocab_path(root: Path, item: str) -> Path:
    text = str(item)
    if "/" in text or text.endswith(".yaml"):
        return root / text
    return root / "vocab" / f"{text}.yaml"


def _entry_path(root: Path, item: str) -> tuple[Path, str]:
    text = str(item)
    if "/" in text or text.endswith(".yaml"):
        path = root / text
        return path, path.stem
    return root / "diagnostics" / f"{text}.yaml", text


def _merge_vocab(root: Path, names: list) -> dict:
    """Merge vocabulary files. `version` is file metadata, not a term."""
    merged: dict = {}
    for item in names:
        loaded = _load_yaml(_vocab_path(root, item))
        for key, value in loaded.items():
            if key == "version":
                continue
            if key in merged:
                raise ValueError(f"duplicate vocabulary key {key} in {item}")
            merged[key] = value
    return merged


def _load_shared(root: Path, names: list) -> dict:
    shared = {}
    for item in names:
        path = root / str(item)
        shared[path.stem] = _load_yaml(path)
    return shared


def _normalise_meta(meta: dict) -> None:
    """Expose pack 0.5.0 sections under the names the scorer already reads."""
    scoring = meta.get("scoring") or {}
    if "maturity_bands" not in meta and scoring.get("maturity"):
        meta["maturity_bands"] = [
            {"name": band.get("level") or band.get("name"), "min": band.get("from", band.get("min", 0))}
            for band in scoring["maturity"]
        ]
    status = scoring.get("status") or {}
    if "status_bands" not in meta and status:
        meta["status_bands"] = {
            "red_below": status.get("red_below", 50),
            "amber_below": status.get("green_from", 67),
        }
    gates = meta.get("gates")
    if isinstance(gates, dict):
        meta.setdefault("gate_floor", gates.get("floor", 40))
    if "area_weights" not in meta and meta.get("areas"):
        meta["area_weights"] = {area["name"]: area.get("points", 0) for area in meta["areas"]}


_CHECK_CACHE: dict[str, int] = {}


def _pack_stamp(root: Path) -> int:
    newest = 0
    for path in root.rglob("*.yaml"):
        newest = max(newest, path.stat().st_mtime_ns)
    script = root / "tools" / "check_pack.py"
    if script.exists():
        newest = max(newest, script.stat().st_mtime_ns)
    return newest


def _require_checker(root: Path) -> None:
    script = root / "tools" / "check_pack.py"
    if not script.exists():
        return
    key = str(root.resolve())
    stamp = _pack_stamp(root)
    if _CHECK_CACHE.get(key) == stamp:
        return
    completed = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part and part.strip())
        raise ValueError(f"knowledge pack failed check_pack.py:\n{detail}")
    _CHECK_CACHE[key] = stamp


def load_pack(path: str | Path) -> dict:
    root = Path(path)
    if root.is_file():
        root = root.parent
    meta = _load_yaml(root / "pack.yaml")
    for field in ("name", "version", "diagnostics"):
        if field not in meta:
            raise ValueError(f"pack.yaml missing {field}")
    _normalise_meta(meta)
    _require_checker(root)
    vocab = _merge_vocab(root, list(meta.get("vocabularies") or []))
    shared = _load_shared(root, list(meta.get("shared_steps") or []))
    diagnostics = []
    known_ids = set()
    for item in meta["diagnostics"]:
        entry_path, diag_id = _entry_path(root, item)
        entry = _load_yaml(entry_path)
        if entry.get("id") != diag_id:
            raise ValueError(f"{entry_path.name} id does not match the file name")
        missing = [field for field in REQUIRED if field not in entry]
        if missing:
            raise ValueError(f"{diag_id} missing {', '.join(missing)}")
        _validate_entry(entry, vocab)
        diagnostics.append(entry)
        known_ids.add(diag_id)
    gates = meta.get("gates")
    gate_ids = gates.get("diagnostics", []) if isinstance(gates, dict) else list(gates or [])
    # Gates whose entries are not in this pack are ignored at runtime.
    # TODO(pack): pack.yaml lists D14 and D34 as gates, but this pack does not ship those entries.
    for gate in gate_ids:
        if gate not in known_ids:
            continue
    validate_ownership(diagnostics)
    library_paths = list(meta.get("library") or ["library/recommendations.yaml"])
    recommendations: list[dict] = []
    for item in library_paths:
        library = _load_yaml(root / str(item))
        recommendations.extend(library.get("recommendations") or [])
    known_recs = {item.get("id") for item in recommendations}
    for entry in diagnostics:
        for signal_id, recommendation in (entry.get("recommendations") or {}).items():
            if recommendation not in known_recs:
                raise ValueError(f"{entry['id']}.{signal_id} references unknown recommendation {recommendation}")
    return {
        "meta": meta,
        "vocab": vocab,
        "shared": shared,
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
        parts = value[1:].split(".")
        if parts[0] in {"pack", "data_stage"}:
            return
        current = vocab
        for part in parts:
            if not isinstance(current, dict) or part not in current:
                raise ValueError(f"{label} references unknown vocabulary {value}")
            current = current[part]
    elif isinstance(value, list):
        for item in value:
            _check_refs(item, vocab, label)
    elif isinstance(value, dict):
        for item in value.values():
            _check_refs(item, vocab, label)
