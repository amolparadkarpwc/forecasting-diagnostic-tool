"""Small shared helpers. No client code is executed from here."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


MAX_BYTES = 50 * 1024 * 1024


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def decode_bytes(data: bytes) -> tuple[str, str]:
    encoding = "latin-1"
    text = ""
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            text = data.decode(enc)
            encoding = "utf-8" if enc == "utf-8-sig" else enc
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("latin-1")
        encoding = "latin-1"
    return text.replace("\r\n", "\n").replace("\r", "\n"), encoding


def read_text(path: Path) -> tuple[str, str]:
    return decode_bytes(path.read_bytes())


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def posix_path(value: str) -> str:
    return value.replace("\\", "/")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def round_score(value: float | None) -> float | None:
    if value is None:
        return None
    return float(f"{float(value):.2f}")


def round_measure(value: float | None) -> float | None:
    if value is None:
        return None
    return float(f"{float(value):.6f}")


def sanitize_error(exc: BaseException, root: Path | None = None) -> str:
    message = f"{type(exc).__name__}: {exc}"
    if root is not None:
        for variant in {str(root), str(root.resolve())}:
            message = message.replace(variant, ".")
    return message[:300]


def strip_private(record: dict) -> dict:
    return {key: value for key, value in record.items() if not str(key).startswith("_")}
