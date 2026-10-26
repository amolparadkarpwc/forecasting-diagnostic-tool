"""Data measures for the original data-first route. Thresholds stay in the pack."""

from __future__ import annotations

import pandas as pd

from diag.util import round_measure


def collect_frames(parsed: list) -> tuple[dict, dict]:
    groups: dict[str, list] = {}
    owners: dict[str, object] = {}
    for artifact in sorted(parsed, key=lambda item: item.artifact_id):
        if not artifact.data_format or artifact.frame is None:
            continue
        groups.setdefault(artifact.data_format, []).append(artifact.frame)
        owners.setdefault(artifact.data_format, artifact)
    frames = {name: pd.concat(parts, ignore_index=True) for name, parts in groups.items()}
    return frames, owners


def _prepare_sales(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["series_id"] = out["series_id"].astype(str)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["actual"] = pd.to_numeric(out["actual"], errors="coerce")
    return out


def _prepare_forecasts(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["series_id"] = out["series_id"].astype(str)
    out["run_date"] = pd.to_datetime(out["run_date"], errors="coerce")
    out["target_date"] = pd.to_datetime(out["target_date"], errors="coerce")
    out["forecast"] = pd.to_numeric(out["forecast"], errors="coerce")
    return out


def infer_freq(dates: pd.Series) -> str:
    clean = pd.to_datetime(dates, errors="coerce").dropna().sort_values()
    deltas = clean.diff().dt.days.dropna()
    if deltas.empty:
        return "M"
    median = float(deltas.median())
    if median >= 20:
        return "M"
    if median >= 5:
        return "W"
    return "D"


def _period_freq(freq: str) -> str:
    return {"M": "M", "W": "W-SUN", "D": "D"}[freq]


def missing_period_rate(sales: pd.DataFrame) -> float | None:
    frame = _prepare_sales(sales).dropna(subset=["series_id", "date"])
    if frame.empty:
        return None
    freq = _period_freq(infer_freq(frame["date"]))
    expected = 0
    missing = 0
    for _, group in frame.groupby("series_id", sort=True):
        periods = sorted(set(group["date"].dt.to_period(freq).dropna()))
        if not periods:
            continue
        full = list(pd.period_range(periods[0], periods[-1], freq=freq))
        expected += len(full)
        missing += len(set(full) - set(periods))
    if expected == 0:
        return None
    return float(missing / expected)


def duplicate_rate(sales: pd.DataFrame) -> float | None:
    frame = _prepare_sales(sales).dropna(subset=["series_id", "date"])
    if frame.empty:
        return None
    frame = frame.assign(day=frame["date"].dt.normalize())
    unique = frame.drop_duplicates(["series_id", "day"]).shape[0]
    return float((len(frame) - unique) / len(frame))


def _aligned(sales: pd.DataFrame, forecasts: pd.DataFrame) -> pd.DataFrame:
    history = _prepare_sales(sales).dropna(subset=["series_id", "date", "actual"])
    forecast = _prepare_forecasts(forecasts).dropna(subset=["series_id", "target_date", "forecast"])
    history = history.sort_values(["series_id", "date"], kind="mergesort").drop_duplicates(
        ["series_id", "date"], keep="first"
    )
    forecast = forecast.sort_values(["run_date", "series_id"], kind="mergesort")
    forecast = forecast.groupby(["series_id", "target_date"], sort=False).tail(1)
    return forecast.merge(history, left_on=["series_id", "target_date"], right_on=["series_id", "date"], how="inner")


def wape(sales: pd.DataFrame, forecasts: pd.DataFrame) -> float | None:
    merged = _aligned(sales, forecasts)
    if merged.empty:
        return None
    denom = float(merged["actual"].abs().sum())
    if denom == 0:
        return None
    return float((merged["forecast"] - merged["actual"]).abs().sum() / denom)


def abs_bias(sales: pd.DataFrame, forecasts: pd.DataFrame) -> float | None:
    merged = _aligned(sales, forecasts)
    if merged.empty:
        return None
    denom = float(merged["actual"].abs().sum())
    if denom == 0:
        return None
    return float(abs((merged["forecast"] - merged["actual"]).sum() / denom))


def margin_over_seasonal_naive(sales: pd.DataFrame, forecasts: pd.DataFrame) -> float | None:
    history = _prepare_sales(sales).dropna(subset=["series_id", "date", "actual"])
    forecast = _prepare_forecasts(forecasts).dropna(subset=["series_id", "target_date", "forecast", "run_date"])
    if history.empty or forecast.empty:
        return None
    freq = infer_freq(history["date"])
    period_freq = _period_freq(freq)
    season = {"M": 12, "W": 52, "D": 7}[freq]
    history = history.sort_values(["series_id", "date"], kind="mergesort")
    history["period"] = history["date"].dt.to_period(period_freq)
    history = history.drop_duplicates(["series_id", "period"], keep="first")
    lookup = {
        (str(row.series_id), row.period): float(row.actual)
        for row in history.itertuples(index=False)
    }
    forecast = forecast.sort_values(["run_date", "series_id"], kind="mergesort")
    forecast["period"] = forecast["target_date"].dt.to_period(period_freq)
    forecast = forecast.groupby(["series_id", "period"], sort=False).tail(1)
    actuals: list[float] = []
    predicted: list[float] = []
    naive: list[float] = []
    for row in forecast.itertuples(index=False):
        key = (str(row.series_id), row.period)
        naive_key = (str(row.series_id), row.period - season)
        if key not in lookup or naive_key not in lookup:
            continue
        actuals.append(lookup[key])
        predicted.append(float(row.forecast))
        naive.append(lookup[naive_key])
    if not actuals:
        return None
    actual_sum = sum(abs(value) for value in actuals)
    if actual_sum == 0:
        return None
    model_wape = sum(abs(pred - actual) for pred, actual in zip(predicted, actuals)) / actual_sum
    naive_wape = sum(abs(base - actual) for base, actual in zip(naive, actuals)) / actual_sum
    return float(naive_wape - model_wape)


def _call_measure(name: str, frames: dict) -> float | None:
    if name == "missing_period_rate" and "sales_history" in frames:
        return missing_period_rate(frames["sales_history"])
    if name == "duplicate_rate" and "sales_history" in frames:
        return duplicate_rate(frames["sales_history"])
    if name == "wape" and "sales_history" in frames and "past_forecasts" in frames:
        return wape(frames["sales_history"], frames["past_forecasts"])
    if name == "abs_bias" and "sales_history" in frames and "past_forecasts" in frames:
        return abs_bias(frames["sales_history"], frames["past_forecasts"])
    if name == "margin_over_seasonal_naive" and "sales_history" in frames and "past_forecasts" in frames:
        return margin_over_seasonal_naive(frames["sales_history"], frames["past_forecasts"])
    return None


def compute_measures(diagnostics: list[dict], frames: dict) -> dict[str, dict[str, float]]:
    values: dict[str, dict[str, float]] = {}
    for diagnostic in diagnostics:
        route = diagnostic.get("data_route") or {}
        requires = route.get("requires") or []
        if requires and any(name not in frames for name in requires):
            continue
        defined = route.get("measures") or []
        slot: dict = {}
        if isinstance(defined, dict):
            # Dict-shaped measures are scored by the combination rule.
            # `later` releases load and stay out of the score.
            for name, spec in defined.items():
                if isinstance(spec, dict) and spec.get("release") == "later":
                    slot[name] = {"value": None, "computed": False, "reason": "not_implemented"}
            if slot:
                values[diagnostic["id"]] = slot
            continue
        for measure in defined:
            try:
                value = _call_measure(measure["name"], frames)
            except Exception:
                value = None
            rounded = round_measure(value)
            if rounded is not None:
                slot[measure["name"]] = rounded
        if slot:
            values[diagnostic["id"]] = slot
    return values


def build_measure_evidence(diagnostics: list[dict], frames: dict, owners: dict, pack_version: str) -> list[dict]:
    measured = compute_measures(diagnostics, frames)
    records: list[dict] = []
    for diagnostic in diagnostics:
        slot = measured.get(diagnostic["id"]) or {}
        route = diagnostic.get("data_route") or {}
        requires = route.get("requires") or []
        owner = owners.get(requires[0]) if requires else None
        if owner is None and owners:
            owner = next(iter(owners.values()))
        for name, value in slot.items():
            if isinstance(value, dict):
                if not value.get("computed") or not isinstance(value.get("value"), (int, float)):
                    continue
                value = float(value["value"])
            records.append(
                {
                    "diagnostic_id": diagnostic["id"],
                    "signal_id": name,
                    "source": {
                        "artifact_id": getattr(owner, "artifact_id", "") if owner else "",
                        "file": getattr(owner, "rel_path", "") if owner else "",
                        "location": {"kind": "attribute", "value": name},
                    },
                    "handler": "data",
                    "block": "data_calc",
                    "fact": f"{name} = {value:.4f}",
                    "values": {
                        "measure": name,
                        "value": value,
                        "inputs": list(requires),
                        "data_stage": "model_ready",
                    },
                    "evidence_level": "Verified",
                    "match_strength": "exact",
                    "status": "auto_accepted",
                    "owner_diagnostic": diagnostic["id"],
                    "model_ref": None,
                    "review": {"by": None, "at": None, "decision": None, "reason": None},
                    "pack_version": pack_version,
                    "provisional": False,
                }
            )
    return records
