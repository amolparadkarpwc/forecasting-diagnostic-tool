"""Run intake, detectors, scoring, and report writing for one engagement."""

from __future__ import annotations

import csv
import importlib.metadata
import platform
import shutil
from pathlib import Path
from typing import Any

from diag import __version__
from diag.blocks import BLOCKS, Match
from diag.dashboard import render_dashboard
from diag.intake import Artifact, collect_artifacts
from diag.jsonutil import read_json, write_json
from diag.masking import mask_obj, mask_text
from diag.packload import PackError, load_pack
from diag.parsers import ParseError, ParsedFile, parse_artifact
from diag.scoring import maturity_for, score_signals, status_for, verdict_for, weighted_average

ASSESSED_DATE = "2026-01-15"
INVENTORY_FIELDS = [
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
_LEVEL_RANK = {"Verified": 3, "Inferred": 2, "Attested": 1}


def init_engagement(engagement_dir: Path) -> Path:
    """Create input, work, and output folders and a frozen engagement config."""
    engagement_dir.mkdir(parents=True, exist_ok=True)
    for name in ("input", "work", "output"):
        (engagement_dir / name).mkdir(exist_ok=True)
    config_path = engagement_dir / "engagement.yaml"
    if not config_path.exists():
        config_path.write_text(_config_text(engagement_dir.name), encoding="utf-8", newline="\n")
    return engagement_dir


def run_engagement(engagement_dir: Path, pack_dir: Path) -> dict[str, Any]:
    """Inventory inputs, score the pack, and write masked output files."""
    engagement_dir = engagement_dir.resolve()
    config = load_config(engagement_dir)
    pack = load_pack(pack_dir)
    input_dir = engagement_dir / "input"
    work_dir = engagement_dir / "work"
    output_dir = engagement_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    artifacts = collect_artifacts(input_dir, work_dir / "unpacked")
    parsed = _parse_all(artifacts)
    records = _collect_records(parsed, pack)
    results = _build_results(config, pack, artifacts, records)
    terms = list(config.get("masking") or [])
    masked_artifacts = mask_obj([artifact.to_dict() for artifact in artifacts], terms)
    masked_records = mask_obj(records, terms)
    masked_results = mask_obj(results, terms)
    masked_results["evidence"] = masked_records
    _write_inventory(output_dir, masked_artifacts)
    write_json(output_dir / "evidence_log.json", {"pack_version": pack["version"], "records": masked_records})
    public_results = {key: value for key, value in masked_results.items() if key != "evidence"}
    write_json(output_dir / "results.json", public_results)
    return masked_results


def report_engagement(engagement_dir: Path) -> Path:
    """Write ``output/dashboard.html`` from the saved results and evidence log."""
    engagement_dir = engagement_dir.resolve()
    output_dir = engagement_dir / "output"
    results_path = output_dir / "results.json"
    if not results_path.is_file():
        raise FileNotFoundError(f"results not found: {results_path}")
    results = read_json(results_path)
    evidence_path = output_dir / "evidence_log.json"
    records: list[dict[str, Any]] = []
    if evidence_path.is_file():
        records = list(read_json(evidence_path).get("records") or [])
    config = load_config(engagement_dir)
    terms = list(config.get("masking") or [])
    results["evidence"] = mask_obj(records, terms)
    html = mask_text(render_dashboard(results), terms)
    dashboard = output_dir / "dashboard.html"
    dashboard.write_text(html, encoding="utf-8", newline="\n")
    return dashboard


def load_config(engagement_dir: Path) -> dict[str, Any]:
    """Read the engagement config written by init."""
    import yaml

    path = engagement_dir / "engagement.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"engagement config not found: {path}. Run diag init first.")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise PackError("engagement.yaml must be a mapping")
    masking = loaded.get("masking") or []
    if not isinstance(masking, list):
        raise PackError("engagement masking must be a list")
    loaded["masking"] = [str(item) for item in masking]
    loaded.setdefault("assessed_date", ASSESSED_DATE)
    loaded.setdefault("id", engagement_dir.name)
    loaded.setdefault("client_alias", "Demo")
    loaded.setdefault("solution", "Forecasting solution")
    return loaded


def _config_text(name: str) -> str:
    safe = name.replace('"', "")
    return (
        f'id: "{safe}"\n'
        'client_alias: "Demo"\n'
        'solution: "Forecasting solution"\n'
        f'assessed_date: "{ASSESSED_DATE}"\n'
        "masking: []\n"
    )


def _parse_all(artifacts: list[Artifact]) -> list[ParsedFile]:
    parsed: list[ParsedFile] = []
    for artifact in artifacts:
        if artifact.status != "readable" or artifact.family in {"model", "none"}:
            continue
        if artifact.abs_path is None:
            artifact.status = "unreadable"
            artifact.reason = "unreadable: missing file"
            continue
        try:
            parsed.append(parse_artifact(artifact))
        except ParseError as exc:
            artifact.status = "unreadable"
            artifact.reason = exc.reason
        except Exception:
            artifact.status = "unreadable"
            artifact.reason = "unreadable"
    return parsed


def _collect_records(parsed: list[ParsedFile], pack: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {artifact.artifact.artifact_id: artifact for artifact in parsed}
    records: list[dict[str, Any]] = []
    for entry in pack["entries"]:
        for signal_id, signal in entry["signals"].items():
            for detector in signal.get("detectors") or []:
                block_name = str(detector["type"])
                block = BLOCKS[block_name]
                family = detector.get("file_family")
                params = detector.get("params") or {}
                for item in parsed:
                    if family and item.artifact.family != family:
                        continue
                    for match in block(item, params):
                        records.append(
                            _record(
                                entry,
                                signal_id,
                                signal,
                                detector,
                                block_name,
                                item,
                                match,
                                pack["version"],
                            )
                        )
    del by_id
    records.sort(key=_record_sort_key)
    for index, record in enumerate(records, start=1):
        record["record_id"] = f"R{index:05d}"
    return records


def _record(
    entry: dict[str, Any],
    signal_id: str,
    signal: dict[str, Any],
    detector: dict[str, Any],
    block_name: str,
    parsed: ParsedFile,
    match: Match,
    pack_version: str,
) -> dict[str, Any]:
    level = str(detector.get("level") or "Verified")
    if parsed.artifact.family == "document":
        level = "Attested"
    return {
        "record_id": "",
        "diagnostic_id": entry["id"],
        "signal_id": signal_id,
        "source": {
            "artifact_id": parsed.artifact.artifact_id,
            "file": parsed.artifact.path,
            "location": {"kind": match.location_kind, "value": match.location_value},
        },
        "handler": parsed.artifact.family,
        "block": block_name,
        "fact": match.fact,
        "values": match.values,
        "evidence_level": level,
        "match_strength": match.match_strength,
        "status": "auto_accepted",
        "owner_diagnostic": signal.get("owner") or entry["id"],
        "model_ref": None,
        "review": {"by": None, "at": None, "decision": None, "reason": None},
        "pack_version": pack_version,
    }


def _record_sort_key(record: dict[str, Any]) -> tuple[str, ...]:
    source = record["source"]
    location = source["location"]
    return (
        source["file"],
        record["diagnostic_id"],
        record["signal_id"],
        location["kind"],
        str(location["value"]),
        record["fact"],
    )


def _build_results(
    config: dict[str, Any],
    pack: dict[str, Any],
    artifacts: list[Artifact],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    manifest = pack["manifest"]
    green = float(manifest.get("status_green", 67))
    amber = float(manifest.get("status_amber", 50))
    ready = float(manifest.get("verdict_ready", 67))
    gaps = float(manifest.get("verdict_gaps", 50))
    gate_floor = float(manifest.get("gate_floor", 40))
    diagnostics = [
        _score_diagnostic(entry, records, green, amber, gate_floor, attested=True)
        for entry in pack["entries"]
    ]
    measured = [
        _score_diagnostic(entry, records, green, amber, gate_floor, attested=False)
        for entry in pack["entries"]
    ]
    areas = _areas(diagnostics, manifest.get("areas") or [], green, amber)
    overall = _overall(diagnostics, manifest.get("maturity") or [], ready, gaps, gate_floor)
    measured_overall = _overall(measured, manifest.get("maturity") or [], ready, gaps, gate_floor)
    return {
        "engagement": {
            "id": config.get("id"),
            "client_alias": config.get("client_alias"),
            "solution": config.get("solution"),
            "assessed_date": config.get("assessed_date"),
        },
        "versions": {
            "pack": pack["version"],
            "engine": __version__,
            "python": platform.python_version(),
            "pyyaml": _package_version("PyYAML"),
        },
        "artifacts_shared": [artifact.to_dict() for artifact in artifacts],
        "artifacts_not_shared": [],
        "diagnostics": diagnostics,
        "areas": areas,
        "overall": overall,
        "coverage": _coverage(diagnostics),
        "measured_view": {
            "overall": measured_overall,
            "diagnostics": [
                {"id": item["id"], "score": item["score"], "status": item["status"]}
                for item in measured
            ],
        },
        "targeted_request": _requests(pack["entries"], diagnostics),
        "root_causes": [],
        "actions": [],
        "sign_off": {"by": None, "at": None, "decision": None},
    }


def _score_diagnostic(
    entry: dict[str, Any],
    records: list[dict[str, Any]],
    green: float,
    amber: float,
    gate_floor: float,
    attested: bool,
) -> dict[str, Any]:
    own = [
        record
        for record in records
        if record["diagnostic_id"] == entry["id"]
        and (attested or record["evidence_level"] != "Attested")
    ]
    active = {record["signal_id"] for record in own}
    score, caps = score_signals(active, entry["scoring"])
    route = _route(own)
    return {
        "id": entry["id"],
        "name": entry.get("name") or entry["id"],
        "area": entry.get("area") or "",
        "tier": entry.get("tier") or "",
        "points": entry.get("points") or 0,
        "gate": bool(entry.get("gate")),
        "question": entry.get("question") or "",
        "applicable": True,
        "route": route,
        "evidence_level": _best_level(own),
        "score": score,
        "status": status_for(score, green, amber),
        "caps_applied": caps,
        "provisional": False,
        "signals": sorted(active),
        "records": [record["record_id"] for record in own],
        "finding": _finding(entry, active),
        "recommendation_ids": [],
        "source_summary": _source_summary(own),
        "gate_failed": bool(entry.get("gate")) and score is not None and float(score) < gate_floor,
    }


def _areas(
    diagnostics: list[dict[str, Any]],
    order: list[str],
    green: float,
    amber: float,
) -> list[dict[str, Any]]:
    names: list[str] = []
    for name in order:
        if name not in names:
            names.append(str(name))
    for diagnostic in diagnostics:
        if diagnostic["area"] and diagnostic["area"] not in names:
            names.append(diagnostic["area"])
    areas: list[dict[str, Any]] = []
    for name in names:
        members = [item for item in diagnostics if item["area"] == name and item["score"] is not None]
        score = weighted_average([(float(item["points"]), item["score"]) for item in members])
        areas.append(
            {
                "name": name,
                "points": weighted_points(members) if members else 0,
                "score": score,
                "status": status_for(score, green, amber),
            }
        )
    return areas


def _overall(
    diagnostics: list[dict[str, Any]],
    bands: list[dict[str, Any]],
    ready: float,
    gaps: float,
    gate_floor: float,
) -> dict[str, Any]:
    scored = [(float(item["points"]), item["score"]) for item in diagnostics if item["score"] is not None]
    score = weighted_average(scored)
    failed = [
        item["id"]
        for item in diagnostics
        if item.get("gate") and item["score"] is not None and float(item["score"]) < gate_floor
    ]
    verdict = verdict_for(score, failed, ready, gaps)
    if failed:
        reason = (
            "Not ready because gate "
            + ", ".join(failed)
            + f" scored below {int(gate_floor) if gate_floor.is_integer() else gate_floor}."
        )
    elif score is None:
        reason = "No diagnostic has evidence, so the score is null."
    elif verdict == "Ready":
        reason = "Overall score is at or above 67 and no gate scored below the floor."
    elif verdict == "Ready with gaps":
        reason = "Overall score is between 50 and 66 and no gate scored below the floor."
    else:
        reason = "Overall score is below 50."
    return {
        "score": score,
        "maturity": maturity_for(score, bands),
        "verdict": verdict,
        "failed_gates": failed,
        "reason": reason,
        "provisional": False,
    }


def _coverage(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    evidenced = [item for item in diagnostics if item["score"] is not None]
    return {
        "diagnostics_with_evidence": len(evidenced),
        "diagnostics_total": len(diagnostics),
        "points_with_evidence": weighted_points(evidenced),
        "points_total": weighted_points(diagnostics),
    }


def weighted_points(items: list[dict[str, Any]]) -> int | float:
    """Sum diagnostic points, keeping integers whole."""
    total = sum(float(item["points"]) for item in items)
    if abs(total - round(total)) < 1e-9:
        return int(round(total))
    return float(f"{total:.2f}")


def _requests(entries: list[dict[str, Any]], diagnostics: list[dict[str, Any]]) -> list[dict[str, str]]:
    missing = {item["id"] for item in diagnostics if item["score"] is None}
    requests: list[dict[str, str]] = []
    for entry in entries:
        if entry["id"] not in missing:
            continue
        text = str(entry.get("gap_request") or "")
        if text:
            requests.append({"diagnostic_id": entry["id"], "request": text})
    requests.sort(key=lambda item: item["diagnostic_id"])
    return requests


def _finding(entry: dict[str, Any], active: set[str]) -> str:
    insights = entry.get("insights") or {}
    ordered: list[str] = []
    for signal_id, signal in entry["signals"].items():
        if signal_id in active and signal.get("polarity") == "negative":
            ordered.append(signal_id)
    for signal_id, signal in entry["signals"].items():
        if signal_id in active and signal.get("polarity") != "negative":
            ordered.append(signal_id)
    for signal_id in ordered:
        if signal_id in insights:
            return str(insights[signal_id])
    if active:
        return "Evidence recorded."
    return ""


def _source_summary(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    first = records[0]
    source = first["source"]
    return f"{source['file']}:{source['location']['value']}"


def _route(records: list[dict[str, Any]]) -> str:
    if any(record["block"] == "data_calc" for record in records):
        return "data"
    if any(record["evidence_level"] == "Verified" for record in records):
        return "inspected"
    if any(record["evidence_level"] == "Inferred" for record in records):
        return "inferred"
    if any(record["evidence_level"] == "Attested" for record in records):
        return "document"
    return "none"


def _best_level(records: list[dict[str, Any]]) -> str | None:
    best: str | None = None
    best_rank = 0
    for record in records:
        rank = _LEVEL_RANK.get(record["evidence_level"], 0)
        if rank > best_rank:
            best = record["evidence_level"]
            best_rank = rank
    return best


def _write_inventory(output_dir: Path, artifacts: list[dict[str, Any]]) -> None:
    write_json(output_dir / "inventory.json", {"artifacts": artifacts})
    path = output_dir / "inventory.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INVENTORY_FIELDS, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for artifact in artifacts:
            writer.writerow({field: artifact.get(field, "") for field in INVENTORY_FIELDS})


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"
