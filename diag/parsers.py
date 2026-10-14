"""Parse client files. Never execute them."""

from __future__ import annotations

import ast
import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import yaml

from diag.intake import Artifact

_LOG_LINE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})"
    r".*?\b(?P<status>OK|SUCCESS|ERROR|FAILED|WARN|WARNING|INFO|CRITICAL|STARTED|COMPLETED)\b",
    re.IGNORECASE,
)


class ParseError(Exception):
    """A single file could not be parsed. The run continues."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class ParsedFile:
    """Family-specific parse result for one readable artifact."""

    artifact: Artifact
    source: str = ""
    lines: list[str] = field(default_factory=list)
    tree: ast.AST | None = None
    flat: dict[str, Any] = field(default_factory=dict)
    fieldnames: list[str] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)
    events: list[dict[str, str]] = field(default_factory=list)


def parse_artifact(artifact: Artifact) -> ParsedFile:
    """Parse one readable artifact according to its detected type."""
    if artifact.abs_path is None:
        raise ParseError("unreadable: missing file")
    text = _read_text(artifact.abs_path)
    parsed = ParsedFile(artifact=artifact, source=text, lines=text.splitlines())
    kind = artifact.detected_type
    if kind == "python":
        parsed.tree = _parse_python(text)
    elif kind == "yaml":
        parsed.flat = flatten(_parse_yaml(text))
    elif kind == "json":
        parsed.flat = flatten(_parse_json(text))
    elif kind == "csv":
        parsed.fieldnames, parsed.rows = _parse_csv(text)
        artifact.period_covered = _period_covered(parsed.rows)
    elif kind == "log":
        parsed.events = _parse_log(parsed.lines)
    elif kind in {"markdown", "text"}:
        pass
    else:
        raise ParseError("unreadable: unsupported type")
    return parsed


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten mappings and lists to dotted key paths."""
    flat: dict[str, Any] = {}
    if isinstance(value, dict):
        for key in sorted(value, key=lambda item: str(item)):
            child = f"{prefix}.{key}" if prefix else str(key)
            flat.update(flatten(value[key], child))
        return flat
    if isinstance(value, list):
        for index, item in enumerate(value):
            flat.update(flatten(item, f"{prefix}[{index}]"))
        return flat
    if prefix:
        flat[prefix] = value
    return flat


def source_line(parsed: ParsedFile, lineno: int | None) -> str:
    """Return one source line, or an empty string when it is unavailable."""
    if lineno is None or lineno < 1 or lineno > len(parsed.lines):
        return ""
    return parsed.lines[lineno - 1].strip()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParseError("could not decode as utf-8") from exc
    except OSError as exc:
        raise ParseError("unreadable: OSError") from exc


def _parse_python(text: str) -> ast.AST:
    try:
        return ast.parse(text)
    except SyntaxError as exc:
        raise ParseError("Python syntax error") from exc


def _parse_yaml(text: str) -> Any:
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ParseError("YAML parse error") from exc
    return {} if loaded is None else loaded


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError("JSON parse error") from exc


def _parse_csv(text: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            return [], []
        fieldnames = [name.strip() for name in reader.fieldnames]
        reader.fieldnames = fieldnames
        rows: list[dict[str, str]] = []
        for row in reader:
            rows.append({key: ("" if value is None else str(value).strip()) for key, value in row.items()})
        return fieldnames, rows
    except csv.Error as exc:
        raise ParseError("CSV parse error") from exc


def _parse_log(lines: list[str]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for line in lines:
        match = _LOG_LINE.search(line)
        if match is None:
            continue
        events.append(
            {
                "timestamp": match.group("ts"),
                "status": match.group("status").upper(),
            }
        )
    return events


def _period_covered(rows: list[dict[str, str]]) -> str:
    parsed_dates = [_parse_date(row.get("date", "")) for row in rows]
    found = [item for item in parsed_dates if item is not None]
    if not found:
        return ""
    start, end = min(found), max(found)
    return f"{start.isoformat()} to {end.isoformat()}"


def _parse_date(value: str) -> date | None:
    text = value.strip()
    if not text:
        return None
    try:
        if len(text) == 7:
            year, month = text.split("-")
            return date(int(year), int(month), 1)
        return date.fromisoformat(text[:10])
    except ValueError:
        return None
