"""Unpack zip and tar archives without allowing path escape."""

from __future__ import annotations

import gzip
import tarfile
import zipfile
from pathlib import Path

from diag.util import MAX_BYTES, posix_path


def is_unsafe_member(name: str) -> bool:
    normalised = name.replace("\\", "/")
    if not normalised or normalised.startswith("/") or normalised.startswith("//"):
        return True
    if len(normalised) >= 2 and normalised[1] == ":":
        return True
    parts = [part for part in normalised.split("/") if part not in {"", "."}]
    return any(part == ".." for part in parts)


def _inside(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_symlink_zip(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == 0o120000


def extract_zip(archive: Path, dest: Path) -> tuple[list[dict], list[dict]]:
    """Return (extracted files, rejected members). Never writes outside dest."""
    extracted: list[dict] = []
    rejected: list[dict] = []
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
        members = sorted(handle.infolist(), key=lambda item: item.filename)
        for info in members:
            name = info.filename
            rel = posix_path(name).rstrip("/")
            if not rel:
                continue
            reason = None
            if is_unsafe_member(name) or _is_symlink_zip(info):
                reason = "path escapes the extract folder"
            target = dest / rel
            if reason is None and not _inside(dest, target):
                reason = "path escapes the extract folder"
            if reason is not None:
                rejected.append({"member": rel, "reason": reason, "size": info.file_size})
                continue
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if info.file_size > MAX_BYTES:
                rejected.append({"member": rel, "reason": "file exceeds 50MB MVP limit", "size": info.file_size})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with handle.open(info) as src:
                data = src.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                rejected.append({"member": rel, "reason": "file exceeds 50MB MVP limit", "size": len(data)})
                continue
            target.write_bytes(data)
            extracted.append({"path": target, "member": rel, "size": len(data)})
    return extracted, rejected


def _reject_tar(member: tarfile.TarInfo) -> str | None:
    if member.issym() or member.islnk():
        return "path escapes the extract folder"
    if is_unsafe_member(member.name):
        return "path escapes the extract folder"
    if member.size > MAX_BYTES:
        return "file exceeds 50MB MVP limit"
    return None


def extract_tar(archive: Path, dest: Path) -> tuple[list[dict], list[dict]]:
    extracted: list[dict] = []
    rejected: list[dict] = []
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as handle:
        members = sorted(handle.getmembers(), key=lambda item: item.name)
        for member in members:
            rel = posix_path(member.name).rstrip("/")
            if not rel:
                continue
            reason = _reject_tar(member)
            target = dest / rel
            if reason is None and not _inside(dest, target):
                reason = "path escapes the extract folder"
            if reason is not None:
                rejected.append({"member": rel, "reason": reason, "size": member.size})
                continue
            if not member.isfile():
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                continue
            source = handle.extractfile(member)
            if source is None:
                rejected.append({"member": rel, "reason": "archive member could not be read", "size": member.size})
                continue
            data = source.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                rejected.append({"member": rel, "reason": "file exceeds 50MB MVP limit", "size": len(data)})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            extracted.append({"path": target, "member": rel, "size": len(data)})
    return extracted, rejected


def extract_gzip(archive: Path, dest: Path) -> tuple[list[dict], list[dict]]:
    """Decompress a single-file gzip into dest using the archive stem as the name."""
    dest.mkdir(parents=True, exist_ok=True)
    stem = archive.name[:-3] if archive.name.lower().endswith(".gz") else archive.stem
    if is_unsafe_member(stem):
        return [], [{"member": stem, "reason": "path escapes the extract folder", "size": 0}]
    target = dest / stem
    if not _inside(dest, target):
        return [], [{"member": stem, "reason": "path escapes the extract folder", "size": 0}]
    with gzip.open(archive, "rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        return [], [{"member": stem, "reason": "file exceeds 50MB MVP limit", "size": len(data)}]
    target.write_bytes(data)
    return [{"path": target, "member": stem, "size": len(data)}], []
