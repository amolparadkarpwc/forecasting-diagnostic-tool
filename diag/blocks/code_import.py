"""Detect imported Python modules. Never executes the file."""

from __future__ import annotations

from diag.blocks.common import Match


def run(parsed, params: dict, vocab: dict, context: dict) -> list[Match]:
    if getattr(parsed, "family", "") != "code":
        return []
    wanted = {str(name) for name in (params.get("modules") or [])}
    if not wanted:
        return []
    matches = []
    for imported in (parsed.parsed or {}).get("imports") or []:
        module = str(imported.get("module") or "")
        root = module.split(".")[0]
        if module in wanted or root in wanted:
            matches.append(
                Match(
                    fact=f"imports {module}",
                    location={"kind": "line", "value": str(imported.get("lineno") or "")},
                    values={"module": module},
                    match_strength="exact",
                )
            )
    return matches
