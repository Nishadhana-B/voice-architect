"""Score one run of a scenario against its ground truth. Pure functions, unit-tested."""
from __future__ import annotations

import statistics

from .model import Design
from .rules import analyze
from .scenarios import Scenario


import re

# STRICT leaks: the model is thinking out loud, talking about "the user", or quoting its instructions. These fail a run.
LEAK_PATTERNS = [r"\bthe user\b", r"\bthe instructions?\b", r"\bmy next question\b", r"\blet'?s stick with\b",
                 r"\bthe engineer (has|added|said|wants|is|mentioned)\b", r"\bi should\b",
                 r"\blet me (think|check|call|see|make|confirm)\b", r"\bmaybe i\b", r"\bhmm\b", r"\bwait,"]
LEAK_RE = re.compile("|".join(LEAK_PATTERNS), re.I)
# MILD narration ("I need to ask ...", "Now I will ..."): robotic but not a leak. Reported, not failing.
NARRATION_RE = re.compile(r"\b(i need to|now i|i'?ll (call|check|add|record))\b", re.I)
MAX_SPOKEN_WORDS = 90


def leaks(transcripts: list[dict]) -> list[str]:
    """Assistant turns that think aloud (strict). Returns a short excerpt for each."""
    return [t["text"][:90].replace("\n", " ") for t in transcripts
            if t["role"] == "assistant" and (LEAK_RE.search(t["text"]) or len(t["text"].split()) > MAX_SPOKEN_WORDS)]


def narration(transcripts: list[dict]) -> list[str]:
    """Assistant turns with mild narration that are not already strict leaks."""
    strict = set(leaks(transcripts))
    return [t["text"][:90].replace("\n", " ") for t in transcripts
            if t["role"] == "assistant" and NARRATION_RE.search(t["text"]) and t["text"][:90].replace("\n", " ") not in strict]


def silent_turns(transcripts: list[dict]) -> int:
    """User turns that never got a spoken reply before the next user turn (or the end)."""
    silent, waiting = 0, False
    for t in transcripts:
        if t["role"] == "user":
            silent += 1 if waiting else 0
            waiting = True
        else:
            waiting = False
    return silent + (1 if waiting else 0)


def score_run(sc: Scenario, design: Design, transcripts: list[dict], tool_calls: list[dict],
              latencies: list[float]) -> dict:
    findings = analyze(design)
    present = {f.rule for f in findings}
    counts: dict[str, int] = {}
    for c in design.components.values():
        counts[c.type] = counts.get(c.type, 0) + 1
    type_hits = {t: counts.get(t, 0) >= n for t, n in sc.expect_types.items()}
    expected_total = sum(sc.expect_types.values())
    extras = sum(max(0, counts.get(t, 0) - sc.expect_types.get(t, 0)) for t in counts if t not in sc.allow_types)
    unexpected_types = sorted(t for t in counts if t not in sc.expect_types and t not in sc.allow_types)
    leaked = leaks(transcripts)
    rule_hits = {r: r in present for r in sc.expect_rules}

    spoken = " ".join(t["text"] for t in transcripts if t["role"] == "assistant").lower()
    by_rule = {f.rule: f for f in findings}
    mention_hits = {}
    for r in sc.expect_rules:
        f = by_rule.get(r)
        mention_hits[r] = bool(f) and any(k in spoken for k in f.keywords)

    called = [c["tool"] for c in tool_calls]
    out = {
        "scenario": sc.name,
        "components_found": sum(counts.values()), "components_expected": expected_total,
        "type_recall": round(sum(type_hits.values()) / len(type_hits), 2) if type_hits else 1.0,
        "missing_types": sorted(t for t, ok in type_hits.items() if not ok),
        "extra_components": extras, "unexpected_types": unexpected_types,
        "rule_recall": round(sum(rule_hits.values()) / len(rule_hits), 2) if rule_hits else 1.0,
        "missed_rules": sorted(r for r, ok in rule_hits.items() if not ok),
        "mention_recall": round(sum(mention_hits.values()) / len(mention_hits), 2) if mention_hits else 1.0,
        "unmentioned_rules": sorted(r for r, ok in mention_hits.items() if not ok),
        "high_findings": sorted(f.rule for f in findings if f.severity == "high"),
        "leaked_turns": len(leaked), "leak_examples": leaked[:2], "narration_turns": len(narration(transcripts)), "silent_turns": silent_turns(transcripts),
        "assistant_turns": sum(1 for t in transcripts if t["role"] == "assistant"),
        "tool_calls": len(called), "called_review_risks": "review_risks" in called,
        "called_estimate_cost": "estimate_cost" in called,
        "called_export": "export_design_doc" in called,
        "median_latency_s": round(statistics.median(latencies), 2) if latencies else None,
    }
    out["pass"] = (out["type_recall"] == 1.0 and out["rule_recall"] == 1.0 and out["leaked_turns"] == 0 and
                   out["silent_turns"] == 0 and
                   (not sc.forbid_high or not out["high_findings"]) and
                   (not sc.expect_cost_question or out["called_estimate_cost"]) and
                   out["mention_recall"] == 1.0)
    return out


def aggregate(results: list[dict]) -> dict:
    """Per scenario: pass rate and mean recalls over repeated runs (one run proves nothing)."""
    by: dict[str, list[dict]] = {}
    for r in results:
        by.setdefault(r["scenario"], []).append(r)
    summary = {}
    for name, rs in by.items():
        lat = [r["median_latency_s"] for r in rs if r["median_latency_s"] is not None]
        summary[name] = {
            "runs": len(rs), "passed": sum(r["pass"] for r in rs),
            "type_recall": round(statistics.mean(r["type_recall"] for r in rs), 2),
            "rule_recall": round(statistics.mean(r["rule_recall"] for r in rs), 2),
            "mention_recall": round(statistics.mean(r["mention_recall"] for r in rs), 2),
            "extra_components_avg": round(statistics.mean(r["extra_components"] for r in rs), 1),
            "leaked_turns": sum(r.get("leaked_turns", 0) for r in rs),
            "silent_turns": sum(r.get("silent_turns", 0) for r in rs),
            "narration_turns": sum(r.get("narration_turns", 0) for r in rs),
            "assistant_turns": sum(r.get("assistant_turns", 0) for r in rs),
            "median_latency_s": round(statistics.median(lat), 2) if lat else None,
            "missed_rules": sorted({m for r in rs for m in r["missed_rules"]}),
            "unmentioned_rules": sorted({m for r in rs for m in r["unmentioned_rules"]}),
        }
    return summary
