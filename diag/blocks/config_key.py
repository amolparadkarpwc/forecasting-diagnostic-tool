"""Match flattened config keys and optional value terms."""

from __future__ import annotations

import fnmatch

from diag.blocks.common import Match


def run(parsed, params: dict, vocab: dict, context: dict) -> list[Match]:
    del vocab, context
    globs = [str(item) for item in params.get("key_globs") or []]
    terms = [str(item).lower() for item in params.get("value_terms") or []]
    matches: list[Match] = []
    for key in sorted(parsed.keys):
        if globs and not any(fnmatch.fnmatchcase(str(key), pattern) for pattern in globs):
            continue
        value = parsed.keys[key]
        rendered = "" if value is None else str(value)
        if terms and not any(term in rendered.lower() for term in terms):
            continue
        matches.append(
            Match(
                fact=f"{key} = {rendered}"[:240],
                location={"kind": "key", "value": str(key)},
                values={"key": str(key), "value": rendered[:120]},
                match_strength="exact",
            )
        )
    return matches
