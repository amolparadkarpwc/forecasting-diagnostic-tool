"""Read CSV files and map obvious columns onto sales_history or past_forecasts."""

from __future__ import annotations

import re
from pathlib import Path

from diag.handlers.base import ParsedArtifact

_SERIES = ["series_id", "series", "sku", "sku_id", "item", "item_id", "product", "product_id"]
_DATE = ["date", "ds", "period", "month", "week"]
_ACTUAL = ["actual", "actuals", "sales", "qty", "quantity", "demand", "units", "volume", "y"]
_RUN = ["run_date", "forecast_origin", "origin", "as_of_date", "as_of"]
_TARGET = ["target_date", "horizon_date", "forecast_target_date", "forecast_date"]
_FORECAST = ["forecast", "forecast_value", "yhat", "prediction", "predicted", "y_pred"]


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def _pick(columns: list[str], candidates: list[str], used: set[str]) -> str | None:
    lookup = {_norm(column): column for column in columns}
    for candidate in candidates:
        original = lookup.get(candidate)
        if original is not None and original not in used:
            return original
    return None


def _read_table(path: Path):
    import pandas as pd

    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            frame = pd.read_csv(path, dtype=str, encoding=encoding)
            return frame, ("utf-8" if encoding == "utf-8-sig" else encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise ValueError("CSV could not be decoded")


def _span(series) -> str:
    import pandas as pd

    values = pd.to_datetime(series, errors="coerce").dropna()
    if values.empty:
        return ""
    return f"{values.min().date().isoformat()} to {values.max().date().isoformat()}"


def standardise(frame):
    import pandas as pd

    columns = [str(column).strip() for column in frame.columns]
    frame = frame.copy()
    frame.columns = columns
    series = _pick(columns, _SERIES, set())
    forecast = _pick(columns, _FORECAST, {series} if series else set())
    if series and forecast:
        used = {series, forecast}
        target = _pick(columns, _TARGET, used) or _pick(columns, _DATE, used)
        run = _pick(columns, _RUN, used | ({target} if target else set()))
        if target:
            out = pd.DataFrame(
                {
                    "series_id": frame[series],
                    "run_date": frame[run] if run else frame[target],
                    "target_date": frame[target],
                    "forecast": frame[forecast],
                }
            )
            return "past_forecasts", out
    series = _pick(columns, _SERIES, set())
    date = _pick(columns, _DATE, {series} if series else set())
    actual = _pick(columns, _ACTUAL, {series, date} - {None})
    if series and date and actual:
        out = pd.DataFrame({"series_id": frame[series], "date": frame[date], "actual": frame[actual]})
        return "sales_history", out
    return None, None


def parse_data(path: Path, record: dict) -> ParsedArtifact:
    frame, encoding = _read_table(path)
    record["encoding"] = encoding
    if frame.empty or len(frame.columns) == 0:
        raise ValueError("CSV has no rows")
    data_format, standard = standardise(frame)
    artifact = ParsedArtifact(
        artifact_id=record["artifact_id"],
        rel_path=record["path"],
        family="data",
        detected_type=record.get("detected_type") or "csv",
        encoding=encoding,
        data_format=data_format,
        frame=standard,
    )
    if data_format is None:
        record["status"] = "manual_review"
        record["reason"] = "CSV columns did not match sales_history or past_forecasts"
        return artifact
    date_column = "date" if data_format == "sales_history" else "target_date"
    record["period_covered"] = _span(standard[date_column])
    return artifact
