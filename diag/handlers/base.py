"""Parsed artifact and handler dispatch."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ParsedArtifact:
    artifact_id: str
    rel_path: str
    family: str
    detected_type: str
    text: str = ""
    encoding: str = ""
    calls: list[dict] = field(default_factory=list)
    imports: list[dict] = field(default_factory=list)
    keys: dict[str, Any] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)
    data_format: str | None = None
    frame: Any = None
    sql_text: str = ""


def dispatch_handler(path: Path, record: dict) -> ParsedArtifact | None:
    from diag.handlers import code, configs, data, documents, logs, models

    detected = record.get("detected_type")
    family = record.get("family")
    if family == "model" or detected in {"pickle", "joblib", "onnx"}:
        return models.parse_model(path, record)
    if detected in {"python", "notebook", "sql", "r"} or family == "code":
        return code.parse_code(path, record)
    if family == "config" or detected in {"yaml", "json", "toml", "ini"}:
        return configs.parse_config(path, record)
    if family == "log" or detected == "log":
        return logs.parse_log(path, record)
    if family == "data" or detected == "csv":
        return data.parse_data(path, record)
    if family == "document" or detected in {
        "txt",
        "md",
        "docx",
        "vtt",
        "transcript",
        "png",
        "jpeg",
        "gif",
        "webp",
        "tiff",
    }:
        return documents.parse_document(path, record)
    return None
