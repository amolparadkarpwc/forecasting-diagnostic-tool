"""Extract document tables whose headers match an expected set.

TODO(pack): header matching against document tables is not implemented yet.
The block returns nothing rather than a guessed table.
"""

from __future__ import annotations

from diag.blocks.common import Match


def run(parsed, params: dict, vocab: dict, context: dict) -> list[Match]:
    return []
