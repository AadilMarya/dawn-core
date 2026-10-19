"""The smallest useful DAWN Core agent.

Install the Remote Script first (``examples/install_remote_script.py``), then run:

    pip install "dawn-core[openai]"
    python examples/quickstart.py
"""

from __future__ import annotations

import asyncio
import os

from dawn_core import Consent, MusicAgent, OscSession

MODEL = os.environ.get("DAWN_CORE_MODEL", "openai:gpt-4o")


async def main() -> None:
    async with OscSession(consent=Consent(confirm=_confirm)) as live:
        agent = MusicAgent(MODEL, session=live)
        result = await agent.run(
            "Build a 4-bar deep house groove at 122: drums, a sub bass, and a chord stab."
        )
        print(result.output)


def _confirm(entry, args) -> bool:
    """Ask before a destructive call. Anything but an explicit yes refuses."""
    print(f"\nDestructive: {entry.address} {args}")
    return input("Proceed? [y/N] ").strip().lower() in {"y", "yes"}


if __name__ == "__main__":
    asyncio.run(main())
