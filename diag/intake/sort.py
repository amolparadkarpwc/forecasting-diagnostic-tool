"""Copy a mixed client dump into handler folders under input/."""

from __future__ import annotations

import shutil
from pathlib import Path

from diag.intake.identify import identify, is_archive
from diag.intake.unpack import extract_gzip, extract_tar, extract_zip
from diag.util import MAX_BYTES, posix_path

CLIENT_DIR = "client_artifacts"

# One folder per handler. The client does not choose these.
BUCKETS = (
    "code",
    "config",
    "data",
    "documents",
    "logs",
    "models",
    "images",
    "transcripts",
    "other",
)

_FAMILY_BUCKET = {
    "code": "code",
    "config": "config",
    "data": "data",
    "log": "logs",
    "model": "models",
    "document": "documents",
}

_IMAGE_TYPES = {"png", "jpeg", "gif", "webp", "tiff"}
_TRANSCRIPT_TYPES = {"vtt", "transcript"}


def bucket_for(detected: str, family: str) -> str:
    """Return the input/ subfolder for a file the tool has identified."""
    if detected in _TRANSCRIPT_TYPES:
        return "transcripts"
    if detected in _IMAGE_TYPES:
        return "images"
    return _FAMILY_BUCKET.get(family, "other")


def ensure_layout(engagement: Path) -> None:
    """Create the dump folder and the sorted input folders."""
    (engagement / CLIENT_DIR).mkdir(parents=True, exist_ok=True)
    input_root = engagement / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    for name in BUCKETS:
        (input_root / name).mkdir(exist_ok=True)


def _place(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.is_file() and dest.read_bytes() == src.read_bytes():
        return
    shutil.copy2(src, dest)


def _sorted_dest(input_root: Path, bucket: str, relative: str) -> Path:
    return input_root / bucket / relative


def _sort_file(path: Path, placed_as: str, input_root: Path, unpack_root: Path) -> None:
    size = path.stat().st_size
    data = path.read_bytes() if size <= MAX_BYTES else None
    kind = is_archive(path, data) if data is not None else None
    if not kind:
        bucket = "other" if data is None else bucket_for(*identify(path, data)[:2])
        _place(path, _sorted_dest(input_root, bucket, placed_as))
        return
    dest = unpack_root / placed_as.replace("/", "__")
    try:
        if kind == "zip":
            extracted, _rejected = extract_zip(path, dest)
        elif kind == "tar":
            extracted, _rejected = extract_tar(path, dest)
        else:
            extracted, _rejected = extract_gzip(path, dest)
    except (OSError, ValueError):
        _place(path, _sorted_dest(input_root, "other", placed_as))
        return
    if not extracted:
        _place(path, _sorted_dest(input_root, "other", placed_as))
        return
    for item in extracted:
        member_rel = posix_path(item["member"])
        _sort_file(Path(item["path"]), f"{placed_as}/{member_rel}", input_root, unpack_root)


def sort_client_artifacts(engagement: Path) -> None:
    """Copy client_artifacts/ into input/<handler>/ without removing the dump."""
    ensure_layout(engagement)
    source = engagement / CLIENT_DIR
    if not source.exists():
        return
    unpack_root = engagement / "work" / "sorted"
    if unpack_root.exists():
        shutil.rmtree(unpack_root)
    unpack_root.mkdir(parents=True, exist_ok=True)
    files = [path for path in source.rglob("*") if path.is_file() and not path.is_symlink()]
    for path in sorted(files, key=lambda item: posix_path(str(item.relative_to(source))).lower()):
        relative = posix_path(str(path.relative_to(source)))
        _sort_file(path, relative, engagement / "input", unpack_root)
