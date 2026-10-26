"""Column lineage classification.

TODO(pack): tracing a column through assignments, renames and imports is not
implemented yet. Until it is, this block records nothing rather than guessing.
"""

from __future__ import annotations

from diag.blocks.common import Match


def run(parsed, params: dict, vocab: dict, context: dict) -> list[Match]:
    return []
