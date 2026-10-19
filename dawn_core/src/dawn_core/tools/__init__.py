"""Curated music tools, bound to one :class:`~dawn_core.session.OscSession`.

Each tool is a typed asynchronous method. ``build_tools`` turns them into
``pydantic_ai.Tool`` objects; the docstring is the description the model sees and the
type hints become the JSON schema.

Every write is read back, and every result is one of ``OK``, ``MISMATCH``,
``SENT, NOT VERIFIED``, ``REFUSED`` or ``ERROR`` (see ``_helpers``).
"""

from __future__ import annotations

import inspect
from typing import Any

from pydantic_ai import Tool

from ..session import OscSession
from ._helpers import Note
from .catalog_tool import CatalogTools
from .clips import ClipTools
from .devices import DeviceTools
from .scenes import SceneTools
from .session import SessionTools
from .tracks import TrackTools

_TOOL_CLASSES = (SessionTools, TrackTools, ClipTools, SceneTools, DeviceTools, CatalogTools)


def _tool_methods(cls: type[Any]) -> tuple[str, ...]:
    return tuple(
        name
        for name, value in vars(cls).items()
        if not name.startswith("_") and inspect.iscoroutinefunction(value)
    )


def tool_names() -> tuple[str, ...]:
    """Names of every curated tool, sorted."""
    return tuple(sorted(name for cls in _TOOL_CLASSES for name in _tool_methods(cls)))


def build_tools(session: OscSession) -> list[Tool[Any]]:
    """Every curated tool, bound to ``session``, in name order.

    All tools are marked ``sequential`` so a write and its read-back keep the order the
    model issued them. Calling these methods concurrently outside the agent bypasses that
    guarantee.
    """
    tools: list[Tool[Any]] = []
    for cls in _TOOL_CLASSES:
        instance = cls(session)
        for name in _tool_methods(cls):
            tools.append(Tool(getattr(instance, name), name=name, sequential=True))
    return sorted(tools, key=lambda tool: tool.name)


__all__ = [
    "CatalogTools",
    "ClipTools",
    "DeviceTools",
    "Note",
    "SceneTools",
    "SessionTools",
    "TrackTools",
    "build_tools",
    "tool_names",
]
