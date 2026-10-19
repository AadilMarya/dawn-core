"""Agent-flow evals: a scripted model drives the tools against the offline Live double.

These do not judge the model's prose. They prove the agent can complete a musical task,
read its work back, and report a refusal honestly.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from dawn_core import Consent, MusicAgent, OscSession
from dawn_core.testing import MiniLive, MiniTrack


def scripted(*calls: tuple[str, dict[str, Any]], final: str) -> FunctionModel:
    def model_fn(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        done = sum(
            1
            for message in messages
            for part in getattr(message, "parts", ())
            if isinstance(part, ToolReturnPart)
        )
        if done < len(calls):
            name, arguments = calls[done]
            return ModelResponse(parts=[ToolCallPart(name, arguments)])
        return ModelResponse(parts=[TextPart(final)])

    return FunctionModel(model_fn)


@pytest.mark.asyncio
async def test_eval_set_tempo(live: MiniLive, ports: tuple[int, int]) -> None:
    model = scripted(("set_tempo", {"bpm": 122}), final="Tempo is 122.")
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = await MusicAgent(model, session=session).run("set the tempo to 122")
    assert result.output == "Tempo is 122."
    assert live.tempo == 122.0


@pytest.mark.asyncio
async def test_eval_create_and_name_a_track(live: MiniLive, ports: tuple[int, int]) -> None:
    def create(_params: tuple[Any, ...]) -> None:
        live.tracks.append(MiniTrack("MIDI", False, 0.7))

    live.serve("/live/song/create_midi_track", create)
    model = scripted(
        ("create_track", {"kind": "midi", "name": "Bass"}), final="Created the Bass track."
    )
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = await MusicAgent(model, session=session).run("add a MIDI track called Bass")
    assert result.output == "Created the Bass track."
    assert live.tracks[-1].name == "Bass"


@pytest.mark.asyncio
async def test_eval_mute_a_track(live: MiniLive, ports: tuple[int, int]) -> None:
    model = scripted(("set_track_mute", {"track_index": 1, "muted": True}), final="Muted Bass.")
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = await MusicAgent(model, session=session).run("mute the bass")
    assert result.output == "Muted Bass."
    assert live.tracks[1].mute is True


@pytest.mark.asyncio
async def test_eval_read_only_session_refuses_a_write(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    model = scripted(("set_tempo", {"bpm": 130}), final="I could not change the tempo.")
    async with OscSession(
        send_port=ports[0], receive_port=ports[1], consent=Consent(read_only=True)
    ) as session:
        result = await MusicAgent(model, session=session).run("set the tempo to 130")
    assert result.output == "I could not change the tempo."
    assert live.tempo == 120.0


@pytest.mark.asyncio
async def test_eval_destructive_delete_is_refused(live: MiniLive, ports: tuple[int, int]) -> None:
    before = len(live.tracks)
    model = scripted(("delete_track", {"track_index": 0}), final="I did not delete the track.")
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = await MusicAgent(model, session=session).run("delete the first track")
    assert result.output == "I did not delete the track."
    assert len(live.tracks) == before


@pytest.mark.asyncio
async def test_eval_unknown_address_is_refused(live: MiniLive, ports: tuple[int, int]) -> None:
    model = scripted(
        ("catalog_call", {"address": "/live/not/a/real/address"}),
        final="That address does not exist.",
    )
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = await MusicAgent(model, session=session).run("call the mystery endpoint")
    assert result.output == "That address does not exist."
