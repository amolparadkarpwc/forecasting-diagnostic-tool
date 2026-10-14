"""Named data measures used by the data_calc detector.

Thresholds stay in the knowledge pack. These functions only compute values.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from diag.parsers import ParsedFile


def columns_present(parsed: ParsedFile, params: dict[str, Any]) -> dict[str, Any]:
    """Whether every required column is in the header."""
    required = [str(name) for name in params.get("required_columns", [])]
    present = all(name in parsed.fieldnames for name in required)
    return {
        "value": 100.0 if present else 0.0,
        "triggered": present and bool(required),
        "fact": "columns present: " + ", ".join(required),
    }


def duplicate_rate(parsed: ParsedFile, params: dict[str, Any]) -> dict[str, Any]:
    """Percent of rows that repeat a key such as (series_id, date)."""
    keys = [str(name) for name in params.get("key_columns", ["series_id", "date"])]
    if not _has_columns(parsed, keys):
        return _not_triggered("duplicate_rate")
    pairs = [tuple(row.get(key, "") for key in keys) for row in parsed.rows]
    total = len(pairs)
    extra = total - len(set(pairs))
    rate = (100.0 * extra / total) if total else 0.0
    return _valued("duplicate_rate", rate, params, f"duplicate rate of ({', '.join(keys)}) is {rate:.4f}%")


def missing_monthly_pct(parsed: ParsedFile, params: dict[str, Any]) -> dict[str, Any]:
    """Percent of months missing between each series min and max date."""
    needed = ["series_id", "date"]
    if not _has_columns(parsed, needed):
        return _not_triggered("missing_monthly_pct")
    grouped: dict[str, set[tuple[int, int]]] = {}
    for row in parsed.rows:
        parsed_date = _parse_date(row.get("date", ""))
        if parsed_date is None:
            continue
        grouped.setdefault(row.get("series_id", ""), set()).add((parsed_date.year, parsed_date.month))
    expected = 0
    missing = 0
    for months in grouped.values():
        if not months:
            continue
        span = _month_span(min(months), max(months))
        expected += len(span)
        missing += len(set(span) - months)
    rate = (100.0 * missing / expected) if expected else 0.0
    return _valued(
        "missing_monthly_pct",
        rate,
        params,
        f"missing monthly periods are {rate:.4f}%",
    )


def null_or_negative_pct(parsed: ParsedFile, params: dict[str, Any]) -> dict[str, Any]:
    """Percent of values in a column that are blank or negative."""
    column = str(params.get("column", "actual"))
    if column not in parsed.fieldnames:
        return _not_triggered("null_or_negative_pct")
    total = len(parsed.rows)
    bad = sum(1 for row in parsed.rows if _is_null_or_negative(row.get(column, "")))
    rate = (100.0 * bad / total) if total else 0.0
    return _valued(
        "null_or_negative_pct",
        rate,
        params,
        f"null or negative {column} values are {rate:.4f}%",
    )


MEASURES: dict[str, Callable[[ParsedFile, dict[str, Any]], dict[str, Any]]] = {
    "columns_present": columns_present,
    "duplicate_rate": duplicate_rate,
    "missing_monthly_pct": missing_monthly_pct,
    "null_or_negative_pct": null_or_negative_pct,
}


def run_measure(parsed: ParsedFile, params: dict[str, Any]) -> dict[str, Any]:
    """Run the named measure. Unknown names do not match."""
    name = str(params.get("measure", ""))
    function = MEASURES.get(name)
    if function is None:
        return _not_triggered(name or "unknown")
    return function(parsed, params)


def _valued(name: str, rate: float, params: dict[str, Any], fact: str) -> dict[str, Any]:
    threshold = float(params.get("threshold", 0))
    op = str(params.get("op", "gt"))
    return {
        "value": rate,
        "triggered": compare(rate, op, threshold),
        "fact": fact,
        "measure": name,
    }


def _not_triggered(name: str) -> dict[str, Any]:
    return {"value": 0.0, "triggered": False, "fact": name, "measure": name}


def compare(value: float, op: str, threshold: float) -> bool:
    """Compare a measure with a pack threshold."""
    if op == "gt":
        return value > threshold
    if op == "gte":
        return value >= threshold
    if op == "lt":
        return value < threshold
    if op == "lte":
        return value <= threshold
    if op == "eq":
        return value == threshold
    raise ValueError(f"unknown comparison {op}")


def _has_columns(parsed: ParsedFile, columns: list[str]) -> bool:
    return all(column in parsed.fieldnames for column in columns)


def _is_null_or_negative(value: str) -> bool:
    text = value.strip()
    if text == "":
        return True
    try:
        number = float(text)
    except ValueError:
        return True
    return number < 0


def _parse_date(value: str) -> date | None:
    text = value.strip()
    if not text:
        return None
    try:
        if len(text) == 7:
            year, month = text.split("-")
            return date(int(year), int(month), 1)
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _month_span(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    year, month = start
    months: list[tuple[int, int]] = []
    while (year, month) <= end:
        months.append((year, month))
        month += 1
        if month == 13:
            month = 1
            year += 1
    return months
