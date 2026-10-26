"""Scan pickle bytes, then load only references the allowlist already accepted.

The restricted unpickler refuses a class the static scan did not allow. It does
not call predict, fit, or any other model method. ONNX files are parsed and
not executed.
"""

from __future__ import annotations

import pickle
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


# Attributes that turn an allowlisted module into code execution during unpickling.
_UNPICKLE_BLOCKED = DANGEROUS_ATTRS | {
    "getattr",
    "setattr",
    "delattr",
    "open",
    "compile",
    "__import__",
    "breakpoint",
    "input",
    "globals",
    "locals",
    "vars",
}


class AllowlistUnpickler(pickle.Unpickler):
    """Rebuild a pickle only from modules the engagement allowlist names."""

    def __init__(self, file, allowlist: list[str]) -> None:
        super().__init__(file)
        self._allowlist = allowlist

    def find_class(self, module: str, name: str):
        blocked = (
            name in _UNPICKLE_BLOCKED
            or dangerous_global(module, name)
            or not module_allowed(module, self._allowlist)
        )
        if blocked:
            raise pickle.UnpicklingError(f"blocked reference {module}.{name}")
        return super().find_class(module, name)


def load_allowlisted(data: bytes, allowlist: list[str]):
    """Reconstruct one allowlisted object. Does not call it."""
    import io

    return AllowlistUnpickler(io.BytesIO(data), allowlist).load()


def _model_summary(obj: object) -> str:
    kind = type(obj)
    module = kind.__module__ or ""
    parts = [f"loaded {module}.{kind.__name__}; the model was not called"]
    params = None
    if module.startswith(("sklearn", "xgboost", "lightgbm", "statsmodels", "prophet")):
        getter = getattr(kind, "get_params", None)
        if callable(getter):
            try:
                params = obj.get_params(deep=False)
            except Exception:
                params = None
    if isinstance(params, dict) and params:
        shown = ", ".join(f"{key}={params[key]!r}" for key in sorted(params)[:12])
        parts.append(f"params: {shown}")
    elif isinstance(obj, dict):
        parts.append("keys: " + ", ".join(sorted(str(key) for key in obj)[:12]))
    return "; ".join(parts)[:500]


def _scan_gate(data: bytes, allowlist: list[str]) -> tuple[str, str] | None:
    """Return a rejection, or None when the bytes may be reconstructed."""
    modules, globals_found, error = scan_pickle_bytes(data)
    if error:
        return "quarantined", f"pickle scan failed: {error}"
    disallowed = sorted(module for module in modules if not module_allowed(module, allowlist))
    risky = sorted(
        f"{module}.{attr}"
        for module, attr in globals_found
        if dangerous_global(module, attr) and module not in disallowed
    )
    if disallowed or risky:
        detail = ", ".join(disallowed + risky)
        return "quarantined", f"disallowed pickle reference: {detail}"
    return None


def _reconstruct(data: bytes, allowlist: list[str]) -> tuple[str, str]:
    rejection = _scan_gate(data, allowlist)
    if rejection is not None:
        return rejection
    try:
        obj = load_allowlisted(data, allowlist)
    except pickle.UnpicklingError as exc:
        return "quarantined", f"restricted unpickler blocked the model: {exc}"
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        return "manual_review", f"allowlist matched but the model was not loaded: {detail[:240]}"
    return "readable", _model_summary(obj)


def _read_varint(data: bytes, index: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while index < len(data):
        byte = data[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, index
        shift += 7
        if shift > 70:
            break
    raise ValueError("truncated protobuf")


def _protobuf_fields(data: bytes) -> list[tuple[int, int, object]]:
    """Walk a protobuf message. Length-delimited values stay as bytes."""
    fields: list[tuple[int, int, object]] = []
    index = 0
    size = len(data)
    while index < size:
        key, index = _read_varint(data, index)
        field, wire = key >> 3, key & 7
        if field == 0:
            raise ValueError("invalid protobuf field")
        if wire == 0:
            value, index = _read_varint(data, index)
        elif wire == 1:
            if index + 8 > size:
                raise ValueError("truncated protobuf")
            value = data[index : index + 8]
            index += 8
        elif wire == 5:
            if index + 4 > size:
                raise ValueError("truncated protobuf")
            value = data[index : index + 4]
            index += 4
        elif wire == 2:
            length, index = _read_varint(data, index)
            if length < 0 or index + length > size:
                raise ValueError("truncated protobuf")
            value = data[index : index + length]
            index += length
        else:
            raise ValueError("unsupported protobuf wire type")
        fields.append((field, wire, value))
    return fields


def _proto_text(value: object) -> str:
    if not isinstance(value, bytes):
        return ""
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    if not text or any(ord(char) < 32 for char in text):
        return ""
    return text


def inspect_onnx(path: Path) -> tuple[str, str]:
    """Read input, output, and operator names from an ONNX protobuf. Does not execute it."""
    try:
        fields = _protobuf_fields(path.read_bytes())
    except (OSError, ValueError):
        return "unreadable", "ONNX model could not be parsed"
    graphs = [value for field, wire, value in fields if field == 7 and wire == 2 and isinstance(value, bytes)]
    if not graphs:
        return "unreadable", "ONNX model could not be parsed"
    try:
        graph = _protobuf_fields(graphs[0])
    except ValueError:
        return "unreadable", "ONNX model could not be parsed"
    ops: set[str] = set()
    inputs: list[str] = []
    outputs: list[str] = []
    for field, wire, value in graph:
        if wire != 2 or not isinstance(value, bytes):
            continue
        try:
            nested = _protobuf_fields(value)
        except ValueError:
            continue
        if field == 1:
            for child, child_wire, child_value in nested:
                if child == 4 and child_wire == 2:
                    text = _proto_text(child_value)
                    if text:
                        ops.add(text)
        elif field == 11:
            name = next((_proto_text(child_value) for child, child_wire, child_value in nested if child == 1 and child_wire == 2), "")
            if name:
                inputs.append(name)
        elif field == 12:
            name = next((_proto_text(child_value) for child, child_wire, child_value in nested if child == 1 and child_wire == 2), "")
            if name:
                outputs.append(name)
    if not ops and not inputs and not outputs:
        return "unreadable", "ONNX model could not be parsed"
    op_text = ", ".join(sorted(ops)[:20]) if ops else "none"
    return (
        "readable",
        f"ONNX graph with {len(inputs)} input(s), {len(outputs)} output(s), ops: {op_text}; the model was not executed",
    )


def _inspect_joblib_zip(path: Path, allowlist: list[str]) -> tuple[str, str]:
    import zipfile

    try:
        with zipfile.ZipFile(path) as handle:
            names = sorted(handle.namelist())
            pickles = [name for name in names if name.lower().endswith((".pkl", ".pickle"))]
            payload = handle.read(pickles[0]) if pickles else None
    except (zipfile.BadZipFile, OSError) as exc:
        return "unreadable", f"joblib archive could not be read: {type(exc).__name__}"
    if payload is None:
        return "readable", f"joblib archive with {len(names)} member(s); no pickle member was loaded"
    status, reason = _reconstruct(payload, allowlist)
    return status, f"joblib member {pickles[0]}: {reason}"


def assess_model(path: Path, detected_type: str, allowlist: list[str]) -> tuple[str, str]:
    """Return inventory status and reason."""
    if detected_type == "onnx":
        return inspect_onnx(path)
    if detected_type not in {"pickle", "joblib"}:
        return "readable", ""
    try:
        data = path.read_bytes()
    except OSError as exc:
        return "unreadable", f"OSError: {exc}"
    if detected_type == "joblib" and not (len(data) >= 2 and data[0] == 0x80):
        if data.startswith(b"PK"):
            return _inspect_joblib_zip(path, allowlist)
        return "manual_review", "joblib file was not a recognisable pickle; it was not loaded"
    return _reconstruct(data, allowlist)
