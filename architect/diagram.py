"""Dependency-free SVG diagram of the design. Left to right layers, risk badges on components."""
from __future__ import annotations

from html import escape

from .model import TYPES, Design

CATEGORY_COLOR = {"edge": "#7c3aed", "network": "#0891b2", "compute": "#ea580c", "storage": "#16a34a",
                  "database": "#2563eb", "integration": "#db2777", "security": "#dc2626", "operations": "#64748b"}
SEVERITY_COLOR = {"high": "#ef4444", "medium": "#f59e0b", "low": "#3b82f6"}
BOX_W, BOX_H, COL_GAP, ROW_GAP, PAD = 214, 62, 76, 40, 36


def _levels(d: Design) -> dict[str, int]:
    """Column per component: longest path from a source, cycles ignored."""
    ids = list(d.components)
    incoming = {i: [] for i in ids}
    for x in d.connections:
        if x.src in incoming and x.dst in incoming:
            incoming[x.dst].append(x.src)
    level: dict[str, int] = {}

    def lvl(i: str, stack: tuple) -> int:
        if i in level:
            return level[i]
        if i in stack:
            return 0
        best = 0
        for s in incoming[i]:
            best = max(best, lvl(s, stack + (i,)) + 1)
        level[i] = best
        return best

    for i in ids:
        lvl(i, ())
    return level


def render_svg(d: Design, findings=None) -> str:
    if not d.components:
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 220" font-family="Helvetica,Arial,sans-serif">'
                '<rect width="640" height="220" fill="#0f172a"/>'
                '<text x="320" y="100" text-anchor="middle" fill="#e2e8f0" font-size="20">Start talking</text>'
                '<text x="320" y="130" text-anchor="middle" fill="#94a3b8" font-size="14">'
                'Describe your architecture and it appears here.</text></svg>')
    worst: dict[str, str] = {}
    count: dict[str, int] = {}
    for f in findings or []:
        for name in f.components:
            for c in d.components.values():
                if c.name == name:
                    count[c.id] = count.get(c.id, 0) + 1
                    cur = worst.get(c.id)
                    if cur is None or ["high", "medium", "low"].index(f.severity) < ["high", "medium", "low"].index(cur):
                        worst[c.id] = f.severity
    level = _levels(d)
    cols: dict[int, list[str]] = {}
    for cid in d.components:
        cols.setdefault(level[cid], []).append(cid)
    pos = {}
    for lv, members in cols.items():
        for row, cid in enumerate(members):
            pos[cid] = (PAD + lv * (BOX_W + COL_GAP), PAD + row * (BOX_H + ROW_GAP))
    width = PAD * 2 + (max(cols) + 1) * BOX_W + max(cols) * COL_GAP
    height = PAD * 2 + max(len(m) for m in cols.values()) * BOX_H + (max(len(m) for m in cols.values()) - 1) * ROW_GAP
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
           f'font-family="Helvetica,Arial,sans-serif">',
           '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
           '<path d="M0 0L10 5L0 10z" fill="#94a3b8"/></marker></defs>',
           f'<rect width="{width}" height="{height}" fill="#0f172a"/>']
    for x in d.connections:
        if x.src not in pos or x.dst not in pos:
            continue
        x1, y1 = pos[x.src][0] + BOX_W, pos[x.src][1] + BOX_H / 2
        x2, y2 = pos[x.dst][0], pos[x.dst][1] + BOX_H / 2
        if x2 <= x1:  # same column or backwards: route from the bottom/top edge
            x1, x2 = pos[x.src][0] + BOX_W / 2, pos[x.dst][0] + BOX_W / 2
            y1 = pos[x.src][1] + (BOX_H if y2 >= y1 else 0)
            y2 = pos[x.dst][1] + (0 if y2 >= y1 else BOX_H)
            path = f"M{x1},{y1} L{x2},{y2}"
        else:
            mx = (x1 + x2) / 2
            path = f"M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}"
        dash = ' stroke-dasharray="6 5"' if x.kind == "async" else ""
        out.append(f'<path d="{path}" fill="none" stroke="#94a3b8" stroke-width="2"{dash} marker-end="url(#arr)"/>')
        if x.label:
            out.append(f'<text x="{(x1 + x2) / 2}" y="{(y1 + y2) / 2 - 6}" text-anchor="middle" fill="#94a3b8" '
                       f'font-size="11">{escape(x.label)}</text>')
    for cid, c in d.components.items():
        x, y = pos[cid]
        color = CATEGORY_COLOR[TYPES[c.type][1]]
        sev = worst.get(cid)
        stroke = SEVERITY_COLOR[sev] if sev else "#334155"
        sw = 3 if sev == "high" else 2
        out.append(f'<rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="9" fill="#1e293b" stroke="{stroke}" stroke-width="{sw}"/>')
        out.append(f'<rect x="{x}" y="{y}" width="8" height="{BOX_H}" rx="4" fill="{color}"/>')
        out.append(f'<text x="{x + 20}" y="{y + 26}" fill="#f1f5f9" font-size="14" font-weight="bold">{escape(c.name[:26])}</text>')
        out.append(f'<text x="{x + 20}" y="{y + 46}" fill="#94a3b8" font-size="12">{escape(TYPES[c.type][0])}</text>')
        if sev:
            out.append(f'<circle cx="{x + BOX_W - 4}" cy="{y + 4}" r="11" fill="{SEVERITY_COLOR[sev]}"/>')
            out.append(f'<text x="{x + BOX_W - 4}" y="{y + 8}" text-anchor="middle" fill="#fff" font-size="12" '
                       f'font-weight="bold">{count[cid]}</text>')
    out.append("</svg>")
    return "".join(out)


def render_mermaid(d: Design) -> str:
    lines = ["flowchart LR"]
    for c in d.components.values():
        lines.append(f'  {c.id.replace("-", "_")}["{c.name} ({TYPES[c.type][0]})"]')
    for x in d.connections:
        arrow = "-.->" if x.kind == "async" else "-->"
        label = f'|{x.label}|' if x.label else ""
        lines.append(f'  {x.src.replace("-", "_")} {arrow}{label} {x.dst.replace("-", "_")}')
    return "\n".join(lines)
