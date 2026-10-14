"""SHA-256 de-duplication. The first sorted path stays readable."""

from __future__ import annotations


def assign_ids(records: list[dict]) -> list[dict]:
    ordered = sorted(records, key=lambda record: (record.get("path") or "", record.get("sha256") or ""))
    for index, record in enumerate(ordered, start=1):
        record["artifact_id"] = f"A{index:03d}"
    return ordered


def mark_duplicates(records: list[dict]) -> list[dict]:
    seen: dict[str, str] = {}
    for record in records:
        digest = record.get("sha256") or ""
        if record.get("status") == "unreadable" or not digest:
            continue
        prior = seen.get(digest)
        if prior is not None:
            record["status"] = "duplicate"
            record["reason"] = f"duplicate of {prior}"
        else:
            seen[digest] = record["artifact_id"]
    return records
