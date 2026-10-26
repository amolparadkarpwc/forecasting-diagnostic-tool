"""Inventory images and, when Tesseract is installed locally, read their text.

No cloud vision API is called. A missing OCR binary leaves the file for review.
A corrupt image is unreadable and does not escape this handler.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from diag.handlers.base import ParsedArtifact

IMAGE_TYPES = frozenset({"png", "jpeg", "gif", "webp", "tiff"})
OCR_TIMEOUT_SECONDS = 20
_PNG = b"\x89PNG\r\n\x1a\n"


def image_kind(data: bytes) -> str | None:
    """Return png, jpeg, gif, webp, or tiff from the file signature."""
    if data.startswith(_PNG):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    return None


def image_is_readable(data: bytes, kind: str | None = None) -> bool:
    """True when the bytes are a complete-enough image of the detected kind."""
    try:
        detected = kind or image_kind(data)
        if detected == "png":
            return _png_ok(data)
        if detected == "jpeg":
            return data.startswith(b"\xff\xd8\xff") and len(data) >= 4 and b"\xff\xd9" in data[2:]
        if detected == "gif":
            return data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 13 and data.endswith(b"\x3b")
        if detected == "webp":
            return _webp_ok(data)
        if detected == "tiff":
            return _tiff_ok(data)
        return False
    except Exception:
        return False


def parse_image(path: Path, record: dict[str, Any]) -> ParsedArtifact | None:
    """Inventory one image. OCR text is returned only when local Tesseract runs."""
    try:
        data = path.read_bytes()
    except OSError:
        record["status"] = "unreadable"
        record["reason"] = "corrupt image"
        return None
    kind = image_kind(data) or str(record.get("detected_type") or "")
    if kind not in IMAGE_TYPES or not image_is_readable(data, kind):
        record["status"] = "unreadable"
        record["reason"] = "corrupt image"
        return None
    record["detected_type"] = kind
    record["family"] = "document"
    if shutil.which("tesseract") is None:
        record["status"] = "manual_review"
        record["reason"] = "image requires visual review; OCR not installed"
        return None
    try:
        text = _ocr(path)
    except subprocess.TimeoutExpired:
        record["status"] = "manual_review"
        record["reason"] = "image requires visual review; OCR timed out"
        return None
    except Exception:
        record["status"] = "manual_review"
        record["reason"] = "image requires visual review; OCR failed"
        return None
    record["status"] = "readable"
    record["encoding"] = "utf-8"
    sections = [{"title": "", "line": 1, "text": text}] if text else []
    return ParsedArtifact(
        artifact_id=str(record.get("artifact_id") or ""),
        rel_path=str(record.get("path") or ""),
        family="document",
        detected_type=kind,
        text=text,
        encoding="utf-8",
        sections=sections,
    )


def _ocr(path: Path) -> str:
    executable = shutil.which("tesseract")
    if not executable:
        raise FileNotFoundError("tesseract")
    absolute = str(path.resolve())
    with tempfile.TemporaryDirectory(prefix="diag-ocr-") as folder:
        completed = subprocess.run(
            [executable, absolute, "stdout"],
            cwd=folder,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=OCR_TIMEOUT_SECONDS,
            check=False,
        )
    raw = completed.stdout or b""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n").strip()
    if completed.returncode != 0 and not text:
        raise RuntimeError("tesseract failed")
    return text


def _png_ok(data: bytes) -> bool:
    if not data.startswith(_PNG):
        return False
    pos = 8
    seen_ihdr = False
    seen_iend = False
    for _ in range(10000):
        if pos + 8 > len(data):
            return False
        length = int.from_bytes(data[pos : pos + 4], "big")
        tag = data[pos + 4 : pos + 8]
        if pos + 12 + length > len(data):
            return False
        if not seen_ihdr:
            if tag != b"IHDR" or length != 13:
                return False
            seen_ihdr = True
        pos += 12 + length
        if tag == b"IEND":
            seen_iend = True
            break
    return seen_ihdr and seen_iend


def _webp_ok(data: bytes) -> bool:
    if len(data) < 12 or not data.startswith(b"RIFF") or data[8:12] != b"WEBP":
        return False
    size = int.from_bytes(data[4:8], "little")
    return 4 <= size and size + 8 <= len(data)


def _tiff_ok(data: bytes) -> bool:
    if len(data) < 8:
        return False
    if data.startswith(b"II*\x00"):
        offset = int.from_bytes(data[4:8], "little")
    elif data.startswith(b"MM\x00*"):
        offset = int.from_bytes(data[4:8], "big")
    else:
        return False
    return 8 <= offset < len(data)
