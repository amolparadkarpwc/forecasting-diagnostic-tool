"""Match SQL text with a regular expression. This is not a SQL parser."""

from __future__ import annotations

import re

from diag.blocks.common import Match


def run(parsed, params: dict, vocab: dict, context: dict) -> list[Match]:
    del vocab, context
    pattern = params.get("pattern")
    if not pattern:
        return []
    text = parsed.sql_text or parsed.text or ""
    matches: list[Match] = []
    for found in re.finditer(pattern, text):
        line_no = text.count("\n", 0, found.start()) + 1
        fact = " ".join(found.group(0).split())[:240]
        groups = {key: value for key, value in found.groupdict().items() if value is not None}
        matches.append(
            Match(
                fact=fact,
                location={"kind": "line", "value": str(line_no)},
                values=groups,
                match_strength="pattern",
            )
        )
        if len(matches) >= 10:
            break
    return matches
