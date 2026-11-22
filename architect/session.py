"""One review session: the design, the recorder and the live web page tied together."""
from __future__ import annotations

import asyncio

from .audio_io import Recorder
from .costs import estimate
from .diagram import render_svg
from .doc import to_html, to_markdown
from .live import LiveView
from .model import Design
from .rules import analyze

NEW_DESIGN_NOTICE = ("[new design] The engineer started a new design. Forget the previous one completely. "
                     "Say one short sentence: fresh start, what are we building?")


class Session:
    def __init__(self, port: int = 8765):
        self.design = Design()
        self.recorder = Recorder()
        self.agent = None   # set by attach() once the voice agent is running
        self.loop = None
        self.live = LiveView(
            self.state, self.svg, port,
            get_md=lambda: to_markdown(self.design, diagram_ref="architecture.svg"),
            get_html=lambda: to_html(self.design),
            get_canvas=lambda: render_svg(self.design, analyze(self.design), background=False),
            actions={"new": lambda body: self.new_design(), "title": lambda body: self.set_title(body.get("title", "")),
                     "say": lambda body: self.say(body.get("text", ""))})

    def attach(self, agent, loop) -> None:
        """Give the page a way to talk to the running voice agent (type-instead and new design)."""
        self.agent, self.loop = agent, loop

    def _send_to_agent(self, text: str) -> None:
        if self.agent is None or self.loop is None:
            raise RuntimeError("The voice session is not running, so there is nobody to send that to.")
        asyncio.run_coroutine_threadsafe(self.agent.send(text), self.loop)

    def new_design(self) -> dict:
        self.design.reset()
        self.recorder.transcripts.clear()
        if self.agent is not None:
            self._send_to_agent(NEW_DESIGN_NOTICE)  # the model remembers the conversation, so tell it to forget
        return {}

    def set_title(self, title: str) -> dict:
        return {"title": self.design.set_title(title)}

    def say(self, text: str) -> dict:
        text = " ".join((text or "").split())
        if not text:
            raise ValueError("Type something first.")
        self._send_to_agent(text)
        return {}

    def svg(self) -> str:
        return render_svg(self.design, analyze(self.design))

    def state(self) -> dict:
        d = self.design
        return {"version": d.version, "title": d.title, "components": len(d.components),
                "connections": len(d.connections), "findings": [f.to_dict() for f in analyze(d)],
                "cost": estimate(d), "transcript": self.recorder.transcripts[-60:]}
