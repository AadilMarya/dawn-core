"""The music agent itself: a model, the tuned prompt, and the Ableton tools.

``MusicAgent`` wraps a ``pydantic_ai.Agent``. It is intentionally small: the value is the
prompt and the tool surface, not a framework. Swap the model, the expertise subset or the
tool list without touching the rest.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pydantic_ai
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage

from .prompt import compose_system_prompt
from .session import OscSession
from .tools import build_tools

# A library should not print a startup banner into its host's output.
pydantic_ai.BANNER_ENABLED = False


class MusicAgent:
    """An Ableton music producer driven by a model and a consent-gated session.

    >>> agent = MusicAgent("openai:gpt-4o", session=live)
    >>> await agent.run("build a 4-bar deep house groove at 122")
    """

    def __init__(
        self,
        model: Any,
        *,
        session: OscSession,
        expertise: Sequence[str] | None = None,
        tools: Sequence[Any] | None = None,
        system_prompt: str | None = None,
        name: str = "dawn_core",
        history: Sequence[ModelMessage] = (),
        **agent_kwargs: Any,
    ) -> None:
        if not isinstance(session, OscSession):
            raise TypeError("session must be an OscSession")
        if system_prompt is not None and expertise is not None:
            raise ValueError("pass system_prompt or expertise, not both")
        prompt = system_prompt if system_prompt is not None else compose_system_prompt(expertise)
        tool_list = build_tools(session) if tools is None else list(tools)
        self._session = session
        self._history: list[ModelMessage] = list(history)
        self._system_prompt = prompt
        self._tools = tuple(tool_list)
        self._agent: Agent[None, str] = Agent(
            model,
            system_prompt=prompt,
            tools=tool_list,
            name=name,
            **agent_kwargs,
        )

    @property
    def agent(self) -> Agent[None, str]:
        """The underlying ``pydantic_ai.Agent``, for advanced use."""
        return self._agent

    @property
    def session(self) -> OscSession:
        """The session every tool is bound to."""
        return self._session

    @property
    def tools(self) -> tuple[Any, ...]:
        """The tool objects handed to the model."""
        return self._tools

    @property
    def system_prompt(self) -> str:
        """The composed prompt for this agent."""
        return self._system_prompt

    def _history_for(
        self, message_history: Sequence[ModelMessage] | None
    ) -> Sequence[ModelMessage] | None:
        if message_history is not None:
            return message_history
        return self._history or None

    async def run(
        self,
        user_prompt: Any = None,
        *,
        message_history: Sequence[ModelMessage] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Run one turn and return the result. ``result.output`` is the answer."""
        return await self._agent.run(
            user_prompt,
            message_history=self._history_for(message_history),
            **kwargs,
        )

    def run_stream(
        self,
        user_prompt: Any = None,
        *,
        message_history: Sequence[ModelMessage] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Stream one turn. Use it as an async context manager."""
        return self._agent.run_stream(
            user_prompt,
            message_history=self._history_for(message_history),
            **kwargs,
        )


def build_agent(
    model: Any,
    session: OscSession,
    *,
    expertise: Sequence[str] | None = None,
    tools: Sequence[Any] | None = None,
    system_prompt: str | None = None,
    history: Sequence[ModelMessage] = (),
    **agent_kwargs: Any,
) -> MusicAgent:
    """Build a :class:`MusicAgent`; the functional form of the constructor."""
    return MusicAgent(
        model,
        session=session,
        expertise=expertise,
        tools=tools,
        system_prompt=system_prompt,
        history=history,
        **agent_kwargs,
    )


__all__ = ["MusicAgent", "build_agent"]
