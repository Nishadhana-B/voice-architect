"""Dependency-free SVG diagram of the design. Left to right layers, risk badges on components."""
from __future__ import annotations

from html import escape

from .model import TYPES, Design

CATEGORY_COLOR = {"edge": "#7c5cc4", "network": "#1e8aa6", "compute": "#d9622b", "storage": "#3b9a5c",
                  "database": "#3b6fd1", "integration": "#c2417f", "security": "#c9453a", "operations": "#6b7280"}
SEVERITY_COLOR = {"high": "#d6342c", "medium": "#d98a00", "low": "#2f6fdd"}
INK, MUTED, LINE, EDGE = "#1f2328", "#6b7280", "#c9ccd1", "#8b95a1"
FONT = "-apple-system,Helvetica Neue,Helvetica,Arial,sans-serif"
BOX_W, BOX_H, COL_GAP, ROW_GAP, PAD = 214, 62, 76, 40, 36
LEVEL_GAP = 58          # vertical layout: space between layers
VERTICAL_FROM = 6       # use the top-to-bottom layout when there are at least this many layers


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


def render_svg(d: Design, findings=None, background: bool = True) -> str:
    """background=False leaves the page transparent (used on the live canvas); exports keep a white background."""
    if not d.components:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 200" font-family="{FONT}">'
                + ('<rect width="640" height="200" fill="#ffffff"/>' if background else "")
                + f'<text x="320" y="92" text-anchor="middle" fill="{INK}" font-size="18">Nothing here yet</text>'
                f'<text x="320" y="120" text-anchor="middle" fill="{MUTED}" font-size="14">'
                'Describe a system out loud and the diagram builds as you go.</text></svg>')
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
    vertical = len(cols) >= VERTICAL_FROM   # long chains read better top to bottom than as a very wide strip
    pos = {}
    for lv, members in cols.items():
        for row, cid in enumerate(members):
            pos[cid] = ((PAD + row * (BOX_W + ROW_GAP), PAD + lv * (BOX_H + LEVEL_GAP)) if vertical
                        else (PAD + lv * (BOX_W + COL_GAP), PAD + row * (BOX_H + ROW_GAP)))
    levels, widest = len(cols), max(len(m) for m in cols.values())
    if vertical:
        width = PAD * 2 + widest * BOX_W + (widest - 1) * ROW_GAP
        height = PAD * 2 + levels * BOX_H + (levels - 1) * LEVEL_GAP
    else:
        width = PAD * 2 + levels * BOX_W + (levels - 1) * COL_GAP
        height = PAD * 2 + widest * BOX_H + (widest - 1) * ROW_GAP
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
           f'font-family="{FONT}">',
           '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
           f'<path d="M0 0L10 5L0 10z" fill="{EDGE}"/></marker></defs>']
    if background:
        out.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')
    for x in d.connections:
        if x.src not in pos or x.dst not in pos:
            continue
        sx, sy = pos[x.src]
        dx, dy = pos[x.dst]
        if vertical:
            if dy > sy:     # down to the next layer
                x1, y1, x2, y2 = sx + BOX_W / 2, sy + BOX_H, dx + BOX_W / 2, dy
                my = (y1 + y2) / 2
                path = f"M{x1},{y1} C{x1},{my} {x2},{my} {x2},{y2}"
            else:           # same layer, or back up: join the facing sides
                right = dx >= sx
                x1, y1 = sx + (BOX_W if right else 0), sy + BOX_H / 2
                x2, y2 = dx + (0 if right else BOX_W), dy + BOX_H / 2
                path = f"M{x1},{y1} L{x2},{y2}"
        else:
            x1, y1 = sx + BOX_W, sy + BOX_H / 2
            x2, y2 = dx, dy + BOX_H / 2
            if x2 <= x1:  # same column or backwards: route from the bottom/top edge
                x1, x2 = sx + BOX_W / 2, dx + BOX_W / 2
                y1 = sy + (BOX_H if y2 >= y1 else 0)
                y2 = dy + (0 if y2 >= y1 else BOX_H)
                path = f"M{x1},{y1} L{x2},{y2}"
            else:
                mx = (x1 + x2) / 2
                path = f"M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}"
        dash = ' stroke-dasharray="6 5"' if x.kind == "async" else ""
        out.append(f'<path d="{path}" fill="none" stroke="{EDGE}" stroke-width="1.75"{dash} marker-end="url(#arr)"/>')
        if x.label:
            out.append(f'<text x="{(x1 + x2) / 2}" y="{(y1 + y2) / 2 - 6}" text-anchor="middle" fill="{MUTED}" '
                       f'font-size="11" stroke="#fff" stroke-width="4" paint-order="stroke">{escape(x.label)}</text>')
    for cid, c in d.components.items():
        x, y = pos[cid]
        color = CATEGORY_COLOR[TYPES[c.type][1]]
        sev = worst.get(cid)
        stroke = SEVERITY_COLOR[sev] if sev else LINE
        sw = 2.5 if sev == "high" else 1.5
        out.append(f'<rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="6" fill="#ffffff" stroke="{stroke}" stroke-width="{sw}"/>')
        out.append(f'<rect x="{x}" y="{y}" width="6" height="{BOX_H}" rx="3" fill="{color}"/>')
        out.append(f'<text x="{x + 18}" y="{y + 26}" fill="{INK}" font-size="14" font-weight="600">{escape(c.name[:26])}</text>')
        out.append(f'<text x="{x + 18}" y="{y + 46}" fill="{MUTED}" font-size="12">{escape(TYPES[c.type][0])}</text>')
        if sev:
            out.append(f'<circle cx="{x + BOX_W - 4}" cy="{y + 4}" r="10" fill="{SEVERITY_COLOR[sev]}"/>')
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
