"""Split log lines into timestamped status events. Unknown lines are ignored."""

from __future__ import annotations

import re
from pathlib import Path

from diag.handlers.base import ParsedArtifact
from diag.util import read_text

_TIMESTAMP = re.compile(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}Z?)")
_STATUS = re.compile(r"\b(SUCCESS|SUCCEEDED|FAILED|FAILURE|ERROR|WARN|WARNING|OK|INFO)\b", re.I)


def parse_log(path: Path, record: dict) -> ParsedArtifact:
    text, encoding = read_text(path)
    record["encoding"] = encoding
    events: list[dict] = []
    for index, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        timestamp = _TIMESTAMP.search(line)
        status = _STATUS.search(line)
        if timestamp is None and status is None:
            continue
        events.append(
            {
                "line": index,
                "timestamp": timestamp.group(1) if timestamp else "",
                "status": status.group(1).upper() if status else "",
                "raw": line.strip()[:240],
            }
        )
    stamps = sorted(event["timestamp"] for event in events if event["timestamp"])
    if stamps:
        record["period_covered"] = f"{stamps[0]} to {stamps[-1]}"
    if not events and record.get("status") == "readable":
        record["reason"] = "no timestamped status events recognised"
    return ParsedArtifact(
        artifact_id=record["artifact_id"],
        rel_path=record["path"],
        family="log",
        detected_type="log",
        text=text,
        encoding=encoding,
        events=events,
    )
