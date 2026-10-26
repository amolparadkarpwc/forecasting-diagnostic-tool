"""Match objects returned by building blocks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Match:
    fact: str
    location: dict
    values: dict = field(default_factory=dict)
    match_strength: str = "pattern"


def location_at(parsed: Any, index: int, line_no: int) -> dict[str, str]:
    """Use a section cue location when the match falls inside one, else the line."""
    sections = getattr(parsed, "sections", None) or []
    for section in sections:
        if not isinstance(section, dict):
            continue
        start = section.get("start")
        end = section.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if index < start or index >= end:
            continue
        location = section.get("location")
        if isinstance(location, dict) and location.get("kind") and str(location.get("value") or ""):
            return {"kind": str(location["kind"]), "value": str(location["value"])}
        break
    return {"kind": "line", "value": str(line_no)}


def _lookup_vocab(ref: str, vocab: dict):
    parts = ref[1:].split(".")
    if parts[0] in {"pack", "data_stage"}:
        return ref
    current = vocab
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        # Older packs store one file under the vocabulary name.
        entry = vocab.get(parts[0], {})
        if isinstance(entry, dict) and len(parts) == 1:
            listed = entry.get("terms") or entry.get("modules")
            if listed is not None:
                return list(listed)
        return []
    if isinstance(current, dict) and ("terms" in current or "modules" in current) and len(current) <= 3:
        return list(current.get("terms") or current.get("modules") or [])
    return current


def resolve_vocab(value, vocab: dict):
    """Expand @name and @name.key references. @pack and @data_stage stay as engine refs."""
    if isinstance(value, str) and value.startswith("@"):
        return _lookup_vocab(value, vocab)
    if isinstance(value, list):
        expanded = []
        for item in value:
            resolved = resolve_vocab(item, vocab)
            if isinstance(item, str) and item.startswith("@") and isinstance(resolved, list):
                expanded.extend(resolved)
            else:
                expanded.append(resolved)
        return expanded
    if isinstance(value, dict):
        return {key: resolve_vocab(item, vocab) for key, item in value.items()}
    return value


def json_safe(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    return str(value)
