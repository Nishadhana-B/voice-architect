#!/usr/bin/env python3
"""Print a Markdown results table from summary.json files.   python scripts/results_table.py out-measure6/*/summary.json"""
import json
import sys

rows = []
for path in sys.argv[1:]:
    data = json.load(open(path))
    for name, s in data["summary"].items():
        rows.append((name, s))
print("| Scenario | Runs passed | Components found | Risks captured | Risks spoken | Strict leaks | Silent turns | Median reply delay |")
print("|---|---:|---:|---:|---:|---:|---:|---:|")
for name, s in rows:
    print(f"| {name} | {s['passed']} of {s['runs']} | {s['type_recall']:.0%} | {s['rule_recall']:.0%} | "
          f"{s['mention_recall']:.0%} | {s.get('leaked_turns', 0)} of {s.get('assistant_turns', 0)} turns | "
          f"{s.get('silent_turns', 0)} | {s['median_latency_s']} s |")
