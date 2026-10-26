"""Golden scores from the pack's worked-example scripts."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "pack"


def _script(name: str) -> str:
    completed = subprocess.run(
        [sys.executable, str(PACK / "tools" / name)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return completed.stdout


class GoldenTests(unittest.TestCase):
    def test_d08_matches_the_reference_script(self) -> None:
        from diag.packload import load_pack
        from diag.scoring.combination import combine, condition_score, control_score

        printed = _script("worked_example.py")
        pack = load_pack(PACK)
        entry = next(item for item in pack["diagnostics"] if item["id"] == "D08")
        clean = {"duplicate_rows": 0, "conflicting_records": 0, "out_of_range": 0, "calendar_consistency": 0}
        prep = {"data_prep_code_present", "dedupe_exact", "zero_fill_gaps", "zero_fill_hides_missing_data", "no_validation_found"}
        better = {"data_prep_code_present", "dedupe_exact", "explicit_gap_handling", "validation_framework_used"}
        cases = [
            ("A", "model_ready", {**clean, "gap_share": 0.018}, set(), "70 (controls not evidenced)"),
            ("B", "model_ready", {**clean, "gap_share": 0.018}, prep, "40"),
            ("C", "raw_source", {**clean, "gap_share": 0.018, "duplicate_rows": 0.003, "parse_errors": 0}, prep, "40"),
            ("D", "raw_source", {**clean, "gap_share": 0.018, "duplicate_rows": 0.003, "parse_errors": 0}, better, "80"),
        ]
        for label, stage, values, signals, expected in cases:
            condition, _scores = condition_score(entry, values, stage, signals)
            control = control_score(entry, signals) if signals else None
            score, note = combine(condition, control)
            shown = f"{score} ({note.lower()})" if note else str(score)
            self.assertEqual(shown, expected, label)
            self.assertIn(expected, printed)

    def test_d43_matches_the_reference_script(self) -> None:
        from diag.packload import load_pack
        from diag.scoring.combination import combine, condition_score, control_score, evaluate_gate, gate_floor

        printed = _script("worked_example_D43.py")
        pack = load_pack(PACK)
        entry = next(item for item in pack["diagnostics"] if item["id"] == "D43")
        floor = gate_floor(pack)
        aligned = {"grain_alignment": "aligned", "unit_alignment": "aligned"}
        good = {
            "training_code_present",
            "target_identified",
            "target_definition_stated",
            "evaluation_actuals_traced",
            "target_same_in_training_and_evaluation",
        }
        cases = [
            ("1", {**aligned, "target_reconciliation": 0.005, "returns_share": 0.04}, good, set(), 85, "passes"),
            (
                "2",
                {**aligned, "target_reconciliation": 0.08},
                {"training_code_present", "target_identified", "evaluation_actuals_traced", "target_mismatch_training_evaluation"},
                {"target_mismatch_training_evaluation"},
                24,
                "tripped",
            ),
            ("3", {**aligned, "target_reconciliation": 0.005, "returns_share": 0.20}, good | {"target_clipped_at_zero"}, set(), 70, "passes"),
            ("4", {}, {"training_code_present", "target_identified", "target_ambiguous"}, set(), 65, "passes"),
            (
                "5a",
                {},
                {"training_code_present", "target_identified", "target_definition_stated", "definitions_conflict"},
                set(),
                35,
                "pending",
            ),
            (
                "5b",
                {},
                {"training_code_present", "target_identified", "target_definition_stated", "definitions_conflict"},
                {"definitions_conflict"},
                35,
                "tripped",
            ),
            ("6", {}, set(), set(), None, "no_evidence"),
        ]
        for label, values, signals, confirmed, expected, gate_status in cases:
            condition, scores = condition_score(entry, values, "model_ready", signals)
            control = control_score(entry, signals) if signals else None
            score, _note = combine(condition, control)
            self.assertEqual(score, expected, label)
            categories = {name: value for name, value in values.items() if isinstance(value, str)}
            gate = evaluate_gate(
                entry,
                score,
                signals,
                scores,
                confirmed,
                floor,
                categories=categories,
                inferred_needs_review=True,
            )
            self.assertEqual(gate["status"], gate_status, label)
        self.assertIn("TRIPPED", printed)
        self.assertIn("no evidence", printed)

    def test_a_positive_control_does_not_lower_the_score(self) -> None:
        from diag.packload import load_pack
        from diag.scoring.combination import combine, condition_score, control_score

        pack = load_pack(PACK)
        entry = next(item for item in pack["diagnostics"] if item["id"] == "D08")
        values = {"gap_share": 0.018, "duplicate_rows": 0, "conflicting_records": 0, "out_of_range": 0, "calendar_consistency": 0}
        weak = {"data_prep_code_present", "no_validation_found"}
        stronger = weak | {"validation_framework_used", "dedupe_exact", "explicit_gap_handling"}
        before, _scores = condition_score(entry, values, "model_ready", weak)
        after_condition, _scores = condition_score(entry, values, "model_ready", stronger)
        before_score, _label = combine(before, control_score(entry, weak))
        after_score, _label = combine(after_condition, control_score(entry, stronger))
        self.assertGreaterEqual(after_score, before_score)
        worse, _scores = condition_score(entry, {**values, "gap_share": 0.2}, "model_ready", stronger)
        worse_score, _label = combine(worse, control_score(entry, stronger))
        self.assertLessEqual(worse_score, after_score)
