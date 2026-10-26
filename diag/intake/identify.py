"""Identify a file by signature, then by a trial parse. The name is only a fallback."""

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
    if name.endswith(".tar.gz") or name.endswith(".tgz") or suffix == ".tar" or (
        len(data) >= 262 and data[257:262] == b"ustar"
    ):
        return "tar"
    if data.startswith(b"\x1f\x8b") or suffix == ".gz":
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


def _python_strength(text: str) -> str | None:
    """Return strong, weak, or None.

    An import, function, or class is strong. A bare assignment is weak because
    the same text can be a TOML or INI config.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    strong = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    if any(isinstance(node, strong) for node in ast.walk(tree)):
        return "strong"
    if any(isinstance(node, ast.Assign) for node in ast.walk(tree)):
        return "weak"
    return None


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

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--") or stripped.startswith("/*") or stripped.startswith("*"):
            continue
        return bool(re.match(r"(?i)(with|select|insert|update|delete|create|alter|drop)\b", stripped))
    return False


def _looks_like_toml(text: str) -> bool:
    import tomllib

    try:
        loaded = tomllib.loads(text)
    except Exception:
        return False
    return isinstance(loaded, dict) and bool(loaded)


def _looks_like_ini(text: str) -> bool:
    import configparser

    if "[" not in text or "=" not in text:
        return False
    parser = configparser.ConfigParser()
    try:
        parser.read_string(text)
    except configparser.Error:
        return False
    return bool(parser.sections())


def _looks_like_r(text: str) -> bool:
    import re

    return bool(re.search(r"(?m)^\s*(library|require)\s*\(", text) and re.search(r"<-", text))


def _looks_like_onnx(data: bytes) -> bool:
    sample = data[:8192].lower()
    return data.startswith(b"\x08") and b"onnx" in sample


_EXTENSION = {
    ".py": ("python", "code"),
    ".sql": ("sql", "code"),
    ".r": ("r", "code"),
    ".csv": ("csv", "data"),
    ".tsv": ("csv", "data"),
    ".yaml": ("yaml", "config"),
    ".yml": ("yaml", "config"),
    ".toml": ("toml", "config"),
    ".ini": ("ini", "config"),
    ".json": ("json", "config"),
    ".log": ("log", "log"),
    ".md": ("md", "document"),
    ".markdown": ("md", "document"),
    ".txt": ("txt", "document"),
    ".text": ("txt", "document"),
    ".vtt": ("vtt", "document"),
    ".ipynb": ("notebook", "code"),
    ".pkl": ("pickle", "model"),
    ".pickle": ("pickle", "model"),
    ".joblib": ("joblib", "model"),
    ".onnx": ("onnx", "model"),
}


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
    name = path.name.lower()
    if _looks_like_pickle(data):
        return "pickle", "model", ""
    if _looks_like_onnx(data):
        return "onnx", "model", ""
    if data.startswith(b"\x1f\x8b"):
        return "gz", "none", ""
    if len(data) >= 262 and data[257:262] == b"ustar":
        return "tar", "none", ""
    if data.startswith(b"PK") and not is_office_zip(path, data):
        try:
            with zipfile.ZipFile(path) as handle:
                handle.namelist()
            return "zip", "none", ""
        except (zipfile.BadZipFile, OSError):
            if suffix == ".zip":
                return "zip", "none", ""
    if suffix == ".zip" or name.endswith((".tar", ".tar.gz", ".tgz")):
        return "zip" if suffix == ".zip" else "tar", "none", ""

    text, encoding = decode_bytes(data) if data else ("", "")
    if not data:
        return "unknown", "none", encoding

    # Content decides the type for every file. The extension is used only when
    # the bytes are not a clear match, such as broken source or a placeholder model.
    if looks_like_vtt(text):
        return "vtt", "document", encoding
    if _looks_like_notebook(text):
        return "notebook", "code", encoding
    if _try_json(text):
        return "json", "config", encoding
    python_strength = _python_strength(text)
    if python_strength == "strong" or (python_strength == "weak" and suffix == ".py"):
        return "python", "code", encoding
    if _try_csv(text):
        return "csv", "data", encoding
    if _try_yaml(text):
        return "yaml", "config", encoding
    if _looks_like_toml(text):
        return "toml", "config", encoding
    if _looks_like_ini(text):
        return "ini", "config", encoding
    if python_strength == "weak":
        return "python", "code", encoding
    if _looks_like_sql(text):
        return "sql", "code", encoding
    if _looks_like_r(text):
        return "r", "code", encoding
    if _looks_like_log(text):
        return "log", "log", encoding
    if looks_like_transcript(text):
        return "transcript", "document", encoding
    if suffix in _EXTENSION:
        return (*_EXTENSION[suffix], encoding)
    if name.endswith(".gz"):
        return "gz", "none", encoding
    if text.strip():
        return "txt", "document", encoding
    return "unknown", "none", encoding
