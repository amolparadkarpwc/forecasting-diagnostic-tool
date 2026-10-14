"""Generic detectors. They do not know which diagnostic called them."""

from __future__ import annotations

import ast
import fnmatch
from dataclasses import dataclass, field
from typing import Any, Callable

from diag.measures import compare, run_measure
from diag.parsers import ParsedFile, source_line


@dataclass
class Match:
    """One detector hit inside a parsed file."""

    fact: str
    location_kind: str
    location_value: str
    match_strength: str
    values: dict[str, Any] = field(default_factory=dict)


def code_import(parsed: ParsedFile, params: dict[str, Any]) -> list[Match]:
    """Match imported module names."""
    if parsed.tree is None:
        return []
    wanted = {str(name) for name in params.get("modules", [])}
    matches: list[Match] = []
    for node in ast.walk(parsed.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _module_wanted(alias.name, wanted):
                    matches.append(_code_match(parsed, node, alias.name, "exact", {"module": alias.name}))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module and _module_wanted(module, wanted):
                matches.append(_code_match(parsed, node, module, "exact", {"module": module}))
                continue
            for alias in node.names:
                if alias.name in wanted:
                    matches.append(
                        _code_match(parsed, node, alias.name, "exact", {"module": alias.name})
                    )
    return matches


def code_call(parsed: ParsedFile, params: dict[str, Any]) -> list[Match]:
    """Match calls by name, definitions by name, and a few generic AST shapes."""
    if parsed.tree is None:
        return []
    if params.get("parsed") is True:
        return [
            Match(
                fact="Python file parsed",
                location_kind="file",
                location_value="1",
                match_strength="exact",
                values={"parsed": True},
            )
        ]
    if params.get("bare_except_continue") is True:
        return _bare_except_continue(parsed)
    names = {str(name) for name in params.get("names", [])}
    if "name" in params:
        names.add(str(params["name"]))
    if not names:
        return []
    negative = bool(params.get("negative_numeric_literal"))
    string_arg = params.get("string_arg")
    matches: list[Match] = []
    for node in ast.walk(parsed.tree):
        if isinstance(node, ast.Call):
            call_names = _call_names(node)
            if names.isdisjoint(call_names):
                continue
            if negative and not _has_negative_numeric(node):
                continue
            if string_arg is not None and str(string_arg) not in _string_args(node):
                continue
            matched = sorted(names.intersection(call_names))[0]
            strength = "pattern" if negative or string_arg is not None else "exact"
            matches.append(
                _code_match(
                    parsed,
                    node,
                    matched,
                    strength,
                    {
                        "name": matched,
                        "negative_numeric_literal": negative,
                    },
                )
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if negative or string_arg is not None or params.get("calls_only") is True:
                continue
            if node.name in names:
                matches.append(_code_match(parsed, node, node.name, "exact", {"name": node.name}))
    return matches


def config_key(parsed: ParsedFile, params: dict[str, Any]) -> list[Match]:
    """Match flattened config key paths with a glob, optionally checking the value."""
    pattern = str(params.get("key", ""))
    if not pattern or not parsed.flat:
        return []
    matches: list[Match] = []
    for key in sorted(parsed.flat):
        if not fnmatch.fnmatchcase(key, pattern):
            continue
        value = parsed.flat[key]
        if "equals" in params and not _values_equal(value, params["equals"]):
            continue
        matches.append(
            Match(
                fact=f"{key}={_display_value(value)}",
                location_kind="key",
                location_value=key,
                match_strength="exact",
                values={"key": key, "value": value if _json_safe(value) else str(value)},
            )
        )
    return matches


def phrase_search(parsed: ParsedFile, params: dict[str, Any]) -> list[Match]:
    """Case-insensitive phrase search over text and markdown."""
    if parsed.artifact.family != "document":
        return []
    phrases = [str(phrase) for phrase in params.get("phrases", [])]
    matches: list[Match] = []
    for lineno, line in enumerate(parsed.lines, start=1):
        folded = line.casefold()
        for phrase in phrases:
            if phrase.casefold() in folded:
                matches.append(
                    Match(
                        fact=line.strip(),
                        location_kind="line",
                        location_value=str(lineno),
                        match_strength="keyword",
                        values={"phrase": phrase},
                    )
                )
    return matches


def data_calc(parsed: ParsedFile, params: dict[str, Any]) -> list[Match]:
    """Run one named measure. The measure name and threshold come from the pack."""
    if parsed.artifact.family != "data":
        return []
    result = run_measure(parsed, params)
    if not result.get("triggered"):
        return []
    value = result.get("value", 0.0)
    rounded = round(float(value), 4)
    return [
        Match(
            fact=str(result.get("fact", "")),
            location_kind="attribute",
            location_value=str(params.get("measure", "")),
            match_strength="exact",
            values={"measure": params.get("measure"), "value": rounded},
        )
    ]


def log_stats(parsed: ParsedFile, params: dict[str, Any]) -> list[Match]:
    """Count log events whose status is in the requested set."""
    if parsed.artifact.family != "log":
        return []
    wanted = {str(status).upper() for status in params.get("statuses", [])}
    if not wanted:
        return []
    count = sum(1 for event in parsed.events if event.get("status", "").upper() in wanted)
    threshold = float(params.get("threshold", 1))
    op = str(params.get("op", "gte"))
    if not compare(float(count), op, threshold):
        return []
    listed = ",".join(sorted(wanted))
    return [
        Match(
            fact=f"log status count {listed} = {count}",
            location_kind="file",
            location_value="1",
            match_strength="derived",
            values={"count": count, "statuses": sorted(wanted)},
        )
    ]


BLOCKS: dict[str, Callable[[ParsedFile, dict[str, Any]], list[Match]]] = {
    "code_import": code_import,
    "code_call": code_call,
    "config_key": config_key,
    "phrase_search": phrase_search,
    "data_calc": data_calc,
    "log_stats": log_stats,
}


def _module_wanted(module: str, wanted: set[str]) -> bool:
    root = module.split(".")[0]
    return module in wanted or root in wanted


def _call_names(node: ast.Call) -> set[str]:
    func = node.func
    names: set[str] = set()
    if isinstance(func, ast.Name):
        names.add(func.id)
    elif isinstance(func, ast.Attribute):
        names.add(func.attr)
        if isinstance(func.value, ast.Name):
            names.add(f"{func.value.id}.{func.attr}")
    return names


def _has_negative_numeric(node: ast.Call) -> bool:
    values = list(node.args) + [keyword.value for keyword in node.keywords]
    return any(_is_negative_literal(value) for value in values)


def _is_negative_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        operand = node.operand
        if isinstance(operand, ast.Constant) and _is_number(operand.value):
            return float(operand.value) > 0
    if isinstance(node, ast.Constant) and _is_number(node.value):
        return float(node.value) < 0
    return False


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _string_args(node: ast.Call) -> set[str]:
    found: set[str] = set()
    nodes = list(node.args) + [keyword.value for keyword in node.keywords]
    for item in nodes:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            found.add(item.value)
    return found


def _bare_except_continue(parsed: ParsedFile) -> list[Match]:
    if parsed.tree is None:
        return []
    matches: list[Match] = []
    for node in ast.walk(parsed.tree):
        if not isinstance(node, ast.ExceptHandler) or node.type is not None:
            continue
        if len(node.body) == 1 and isinstance(node.body[0], ast.Continue):
            matches.append(
                _code_match(parsed, node, "bare_except_continue", "pattern", {"pattern": "bare_except_continue"})
            )
    return matches


def _code_match(
    parsed: ParsedFile,
    node: ast.AST,
    label: str,
    strength: str,
    values: dict[str, Any],
) -> Match:
    lineno = getattr(node, "lineno", None)
    fact = source_line(parsed, lineno) or label
    return Match(
        fact=fact,
        location_kind="line",
        location_value=str(lineno or 1),
        match_strength=strength,
        values=values,
    )


def _values_equal(actual: Any, expected: Any) -> bool:
    if actual == expected:
        return True
    if isinstance(expected, bool) and isinstance(actual, str):
        return actual.strip().lower() == ("true" if expected else "false")
    return False


def _display_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _json_safe(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))
