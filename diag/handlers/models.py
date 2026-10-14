"""Model handler. Records the safety-scan reason and never unpickles the file."""

from __future__ import annotations

from pathlib import Path

from diag.handlers.base import ParsedArtifact


def parse_model(path: Path, record: dict) -> ParsedArtifact:
    # The bytes are not deserialised. Intake has already scanned them with pickletools.
    del path
    return ParsedArtifact(
        artifact_id=record["artifact_id"],
        rel_path=record["path"],
        family="model",
        detected_type=record.get("detected_type") or "pickle",
        text=record.get("reason") or "",
    )
