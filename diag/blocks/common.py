"""Match objects returned by building blocks."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Match:
    fact: str
    location: dict
    values: dict = field(default_factory=dict)
    match_strength: str = "pattern"


def resolve_vocab(value, vocab: dict):
    """Expand @name references into vocabulary term lists."""
    if isinstance(value, str) and value.startswith("@"):
        entry = vocab.get(value[1:], {})
        if isinstance(entry, dict):
            return list(entry.get("terms") or entry.get("modules") or [])
        if isinstance(entry, list):
            return list(entry)
        return []
    if isinstance(value, list):
        expanded = []
        for item in value:
            resolved = resolve_vocab(item, vocab)
            if isinstance(item, str) and item.startswith("@"):
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
