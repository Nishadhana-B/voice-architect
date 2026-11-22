"""Turn the live design into a short design document (Markdown, ADR style)."""
from __future__ import annotations

import datetime as dt
from html import escape

from .costs import estimate
from .diagram import render_mermaid, render_svg
from .model import TYPES, Design
from .rules import analyze


def to_markdown(d: Design, title: str | None = None, diagram_ref: str | None = None) -> str:
    title = title or d.title
    findings, cost = analyze(d), estimate(d)
    names = {c.id: c.name for c in d.components.values()}
    out = [f"# {title}", f"*Generated {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} from a spoken design review.*", "",
           "## Context", "Traffic assumptions: " + (", ".join(f"{k}={v:g}" for k, v in d.traffic.items() if v is not None)
                                                    or "none stated (cost uses defaults)."), "",
           "## Design"]
    if diagram_ref:  # the picture first: a design document without its diagram is half a document
        out += [f"![Architecture diagram]({diagram_ref})", ""]
    out += ["```mermaid", render_mermaid(d), "```", "", "### Components"]
    for c in d.components.values():
        props = ", ".join(f"{k}={v}" for k, v in c.attrs.items() if v is not None)
        out.append(f"- **{c.name}** ({TYPES[c.type][0]})" + (f": {props}" if props else ""))
    out += ["", "### Connections"]
    out += [f"- {names[x.src]} -> {names[x.dst]} ({x.kind}{', ' + x.label if x.label else ''})" for x in d.connections]
    out += ["", "## Risks (Well-Architected pillars)"]
    if not findings:
        out.append("No risks found by the rule set. That is not proof the design is sound.")
    for f in findings:
        out += [f"- **[{f.severity.upper()}] {f.pillar}**: {f.message} "
                f"_({'stated' if f.confidence == 'stated' else 'to confirm: not stated'})_",
                f"  - Why: {f.why}", f"  - Fix: {f.fix}"]
    out += ["", "## Estimated monthly cost", f"**About ${cost['monthly_total_usd']:,.0f} per month.**", "",
            "| Component | $/month | Basis |", "|---|---:|---|"]
    out += [f"| {r['component']} | {r['monthly_usd']:,.2f} | {r['note']} |" for r in cost["breakdown"]]
    out += ["", f"Price basis: {cost['price_basis']}."]
    if cost["assumptions"]:
        out += ["", "Assumptions:"] + [f"- {a}" for a in cost["assumptions"]]
    return "\n".join(out) + "\n"


SEVERITY_COLOR = {"high": "#ef4444", "medium": "#f59e0b", "low": "#3b82f6"}


def to_html(d: Design, title: str | None = None) -> str:
    title = title or d.title
    """One self-contained page (inline SVG, no external files) that opens anywhere and prints to PDF."""
    findings, cost = analyze(d), estimate(d)
    risks = "".join(
        f'<div class="r" style="border-color:{SEVERITY_COLOR[f.severity]}"><b>{escape(f.severity.upper())}</b> '
        f'{escape(f.pillar)}<br>{escape(f.message)}<br><span class="fix">Fix: {escape(f.fix)}</span><br>'
        f'<span class="t">{"stated by the engineer" if f.confidence == "stated" else "not stated, to confirm"}</span></div>'
        for f in findings) or "<p>No risks found by the rule set. That is not proof the design is sound.</p>"
    rows = "".join(f"<tr><td>{escape(r['component'])}</td><td>${r['monthly_usd']:,.0f}</td><td>{escape(r['note'])}</td></tr>"
                   for r in cost["breakdown"])
    assume = "".join(f"<li>{escape(a)}</li>" for a in cost["assumptions"])
    traffic = ", ".join(f"{k}={v:g}" for k, v in d.traffic.items() if v is not None) or "not stated (cost uses defaults)"
    return f"""<!doctype html><meta charset=utf-8><title>{escape(title)}</title>
<style>:root{{color-scheme:light}}body{{font:15px/1.5 -apple-system,Helvetica,Arial,sans-serif;max-width:980px;margin:30px auto;padding:0 18px;color:#111;background:#fff}}
.d svg{{max-width:100%;height:auto;display:block}}
h1{{font-size:24px}}h2{{font-size:17px;margin-top:28px;border-bottom:1px solid #ddd;padding-bottom:4px}}
.d{{overflow:auto;border:1px solid #ddd;border-radius:8px}}.r{{border-left:5px solid;padding:6px 10px;margin:8px 0;background:#fafafa}}
.fix{{color:#166534}}.t{{color:#666;font-size:12px}}table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #eee;padding:5px 8px;text-align:left}}.big{{font-size:28px;font-weight:700}}</style>
<h1>{escape(title)}</h1><p>Generated {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} from a spoken design review. Traffic: {escape(traffic)}.</p>
<h2>Architecture</h2><div class="d">{render_svg(d, findings)}</div>
<h2>Risks (Well-Architected pillars)</h2>{risks}
<h2>Estimated monthly cost</h2><p class="big">About ${cost['monthly_total_usd']:,.0f} per month</p>
<table><tr><th>Component</th><th>$/month</th><th>Basis</th></tr>{rows}</table>
<p><small>Price basis: {escape(cost['price_basis'])}.</small></p><ul>{assume}</ul>"""
