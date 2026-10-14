"""Render the single-file dashboard from results.json."""

from __future__ import annotations

import html
import json
from pathlib import Path


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _score_text(value) -> str:
    if value is None:
        return "—"
    text = f"{float(value):.2f}"
    if text.endswith("00"):
        return text[:-3]
    if text.endswith("0"):
        return text[:-1]
    return text


def _css(status: str | None) -> str:
    return {"Green": "green", "Amber": "amber", "Red": "red"}.get(status or "", "grey")


def _pill(full: str, measured: str) -> str:
    return (
        f'<span class="pill {_css(full)}" data-full="{_esc(full)}" data-measured="{_esc(measured)}" '
        f'data-full-class="{_css(full)}" data-measured-class="{_css(measured)}">{_esc(full)}</span>'
    )


def _swap(full: str, measured: str, cls: str = "") -> str:
    class_attr = f' class="{cls}"' if cls else ""
    return f'<span{class_attr} data-full="{_esc(full)}" data-measured="{_esc(measured)}">{_esc(full)}</span>'


def _measured_status(results: dict, diagnostic: dict) -> tuple[str, str]:
    measured = (results.get("measured_view") or {}).get("diagnostics", {}).get(diagnostic["id"], {})
    return _score_text(measured.get("score")), measured.get("status") or diagnostic["status"]


def _area_measured(results: dict, name: str) -> tuple[str, str]:
    for area in (results.get("measured_view") or {}).get("areas") or []:
        if area["name"] == name:
            return _score_text(area.get("score")), area.get("status") or "No evidence"
    return "—", "No evidence"


def render_dashboard(results: dict) -> str:
    template_path = Path(__file__).resolve().parents[1] / "templates" / "dashboard.html"
    template = template_path.read_text(encoding="utf-8")
    engagement = results.get("engagement") or {}
    overall = results.get("overall") or {}
    measured_overall = (results.get("measured_view") or {}).get("overall") or overall
    title = f"Forecast diagnostic — {engagement.get('id') or 'engagement'}"
    payload = json.dumps(results, ensure_ascii=False).replace("<", "\\u003c")
    content = _body(results, overall, measured_overall)
    return (
        template.replace("__TITLE__", _esc(title))
        .replace("__CONTENT__", content)
        .replace("__JSON__", payload)
    )


def _body(results: dict, overall: dict, measured_overall: dict) -> str:
    engagement = results.get("engagement") or {}
    versions = results.get("versions") or {}
    failed = overall.get("failed_gates") or []
    gate_text = (
        "All included gate diagnostics are at or above the floor."
        if not failed
        else "Failed gates: "
        + ", ".join(f"{item['id']} — {item['reason']}" + (f" ({_score_text(item.get('score'))})" if item.get("score") is not None else "") for item in failed)
    )
    coverage = results.get("coverage") or {}
    parts = [
        "<header>",
        "<div>",
        f"<p class='eyebrow'>Forecast diagnostic</p>",
        f"<h1>{_esc(engagement.get('id'))}</h1>",
        f"<p class='sub'>{_esc(engagement.get('solution'))} · {_esc(engagement.get('client_alias'))} · assessed {_esc(engagement.get('assessed_date'))}</p>",
        "</div>",
        "<div class='header-actions'>",
        "<button type='button' id='measured-toggle' aria-pressed='false'>Measured evidence only</button>",
        "</div>",
        "</header>",
        "<nav class='tabs'>",
        "<button type='button' class='tab active' data-tab='summary'>Summary</button>",
        "<button type='button' class='tab' data-tab='scorecard'>Scorecard</button>",
        "<button type='button' class='tab' data-tab='recommendations'>Recommendations</button>",
        "</nav>",
        "<section id='summary' class='panel active'>",
        "<div class='verdict'>",
        f"<p class='eyebrow'>Readiness</p>",
        f"<h2>{_swap(str(overall.get('verdict') or ''), str(measured_overall.get('verdict') or ''))}</h2>",
        f"<p class='bigscore'>{_swap(_score_text(overall.get('score')), _score_text(measured_overall.get('score')))}</p>",
        f"<p>{_swap(str(overall.get('maturity') or ''), str(measured_overall.get('maturity') or ''))} maturity"
        f"{' · provisional' if overall.get('provisional') else ''}</p>",
        f"<p class='reason'>{_esc(overall.get('headline'))}</p>",
        f"<p class='reason'>{_esc(gate_text)}</p>",
        "</div>",
        "<div class='scale'><span>0 Initial</span><span>25 Developing</span><span>50 Defined</span><span class='ready-line'>67 Ready</span><span>85 Optimised</span></div>",
        f"<p class='coverage'>Evidence covers {coverage.get('diagnostics_with_evidence', 0)} of {coverage.get('diagnostics_total', 0)} scored diagnostics "
        f"({_score_text((coverage.get('points_coverage') or 0) * 100)}% of included points). Model family: {_esc(results.get('model_family'))}.</p>",
        "<div class='cards'>",
    ]
    for area in results.get("areas") or []:
        m_score, m_status = _area_measured(results, area["name"])
        parts.append(
            "<article class='card'>"
            f"<h3>{_esc(area['name'])}</h3>"
            f"<p class='bigscore'>{_swap(_score_text(area.get('score')), m_score)}</p>"
            f"{_pill(area.get('status') or 'No evidence', m_status)}"
            f"<p class='meta'>{_esc(area.get('points'))} points in this pack</p>"
            "</article>"
        )
    parts.append("</div><h3>Findings</h3><ul class='findings'>")
    for diagnostic in results.get("diagnostics") or []:
        _m_score, m_status = _measured_status(results, diagnostic)
        parts.append(
            "<li>"
            f"<strong>{_esc(diagnostic['id'])}</strong> {_esc(diagnostic['name'])} "
            f"{_pill(diagnostic.get('status') or 'No evidence', m_status)}"
            "</li>"
        )
    parts.append("</ul></section>")
    parts.append("<section id='scorecard' class='panel'><table><thead><tr>"
                 "<th>ID</th><th>Check</th><th>Area</th><th>Score</th><th>Status</th><th>Route</th><th>Evidence</th>"
                 "</tr></thead><tbody>")
    for diagnostic in results.get("diagnostics") or []:
        m_score, m_status = _measured_status(results, diagnostic)
        parts.append(
            "<tr>"
            f"<td>{_esc(diagnostic['id'])}</td>"
            f"<td>{_esc(diagnostic['name'])}</td>"
            f"<td>{_esc(diagnostic['area'])}</td>"
            f"<td>{_swap(_score_text(diagnostic.get('score')), m_score)}</td>"
            f"<td>{_pill(diagnostic.get('status') or 'No evidence', m_status)}</td>"
            f"<td>{_esc(diagnostic.get('route'))}</td>"
            f"<td>{_esc(diagnostic.get('evidence_level') or '—')}</td>"
            "</tr>"
        )
    parts.append("</tbody></table></section>")
    parts.append("<section id='recommendations' class='panel'>")
    parts.append("<h3>Root causes</h3><div class='cards'>")
    for cause in results.get("root_causes") or []:
        parts.append(
            "<article class='card'>"
            f"<h3>{_esc(cause.get('title'))}</h3>"
            f"<p>{_esc(cause.get('summary'))}</p>"
            f"<p class='meta'>{_esc(', '.join(cause.get('diagnostics') or []))}</p>"
            "</article>"
        )
    if not results.get("root_causes"):
        parts.append("<p>No weak diagnostics to group.</p>")
    parts.append("</div><h3>Improvement plan</h3><ol class='actions'>")
    for action in results.get("actions") or []:
        targets = ", ".join(f"{key} → {value}" for key, value in (action.get("targets") or {}).items())
        parts.append(
            "<li>"
            f"<strong>{_esc(action.get('id'))}</strong> "
            f"<span class='pill grey'>{_esc(action.get('effort') or '—')}</span>"
            f"<p>{_esc(action.get('text'))}</p>"
            f"<p class='meta'>Targets { _esc(targets) }. Root cause: {_esc(action.get('root_cause'))}.</p>"
            "</li>"
        )
    parts.append("</ol><h3>Check detail</h3>")
    for diagnostic in results.get("diagnostics") or []:
        if diagnostic.get("tier") == "synthesis":
            continue
        parts.append(
            "<article class='detail'>"
            f"<h3>{_esc(diagnostic['id'])} {_esc(diagnostic['name'])}</h3>"
            f"<p>{_esc(diagnostic.get('question'))}</p>"
            f"<p><strong>Finding.</strong> {_esc(diagnostic.get('finding'))}</p>"
            f"<p class='meta'>Source: {_esc(diagnostic.get('source_summary') or '—')}. "
            f"Recommendations: {_esc(', '.join(diagnostic.get('recommendation_ids') or []) or '—')}.</p>"
            "</article>"
        )
    parts.append("</section>")
    parts.append(
        f"<footer>Pack { _esc(versions.get('pack')) } · engine { _esc(versions.get('engine')) } · "
        f"Python { _esc(versions.get('python')) }. Thresholds in this pack are placeholders.</footer>"
    )
    return "\n".join(parts)
