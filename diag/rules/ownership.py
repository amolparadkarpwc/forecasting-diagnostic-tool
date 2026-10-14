"""Every signal has exactly one owner."""


def validate_ownership(diagnostics: list[dict]) -> None:
    errors: list[str] = []
    for diagnostic in diagnostics:
        for signal_id, signal in (diagnostic.get("signals") or {}).items():
            owner = signal.get("owner")
            if not isinstance(owner, str) or not owner.strip():
                errors.append(f"{diagnostic['id']}.{signal_id} has no owner")
            elif owner != diagnostic["id"]:
                errors.append(f"{diagnostic['id']}.{signal_id} owner must be {diagnostic['id']} in this MVP")
    if errors:
        raise ValueError("knowledge pack ownership: " + "; ".join(errors))
