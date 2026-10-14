"""Walk an engagement input folder, unpack archives, and inventory files.

Model files are hashed and quarantined. They are never unpickled or loaded.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

MAX_ZIP_DEPTH = 5
MAX_ZIP_MEMBERS = 1000
MAX_MEMBER_BYTES = 20_000_000

TEXT_TYPES: dict[str, tuple[str, str]] = {
    ".py": ("python", "code"),
    ".yaml": ("yaml", "config"),
    ".yml": ("yaml", "config"),
    ".json": ("json", "config"),
    ".csv": ("csv", "data"),
    ".md": ("markdown", "document"),
    ".txt": ("text", "document"),
    ".log": ("log", "log"),
}

MODEL_TYPES: dict[str, str] = {
    ".pkl": "pickle",
    ".pickle": "pickle",
    ".joblib": "joblib",
    ".onnx": "onnx",
}

_DRIVE = re.compile(r"^[A-Za-z]:")


@dataclass
class Artifact:
    """One inventoried file."""

    path: str
    sha256: str
    size_bytes: int
    detected_type: str
    family: str
    encoding: str
    period_covered: str
    status: str
    reason: str
    version_group: str = ""
    artifact_id: str = ""
    abs_path: Path | None = None

    def to_dict(self) -> dict[str, object]:
        """Public inventory fields."""
        return {
            "artifact_id": self.artifact_id,
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "detected_type": self.detected_type,
            "family": self.family,
            "encoding": self.encoding,
            "period_covered": self.period_covered,
            "status": self.status,
            "reason": self.reason,
            "version_group": self.version_group,
        }


def collect_artifacts(input_dir: Path, work_dir: Path) -> list[Artifact]:
    """Inventory ``input_dir``, unpacking zip files under ``work_dir``."""
    input_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    pending: list[tuple[Path, str, int]] = []
    for path in _iter_files(input_dir):
        pending.append((path, path.relative_to(input_dir).as_posix(), 0))
    artifacts: list[Artifact] = []
    seen: set[Path] = set()
    while pending:
        path, display, depth = pending.pop(0)
        try:
            real = path.resolve()
        except OSError:
            artifacts.append(_unreadable(display, "unreadable: OSError", path))
            continue
        if real in seen:
            continue
        seen.add(real)
        artifact = inspect_file(path, display)
        artifacts.append(artifact)
        if artifact.detected_type != "zip" or artifact.status != "readable":
            continue
        if depth >= MAX_ZIP_DEPTH:
            artifact.status = "unreadable"
            artifact.reason = "zip nesting limit"
            continue
        dest = work_dir / f"unpack-{len(artifacts):03d}"
        try:
            extracted, rejected = unpack_zip(path, dest, display)
        except (zipfile.BadZipFile, OSError):
            artifact.status = "unreadable"
            artifact.reason = "unreadable: BadZipFile"
            continue
        artifacts.extend(rejected)
        for child, child_display in extracted:
            pending.append((child, child_display, depth + 1))
    artifacts.sort(key=lambda item: item.path)
    for index, artifact in enumerate(artifacts, start=1):
        artifact.artifact_id = f"A{index:03d}"
    return artifacts


def inspect_file(path: Path, display_path: str) -> Artifact:
    """Hash and classify one file. Model bytes are never decoded as models."""
    try:
        raw = path.read_bytes()
    except OSError:
        size = path.stat().st_size if path.exists() else 0
        return _unreadable(display_path, "unreadable: OSError", path, size)
    digest = hashlib.sha256(raw).hexdigest()
    size = len(raw)
    suffix = path.suffix.lower()
    if suffix in MODEL_TYPES:
        return Artifact(
            path=display_path,
            sha256=digest,
            size_bytes=size,
            detected_type=MODEL_TYPES[suffix],
            family="model",
            encoding="",
            period_covered="",
            status="quarantined",
            reason="model file quarantined and was not loaded",
            abs_path=path,
        )
    if suffix == ".zip":
        return Artifact(
            path=display_path,
            sha256=digest,
            size_bytes=size,
            detected_type="zip",
            family="none",
            encoding="",
            period_covered="",
            status="readable",
            reason="unpacked",
            abs_path=path,
        )
    if suffix not in TEXT_TYPES:
        return Artifact(
            path=display_path,
            sha256=digest,
            size_bytes=size,
            detected_type="unknown",
            family="none",
            encoding="",
            period_covered="",
            status="manual_review",
            reason="unrecognised file type",
            abs_path=path,
        )
    try:
        raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        detected, family = TEXT_TYPES[suffix]
        return Artifact(
            path=display_path,
            sha256=digest,
            size_bytes=size,
            detected_type=detected,
            family=family,
            encoding="",
            period_covered="",
            status="unreadable",
            reason="could not decode as utf-8",
            abs_path=path,
        )
    detected, family = TEXT_TYPES[suffix]
    return Artifact(
        path=display_path,
        sha256=digest,
        size_bytes=size,
        detected_type=detected,
        family=family,
        encoding="utf-8",
        period_covered="",
        status="readable",
        reason="",
        abs_path=path,
    )


def unpack_zip(
    archive: Path, dest: Path, display_prefix: str
) -> tuple[list[tuple[Path, str]], list[Artifact]]:
    """Extract zip members that stay inside ``dest``. Escaping paths are refused."""
    extracted: list[tuple[Path, str]] = []
    rejected: list[Artifact] = []
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        if len(members) > MAX_ZIP_MEMBERS:
            rejected.append(
                _unreadable(
                    f"{display_prefix}/(rejected-00)",
                    "zip member limit",
                    None,
                )
            )
            return extracted, rejected
        reject_index = 0
        for info in members:
            kind, parts = classify_member(info.filename)
            if kind == "dir":
                continue
            if kind == "escape":
                reject_index += 1
                rejected.append(
                    _rejected_member(zf, info, display_prefix, reject_index)
                )
                continue
            if info.file_size > MAX_MEMBER_BYTES:
                reject_index += 1
                rejected.append(
                    _unreadable(
                        f"{display_prefix}/(rejected-{reject_index:02d})",
                        "zip member too large",
                        None,
                        info.file_size,
                    )
                )
                continue
            target = dest.joinpath(*parts)
            try:
                target.resolve().relative_to(dest.resolve())
            except ValueError:
                reject_index += 1
                rejected.append(
                    _rejected_member(zf, info, display_prefix, reject_index)
                )
                continue
            try:
                payload = zf.read(info)
            except (zipfile.BadZipFile, OSError, RuntimeError):
                reject_index += 1
                rejected.append(
                    _unreadable(
                        f"{display_prefix}/(rejected-{reject_index:02d})",
                        "unreadable: zip member",
                        None,
                    )
                )
                continue
            if len(payload) > MAX_MEMBER_BYTES:
                reject_index += 1
                rejected.append(
                    _unreadable(
                        f"{display_prefix}/(rejected-{reject_index:02d})",
                        "zip member too large",
                        None,
                        len(payload),
                    )
                )
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            child_display = "/".join([display_prefix, *parts])
            extracted.append((target, child_display))
    return extracted, rejected


def classify_member(member: str) -> tuple[str, list[str]]:
    """Return ``dir``, ``ok``, or ``escape`` plus any safe path parts."""
    name = member.replace("\\", "/")
    if name == "" or name.endswith("/"):
        return "dir", []
    if name.startswith("/") or _DRIVE.match(name):
        return "escape", []
    parts = [part for part in name.split("/") if part not in ("", ".")]
    if not parts:
        return "dir", []
    if any(part == ".." or _DRIVE.match(part) or ":" in part for part in parts):
        return "escape", []
    return "ok", parts


def _rejected_member(
    zf: zipfile.ZipFile, info: zipfile.ZipInfo, display_prefix: str, index: int
) -> Artifact:
    """Record a refused member without writing it to disk."""
    try:
        payload = zf.read(info)
        digest = hashlib.sha256(payload).hexdigest()
        size = len(payload)
    except (zipfile.BadZipFile, OSError, RuntimeError):
        digest = ""
        size = int(info.file_size)
    return _unreadable(
        f"{display_prefix}/(rejected-{index:02d})",
        "path escapes the folder",
        None,
        size,
        digest,
    )


def _unreadable(
    display: str,
    reason: str,
    path: Path | None,
    size: int = 0,
    digest: str = "",
) -> Artifact:
    return Artifact(
        path=display,
        sha256=digest,
        size_bytes=size,
        detected_type="unknown",
        family="none",
        encoding="",
        period_covered="",
        status="unreadable",
        reason=reason,
        abs_path=path,
    )


def _iter_files(root: Path) -> list[Path]:
    files = [path for path in root.rglob("*") if path.is_file()]
    files.sort(key=lambda path: path.relative_to(root).as_posix())
    return files
