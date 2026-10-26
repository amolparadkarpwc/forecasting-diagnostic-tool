"""Check the fields the results, evidence, and inventory contracts require."""

from __future__ import annotations


def _require(obj: dict, fields: list[str], label: str) -> None:
    missing = [field for field in fields if field not in obj]
    if missing:
        raise ValueError(f"{label} missing {', '.join(missing)}")


def validate_inventory(records: list) -> None:
    fields = [
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
    if not isinstance(records, list):
        raise ValueError("inventory must be a list")
    for record in records:
        _require(record, fields, f"inventory {record.get('artifact_id', '?')}")


def validate_evidence(document: dict) -> None:
    _require(document, ["pack_version", "engine_version", "records"], "evidence log")
    fields = [
        "record_id",
        "diagnostic_id",
        "signal_id",
        "source",
        "handler",
        "block",
        "fact",
        "values",
        "evidence_level",
        "match_strength",
        "status",
        "owner_diagnostic",
        "model_ref",
        "review",
        "pack_version",
    ]
    for record in document["records"]:
        _require(record, fields, f"evidence {record.get('record_id', '?')}")
        _require(record["source"], ["artifact_id", "file", "location"], record.get("record_id", "source"))
        _require(record["source"]["location"], ["kind", "value"], record.get("record_id", "location"))


def validate_results(document: dict) -> None:
    _require(
        document,
        [
            "engagement",
            "versions",
            "artifacts_shared",
            "artifacts_not_shared",
            "diagnostics",
            "areas",
            "overall",
            "coverage",
            "measured_view",
            "targeted_request",
            "root_causes",
            "actions",
            "sign_off",
        ],
        "results",
    )
    _require(document["versions"], ["pack", "engine", "python"], "versions")
    _require(document["overall"], ["score", "maturity", "verdict", "verdict_reason", "failed_gates"], "overall")
