"""Apply a regular expression with named groups to text."""

from __future__ import annotations

import re

from diag.blocks.common import Match, location_at


def run(parsed, params: dict, vocab: dict, context: dict) -> list[Match]:
    del vocab, context
    pattern = params.get("pattern")
    if not pattern:
        return []
    text = parsed.text or ""
    matches: list[Match] = []
    for found in re.finditer(pattern, text):
        line_no = text.count("\n", 0, found.start()) + 1
        fact = " ".join(found.group(0).split())[:240]
        matches.append(
            Match(
                fact=fact,
                location=location_at(parsed, found.start(), line_no),
                values={key: value for key, value in found.groupdict().items() if value is not None},
                match_strength="pattern",
            )
        )
        if len(matches) >= 10:
            break
    return matches
