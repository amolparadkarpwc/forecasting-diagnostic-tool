"""Find phrases in document text."""

from __future__ import annotations

from diag.blocks.common import Match


def run(parsed, params: dict, vocab: dict, context: dict) -> list[Match]:
    del vocab, context
    phrases = [str(phrase) for phrase in params.get("phrases") or [] if str(phrase).strip()]
    window = int(params.get("uncertain_window") or 80)
    uncertain_words = [str(word).lower() for word in params.get("uncertain_context") or []]
    text = parsed.text or ""
    lowered = text.lower()
    lines = text.splitlines()
    matches: list[Match] = []
    for phrase in phrases:
        needle = phrase.lower()
        start = 0
        while len(matches) < 20:
            index = lowered.find(needle, start)
            if index < 0:
                break
            line_no = text.count("\n", 0, index) + 1
            line = lines[line_no - 1].strip() if 0 < line_no <= len(lines) else phrase
            left = max(0, index - window)
            right = min(len(text), index + len(needle) + window)
            nearby = text[left:right].lower()
            uncertain = any(word in nearby for word in uncertain_words)
            matches.append(
                Match(
                    fact=line[:240],
                    location={"kind": "line", "value": str(line_no)},
                    values={"phrase": phrase, "uncertain": uncertain},
                    match_strength="keyword",
                )
            )
            start = index + max(len(needle), 1)
    return matches
