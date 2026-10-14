"""MVP checks for the planted scenarios, safety, masking, and determinism."""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack"


def test_leaky_forecast(tmp_path: Path) -> None:
    features = (REPO / "tests" / "planted" / "leaky_forecast" / "features.py").read_text(encoding="utf-8")
    training = (REPO / "tests" / "planted" / "leaky_forecast" / "train.py").read_text(encoding="utf-8")
    assert 'df["lag"] = df["actual"].shift(-1)' in features
    assert 'warnings.filterwarnings("ignore")' in training
    assert "except:" in training and "continue" in training

    eng = prepare(tmp_path, REPO / "tests" / "planted" / "leaky_forecast")
    output = eng / "output"
    for name in ("inventory.json", "inventory.csv", "evidence_log.json", "results.json", "dashboard.html"):
        assert (output / name).is_file()

    found = diagnostics(eng)
    assert found["D08"]["status"] in {"Red", "Amber"}
    assert {"duplicate_keys", "missing_periods", "bad_actuals"} <= set(found["D08"]["signals"])
    assert "negative_shift" in found["D14"]["signals"]
    assert found["D14"]["records"]
    assert found["D14"]["score"] < 40
    assert {"warnings_ignored", "silent_except"} <= set(found["D41"]["signals"])
    assert found["D41"]["score"] < 50
    for diagnostic_id in ("D21", "D34", "D22"):
        assert found[diagnostic_id]["status"] == "No evidence"
        assert found[diagnostic_id]["score"] is None

    overall = results(eng)["overall"]
    assert overall["verdict"] == "Not ready"
    assert overall["failed_gates"] == ["D14"]

    html = (output / "dashboard.html").read_text(encoding="utf-8")
    assert "<style>" in html
    assert "http://" not in html and "https://" not in html
    assert "cdn" not in html.lower()
    assert "Not ready" in html


def test_healthy_forecast(tmp_path: Path) -> None:
    eng = prepare(tmp_path, REPO / "tests" / "planted" / "healthy_forecast")
    found = diagnostics(eng)
    for diagnostic_id in ("D08", "D14", "D21", "D22", "D34"):
        assert found[diagnostic_id]["status"] == "Green"
        assert found[diagnostic_id]["score"] >= 67
    assert "negative_shift" not in found["D14"]["signals"]
    assert results(eng)["overall"]["verdict"] != "Not ready"
    assert "D34" not in results(eng)["overall"]["failed_gates"]
    assert "D14" not in results(eng)["overall"]["failed_gates"]


def test_robustness_corrupt_and_quarantine(tmp_path: Path) -> None:
    eng = prepare(tmp_path, REPO / "tests" / "planted" / "robust_forecast")
    inventory = {
        item["path"]: item
        for item in json.loads((eng / "output" / "inventory.json").read_text(encoding="utf-8"))["artifacts"]
    }
    assert inventory["corrupt.csv"]["status"] == "unreadable"
    assert inventory["model.pkl"]["status"] == "quarantined"
    assert inventory["model.pkl"]["family"] == "model"
    assert inventory["model.pkl"]["detected_type"] == "pickle"
    assert inventory["good_sales.csv"]["status"] == "readable"
    assert diagnostics(eng)["D08"]["score"] is not None
    assert diagnostics(eng)["D08"]["status"] == "Green"


def test_masking_removes_configured_terms(tmp_path: Path) -> None:
    eng = prepare(tmp_path, REPO / "tests" / "planted" / "masked_forecast", masking=["AcmeCorp"])
    for path in (eng / "output").rglob("*"):
        if path.is_file():
            assert b"AcmeCorp" not in path.read_bytes()
    blob = b"".join(path.read_bytes() for path in (eng / "output").rglob("*") if path.is_file())
    assert b"[masked]" in blob


def test_results_are_deterministic(tmp_path: Path) -> None:
    eng = prepare(tmp_path, REPO / "tests" / "planted" / "leaky_forecast")
    names = ["results.json", "inventory.json", "inventory.csv", "evidence_log.json", "dashboard.html"]
    first = {name: (eng / "output" / name).read_bytes() for name in names}
    assert first["results.json"].endswith(b"\n")
    cli(["run", str(eng), "--pack", str(PACK)])
    cli(["report", str(eng)])
    second = {name: (eng / "output" / name).read_bytes() for name in names}
    assert first == second
    assert b"2026-01-15" in first["results.json"]


def test_keyword_negative_shift(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "features.py").write_text("df.shift(periods=-1)\n", encoding="utf-8", newline="\n")
    eng = prepare(tmp_path / "run", source)
    found = diagnostics(eng)["D14"]
    assert "negative_shift" in found["signals"]
    assert found["score"] < 40
    assert results(eng)["overall"]["verdict"] == "Not ready"


def test_rolling_origin_levels(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "model.py").write_text(
        "from sklearn.model_selection import TimeSeriesSplit\nTimeSeriesSplit(n_splits=2)\n",
        encoding="utf-8",
        newline="\n",
    )
    (source / "backtest.yaml").write_text(
        "backtest:\n  rolling_origin: true\n",
        encoding="utf-8",
        newline="\n",
    )
    (source / "method.md").write_text(
        "# Method\nWe use a Rolling Origin evaluation.\n",
        encoding="utf-8",
        newline="\n",
    )
    eng = prepare(tmp_path / "run", source)
    records = json.loads((eng / "output" / "evidence_log.json").read_text(encoding="utf-8"))["records"]
    levels = {item["signal_id"]: item["evidence_level"] for item in records if item["diagnostic_id"] == "D22"}
    assert levels["time_series_split"] == "Verified"
    assert levels["rolling_origin_config"] == "Verified"
    assert levels["rolling_origin_phrase"] == "Attested"
    assert diagnostics(eng)["D22"]["status"] == "Green"


def test_zip_slip_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    with zipfile.ZipFile(source / "bundle.zip", "w") as archive:
        archive.writestr(zipfile.ZipInfo("../outside.txt"), "nope")
        archive.writestr("ok.py", "import mlflow\n")
    eng = prepare(tmp_path / "run", source)
    assert not (tmp_path / "outside.txt").exists()
    assert not (eng / "outside.txt").exists()
    work = eng / "work"
    for path in work.rglob("*"):
        if path.is_file():
            assert b"nope" not in path.read_bytes()
    inventory = json.loads((eng / "output" / "inventory.json").read_text(encoding="utf-8"))["artifacts"]
    assert any(item["reason"] == "path escapes the folder" for item in inventory)
    assert diagnostics(eng)["D21"]["status"] == "Green"


def test_pack_refuses_incomplete_entry(tmp_path: Path) -> None:
    from diag.packload import PackError, validate_entry

    with pytest.raises(PackError, match="missing id"):
        validate_entry({"signals": {"a": {"detectors": [{"type": "code_import"}]}}, "scoring": [{"otherwise": "no_evidence"}]})
    with pytest.raises(PackError, match="missing signals"):
        validate_entry({"id": "D99", "scoring": [{"otherwise": "no_evidence"}]})
    with pytest.raises(PackError, match="missing scoring"):
        validate_entry({"id": "D99", "signals": {"a": {"detectors": [{"type": "code_import"}]}}})

    bad = tmp_path / "badpack"
    shutil.copytree(PACK, bad)
    (bad / "diagnostics" / "D21.yaml").write_text("id: D21\nname: Experiment tracking\n", encoding="utf-8")
    eng = tmp_path / "eng"
    cli(["init", str(eng)])
    proc = _run(["run", str(eng), "--pack", str(bad)])
    assert proc.returncode == 2
    assert "missing" in proc.stderr


def test_generic_detectors_and_scoring() -> None:
    from diag.blocks import config_key, log_stats, phrase_search
    from diag.intake import Artifact
    from diag.parsers import ParsedFile
    from diag.scoring import score_signals, status_for, verdict_for, weighted_average

    artifact = Artifact(
        path="a.yaml",
        sha256="",
        size_bytes=1,
        detected_type="yaml",
        family="config",
        encoding="utf-8",
        period_covered="",
        status="readable",
        reason="",
    )
    parsed = ParsedFile(artifact=artifact, flat={"backtest.rolling_origin": True, "backtest.horizon": 12})
    assert len(config_key(parsed, {"key": "backtest.rolling_origin", "equals": True})) == 1
    assert config_key(parsed, {"key": "backtest.rolling_origin", "equals": False}) == []
    assert len(config_key(parsed, {"key": "backtest.*"})) == 2

    document = Artifact(
        path="note.md",
        sha256="",
        size_bytes=1,
        detected_type="markdown",
        family="document",
        encoding="utf-8",
        period_covered="",
        status="readable",
        reason="",
    )
    note = ParsedFile(artifact=document, lines=["We use a Rolling Origin evaluation."])
    assert phrase_search(note, {"phrases": ["rolling origin"]})

    log_artifact = Artifact(
        path="job.log",
        sha256="",
        size_bytes=1,
        detected_type="log",
        family="log",
        encoding="utf-8",
        period_covered="",
        status="readable",
        reason="",
    )
    log_file = ParsedFile(
        artifact=log_artifact,
        events=[{"timestamp": "2024-01-01 00:00:00", "status": "ERROR"}],
    )
    assert log_stats(log_file, {"statuses": ["ERROR", "FAILED"], "op": "gte", "threshold": 1})

    score, _caps = score_signals(
        {"warnings_ignored", "silent_except"},
        [
            {"when_all": ["warnings_ignored", "silent_except"], "score": 30},
            {"when_all": ["warnings_ignored"], "score": 45},
            {"when_all": ["warnings_ignored"], "cap": 20},
        ],
    )
    assert score == 20
    assert score_signals(set(), [{"when_all": ["a"], "score": 10}])[0] is None
    assert verdict_for(90, [], 67, 50) == "Ready"
    assert verdict_for(60, [], 67, 50) == "Ready with gaps"
    assert verdict_for(40, [], 67, 50) == "Not ready"
    assert verdict_for(90, ["D14"], 67, 50) == "Not ready"
    assert verdict_for(None, [], 67, 50) == "No evidence"
    assert status_for(None, 67, 50) == "No evidence"
    assert status_for(67, 67, 50) == "Green"
    assert status_for(66, 67, 50) == "Amber"
    assert status_for(49, 67, 50) == "Red"
    assert weighted_average([]) is None


def test_csv_nul_does_not_parse(tmp_path: Path) -> None:
    from diag.intake import inspect_file
    from diag.parsers import ParseError, parse_artifact

    path = tmp_path / "bad.csv"
    path.write_bytes(b"series_id,date,actual\nA,2024-01-01,1\x00\n")
    artifact = inspect_file(path, "bad.csv")
    assert artifact.status == "readable"
    with pytest.raises(ParseError):
        parse_artifact(artifact)


def test_client_code_is_parsed_not_executed() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in (REPO / "diag").glob("*.py"))
    assert "pickle.load" not in source
    assert "pickle.loads" not in source
    assert "joblib.load" not in source
    assert "yaml.load(" not in source
    assert "exec(" not in source
    tree = ast.parse((REPO / "tests" / "planted" / "leaky_forecast" / "features.py").read_text(encoding="utf-8"))
    assert isinstance(tree, ast.AST)


def prepare(tmp_path: Path, source: Path, masking: list[str] | None = None) -> Path:
    """Init, copy a fixture, and run the CLI."""
    eng = tmp_path / "case"
    cli(["init", str(eng)])
    dest = eng / "input"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest)
    if masking:
        path = eng / "engagement.yaml"
        text = path.read_text(encoding="utf-8")
        lines = "\n".join(f"  - {item}" for item in masking)
        text = text.replace("masking: []", f"masking:\n{lines}")
        path.write_text(text, encoding="utf-8", newline="\n")
    cli(["run", str(eng), "--pack", str(PACK)])
    cli(["report", str(eng)])
    return eng


def cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the diag CLI and require success."""
    proc = _run(args)
    if proc.returncode != 0:
        raise AssertionError(f"{args}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return proc


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "diag", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def results(eng: Path) -> dict:
    return json.loads((eng / "output" / "results.json").read_text(encoding="utf-8"))


def diagnostics(eng: Path) -> dict:
    return {item["id"]: item for item in results(eng)["diagnostics"]}
