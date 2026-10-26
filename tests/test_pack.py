"""Pack 0.5.0 loads, and a broken reference fails both the loader and the checker."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "pack"


class PackTests(unittest.TestCase):
    def test_checker_accepts_the_shipped_pack(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(PACK / "tools" / "check_pack.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("OK: pack 0.5.0", completed.stdout)

    def test_loader_accepts_the_shipped_pack(self) -> None:
        from diag.packload import load_pack

        pack = load_pack(PACK)
        self.assertEqual(pack["meta"]["version"], "0.5.0")
        self.assertEqual({item["id"] for item in pack["diagnostics"]}, {"D08", "D43"})
        self.assertIn("data_stage", pack["shared"])
        self.assertIn("validation_libraries", pack["vocab"])
        self.assertIn("target_config_keys", pack["vocab"])

    def test_broken_reference_fails_loader_and_checker(self) -> None:
        from diag.packload import load_pack

        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "pack"
            shutil.copytree(PACK, copy)
            target = copy / "diagnostics" / "D08.yaml"
            text = target.read_text(encoding="utf-8")
            self.assertIn("@dq_phrases", text)
            target.write_text(text.replace("@dq_phrases", "@not_a_vocabulary", 1), encoding="utf-8")
            checked = subprocess.run(
                [sys.executable, str(copy / "tools" / "check_pack.py")],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(checked.returncode, 0, checked.stdout)
            self.assertIn("not_a_vocabulary", checked.stdout)
            with self.assertRaises(ValueError):
                load_pack(copy)

    def test_duplicate_vocabulary_key_fails_the_loader(self) -> None:
        from diag.packload import load_pack

        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "pack"
            shutil.copytree(PACK, copy)
            for name in ("data_validation.yaml", "target_definition.yaml"):
                path = copy / "vocab" / name
                path.write_text(path.read_text(encoding="utf-8") + "\nshared_marker: [1]\n", encoding="utf-8")
            with self.assertRaises(ValueError) as raised:
                load_pack(copy)
            self.assertIn("shared_marker", str(raised.exception))

    def test_later_measures_do_not_score(self) -> None:
        from diag.packload import load_pack
        from diag.scoring.score import score_diagnostics

        pack = load_pack(PACK)
        scored = {item["id"]: item for item in score_diagnostics(pack, [], {})}
        later = [row for row in scored["D08"]["measures"] if row["reason_not_computed"] == "not_implemented"]
        self.assertTrue(later)
        self.assertTrue(all(row["computed"] is False and row["score"] is None for row in later))
        self.assertIsNone(scored["D08"]["score"])

    def test_stockout_records_are_not_counted(self) -> None:
        from diag.packload import load_pack
        from diag.scoring.score import score_diagnostics

        pack = load_pack(PACK)
        evidence = [
            {
                "record_id": "E1",
                "diagnostic_id": "D08",
                "signal_id": "zero.stockout_candidate",
                "status": "auto_accepted",
                "owner_diagnostic": None,
                "evidence_level": "Inferred",
                "values": {},
            }
        ]
        scored = {item["id"]: item for item in score_diagnostics(pack, evidence, {})}
        self.assertNotIn("zero.stockout_candidate", scored["D08"]["signals"])
