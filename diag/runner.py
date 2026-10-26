"""Engagement lifecycle: init, run, finalise, report."""

from __future__ import annotations

from pathlib import Path

import yaml

from diag.intake.inventory import write_inventory
from diag.intake.pipeline import collect
from diag.intake.sort import ensure_layout
from diag.outputs.dashboard import render_dashboard
from diag.outputs.mask import mask_obj
from diag.packload import load_pack
from diag.rules.engine import assign_record_ids, build_signal_evidence
from diag.scoring.measures import build_measure_evidence, collect_frames, compute_measures
from diag.scoring.score import assemble_results
from diag.util import strip_private, write_json
from diag.validate import validate_evidence, validate_inventory, validate_results
from diag import __version__


def init_engagement(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "work").mkdir(exist_ok=True)
    (path / "output").mkdir(exist_ok=True)
    ensure_layout(path)
    config_path = path / "engagement.yaml"
    if not config_path.exists():
        config_path.write_text(
            "\n".join(
                [
                    f"engagement_id: {path.name}",
                    "client_alias: Demo Client",
                    "solution: Demand forecast",
                    "mask_terms:",
                    "  - AcmeForecast",
                    "  - Jane Doe",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return path


def load_config(path: Path) -> dict:
    config_path = path / "engagement.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"no engagement config at {config_path}. Run: python -m diag init {path}")
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError("engagement.yaml must be a mapping")
    loaded.setdefault("engagement_id", path.name)
    loaded.setdefault("client_alias", "Client")
    loaded.setdefault("solution", "Forecasting solution")
    loaded.setdefault("mask_terms", [])
    return loaded


def save_config(path: Path, config: dict) -> None:
    payload = {
        "engagement_id": config.get("engagement_id"),
        "client_alias": config.get("client_alias"),
        "solution": config.get("solution"),
        "mask_terms": list(config.get("mask_terms") or []),
        "pack_path": config.get("pack_path") or "",
    }
    (path / "engagement.yaml").write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _apply_unconfirmed_stage(inventory: list[dict], pack: dict) -> None:
    """Use the pack default until Gate 1 imports a decision. Never apply a proposed hint."""
    shared = (pack.get("shared") or {}).get("data_stage") or {}
    stage = shared.get("stage") or {}
    default_stage = stage.get("default_when_unknown") or "model_ready"
    flag = ((shared.get("effects") or {}).get("unknown") or {}).get("flag") or ""
    absent = shared.get("absent_row_semantics") or {}
    default_absent = absent.get("default_when_unknown") or "unknown"
    for record in inventory:
        if record.get("family") != "data":
            continue
        if record.get("data_stage_confirmed"):
            continue
        record["data_stage"] = default_stage
        record["data_stage_hints"] = []
        record["data_stage_flag"] = flag
        if record.get("data_format") == "sales_history" or record.get("detected_type") == "sales_history":
            record["absent_row_semantics"] = default_absent
            record["absent_row_basis"] = "none"


def execute(engagement: Path, pack_dir: Path, *, stage: str) -> dict:
    config = load_config(engagement)
    pack = load_pack(pack_dir)
    allowlist = list((pack["vocab"].get("model_file_allowlist") or {}).get("modules") or [])
    inventory, parsed = collect(engagement, allowlist)
    _apply_unconfirmed_stage(inventory, pack)
    signal_records = build_signal_evidence(pack, parsed)
    frames, owners = collect_frames(parsed)
    measure_values = compute_measures(pack["diagnostics"], frames)
    measure_records = build_measure_evidence(pack["diagnostics"], frames, owners, pack["meta"]["version"])
    evidence = assign_record_ids(signal_records + measure_records)
    results = assemble_results(config, pack, inventory, parsed, evidence, measure_values, stage=stage)
    terms = list(config.get("mask_terms") or [])
    public_inventory = [strip_private(record) for record in mask_obj(inventory, terms)]
    evidence_doc = mask_obj(
        {"pack_version": pack["meta"]["version"], "engine_version": __version__, "records": evidence},
        terms,
    )
    results = mask_obj(results, terms)
    validate_inventory(public_inventory)
    validate_evidence(evidence_doc)
    validate_results(results)
    output = engagement / "output"
    output.mkdir(parents=True, exist_ok=True)
    write_inventory(output / "inventory.json", public_inventory)
    write_json(output / "evidence_log.json", evidence_doc)
    write_json(output / "results.json", results)
    config["pack_path"] = str(pack_dir.resolve())
    save_config(engagement, config)
    return results


def run_engagement(engagement: Path, pack_dir: Path) -> dict:
    return execute(engagement, pack_dir, stage="provisional")


def finalise_engagement(engagement: Path, pack_dir: Path | None = None) -> dict:
    if pack_dir is None:
        config = load_config(engagement)
        recorded = config.get("pack_path") or ""
        if not recorded:
            raise FileNotFoundError("pack path is not recorded. Run diag run --pack first, or pass --pack.")
        pack_dir = Path(recorded)
    return execute(engagement, pack_dir, stage="final")


def report_engagement(engagement: Path) -> Path:
    results_path = engagement / "output" / "results.json"
    if not results_path.exists():
        raise FileNotFoundError(f"no results at {results_path}. Run diag run and diag finalise first.")
    import json

    results = json.loads(results_path.read_text(encoding="utf-8"))
    dashboard = engagement / "output" / "dashboard.html"
    dashboard.write_text(render_dashboard(results), encoding="utf-8")
    return dashboard
