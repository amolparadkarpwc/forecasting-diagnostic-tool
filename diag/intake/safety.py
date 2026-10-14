"""Scan pickle bytes with pickletools. Never unpickles."""

from __future__ import annotations

import pickletools
from pathlib import Path


DANGEROUS_MODULES = {"os", "subprocess", "sys", "nt", "posix", "shutil"}
DANGEROUS_ATTRS = {
    "system",
    "popen",
    "exec",
    "eval",
    "execl",
    "execve",
    "spawn",
    "check_output",
    "Popen",
    "remove",
    "unlink",
}

STRING_OPS = {
    "STRING",
    "BINSTRING",
    "SHORT_BINSTRING",
    "UNICODE",
    "BINUNICODE",
    "SHORT_BINUNICODE",
    "BINUNICODE8",
}


class PickleScanError(Exception):
    pass


def _as_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("latin-1")
    return None


def _is_mark_descriptor(item: object) -> bool:
    return getattr(item, "name", None) == "mark" or str(item) == "mark"


def scan_pickle_bytes(data: bytes) -> tuple[set[str], set[tuple[str, str]], str | None]:
    """Return (modules, (module, name) pairs, error).

    Memo entries store whatever is on the stack, including non-strings, so a
    later MEMOIZE cannot be confused with an earlier string.
    """
    stack: list[object] = []
    memo: dict[int, object] = {}
    modules: set[str] = set()
    globals_found: set[tuple[str, str]] = set()
    mark = ("MARK",)

    def push(value: object) -> None:
        stack.append(value)

    def pop() -> object:
        if not stack:
            raise PickleScanError("stack underflow")
        return stack.pop()

    def remember(key: int) -> None:
        if not stack:
            raise PickleScanError("memo without a stack value")
        memo[key] = stack[-1]

    def note_global(module: object, name: object) -> None:
        mod = module if isinstance(module, str) else "UNKNOWN_NONSTRING"
        attr = name if isinstance(name, str) else ""
        modules.add(mod)
        globals_found.add((mod, attr))
        push(("GLOBAL", mod, attr))

    try:
        for opcode, arg, _pos in pickletools.genops(data):
            name = opcode.name
            if name == "MEMOIZE":
                remember(len(memo))
                continue
            if name in {"PUT", "BINPUT", "LONG_BINPUT"}:
                remember(int(arg))
                continue
            if name in {"GET", "BINGET", "LONG_BINGET"}:
                key = int(arg)
                push(memo.get(key, ("MISSING",)))
                continue
            if name == "GLOBAL":
                text = str(arg or "")
                module, _, attr = text.partition(" ")
                note_global(module, attr)
                continue
            if name == "INST":
                text = str(arg or "")
                module, _, attr = text.partition(" ")
                modules.add(module or "UNKNOWN_NONSTRING")
                globals_found.add((module or "UNKNOWN_NONSTRING", attr))
                # INST still consumes the mark slice; fall through to stack effect below
                # after recording the reference. Re-handle via generic path by not continuing
                # only when stack_before is present. Recorded above; still apply stack effect.
            if name == "STACK_GLOBAL":
                attr = pop()
                module = pop()
                note_global(module, attr)
                continue
            if name == "MARK":
                push(mark)
                continue
            if name == "POP":
                pop()
                continue
            if name == "POP_MARK":
                while stack and stack[-1] is not mark:
                    pop()
                if stack and stack[-1] is mark:
                    pop()
                continue
            if name == "DUP":
                if not stack:
                    raise PickleScanError("dup on empty stack")
                push(stack[-1])
                continue
            if name in STRING_OPS:
                text = _as_text(arg)
                push(text if text is not None else ("NONSTR",))
                continue
            if name == "INST":
                before = list(opcode.stack_before or [])
            else:
                before = list(opcode.stack_before or [])
            if any(_is_mark_descriptor(item) for item in before):
                while stack and stack[-1] is not mark:
                    pop()
                if stack and stack[-1] is mark:
                    pop()
                mark_at = next(index for index, item in enumerate(before) if _is_mark_descriptor(item))
                for _ in range(mark_at):
                    pop()
                for _ in opcode.stack_after or []:
                    push(("NONSTR",))
                continue
            for _ in before:
                pop()
            for _ in opcode.stack_after or []:
                push(("NONSTR",))
    except PickleScanError as exc:
        return modules, globals_found, str(exc)
    except Exception as exc:
        return modules, globals_found, f"{type(exc).__name__}: {exc}"
    return modules, globals_found, None


def module_allowed(module: str, allowlist: list[str]) -> bool:
    if not module or module.startswith("UNKNOWN"):
        return False
    for item in allowlist:
        if module == item or module.startswith(item + "."):
            return True
    return False


def dangerous_global(module: str, attr: str) -> bool:
    return module in DANGEROUS_MODULES | {"builtins", "__builtin__"} and attr in DANGEROUS_ATTRS


def assess_model(path: Path, detected_type: str, allowlist: list[str]) -> tuple[str, str]:
    """Return inventory status and reason. Does not load the model."""
    if detected_type == "onnx":
        return "manual_review", "ONNX inspection is not implemented in this MVP"
    if detected_type not in {"pickle", "joblib"}:
        return "readable", ""
    try:
        data = path.read_bytes()
    except OSError as exc:
        return "unreadable", f"OSError: {exc}"
    if detected_type == "joblib" and not (len(data) >= 2 and data[0] == 0x80):
        return "manual_review", "joblib file was not a recognisable pickle; it was not loaded"
    modules, globals_found, error = scan_pickle_bytes(data)
    if error:
        return "quarantined", f"pickle scan failed: {error}"
    disallowed = sorted(module for module in modules if not module_allowed(module, allowlist))
    risky = sorted(
        f"{module}.{attr}" for module, attr in globals_found if dangerous_global(module, attr) and module not in disallowed
    )
    if disallowed or risky:
        detail = ", ".join(disallowed + risky)
        return "quarantined", f"disallowed pickle reference: {detail}"
    if not modules:
        return "manual_review", "pickletools found no external modules; model was not unpickled"
    return "manual_review", "pickletools scan matched the allowlist; model was not unpickled in this MVP"
