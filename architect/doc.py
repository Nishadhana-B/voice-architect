"""Turn the live design into a short design document (Markdown, ADR style)."""
from __future__ import annotations

import datetime as dt

from .costs import estimate
from .diagram import render_mermaid
from .model import TYPES, Design
from .rules import analyze


def to_markdown(d: Design, title: str = "Architecture design review") -> str:
    findings, cost = analyze(d), estimate(d)
    names = {c.id: c.name for c in d.components.values()}
    out = [f"# {title}", f"*Generated {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} from a spoken design review.*", "",
           "## Context", "Traffic assumptions: " + (", ".join(f"{k}={v:g}" for k, v in d.traffic.items() if v is not None)
                                                    or "none stated (cost uses defaults)."), "",
           "## Design", "```mermaid", render_mermaid(d), "```", "", "### Components"]
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
