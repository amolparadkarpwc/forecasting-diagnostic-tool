"""Choose the evidence route for a diagnostic."""

LEVEL_RANK = {"Verified": 3, "Inferred": 2, "Attested": 1}


def best_level(records: list[dict]) -> str | None:
    chosen = None
    rank = 0
    for record in records:
        current = LEVEL_RANK.get(record.get("evidence_level") or "", 0)
        if current > rank:
            chosen = record["evidence_level"]
            rank = current
    return chosen


def choose_route(records: list[dict], used_data: bool) -> str:
    if used_data:
        return "data"
    level = best_level(records)
    if level == "Verified":
        return "inspected"
    if level == "Inferred":
        return "inferred"
    if level == "Attested":
        return "document"
    return "none"
