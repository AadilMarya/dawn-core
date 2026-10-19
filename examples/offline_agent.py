"""Run the agent with no Ableton and no API key.

MiniLive serves an in-memory Set over the real authenticated envelope. A scripted model
calls one tool and then answers, so the whole path is deterministic.
"""

from __future__ import annotations

import asyncio
import socket

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from dawn_core import Consent, MusicAgent, OscSession
from dawn_core.testing import MiniLive
from dawn_osc.security import start_osc_session


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def scripted() -> FunctionModel:
    """Call set_tempo once, then answer."""

    def model_fn(messages, _info: AgentInfo) -> ModelResponse:
        called = any(
            getattr(part, "tool_name", None) == "set_tempo"
            for message in messages
            for part in getattr(message, "parts", ())
        )
        if called:
            return ModelResponse(parts=[TextPart("Tempo is 124.")])
        return ModelResponse(parts=[ToolCallPart("set_tempo", {"bpm": 124})])

    return FunctionModel(model_fn)


async def main() -> None:
    listen_port = free_udp_port()
    reply_port = free_udp_port()
    live = MiniLive(
        session=start_osc_session(),
        listen_port=listen_port,
        reply_port=reply_port,
    )
    live.start()
    try:
        async with OscSession(
            send_port=listen_port, receive_port=reply_port, consent=Consent()
        ) as session:
            agent = MusicAgent(scripted(), session=session)
            result = await agent.run("set the tempo to 124")
            print(result.output)
            print(f"MiniLive tempo is now {live.tempo:g}")
    finally:
        live.stop()


if __name__ == "__main__":
    asyncio.run(main())
