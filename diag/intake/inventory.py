"""Inventory records and writers."""

from __future__ import annotations

import csv
from pathlib import Path

from diag.util import strip_private, write_json


FIELDS = [
    "artifact_id",
    "path",
    "sha256",
    "size_bytes",
    "detected_type",
    "family",
    "encoding",
    "period_covered",
    "status",
    "reason",
    "version_group",
]


def empty_record(path: str) -> dict:
    return {
        "artifact_id": "",
        "path": path,
        "sha256": "",
        "size_bytes": 0,
        "detected_type": "unknown",
        "family": "none",
        "encoding": "",
        "period_covered": "",
        "status": "readable",
        "reason": "",
        "version_group": "",
    }


def write_inventory(path_stem: Path, records: list[dict]) -> None:
    public = [strip_private(record) for record in records]
    write_json(path_stem.with_suffix(".json"), public)
    csv_path = path_stem.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for record in public:
            writer.writerow({field: record.get(field, "") for field in FIELDS})
