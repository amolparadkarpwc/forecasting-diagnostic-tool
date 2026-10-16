"""Planted-scenario tests for the MVP diagnostic."""

from __future__ import annotations

import json
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "pack"
DEMO = ROOT / "examples" / "demo_input"

sys.path.insert(0, str(ROOT))

from diag.intake.safety import assess_model  # noqa: E402
from diag.intake.unpack import extract_zip  # noqa: E402
from diag.rules.derived import rate_above  # noqa: E402
from diag.runner import init_engagement, report_engagement, run_engagement  # noqa: E402


def _scores(results: dict) -> dict:
    return {item["id"]: item for item in results["diagnostics"]}


def _dashboard_payload(html: str) -> dict:
    marker = '<script id="results" type="application/json">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    return json.loads(html[start:end])


class DiagnosticTests(unittest.TestCase):
    def test_help(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "diag", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("finalise", completed.stdout)
        self.assertIn("run", completed.stdout)

    def test_pack_and_derived_helper(self) -> None:
        from diag.packload import load_pack

        pack = load_pack(PACK)
        self.assertEqual(pack["meta"]["version"], "0.1.0")
        self.assertIn("D14", {item["id"] for item in pack["diagnostics"]})
        self.assertTrue(rate_above(0.3, 0.2))
        self.assertFalse(rate_above(0.1, 0.2))

    def test_source_does_not_unpickle_or_execute(self) -> None:
        banned = ("pickle.loads", "pickle.load(", "exec(", "eval(")
        text = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "diag").rglob("*.py"))
        for token in banned:
            self.assertNotIn(token, text)

    def test_zip_slip_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            archive = folder / "evil.zip"
            dest = folder / "out"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("ok.txt", "hello")
                handle.writestr("../escaped.txt", "nope")
                handle.writestr("..\\also.txt", "nope")
            extracted, rejected = extract_zip(archive, dest)
            self.assertEqual([item["member"] for item in extracted], ["ok.txt"])
            self.assertTrue(any("escapes" in item["reason"] for item in rejected))
            self.assertFalse((folder / "escaped.txt").exists())
            self.assertFalse(any(path.name in {"escaped.txt", "also.txt"} for path in dest.rglob("*")))

    def test_disallowed_pickle_is_quarantined_and_not_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            marker = folder / "PWNED.txt"
            engagement = folder / "eng"

            class Evil:
                def __reduce__(self):
                    return (os.system, (f'echo pwned > "{marker}"',))

            init_engagement(engagement)
            (engagement / "input" / "bad.pkl").write_bytes(pickle.dumps(Evil(), protocol=4))
            run_engagement(engagement, PACK)
            self.assertFalse(marker.exists())
            inventory = json.loads((engagement / "output" / "inventory.json").read_text(encoding="utf-8"))
            pickle_row = next(row for row in inventory if row["path"].endswith("bad.pkl"))
            self.assertEqual(pickle_row["status"], "quarantined")
            self.assertIn("disallowed", pickle_row["reason"])
            status, reason = assess_model(engagement / "input" / "bad.pkl", "pickle", ["sklearn"])
            self.assertEqual(status, "quarantined")
            self.assertTrue("os" in reason or "nt" in reason or "posix" in reason)

    def test_label_shift_is_not_scored_as_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engagement = Path(tmp) / "eng"
            init_engagement(engagement)
            shutil.copy(ROOT / "tests" / "planted" / "label_shift" / "train.py", engagement / "input" / "train.py")
            results = run_engagement(engagement, PACK)
            evidence = json.loads((engagement / "output" / "evidence_log.json").read_text(encoding="utf-8"))
            leakage = [
                record
                for record in evidence["records"]
                if record["signal_id"] == "negative_shift" and record["status"] in {"auto_accepted", "counted_flagged"}
            ]
            review = [record for record in evidence["records"] if record["signal_id"] == "possible_label_shift"]
            self.assertEqual(leakage, [])
            self.assertTrue(review)
            self.assertTrue(all(record["status"] == "needs_review" for record in review))
            self.assertIsNone(_scores(results)["D14"]["score"])

    def test_naive_fallback_mention_needs_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engagement = Path(tmp) / "eng"
            init_engagement(engagement)
            shutil.copy(ROOT / "tests" / "planted" / "naive_fallback" / "note.md", engagement / "input" / "note.md")
            results = run_engagement(engagement, PACK)
            evidence = json.loads((engagement / "output" / "evidence_log.json").read_text(encoding="utf-8"))
            mentions = [record for record in evidence["records"] if record["signal_id"] == "baseline_mentioned"]
            self.assertTrue(mentions)
            self.assertTrue(all(record["status"] == "needs_review" for record in mentions))
            self.assertIsNone(_scores(results)["D34"]["score"])

    def test_demo_end_to_end(self) -> None:
        self.assertTrue(DEMO.exists(), "run python examples/build_demo_input.py first")
        with tempfile.TemporaryDirectory() as tmp:
            engagement = Path(tmp) / "demo"
            init_engagement(engagement)
            shutil.copytree(DEMO, engagement / "input", dirs_exist_ok=True)
            results = run_engagement(engagement, PACK)
            scores = _scores(results)
            scored = [item for item in results["diagnostics"] if item["score"] is not None]
            self.assertGreaterEqual(len(scored), 3)
            self.assertEqual(scores["D14"]["score"], 20)
            self.assertEqual(scores["D14"]["status"], "Red")
            self.assertEqual(scores["D41"]["score"], 30)
            self.assertGreaterEqual(scores["D23"]["score"], 67)
            self.assertGreaterEqual(scores["D34"]["score"], 40)
            self.assertIsNotNone(scores["D08"]["score"])
            self.assertLess(scores["D08"]["score"], 80)
            self.assertIsNone(scores["D43"]["score"])
            self.assertEqual(scores["D42"]["status"], "Not scored")
            self.assertEqual(results["overall"]["verdict"], "Not ready")
            failed = {item["id"] for item in results["overall"]["failed_gates"]}
            self.assertIn("D14", failed)
            self.assertIn("D43", failed)
            self.assertNotIn("D34", failed)
            self.assertEqual(results["versions"]["pack"], "0.1.0")
            self.assertIn("python", results["versions"])
            inventory = json.loads((engagement / "output" / "inventory.json").read_text(encoding="utf-8"))
            self.assertTrue(any(row["status"] == "quarantined" for row in inventory))
            self.assertTrue(any(row["status"] == "duplicate" for row in inventory))
            self.assertTrue(any(row["status"] == "unreadable" for row in inventory))
            onnx = next(row for row in inventory if row["detected_type"] == "onnx")
            self.assertEqual(onnx["status"], "manual_review")
            self.assertIn("ONNX", onnx["reason"])
            pdf = next(row for row in inventory if row["detected_type"] == "pdf")
            self.assertEqual(pdf["status"], "manual_review")
            output_text = "\n".join(
                path.read_text(encoding="utf-8") for path in (engagement / "output").iterdir() if path.suffix != ".html"
            )
            self.assertNotIn("AcmeForecast", output_text)
            self.assertNotIn("Jane Doe", output_text)
            self.assertIn("[REDACTED]", output_text)
            dashboard = report_engagement(engagement)
            html = dashboard.read_text(encoding="utf-8")
            self.assertIn("Not ready", html)
            self.assertIn("Summary", html)
            self.assertIn("Coverage", html)
            self.assertIn("Scorecard", html)
            self.assertIn("Recommendations", html)
            self.assertIn("What-if", html)
            self.assertIn("Measured evidence only", html)
            self.assertNotIn("AcmeForecast", html)
            self.assertNotIn("Client A", html)
            self.assertNotIn("carefully guarded", html)
            self.assertNotIn("fonts.googleapis.com", html)
            self.assertNotIn("client_pipeline.py", html)
            payload = _dashboard_payload(html)
            by_id = {item["id"]: item for item in payload["checks"]}
            self.assertEqual(payload["engine"]["final"]["verdict"], results["overall"]["verdict"])
            self.assertEqual(payload["engine"]["final"]["score"], results["overall"]["score"])
            self.assertEqual(by_id["D14"]["score"], scores["D14"]["score"])
            self.assertIsNone(by_id["D43"]["score"])
            self.assertTrue(by_id["D43"]["inPack"])
            self.assertEqual(by_id["D43"]["ev"], "NE")
            self.assertIsNone(by_id["D21"]["score"])
            self.assertEqual(by_id["D21"]["ev"], "NE")
            self.assertFalse(by_id["D21"]["inPack"])
            self.assertEqual(by_id["D21"]["name"], "Experiment tracking")
            self.assertIsNone(by_id["D22"]["score"])
            self.assertIsNone(by_id["D10"]["score"])
            self.assertNotEqual(by_id["D14"]["score"], 82)

    def test_repeat_run_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            first = folder / "one"
            second = folder / "two"
            for engagement in (first, second):
                init_engagement(engagement)
                config_path = engagement / "engagement.yaml"
                config_text = config_path.read_text(encoding="utf-8")
                config_path.write_text(
                    config_text.replace(f"engagement_id: {engagement.name}", "engagement_id: demo"),
                    encoding="utf-8",
                )
                shutil.copytree(DEMO, engagement / "input", dirs_exist_ok=True)
                run_engagement(engagement, PACK)
            left = json.loads((first / "output" / "results.json").read_text(encoding="utf-8"))
            right = json.loads((second / "output" / "results.json").read_text(encoding="utf-8"))
            left["versions"].pop("generated_at", None)
            right["versions"].pop("generated_at", None)
            self.assertEqual(left, right)


if __name__ == "__main__":
    unittest.main()
