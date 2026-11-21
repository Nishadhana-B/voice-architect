"""One review session: the design, the recorder and the live web view tied together."""
from __future__ import annotations

from .audio_io import Recorder
from .costs import estimate
from .diagram import render_svg
from .live import LiveView
from .model import Design
from .rules import analyze


class Session:
    def __init__(self, port: int = 8765):
        self.design = Design()
        self.recorder = Recorder()
        self.live = LiveView(self.state, self.svg, port)

    def svg(self) -> str:
        return render_svg(self.design, analyze(self.design))

    def state(self) -> dict:
        d = self.design
        return {"version": d.version, "components": len(d.components), "connections": len(d.connections),
                "findings": [f.to_dict() for f in analyze(d)], "cost": estimate(d),
                "transcript": self.recorder.transcripts[-40:]}
