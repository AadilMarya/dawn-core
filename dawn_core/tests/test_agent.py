"""The agent loop, with a deterministic model and the offline Live double."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from dawn_core import (
    SYSTEM_PROMPT,
    Consent,
    MusicAgent,
    OscSession,
    build_agent,
    compose_system_prompt,
)
from dawn_core.testing import MiniLive


def _tool_returns(messages: list[ModelMessage]) -> int:
    return sum(
        1
        for message in messages
        for part in getattr(message, "parts", ())
        if isinstance(part, ToolReturnPart)
    )


def scripted(*calls: tuple[str, dict[str, Any]], final: str = "Done.") -> FunctionModel:
    """A model that calls ``calls`` in order, then answers with ``final``."""

    def model_fn(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        done = _tool_returns(messages)
        if done < len(calls):
            name, arguments = calls[done]
            return ModelResponse(parts=[ToolCallPart(name, arguments)])
        return ModelResponse(parts=[TextPart(final)])

    return FunctionModel(model_fn)


@pytest.mark.asyncio
async def test_agent_calls_a_tool_and_answers(live: MiniLive, ports: tuple[int, int]) -> None:
    model = scripted(("set_tempo", {"bpm": 128}), final="Tempo is 128.")
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        agent = MusicAgent(model, session=session)
        result = await agent.run("set the tempo to 128")
    assert result.output == "Tempo is 128."
    assert live.tempo == 128.0


@pytest.mark.asyncio
async def test_agent_reports_a_refused_write(live: MiniLive, ports: tuple[int, int]) -> None:
    model = scripted(("set_tempo", {"bpm": 128}), final="I could not change it.")
    async with OscSession(
        send_port=ports[0], receive_port=ports[1], consent=Consent(read_only=True)
    ) as session:
        agent = MusicAgent(model, session=session)
        result = await agent.run("set the tempo to 128")
    assert result.output == "I could not change it."
    assert live.tempo == 120.0


@pytest.mark.asyncio
async def test_agent_streams_text(live: MiniLive, ports: tuple[int, int]) -> None:
    async def stream_fn(_messages: list[ModelMessage], _info: AgentInfo):
        yield "A short answer."

    model = FunctionModel(stream_function=stream_fn)
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        agent = MusicAgent(model, session=session)
        chunks: list[str] = []
        async with agent.run_stream("say something") as stream:
            async for chunk in stream.stream_text(delta=True):
                chunks.append(chunk)
    assert "".join(chunks) == "A short answer."


def _model() -> FunctionModel:
    return FunctionModel(lambda _messages, _info: ModelResponse(parts=[TextPart("ok")]))


def test_agent_binds_the_curated_tools(ports: tuple[int, int]) -> None:
    session = OscSession(send_port=ports[0], receive_port=ports[1])
    agent = MusicAgent(_model(), session=session)
    names = {tool.name for tool in agent.tools}
    assert "set_tempo" in names
    assert "add_notes" in names
    assert len(names) == 27


def test_agent_uses_the_tuned_prompt(ports: tuple[int, int]) -> None:
    session = OscSession(send_port=ports[0], receive_port=ports[1])
    agent = MusicAgent(_model(), session=session)
    assert "music producer and mix engineer" in SYSTEM_PROMPT
    assert "music producer and mix engineer" in agent.system_prompt


def test_expertise_selects_sections(ports: tuple[int, int]) -> None:
    session = OscSession(send_port=ports[0], receive_port=ports[1])
    agent = MusicAgent(_model(), session=session, expertise=["mixing"])
    prompt = agent.system_prompt
    assert "Mixing doctrine" in prompt
    assert "Arrangement doctrine" not in prompt
    assert "Persona" in prompt
    assert "Ableton Live" in prompt


def test_system_prompt_and_expertise_are_exclusive(ports: tuple[int, int]) -> None:
    session = OscSession(send_port=ports[0], receive_port=ports[1])
    with pytest.raises(ValueError):
        MusicAgent(
            _model(),
            session=session,
            expertise=["mixing"],
            system_prompt="custom",
        )


def test_build_agent_is_the_functional_form(ports: tuple[int, int]) -> None:
    session = OscSession(send_port=ports[0], receive_port=ports[1])
    agent = build_agent(_model(), session)
    assert isinstance(agent, MusicAgent)
    assert agent.session is session


def test_unknown_expertise_is_refused(ports: tuple[int, int]) -> None:
    session = OscSession(send_port=ports[0], receive_port=ports[1])
    with pytest.raises(ValueError):
        MusicAgent(_model(), session=session, expertise=["teleportation"])


def test_prompt_is_within_the_token_budget() -> None:
    # A rough token estimate: four characters per token. The cap keeps every turn cheap.
    assert len(compose_system_prompt()) <= 10_000
