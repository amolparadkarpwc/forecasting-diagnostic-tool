"""Identify a file by signature, then by a trial parse. The extension is only a hint."""

from __future__ import annotations

import ast
import json
import zipfile
from pathlib import Path

from diag.handlers.images import image_kind
from diag.handlers.transcripts import looks_like_transcript, looks_like_vtt
from diag.util import decode_bytes


def _office_kind(path: Path) -> tuple[str, str] | None:
    try:
        with zipfile.ZipFile(path) as handle:
            names = handle.namelist()
    except (zipfile.BadZipFile, OSError):
        return None
    if any(name.startswith("word/") for name in names):
        return "docx", "document"
    if any(name.startswith("xl/") for name in names):
        return "xlsx", "data"
    if any(name.startswith("ppt/") for name in names):
        return "pptx", "document"
    return None


def is_office_zip(path: Path, data: bytes) -> bool:
    return data.startswith(b"PK") and _office_kind(path) is not None


def is_archive(path: Path, data: bytes) -> str | None:
    """Return zip, tar, or gz when the file should be unpacked. Office zips are not archives."""
    suffix = path.suffix.lower()
    name = path.name.lower()
    if data.startswith(b"PK") and not is_office_zip(path, data):
        if suffix in {".docx", ".xlsx", ".pptx", ".xlsm"}:
            return None
        try:
            with zipfile.ZipFile(path) as handle:
                handle.namelist()
            return "zip"
        except (zipfile.BadZipFile, OSError):
            return "zip" if suffix == ".zip" else None
    if name.endswith(".tar.gz") or name.endswith(".tgz") or suffix == ".tar":
        return "tar"
    if suffix == ".gz":
        return "gz"
    return None


def _looks_like_pickle(data: bytes) -> bool:
    return len(data) >= 2 and data[0] == 0x80 and data[1] <= 5


def _looks_like_notebook(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped.startswith("{"):
        return False
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and "cells" in payload and "nbformat" in payload


def _try_json(text: str) -> bool:
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return False
    try:
        json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return True


def _try_python(text: str) -> bool:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    interesting = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign)
    return any(isinstance(node, interesting) for node in ast.walk(tree))


def _try_csv(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()][:30]
    if len(lines) < 2:
        return False
    for delimiter in (",", "\t", ";", "|"):
        counts = [line.count(delimiter) for line in lines]
        if counts[0] >= 1 and all(count == counts[0] for count in counts):
            return True
    return False


def _try_yaml(text: str) -> bool:
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    try:
        loaded = yaml.load(text, Loader=Loader)
    except Exception:
        return False
    return isinstance(loaded, (dict, list))


def _looks_like_log(text: str) -> bool:
    import re

    lines = [line for line in text.splitlines() if line.strip()][:40]
    if len(lines) < 2:
        return False
    hits = 0
    for line in lines:
        if re.search(r"\d{4}-\d{2}-\d{2}", line) and re.search(
            r"\b(SUCCESS|FAILED|FAILURE|ERROR|WARN|WARNING|INFO|OK)\b", line, re.I
        ):
            hits += 1
    return hits >= 2 and hits / len(lines) >= 0.5


def _looks_like_sql(text: str) -> bool:
    import re

    return bool(re.search(r"\b(select|insert|update|delete|join|with)\b", text, re.I))


def identify(path: Path, data: bytes) -> tuple[str, str, str]:
    """Return detected_type, family, encoding."""
    if data.startswith(b"%PDF"):
        return "pdf", "document", ""
    if data.startswith(b"PAR1"):
        return "parquet", "data", ""
    if data.startswith(b"PK"):
        office = _office_kind(path)
        if office is not None:
            return office[0], office[1], ""
    kind = image_kind(data)
    if kind is not None:
        return kind, "document", ""
    suffix = path.suffix.lower()
    if _looks_like_pickle(data) or suffix in {".pkl", ".pickle"}:
        return "pickle", "model", ""
    if suffix == ".joblib":
        return "joblib", "model", ""
    if suffix == ".onnx":
        return "onnx", "model", ""

    if suffix == ".zip":
        return "zip", "none", ""
    if path.name.lower().endswith((".tar", ".tar.gz", ".tgz")):
        return "tar", "none", ""

    text, encoding = decode_bytes(data) if data else ("", "")
    if not data:
        return "unknown", "none", encoding

    # WEBVTT is a transcript even when the extension is .txt. Speaker lines only
    # override plain-text extensions so code and configs keep their own trials.
    if looks_like_vtt(text) or suffix == ".vtt":
        return "vtt", "document", encoding
    if suffix in {"", ".txt", ".text", ".md", ".markdown"} and looks_like_transcript(text):
        return "transcript", "document", encoding

    if _looks_like_notebook(text) or suffix == ".ipynb":
        return "notebook", "code", encoding

    ext_first = {
        ".py": ("python", "code"),
        ".sql": ("sql", "code"),
        ".r": ("r", "code"),
        ".csv": ("csv", "data"),
        ".tsv": ("csv", "data"),
        ".yaml": ("yaml", "config"),
        ".yml": ("yaml", "config"),
        ".toml": ("toml", "config"),
        ".ini": ("ini", "config"),
        ".log": ("log", "log"),
        ".md": ("md", "document"),
        ".markdown": ("md", "document"),
        ".txt": ("txt", "document"),
    }

    # Content trials. A labelled extension still wins when the trial is ambiguous,
    # but a clear content match overrides a missing or generic extension.
    if suffix == ".json" or (suffix not in ext_first and _try_json(text)):
        if suffix == ".json" or _try_json(text):
            return "json", "config", encoding
    if suffix == ".py" or (suffix not in {".md", ".txt", ".log"} and _try_python(text)):
        return "python", "code", encoding
    if suffix in {".csv", ".tsv"} or (suffix not in ext_first and _try_csv(text)):
        return "csv", "data", encoding
    if suffix in {".yaml", ".yml"} or (suffix not in ext_first and _try_yaml(text)):
        return "yaml", "config", encoding
    if suffix == ".sql" or (suffix not in ext_first and _looks_like_sql(text)):
        return "sql", "code", encoding
    if suffix == ".log" or _looks_like_log(text):
        return "log", "log", encoding
    if suffix in ext_first:
        detected, family = ext_first[suffix]
        if detected == "txt" and _looks_like_log(text):
            return "log", "log", encoding
        return detected, family, encoding
    if text.strip():
        return "txt", "document", encoding
    return "unknown", "none", encoding
