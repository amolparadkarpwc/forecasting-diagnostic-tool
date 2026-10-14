"""Load YAML and JSON configs without executing tags. Bool-like words stay strings."""

from __future__ import annotations

from pathlib import Path

import yaml

from diag.handlers.base import ParsedArtifact
from diag.util import read_text


class NoBoolLoader(yaml.SafeLoader):
    """Safe loader that keeps yes/no/on/off as strings."""


NoBoolLoader.yaml_implicit_resolvers = {
    key: [pair for pair in pairs if pair[0] != "tag:yaml.org,2002:bool"]
    for key, pairs in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def flatten(value: object, prefix: str = "") -> dict:
    flat: dict = {}
    if isinstance(value, dict):
        for key in value:
            child = f"{prefix}.{key}" if prefix else str(key)
            flat.update(flatten(value[key], child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            flat.update(flatten(item, f"{prefix}[{index}]"))
    else:
        flat[prefix] = value
    return flat


def _load(text: str, detected: str) -> object:
    if detected == "json":
        import json

        return json.loads(text)
    if detected == "toml":
        import tomllib

        return tomllib.loads(text)
    if detected == "ini":
        import configparser

        parser = configparser.ConfigParser()
        parser.read_string(text)
        return {section: dict(parser[section]) for section in parser.sections()}
    return yaml.load(text, Loader=NoBoolLoader)


def parse_config(path: Path, record: dict) -> ParsedArtifact:
    text, encoding = read_text(path)
    record["encoding"] = encoding
    loaded = _load(text, record.get("detected_type") or "yaml")
    if not isinstance(loaded, (dict, list)):
        raise ValueError("config root must be a mapping or list")
    return ParsedArtifact(
        artifact_id=record["artifact_id"],
        rel_path=record["path"],
        family="config",
        detected_type=record.get("detected_type") or "yaml",
        text=text,
        encoding=encoding,
        keys=flatten(loaded),
    )
