#!/usr/bin/env python3
"""Re-score every saved round with the CURRENT leak definition, so rounds are comparable.

Only transcripts are needed for leak, narration and silent-turn counts."""
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from architect.scoring import leaks, narration, silent_turns  # noqa: E402

rows = []
for d in sorted(glob.glob("out-*/**/transcript.json", recursive=True)):
    t = json.load(open(d))
    a = sum(1 for x in t if x["role"] == "assistant")
    if a:
        rows.append((d.split("/")[0], d.split("/")[-2], a, len(leaks(t)), len(narration(t)), silent_turns(t)))
by = {}
for rnd, run, a, l, n, s in rows:
    r = by.setdefault(rnd, [0, 0, 0, 0, 0])
    r[0] += 1; r[1] += a; r[2] += l; r[3] += n; r[4] += s
print(f"{'round':<14}{'runs':>5}{'turns':>7}{'leaks':>7}{'leak%':>7}{'mild':>6}{'silent':>8}")
for rnd, (runs, a, l, n, s) in by.items():
    print(f"{rnd:<14}{runs:>5}{a:>7}{l:>7}{100*l/a:>6.0f}%{n:>6}{s:>8}")
