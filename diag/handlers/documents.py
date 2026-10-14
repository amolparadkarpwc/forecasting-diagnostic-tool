"""Document handler for txt, markdown, and docx. PDFs are left for review."""

from __future__ import annotations

import re
from pathlib import Path

from diag.handlers.base import ParsedArtifact
from diag.util import read_text


def _sections_from_markdown(text: str) -> list[dict]:
    sections: list[dict] = []
    current = {"title": "", "line": 1, "lines": []}
    for index, line in enumerate(text.splitlines(), start=1):
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            if current["lines"] or current["title"]:
                sections.append(
                    {
                        "title": current["title"],
                        "line": current["line"],
                        "text": "\n".join(current["lines"]).strip(),
                    }
                )
            current = {"title": heading.group(2).strip(), "line": index, "lines": []}
        else:
            current["lines"].append(line)
    if current["lines"] or current["title"]:
        sections.append(
            {"title": current["title"], "line": current["line"], "text": "\n".join(current["lines"]).strip()}
        )
    return sections or [{"title": "", "line": 1, "text": text}]


def _read_docx(path: Path) -> str:
    try:
        import docx
    except ImportError as exc:
        raise RuntimeError("python-docx is not installed") from exc
    document = docx.Document(str(path))
    lines: list[str] = []
    for paragraph in document.paragraphs:
        style = paragraph.style.name if paragraph.style is not None and paragraph.style.name else ""
        text = paragraph.text or ""
        if style.startswith("Heading") and text:
            level = style.replace("Heading", "").strip()
            depth = int(level) if level.isdigit() else 1
            lines.append(f"{'#' * max(1, min(depth, 6))} {text}")
        else:
            lines.append(text)
    return "\n".join(lines)


def parse_document(path: Path, record: dict) -> ParsedArtifact:
    if record.get("detected_type") == "docx":
        text = _read_docx(path).replace("\r\n", "\n").replace("\r", "\n")
        encoding = ""
    else:
        text, encoding = read_text(path)
        record["encoding"] = encoding
    return ParsedArtifact(
        artifact_id=record["artifact_id"],
        rel_path=record["path"],
        family="document",
        detected_type=record.get("detected_type") or "txt",
        text=text,
        encoding=encoding,
        sections=_sections_from_markdown(text),
    )
