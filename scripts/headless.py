#!/usr/bin/env python3
"""Run scripted design reviews against Nova 2 Sonic (macOS `say` is the engineer) and score them.

    python scripts/headless.py [scenario ...] [--runs N] [--out DIR] [--live] [--hold SECONDS]

--live starts the web view on http://127.0.0.1:8765 (for screenshots); --hold keeps it up after the run.
Scenarios: store, pipeline, clean (default: all). One run proves nothing, so use --runs 3 or more.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from architect.agent import build_agent  # noqa: E402
from architect.audio_io import ScriptedAudioInput  # noqa: E402
from architect.diagram import render_svg  # noqa: E402
from architect.doc import to_markdown  # noqa: E402
from architect.rules import analyze  # noqa: E402
from architect.scenarios import SCENARIOS  # noqa: E402
from architect.scoring import aggregate, score_run  # noqa: E402
from architect.session import Session  # noqa: E402
from architect.speech import tts  # noqa: E402


async def one_run(sc, out_dir: Path, live: bool, hold: float, port: int) -> dict:
    s = Session(port=port)
    if live:
        print("live view:", s.live.start(), flush=True)
    agent = build_agent(s.design)
    mic = ScriptedAudioInput(sc.lines, tts, s.recorder)
    runner = asyncio.create_task(agent.run(inputs=[mic], outputs=[s.recorder]))
    finished = asyncio.create_task(mic.finished.wait())
    done, _ = await asyncio.wait({runner, finished}, return_when=asyncio.FIRST_COMPLETED, timeout=600)
    problem = None
    if runner in done and not mic.finished.is_set():
        problem = f"agent stopped early: {runner.exception()!r}"
    elif not done:
        problem = "timed out after 600 s"
    try:
        await agent.stop()
    except Exception as e:  # noqa: BLE001
        print("stop error:", repr(e))
    await asyncio.gather(runner, finished, return_exceptions=True)
    m = score_run(sc, s.design, s.recorder.transcripts, s.recorder.tool_calls, s.recorder.latencies)
    if problem:
        m["problem"], m["pass"] = problem, False
    out_dir.mkdir(parents=True, exist_ok=True)
    s.recorder.save(out_dir)
    findings = analyze(s.design)
    (out_dir / "design.json").write_text(json.dumps({"design": s.design.summary(),
                                                     "findings": [f.to_dict() for f in findings]}, indent=2))
    (out_dir / "design.svg").write_text(render_svg(s.design, findings))
    (out_dir / "design.md").write_text(to_markdown(s.design))
    (out_dir / "metrics.json").write_text(json.dumps(m, indent=2))
    if live and hold:
        print(f"holding the live view for {hold:.0f} s", flush=True)
        await asyncio.sleep(hold)
    s.live.stop()
    return m


async def main(names, runs, out: Path, live: bool, hold: float, port: int):
    results = []
    for name in names:
        for k in range(1, runs + 1):
            print(f"--- {name} run {k}/{runs}", flush=True)
            m = await one_run(SCENARIOS[name], out / f"{name}-run{k}", live, hold, port)
            results.append(m)
            print(f"    pass={m['pass']} types={m['type_recall']} rules={m['rule_recall']} "
                  f"mention={m['mention_recall']} extra={m['extra_components']} latency={m['median_latency_s']}"
                  + (f" PROBLEM={m['problem']}" if m.get('problem') else ""), flush=True)
    summary = aggregate(results)
    (out / "summary.json").write_text(json.dumps({"runs": results, "summary": summary}, indent=2))
    print("\nSUMMARY", json.dumps(summary, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="*", default=list(SCENARIOS))
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--out", default="out")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--hold", type=float, default=0)
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    asyncio.run(main(a.scenarios, a.runs, Path(a.out), a.live, a.hold, a.port))
