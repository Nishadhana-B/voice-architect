#!/usr/bin/env python3
"""Talk through an architecture with your microphone while a live page shows the diagram, risks and cost.

    ./run.sh          (echo cancellation is on; use --headphones if the architect seems to hear itself)
"""
from __future__ import annotations

import asyncio
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from strands.bidi.io import AudioIO  # noqa: E402

from architect.agent import build_agent  # noqa: E402
from architect.session import Session  # noqa: E402

TRY = """
Try describing a design out loud, a little at a time. For example:
  "I'm designing an online store. Customers come through CloudFront to a load balancer."
  "The load balancer sends traffic to two EC2 web servers, which use a Postgres database."
  "The database is in a single availability zone and there are no backups."
  "Product images are in a public S3 bucket. We expect about two hundred requests per second."
  "What are the biggest risks?"   "What would this cost per month?"   "Please export the design document."
You can interrupt it at any time. Press Ctrl+C to stop.
"""


async def main(headphones: bool) -> None:
    s = Session()
    url = s.live.start()
    print("Live view:", url)
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - opening a browser is a convenience only
        pass
    agent = build_agent(s.design)
    audio = AudioIO(audio_processor=not headphones)
    print("Echo cancellation:", "off (headphones mode)" if headphones else "on (speakers OK)")
    print(TRY)
    await agent.run(inputs=[audio.input()], outputs=[audio.output(), s.recorder])


if __name__ == "__main__":
    try:
        asyncio.run(main("--headphones" in sys.argv))
    except KeyboardInterrupt:
        print("\nBye.")
