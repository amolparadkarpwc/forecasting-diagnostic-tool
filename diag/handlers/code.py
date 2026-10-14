"""Parse Python with ast, notebooks as JSON, and SQL as text. Never executes client code."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from diag.handlers.base import ParsedArtifact
from diag.util import read_text

_LABEL_RE = re.compile(r"target|label", re.I)
_Y_ASSIGN_RE = re.compile(r"(^|[^\w])y\s*=")


def _assigned_name(target: ast.AST) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Subscript):
        slice_node = target.slice
        if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
            return slice_node.value
    return None


def _call_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _literal(node: ast.AST):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _literal(node.operand)
        if isinstance(inner, (int, float)) and not isinstance(inner, bool):
            return -inner
    return None


def _classify_role(assigned: str | None, func_name: str | None, line: str) -> str:
    blob = " ".join(part for part in (assigned or "", func_name or "") if part)
    if _LABEL_RE.search(blob):
        return "possible_label"
    if assigned and assigned.lower() in {"y", "yy"}:
        return "possible_label"
    if _Y_ASSIGN_RE.search(line):
        return "possible_label"
    return "feature"


def extract_python(source: str, line_offset: int = 0) -> dict:
    """Walk a syntax tree. Raises SyntaxError when the source does not parse."""
    tree = ast.parse(source)
    lines = source.splitlines()
    calls: list[dict] = []
    imports: list[dict] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.func: str | None = None
            self.assigned: str | None = None

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            previous = self.func
            self.func = node.name
            self.generic_visit(node)
            self.func = previous

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                imports.append({"module": alias.name, "lineno": node.lineno + line_offset, "names": []})

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            imports.append(
                {
                    "module": node.module or "",
                    "lineno": node.lineno + line_offset,
                    "names": [alias.name for alias in node.names],
                }
            )

        def visit_Assign(self, node: ast.Assign) -> None:
            name = next((_assigned_name(target) for target in node.targets if _assigned_name(target)), None)
            previous = self.assigned
            self.assigned = name
            self.visit(node.value)
            self.assigned = previous

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            previous = self.assigned
            self.assigned = _assigned_name(node.target)
            if node.value is not None:
                self.visit(node.value)
            self.assigned = previous

        def visit_Call(self, node: ast.Call) -> None:
            name = _call_name(node.func)
            if name:
                lineno = getattr(node, "lineno", 1)
                line = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""
                args = [_literal(arg) for arg in list(node.args) + [keyword.value for keyword in node.keywords]]
                calls.append(
                    {
                        "name": name,
                        "lineno": lineno + line_offset,
                        "line": line,
                        "args": args,
                        "assigned_to": self.assigned,
                        "function": self.func,
                        "role": _classify_role(self.assigned, self.func, line),
                    }
                )
            self.generic_visit(node)

    Visitor().visit(tree)
    return {"calls": calls, "imports": imports}


def _base_artifact(record: dict, text: str, encoding: str) -> ParsedArtifact:
    return ParsedArtifact(
        artifact_id=record["artifact_id"],
        rel_path=record["path"],
        family="code",
        detected_type=record.get("detected_type") or "python",
        text=text,
        encoding=encoding,
    )


def _parse_notebook(path: Path, record: dict) -> ParsedArtifact | None:
    text, encoding = read_text(path)
    record["encoding"] = encoding
    try:
        notebook = json.loads(text)
    except json.JSONDecodeError as exc:
        record["status"] = "unreadable"
        record["reason"] = f"JSONDecodeError: {exc.msg}"
        return None
    calls: list[dict] = []
    imports: list[dict] = []
    chunks: list[str] = []
    notes: list[str] = []
    offset = 0
    for index, cell in enumerate(notebook.get("cells") or []):
        source = cell.get("source") or ""
        if isinstance(source, list):
            source = "".join(source)
        source = source.replace("\r\n", "\n").replace("\r", "\n")
        if cell.get("cell_type") != "code":
            offset += source.count("\n") + 1
            continue
        chunks.append(source)
        try:
            extracted = extract_python(source, line_offset=offset)
        except SyntaxError as exc:
            notes.append(f"cell {index} not parsed: {exc.msg}")
        else:
            calls.extend(extracted["calls"])
            imports.extend(extracted["imports"])
        offset += source.count("\n") + 1
    if notes:
        record["reason"] = "; ".join(notes)[:300]
    artifact = _base_artifact(record, "\n\n".join(chunks), encoding)
    artifact.calls = calls
    artifact.imports = imports
    return artifact


def parse_code(path: Path, record: dict) -> ParsedArtifact | None:
    detected = record.get("detected_type")
    if detected == "notebook":
        return _parse_notebook(path, record)
    text, encoding = read_text(path)
    record["encoding"] = encoding
    artifact = _base_artifact(record, text, encoding)
    if detected == "sql":
        artifact.sql_text = text
        return artifact
    if detected == "r":
        return artifact
    try:
        extracted = extract_python(text)
    except SyntaxError as exc:
        record["status"] = "unreadable"
        record["reason"] = f"SyntaxError: {exc.msg}"
        return None
    artifact.calls = extracted["calls"]
    artifact.imports = extracted["imports"]
    return artifact
