"""Load and validate a knowledge pack."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DETECTOR_TYPES = {
    "code_import",
    "code_call",
    "config_key",
    "phrase_search",
    "data_calc",
    "log_stats",
}


class PackError(ValueError):
    """The knowledge pack is missing required fields or is otherwise invalid."""


def load_pack(pack_dir: Path) -> dict[str, Any]:
    """Load ``pack.yaml`` and the diagnostic entries it lists."""
    pack_dir = pack_dir.resolve()
    manifest_path = pack_dir / "pack.yaml"
    if not manifest_path.is_file():
        raise PackError(f"pack manifest not found: {manifest_path}")
    manifest = _read_yaml(manifest_path)
    if not isinstance(manifest, dict):
        raise PackError("pack.yaml must be a mapping")
    version = manifest.get("version")
    if not version:
        raise PackError("pack.yaml missing version")
    names = manifest.get("diagnostics")
    if not isinstance(names, list) or not names:
        raise PackError("pack.yaml missing diagnostics")
    entries: list[dict[str, Any]] = []
    for name in names:
        path = pack_dir / "diagnostics" / f"{name}.yaml"
        if not path.is_file():
            raise PackError(f"diagnostic file not found: {path}")
        entry = _read_yaml(path)
        validate_entry(entry, path)
        if entry["id"] != name:
            raise PackError(f"{path} id is {entry['id']!r}, expected {name!r}")
        entries.append(entry)
    entries.sort(key=lambda item: item["id"])
    return {"manifest": manifest, "entries": entries, "version": str(version)}


def validate_entry(entry: Any, path: Path | None = None) -> None:
    """Refuse a diagnostic entry missing id, signals, or scoring."""
    label = str(path) if path is not None else "diagnostic entry"
    if not isinstance(entry, dict):
        raise PackError(f"{label} must be a mapping")
    for key in ("id", "signals", "scoring"):
        if key not in entry or entry[key] in (None, "", [], {}):
            raise PackError(f"{label} missing {key}")
    if not isinstance(entry["signals"], dict):
        raise PackError(f"{label} signals must be a mapping")
    if not isinstance(entry["scoring"], list):
        raise PackError(f"{label} scoring must be a list")
    for signal_id, signal in entry["signals"].items():
        if not isinstance(signal, dict):
            raise PackError(f"{label} signal {signal_id} must be a mapping")
        detectors = signal.get("detectors")
        if not isinstance(detectors, list) or not detectors:
            raise PackError(f"{label} signal {signal_id} missing detectors")
        for detector in detectors:
            if not isinstance(detector, dict) or "type" not in detector:
                raise PackError(f"{label} signal {signal_id} has a detector without type")
            if detector["type"] not in DETECTOR_TYPES:
                raise PackError(
                    f"{label} signal {signal_id} uses unknown detector {detector['type']!r}"
                )
    for rule in entry["scoring"]:
        if not isinstance(rule, dict):
            raise PackError(f"{label} has a scoring rule that is not a mapping")
        if "otherwise" in rule:
            continue
        if "when_all" not in rule or not isinstance(rule["when_all"], list):
            raise PackError(f"{label} scoring rule missing when_all")
        if "score" not in rule and "cap" not in rule:
            raise PackError(f"{label} scoring rule needs score or cap")


def _read_yaml(path: Path) -> Any:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PackError(f"invalid YAML in {path}: {exc.__class__.__name__}") from exc
    return loaded
