"""Replace configured identifying strings in output values."""

from __future__ import annotations

from typing import Any


def mask_text(value: str, terms: list[str]) -> str:
    """Replace each masking term with ``[masked]``."""
    masked = value
    for term in sorted((term for term in terms if term), key=len, reverse=True):
        masked = masked.replace(term, "[masked]")
    return masked


def mask_obj(value: Any, terms: list[str]) -> Any:
    """Mask strings nested in dicts and lists. Keys are left unchanged."""
    if not terms:
        return value
    if isinstance(value, str):
        return mask_text(value, terms)
    if isinstance(value, list):
        return [mask_obj(item, terms) for item in value]
    if isinstance(value, dict):
        return {key: mask_obj(item, terms) for key, item in value.items()}
    return value
