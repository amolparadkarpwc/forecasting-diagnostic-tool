"""Intake: unpack, identify, de-duplicate, safety-check, inventory."""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

from diag.handlers.base import ParsedArtifact, dispatch_handler
from diag.intake.dedupe import assign_ids, mark_duplicates
from diag.intake.identify import identify, is_archive
from diag.intake.inventory import empty_record
from diag.intake.safety import assess_model
from diag.intake.sort import sort_client_artifacts
from diag.intake.unpack import extract_gzip, extract_tar, extract_zip
from diag.util import MAX_BYTES, posix_path, sanitize_error, sha256_bytes

UNSUPPORTED = {
    "pdf": "PDF parsing is not enabled in this MVP",
    "pptx": "PowerPoint parsing is not enabled in this MVP",
    "xlsx": "Excel parsing is not enabled in this MVP",
    "parquet": "Parquet parsing is not enabled in this MVP",
}


def _version_group(path: str) -> str:
    stem = Path(path).stem.lower()
    stem = re.sub(r"[\s._-]*(v\d+|copy|\(\d+\)|\d{4}-\d{2}-\d{2})$", "", stem)
    return stem or Path(path).stem.lower()


def _iter_files(root: Path) -> list[Path]:
    files = [path for path in root.rglob("*") if path.is_file()]
    return sorted(files, key=lambda path: posix_path(str(path.relative_to(root))).lower())


def _stage_archive(path: Path, kind: str, dest: Path) -> tuple[list[dict], list[dict], str | None]:
    try:
        if kind == "zip":
            return (*extract_zip(path, dest), None)
        if kind == "tar":
            return (*extract_tar(path, dest), None)
        return (*extract_gzip(path, dest), None)
    except (zipfile.BadZipFile, tarfile_error(), OSError, EOFError, ValueError) as exc:
        return [], [], sanitize_error(exc)


def tarfile_error() -> type[BaseException]:
    import tarfile

    return tarfile.TarError


def _record_for_path(rel: str, abs_path: Path | None, data: bytes | None, reason: str | None = None) -> dict:
    record = empty_record(posix_path(rel))
    record["version_group"] = _version_group(rel)
    record["_abs"] = str(abs_path) if abs_path is not None else ""
    if reason:
        record["status"] = "unreadable"
        record["reason"] = reason
        record["size_bytes"] = 0 if data is None else len(data)
        if data:
            record["sha256"] = sha256_bytes(data)
        return record
    if data is None:
        record["status"] = "unreadable"
        record["reason"] = "file exceeds 50MB MVP limit"
        return record
    record["size_bytes"] = len(data)
    record["sha256"] = sha256_bytes(data)
    if len(data) == 0:
        record["status"] = "unreadable"
        record["reason"] = "empty file"
        return record
    detected, family, encoding = identify(abs_path, data)
    record["detected_type"] = detected
    record["family"] = family
    record["encoding"] = encoding
    return record


def collect(engagement: Path, allowlist: list[str]) -> tuple[list[dict], list[ParsedArtifact]]:
    """Sort client_artifacts/ into input/, then inventory and parse every readable file."""
    sort_client_artifacts(engagement)
    root = engagement / "input"
    if not root.exists():
        raise FileNotFoundError(f"no input folder at {root}")
    unpack_root = engagement / "work" / "unpacked"
    if unpack_root.exists():
        shutil.rmtree(unpack_root)
    unpack_root.mkdir(parents=True, exist_ok=True)

    staged: list[dict] = []
    for file in _iter_files(root):
        rel = posix_path(str(file.relative_to(root)))
        size = file.stat().st_size
        data = file.read_bytes() if size <= MAX_BYTES else None
        kind = None
        if data is not None and size <= MAX_BYTES:
            kind = is_archive(file, data)
        if kind:
            dest = unpack_root / rel.replace("/", "__")
            extracted, rejected, error = _stage_archive(file, kind, dest)
            archive_rec = _record_for_path(rel, file, data)
            if error:
                archive_rec["status"] = "unreadable"
                archive_rec["reason"] = error
                archive_rec["detected_type"] = kind
                archive_rec["family"] = "none"
            else:
                archive_rec["detected_type"] = kind
                archive_rec["family"] = "none"
                archive_rec["status"] = "readable"
                archive_rec["reason"] = f"extracted {len(extracted)} file(s)"
            staged.append(archive_rec)
            for item in extracted:
                member_rel = f"{rel}!/{item['member']}"
                member_data = Path(item["path"]).read_bytes()
                staged.append(_record_for_path(member_rel, Path(item["path"]), member_data))
            for item in rejected:
                member_rel = f"{rel}!/{item['member']}"
                rejected_rec = empty_record(member_rel)
                rejected_rec["status"] = "unreadable"
                rejected_rec["reason"] = item["reason"]
                rejected_rec["size_bytes"] = int(item.get("size") or 0)
                rejected_rec["version_group"] = _version_group(item["member"])
                staged.append(rejected_rec)
            continue
        staged.append(_record_for_path(rel, file, data, None if data is not None or size <= MAX_BYTES else "file exceeds 50MB MVP limit"))

    for record in staged:
        if record["status"] != "readable":
            continue
        if record["family"] == "model" or record["detected_type"] in {"pickle", "joblib", "onnx"}:
            abs_path = record.get("_abs")
            if abs_path:
                status, reason = assess_model(Path(abs_path), record["detected_type"], allowlist)
                record["status"] = status
                record["reason"] = reason
        elif record["detected_type"] in UNSUPPORTED:
            record["status"] = "manual_review"
            record["reason"] = UNSUPPORTED[record["detected_type"]]

    records = mark_duplicates(assign_ids(staged))
    parsed: list[ParsedArtifact] = []
    for record in records:
        if record["status"] == "duplicate":
            continue
        if record["status"] not in {"readable", "manual_review"}:
            continue
        if record["detected_type"] in UNSUPPORTED or record["family"] == "none":
            continue
        if record["status"] == "manual_review" and record["family"] != "model":
            continue
        abs_path = record.get("_abs") or ""
        if not abs_path:
            continue
        try:
            artifact = dispatch_handler(Path(abs_path), record)
        except Exception as exc:
            record["status"] = "unreadable"
            record["reason"] = sanitize_error(exc, engagement)
            continue
        if artifact is not None:
            parsed.append(artifact)
    parsed.sort(key=lambda artifact: artifact.artifact_id)
    return records, parsed
