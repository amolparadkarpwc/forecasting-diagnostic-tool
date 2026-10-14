"""Match Python calls recorded by the ast walker."""

from __future__ import annotations

from diag.blocks.common import Match, json_safe


def _negative(args: list) -> bool:
    return any(isinstance(arg, (int, float)) and not isinstance(arg, bool) and arg < 0 for arg in args)


def _contains_ignore(args: list) -> bool:
    return any(isinstance(arg, str) and "ignore" in arg.lower() for arg in args)


def run(parsed, params: dict, vocab: dict, context: dict) -> list[Match]:
    del vocab, context
    names = set(params.get("names") or [])
    condition = params.get("arg_condition")
    role = params.get("role")
    matches: list[Match] = []
    for call in parsed.calls:
        if names and call.get("name") not in names:
            continue
        if role and call.get("role") != role:
            continue
        args = call.get("args") or []
        if condition == "negative_literal" and not _negative(args):
            continue
        if condition == "contains_ignore" and not _contains_ignore(args):
            continue
        matches.append(
            Match(
                fact=(call.get("line") or call.get("name") or "")[:240],
                location={"kind": "line", "value": str(call.get("lineno") or "")},
                values=json_safe(
                    {
                        "name": call.get("name"),
                        "role": call.get("role"),
                        "assigned_to": call.get("assigned_to"),
                        "args": args,
                    }
                ),
                match_strength="pattern",
            )
        )
    matches.sort(key=lambda item: (item.location["value"], item.fact))
    return matches
