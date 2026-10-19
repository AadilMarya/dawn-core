"""Change the producer, not the machinery.

Use a subset of the built-in doctrine, or replace the prompt entirely.
"""

from __future__ import annotations

import asyncio
import os

from dawn_core import Consent, MusicAgent, OscSession

MODEL = os.environ.get("DAWN_CORE_MODEL", "openai:gpt-4o")

TECHNO = """\
You are a techno producer working inside Ableton Live.

Build hypnotic, loop-based arrangements. Favour a steady 4/4 kick, off-beat hats, a rolling
bass and one evolving lead. Introduce change by filtering and subtracting, not by adding.
Keep the low end mono. Leave 6 dB of headroom.
"""


async def main() -> None:
    async with OscSession(consent=Consent()) as live:
        mixer = MusicAgent(
            MODEL,
            session=live,
            expertise=["mixing", "production"],
        )
        print((await mixer.run("balance the drums and bass in the current Set")).output)

        techno = MusicAgent(MODEL, session=live, system_prompt=TECHNO)
        print((await techno.run("start a 130 BPM techno loop")).output)


if __name__ == "__main__":
    asyncio.run(main())
