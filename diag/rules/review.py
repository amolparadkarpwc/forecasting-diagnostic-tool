"""Initial review status from a knowledge-pack policy."""

POLICIES = {
    "none": "auto_accepted",
    "count_and_flag": "counted_flagged",
    "block": "needs_review",
}

COUNTED = {"auto_accepted", "counted_flagged", "confirmed", "resolved"}


def initial_status(policy: str | None) -> str:
    try:
        return POLICIES[policy or "none"]
    except KeyError as exc:
        raise ValueError(f"unknown review policy: {policy}") from exc
