# Forecasting diagnostic tool (MVP)

A deterministic diagnostic for a forecasting solution a client already runs. It reads the files they share, records evidence, scores a small knowledge pack, and writes a single-file HTML dashboard.

This is a fixed-deadline slice of the full build spec, not the 10-week product. There is no LLM and no network call at runtime. Client Python is parsed, never executed. Model files are scanned with `pickletools` and never unpickled.

## Run the demo

From the repository root, on Windows:

```powershell
python -m diag --help
python -m diag init engagements\demo
Copy-Item -Recurse -Force examples\demo_input\* engagements\demo\client_artifacts\
python -m diag run engagements\demo --pack pack
python -m diag finalise engagements\demo
python -m diag report engagements\demo
start engagements\demo\output\dashboard.html
```

`python -m diag` works without an install. Optional: `pip install -e .` then use the `diag` command.

Rebuild the planted demo files with `python examples\build_demo_input.py`.

Tests:

```powershell
python -m unittest tests.test_mvp -v
```

## What the demo is meant to show

The client drops every file into `client_artifacts/`. `diag run` reads each one and decides what it is from the contents: code, config, tables, logs, documents, transcripts, images, and models. The file name is used only when the bytes are not a clear match. Each file is then copied into `input/` (`code`, `config`, `data`, `documents`, `logs`, `models`, `images`, `transcripts`, or `other`). The dump itself is left as the client provided it. Files already placed in `input/` are still read.

The sample engagement mixes sound and weak artifacts:

- A demand extract with any file name, missing months, and one duplicate key. The table role comes from the columns, not the name.
- A forecast export, also with any file name, that can be scored for WAPE, bias, and a seasonal-naive margin
- Python that shifts a feature forward and swallows fit errors, plus a SQL join on a future date
- A scheduler log with failed runs
- A config and a short methodology note that name WAPE, bias, and a seasonal naive baseline
- A pickle that references an OS module (quarantined), a placeholder ONNX file, a fake PDF, a broken Python file, and a broken JSON file
- A zip with one safe member, and a duplicate text file

One bad file does not stop the run. `AcmeForecast` and `Jane Doe` are on the masking list created by `diag init`, and those strings are replaced with `[REDACTED]` in outputs.

Gates are D14, D34, and D43. The overall score weights every pack area. An area with no diagnostic in this pack counts as zero, so a run that only has evidence in Data cannot show that area's score as the engagement score. Thresholds in `pack/` are placeholders.

## Layout

- `diag/` engine: CLI, intake, handlers, blocks, rules, scoring, outputs
- `pack/` knowledge pack (YAML)
- `examples/demo_input/` planted engagement
- `tests/` planted scenarios and end-to-end checks

Useful outputs, written under the engagement `output/` folder:

- `inventory.csv` and `inventory.json`
- `evidence_log.json`
- `results.json` (pack, engine, and Python versions)
- `dashboard.html` (Summary, Scorecard, Recommendations)

`diag run` writes a provisional results file. `diag finalise` rewrites it as final. Review sign-off is still empty. `diag report` only renders the dashboard.

## Deferred versus the full spec

- The other diagnostics beyond D08, D14, D23, D34, D41, D42, and D43
- Review-sheet export and import (uncertain matches are left as `needs_review` and are not scored)
- Unpickling allowlisted models, ONNX inspection, PDF, Excel, and Parquet
- Incremental re-runs, targeted-request ranking beyond the gap list, what-if editing, and a separate coverage tab
- Family-specific scoring branches (a family is detected and stored, and every included diagnostic stays applicable)
- Practitioner sign-off and knowledge-pack feedback
- Overall score is the points-weighted average of the diagnostics **in this pack**. Missing evidence counts as zero. It is not divided by the full 100-point catalogue

`needs_review` is used when a negative `shift` looks like a label, and when a seasonal naive is mentioned only as a fallback. Those records do not change the score until a practitioner confirms them.
