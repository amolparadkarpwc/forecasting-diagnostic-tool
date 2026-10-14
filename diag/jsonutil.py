"""Deterministic JSON read and write."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: Any) -> None:
    """Write JSON with sorted keys and a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def read_json(path: Path) -> Any:
    """Read a JSON file as UTF-8."""
    return json.loads(path.read_text(encoding="utf-8"))
