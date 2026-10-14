"""Mask configured identifying strings in outputs."""

from __future__ import annotations

import re


def mask_text(text: str, terms: list[str]) -> str:
    if not text:
        return text
    for term in sorted((term for term in terms if term), key=len, reverse=True):
        text = re.sub(re.escape(term), "[REDACTED]", text, flags=re.IGNORECASE)
    return text


def mask_obj(value, terms: list[str]):
    if isinstance(value, str):
        return mask_text(value, terms)
    if isinstance(value, list):
        return [mask_obj(item, terms) for item in value]
    if isinstance(value, dict):
        return {key: mask_obj(item, terms) for key, item in value.items()}
    return value
