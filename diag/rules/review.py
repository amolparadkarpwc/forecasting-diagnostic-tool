"""Initial review status from a knowledge-pack policy."""

POLICIES = {
    "none": "auto_accepted",
    "count_and_flag": "counted_flagged",
    "block": "needs_review",
    "needs_review": "needs_review",
    # Counts toward the score, but cannot meet a gate trigger until review.
    "block_for_gate": "blocked_for_gate",
}

COUNTED = {"auto_accepted", "counted_flagged", "confirmed", "resolved", "blocked_for_gate"}


def initial_status(policy: str | None) -> str:
    try:
        return POLICIES[policy or "none"]
    except KeyError as exc:
        raise ValueError(f"unknown review policy: {policy}") from exc
