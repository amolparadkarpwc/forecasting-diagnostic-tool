"""Render a single self-contained HTML dashboard. No network and no CDN."""

from __future__ import annotations

import html
from typing import Any


def render_dashboard(results: dict[str, Any]) -> str:
    """Build the dashboard HTML from a results document."""
    engagement = results.get("engagement") or {}
    overall = results.get("overall") or {}
    verdict = str(overall.get("verdict") or "No evidence")
    score = overall.get("score")
    maturity = overall.get("maturity") or "—"
    reason = str(overall.get("reason") or "")
    title = f"Forecast diagnostic — {engagement.get('id', '')}"
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"<title>{_esc(title)}</title>",
        "<style>",
        _CSS,
        "</style>",
        "</head>",
        "<body>",
        "<header>",
        "<p class=\"eyebrow\">Forecasting diagnostic</p>",
        f"<h1>{_esc(title)}</h1>",
        "<p class=\"meta\">",
        _esc(
            f"Assessed {engagement.get('assessed_date', '')} · "
            f"Pack {((results.get('versions') or {}).get('pack', ''))} · "
            f"Engine {((results.get('versions') or {}).get('engine', ''))}"
        ),
        "</p>",
        "</header>",
        "<section id=\"summary\">",
        f"<p class=\"verdict {_verdict_class(verdict)}\">{_esc(verdict)}</p>",
        "<div class=\"score-row\">",
        f"<p><span>Overall</span><strong>{_score_text(score)}</strong></p>",
        f"<p><span>Maturity</span><strong>{_esc(maturity)}</strong></p>",
        "</div>",
        f"<p class=\"reason\">{_esc(reason)}</p>",
        _gates(overall),
        "</section>",
        "<section id=\"areas\">",
        "<h2>Areas</h2>",
        "<div class=\"cards\">",
        *[_area_card(area) for area in results.get("areas") or []],
        "</div>",
        "</section>",
        "<section id=\"scorecard\">",
        "<h2>Diagnostics</h2>",
        "<table>",
        "<thead><tr><th>ID</th><th>Check</th><th>Area</th><th>Points</th><th>Score</th><th>Status</th><th>Finding</th></tr></thead>",
        "<tbody>",
        *[_diagnostic_row(item) for item in results.get("diagnostics") or []],
        "</tbody>",
        "</table>",
        "</section>",
        "<section id=\"evidence\">",
        "<h2>Evidence</h2>",
        _evidence_table(results.get("evidence") or []),
        "</section>",
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(parts)


def _area_card(area: dict[str, Any]) -> str:
    status = str(area.get("status") or "No evidence")
    return (
        "<article class=\"card\">"
        f"<h3>{_esc(area.get('name', ''))}</h3>"
        f"<p class=\"status {_status_class(status)}\">{_esc(status)}</p>"
        f"<p class=\"big\">{_score_text(area.get('score'))}</p>"
        "</article>"
    )


def _diagnostic_row(item: dict[str, Any]) -> str:
    status = str(item.get("status") or "No evidence")
    gate = " gate" if item.get("gate") else ""
    return (
        "<tr>"
        f"<td>{_esc(item.get('id', ''))}{_esc(gate)}</td>"
        f"<td>{_esc(item.get('name', ''))}</td>"
        f"<td>{_esc(item.get('area', ''))}</td>"
        f"<td>{_esc(item.get('points', ''))}</td>"
        f"<td>{_score_text(item.get('score'))}</td>"
        f"<td><span class=\"status {_status_class(status)}\">{_esc(status)}</span></td>"
        f"<td>{_esc(item.get('finding', ''))}</td>"
        "</tr>"
    )


def _evidence_table(records: list[dict[str, Any]]) -> str:
    if not records:
        return "<p>No evidence records.</p>"
    rows = []
    for record in records:
        source = record.get("source") or {}
        location = source.get("location") or {}
        where = f"{source.get('file', '')}:{location.get('value', '')}"
        rows.append(
            "<tr>"
            f"<td>{_esc(record.get('record_id', ''))}</td>"
            f"<td>{_esc(record.get('diagnostic_id', ''))}</td>"
            f"<td>{_esc(record.get('signal_id', ''))}</td>"
            f"<td>{_esc(where)}</td>"
            f"<td>{_esc(record.get('evidence_level', ''))}</td>"
            f"<td>{_esc(record.get('fact', ''))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Record</th><th>Diagnostic</th><th>Signal</th>"
        "<th>Source</th><th>Level</th><th>Fact</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _gates(overall: dict[str, Any]) -> str:
    failed = overall.get("failed_gates") or []
    if not failed:
        return "<p>No gate failed. A null gate score does not fail a gate.</p>"
    listed = ", ".join(str(item) for item in failed)
    return f"<p class=\"gate\">Gate failed: {_esc(listed)}. Score is below the gate floor.</p>"


def _score_text(score: Any) -> str:
    if score is None:
        return "—"
    return _esc(score)


def _status_class(status: str) -> str:
    return {
        "Green": "status-green",
        "Amber": "status-amber",
        "Red": "status-red",
    }.get(status, "status-none")


def _verdict_class(verdict: str) -> str:
    return {
        "Ready": "verdict-ready",
        "Ready with gaps": "verdict-gaps",
        "Not ready": "verdict-not",
    }.get(verdict, "verdict-none")


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


_CSS = """
:root {
  color-scheme: light;
  --ink: #1f2933;
  --muted: #52606d;
  --line: #e4e7eb;
  --paper: #f7f6f3;
  --card: #ffffff;
  --green: #0f6b45;
  --green-bg: #e5f6ee;
  --amber: #8a5a00;
  --amber-bg: #fff4d6;
  --red: #9b1c1c;
  --red-bg: #fde8e8;
  --none: #3e4c59;
  --none-bg: #eef1f4;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
  color: var(--ink);
  background: var(--paper);
  line-height: 1.45;
}
header, section { max-width: 1100px; margin: 0 auto; padding: 1.25rem 1.5rem; }
header { padding-top: 2rem; }
h1, h2, h3 { font-weight: 600; margin: 0 0 0.5rem; }
h1 { font-size: 2rem; }
h2 { font-size: 1.35rem; margin-bottom: 0.75rem; }
.eyebrow { letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); font-size: 0.78rem; margin: 0; }
.meta, .reason { color: var(--muted); }
.verdict {
  display: inline-block;
  margin: 0.5rem 0;
  padding: 0.35rem 0.75rem;
  border-radius: 999px;
  font-weight: 700;
}
.verdict-ready { background: var(--green-bg); color: var(--green); }
.verdict-gaps { background: var(--amber-bg); color: var(--amber); }
.verdict-not { background: var(--red-bg); color: var(--red); }
.verdict-none { background: var(--none-bg); color: var(--none); }
.score-row { display: flex; gap: 2rem; }
.score-row span { display: block; color: var(--muted); font-size: 0.85rem; }
.score-row strong { font-size: 1.8rem; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.75rem; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 0.9rem; }
.big { font-size: 1.6rem; margin: 0.4rem 0 0; }
.status {
  display: inline-block;
  padding: 0.1rem 0.45rem;
  border-radius: 999px;
  font-size: 0.85rem;
  font-weight: 700;
}
.status-green { background: var(--green-bg); color: var(--green); }
.status-amber { background: var(--amber-bg); color: var(--amber); }
.status-red { background: var(--red-bg); color: var(--red); }
.status-none { background: var(--none-bg); color: var(--none); }
.gate { color: var(--red); font-weight: 700; }
table { width: 100%; border-collapse: collapse; background: var(--card); }
th, td { border-bottom: 1px solid var(--line); text-align: left; padding: 0.45rem 0.5rem; vertical-align: top; font-size: 0.92rem; }
th { color: var(--muted); font-weight: 600; }
"""
