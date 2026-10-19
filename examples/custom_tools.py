"""Add a tool next to the curated ones.

A tool is a typed async function with a docstring. The docstring is the model's
instruction; the type hints become the JSON schema.
"""

from __future__ import annotations

import asyncio
import os

from pydantic_ai import Tool

from dawn_core import Consent, MusicAgent, OscSession, build_tools

MODEL = os.environ.get("DAWN_CORE_MODEL", "openai:gpt-4o")


def make_tools(session: OscSession) -> list[Tool]:
    async def nudge_tempo(delta: float) -> str:
        """Change the tempo by a small amount, then read it back.

        ``delta`` is in BPM and must be between -20 and 20.
        """
        if not -20 <= delta <= 20:
            return f"REFUSED: delta must be between -20 and 20, not {delta:g}."
        (current,) = await session.call("/live/song/get/tempo")
        target = float(current) + delta
        await session.send("/live/song/set/tempo", target)
        (actual,) = await session.call("/live/song/get/tempo")
        if abs(float(actual) - target) < 0.001:
            return f"OK: tempo is {float(actual):g} BPM."
        return f"MISMATCH: asked for {target:g}; Live reports {float(actual):g}."

    return [Tool(nudge_tempo, sequential=True)]


async def main() -> None:
    async with OscSession(consent=Consent()) as live:
        agent = MusicAgent(
            MODEL,
            session=live,
            tools=[*build_tools(live), *make_tools(live)],
        )
        print((await agent.run("nudge the tempo up by 2 BPM")).output)


if __name__ == "__main__":
    asyncio.run(main())
