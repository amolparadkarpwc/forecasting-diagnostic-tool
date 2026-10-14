"""Summarise failure rate from parsed log events."""

from __future__ import annotations

from diag.blocks.common import Match
from diag.util import round_measure

_FAILURES = {"FAILED", "FAILURE", "ERROR"}


def run(parsed, params: dict, vocab: dict, context: dict) -> list[Match]:
    del vocab, context
    if (params.get("metric") or "failure_rate") != "failure_rate":
        return []
    statuses = [str(event.get("status") or "").upper() for event in parsed.events if event.get("status")]
    minimum = int(params.get("min_events") or 1)
    if len(statuses) < minimum:
        return []
    failures = sum(1 for status in statuses if status in _FAILURES)
    rate = failures / len(statuses)
    threshold = float(params.get("threshold"))
    compare = params.get("compare") or "gte"
    matched = rate >= threshold if compare == "gte" else rate <= threshold
    if not matched:
        return []
    return [
        Match(
            fact=f"failure rate {rate:.2f} ({failures}/{len(statuses)} events)",
            location={"kind": "file", "value": parsed.rel_path},
            values={
                "failure_rate": round_measure(rate),
                "failures": failures,
                "events": len(statuses),
            },
            match_strength="exact",
        )
    ]
