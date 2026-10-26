"""Teams meeting transcripts: WebVTT and plain-text speaker cues.

Searchable text is the utterance only. Cue settings and timestamps stay on the
section so evidence can point at the cue.
"""

from __future__ import annotations

import re
from typing import Any

from diag.handlers.base import ParsedArtifact

_CLOCK = r"\d{1,2}:\d{2}(?::\d{2})?(?:\.\d{1,3})?"
_NAME = r"(?:[A-Z][\w.'-]*)(?:\s+[A-Z0-9][\w.'-]*){0,4}"
_SPEAKER_LINE = re.compile(rf"^(?P<speaker>{_NAME})\s+(?P<ts>{_CLOCK})\s*$")
_TIME_FIRST = re.compile(rf"^(?P<ts>{_CLOCK})\s+(?P<speaker>{_NAME})\s*$")
_BRACKET = re.compile(
    rf"^\[(?P<ts>{_CLOCK})\]\s*(?:(?P<speaker>{_NAME})\s*:\s*)?(?P<text>\S.*)$"
)
_VOICE_TAG = re.compile(r"<v(?:\.[^\s>]+)?(?:\s+[^>]+)?>", re.I)
_VOICE_SPAN = re.compile(r"<v(?:\.[^\s>]+)?(?:\s+([^>]*))?>(.*?)</v>", re.I | re.S)
_CUE_TIME = re.compile(
    r"(?P<start>(?:\d+:)?\d{2}:\d{2}(?:\.\d{1,3})?)\s*-->\s*"
    r"(?P<end>(?:\d+:)?\d{2}:\d{2}(?:\.\d{1,3})?)"
)
_MARKUP = re.compile(r"<[^>]+>")


def looks_like_vtt(text: str) -> bool:
    """True when the file is a WebVTT transcript, regardless of extension."""
    return text.lstrip("\ufeff").lstrip().upper().startswith("WEBVTT")


def looks_like_transcript(text: str) -> bool:
    """True for WebVTT, voice tags, or Teams speaker/timestamp lines with a body."""
    if looks_like_vtt(text):
        return True
    if _VOICE_TAG.search(text):
        return True
    pending = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _SPEAKER_LINE.match(line) or _TIME_FIRST.match(line):
            pending = True
            continue
        if _BRACKET.match(line):
            return True
        if pending:
            return True
        pending = False
    return False


def parse_transcript(record: dict[str, Any], text: str, encoding: str = "") -> ParsedArtifact:
    """Parse a transcript into speaker, timestamp, and utterance sections."""
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    cues = _parse_vtt(normalised) if looks_like_vtt(normalised) else []
    if not cues:
        cues = _parse_teams(normalised)
    if not cues:
        fallback = _fallback_text(normalised)
        if fallback:
            cues = [{"speaker": "", "timestamp": "", "text": fallback}]
    return _artifact(record, cues, encoding)


def _parse_vtt(text: str) -> list[dict[str, str]]:
    lines = text.split("\n")
    if lines:
        lines[0] = lines[0].lstrip("\ufeff")
    index = 0
    if index < len(lines) and lines[index].strip().upper().startswith("WEBVTT"):
        index += 1
        while index < len(lines) and lines[index].strip():
            index += 1
    cues: list[dict[str, str]] = []
    while index < len(lines):
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines):
            break
        word = lines[index].strip().split(" ", 1)[0].upper()
        if word in {"NOTE", "STYLE", "REGION"}:
            index += 1
            while index < len(lines) and lines[index].strip():
                index += 1
            continue
        timing_at = index
        if "-->" not in lines[index] and index + 1 < len(lines) and "-->" in lines[index + 1]:
            timing_at = index + 1
        if "-->" not in lines[timing_at]:
            index += 1
            continue
        timing = _CUE_TIME.search(lines[timing_at])
        timestamp = timing.group("start") if timing else ""
        index = timing_at + 1
        payload: list[str] = []
        while index < len(lines) and lines[index].strip():
            payload.append(lines[index])
            index += 1
        speaker, utterance = _strip_markup("\n".join(payload))
        if utterance:
            cues.append({"speaker": speaker, "timestamp": timestamp, "text": utterance})
    return cues


def _parse_teams(text: str) -> list[dict[str, str]]:
    lines = text.split("\n")
    if _VOICE_TAG.search(text) and not any(_is_header(line.strip()) for line in lines):
        voiced = _cues_from_voice(text)
        if voiced:
            return voiced
    cues: list[dict[str, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        bracket = _BRACKET.match(line)
        if bracket:
            speaker = (bracket.group("speaker") or "").strip()
            utterance = _strip_markup(bracket.group("text") or "")[1]
            if utterance:
                cues.append({"speaker": speaker, "timestamp": bracket.group("ts"), "text": utterance})
            index += 1
            continue
        header = _SPEAKER_LINE.match(line) or _TIME_FIRST.match(line)
        if header:
            speaker = header.group("speaker").strip()
            timestamp = header.group("ts")
            index += 1
            body: list[str] = []
            while index < len(lines) and not _is_header(lines[index].strip()):
                stripped = lines[index].strip()
                if stripped:
                    body.append(stripped)
                index += 1
            utterance = _strip_markup("\n".join(body))[1]
            if utterance:
                cues.append({"speaker": speaker, "timestamp": timestamp, "text": utterance})
            continue
        index += 1
    return cues


def _is_header(line: str) -> bool:
    if not line:
        return False
    return bool(_SPEAKER_LINE.match(line) or _TIME_FIRST.match(line) or _BRACKET.match(line))


def _cues_from_voice(text: str) -> list[dict[str, str]]:
    cues: list[dict[str, str]] = []
    for match in _VOICE_SPAN.finditer(text):
        speaker = " ".join((match.group(1) or "").split())
        _speaker, utterance = _strip_markup(match.group(2) or "")
        if utterance:
            cues.append({"speaker": speaker, "timestamp": "", "text": utterance})
    return cues


def _strip_markup(payload: str) -> tuple[str, str]:
    speaker = ""
    voice = re.search(r"<v(?:\.[^\s>]+)?(?:\s+([^>]*))?>", payload, flags=re.I)
    if voice and voice.group(1):
        speaker = " ".join(voice.group(1).split())
    text = _MARKUP.sub("", payload)
    for old, new in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"')):
        text = text.replace(old, new)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return speaker, "\n".join(line for line in lines if line).strip()


def _fallback_text(text: str) -> str:
    lines = text.split("\n")
    if lines and lines[0].lstrip("\ufeff").strip().upper().startswith("WEBVTT"):
        lines = lines[1:]
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        word = stripped.split(" ", 1)[0].upper()
        if word in {"NOTE", "STYLE", "REGION"} or "-->" in stripped:
            continue
        speaker, utterance = _strip_markup(stripped)
        del speaker
        if utterance:
            kept.append(utterance)
    return "\n".join(kept).strip()


def _artifact(record: dict[str, Any], cues: list[dict[str, str]], encoding: str) -> ParsedArtifact:
    parts: list[str] = []
    sections: list[dict[str, Any]] = []
    offset = 0
    stamps: list[str] = []
    cue_index = 0
    for cue in cues:
        utterance = str(cue.get("text") or "").strip()
        if not utterance:
            continue
        cue_index += 1
        if parts:
            parts.append("\n")
            offset += 1
        start = offset
        parts.append(utterance)
        offset += len(utterance)
        timestamp = str(cue.get("timestamp") or "")
        if timestamp:
            stamps.append(timestamp)
        speaker = str(cue.get("speaker") or "")
        sections.append(
            {
                "title": speaker,
                "speaker": speaker,
                "timestamp": timestamp,
                "cue": cue_index,
                "line": 1,
                "start": start,
                "end": offset,
                "text": utterance,
                "location": {"kind": "cue", "value": timestamp or str(cue_index)},
            }
        )
    text = "".join(parts)
    for section in sections:
        section["line"] = text.count("\n", 0, int(section["start"])) + 1
    if stamps:
        record["period_covered"] = stamps[0] if len(stamps) == 1 else f"{stamps[0]} to {stamps[-1]}"
    if not sections:
        sections = [{"title": "", "line": 1, "text": text}]
    return ParsedArtifact(
        artifact_id=str(record.get("artifact_id") or ""),
        rel_path=str(record.get("path") or ""),
        family="document",
        detected_type=str(record.get("detected_type") or "transcript"),
        text=text,
        encoding=encoding,
        sections=sections,
    )
