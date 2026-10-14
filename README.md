# Forecasting diagnostic tool (MVP)

A deterministic, offline check of forecasting artifacts. It inventories files, parses them without running them, applies a small YAML knowledge pack, and writes a single HTML dashboard.

## Setup and the path to a dashboard

From this directory, on Python 3.11+:

```
python -m pip install -r requirements.txt
python -m diag demo leaky
```

That copies `tests/planted/leaky_forecast` into `demo/input`, then runs init, run, and report. Open `demo/output/dashboard.html`.

The same steps one command at a time:

```
python -m pip install -r requirements.txt
python -m diag init demo
python -m diag run demo --pack pack
python -m diag report demo
python -m pytest
```

`diag demo leaky` is what fills `demo/input` with the planted leaky scenario before scoring. `init` / `run` / `report` on an empty `demo/input` still complete; they just have nothing to score.

The assessed date is frozen in `engagement.yaml` (`2026-01-15`) so two runs write identical `output/results.json`.

## What a run writes

Inside the engagement `output/` folder:

- `inventory.json` and `inventory.csv`
- `evidence_log.json`
- `results.json`
- `dashboard.html` (inline CSS, no CDN, no network)

`.pkl`, `.joblib`, and `.onnx` files are hashed, marked quarantined, and never unpickled or loaded. A file that cannot be decoded or parsed is marked unreadable and the rest of the run continues. Zip members whose paths escape the folder are refused.

Masking terms in the engagement config are replaced with `[masked]` in inventory, evidence, results, and the dashboard.

## Pack

Thresholds and scores live in `pack/diagnostics/`. The engine refuses an entry that is missing `id`, `signals`, or `scoring`. This MVP ships six diagnostics:

| ID | Check | Gate |
| --- | --- | --- |
| D08 | Data profiling on `series_id`, `date`, `actual` | |
| D14 | Leakage via a negative `shift` literal, including `periods=` | Yes |
| D21 | Experiment tracking (`mlflow` or `wandb` import) | |
| D22 | Rolling-origin (`TimeSeriesSplit`, config, or a document phrase) | |
| D34 | Naive baseline (`seasonal_naive` or `SeasonalNaive`) | Yes |
| D41 | Pipeline reliability (`filterwarnings("ignore")`, bare `except: continue`) | |

No evidence leaves the score null and the status `No evidence`. It does not become 0, and a null gate score does not force Not ready. Green is 67 and above, Amber is 50–66, and Red is below 50. D14 or D34 forces Not ready only when its numeric score is below 40.

## Left out of the full spec

- Only these six diagnostics. The other diagnostics are not implemented and have no pack files.
- No model execution. Model files are quarantined.
- No PDF, Word, PowerPoint, Excel, Parquet, or notebook parsers.
- No review spreadsheet, recommendation library, or network calls. There is no LLM.
