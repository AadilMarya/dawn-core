"""Shared plumbing for the curated music tools.

Every tool returns a short string, never an exception:

* ``OK: ...`` — a write was read back and matches;
* ``MISMATCH: ...`` — Live holds another value;
* ``SENT, NOT VERIFIED: ...`` — the message left but Live did not confirm it;
* ``REFUSED: ...`` — the consent policy or a musical range check refused it;
* ``ERROR: ...`` — the call failed.

The strings are the public result protocol; see ``docs/tool-reference.md``.
"""

from __future__ import annotations

import functools
import inspect
import json
import math
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from ..safety import ConsentDenied
from ..session import OscCallError, OscSession, UnknownAddressError

Scalar = str | int | float | bool

# Live's mixer ranges. Values outside them are refused before a datagram is sent.
MIN_TEMPO = 20.0
MAX_TEMPO = 999.0
MAX_NOTES_PER_CALL = 512


class Note(BaseModel):
    """One MIDI note in a clip."""

    pitch: int = Field(ge=0, le=127, description="MIDI note number, 0-127 (60 is middle C).")
    start: float = Field(ge=0, description="Start position in beats from the clip start.")
    duration: float = Field(gt=0, description="Note length in beats.")
    velocity: int = Field(ge=1, le=127, default=100, description="MIDI velocity, 1-127.")
    mute: bool = Field(default=False, description="Whether the note is muted.")


class Refused(ValueError):
    """A musical or range check refused the call before anything was sent."""


def refused(message: str) -> str:
    return f"REFUSED: {message}"


def error(message: str) -> str:
    return f"ERROR: {message}"


def show(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def subject(group: str, selector: str, where: str = "") -> str:
    """``group.selector`` followed by its indices, e.g. ``track.mute track_index=1``."""
    return " ".join(part for part in (f"{group}.{selector}", where) if part)


def unwrap(reply: tuple[Any, ...], indices: Sequence[Any]) -> Any:
    """The value in a reply. Getters echo their index arguments before the value."""
    count = len(indices)
    rest = reply
    if count and len(reply) > count and tuple(reply[:count]) == tuple(indices):
        rest = reply[count:]
    return rest[0] if len(rest) == 1 else list(rest)


def same(requested: Any, actual: Any) -> bool:
    """Compare a written value with a read-back, tolerating bool/int and float noise."""
    if isinstance(actual, bool):
        return (
            isinstance(requested, (bool, int)) and requested in (0, 1) and bool(requested) == actual
        )
    if isinstance(requested, bool):
        return requested == actual
    if isinstance(requested, (int, float)) and isinstance(actual, (int, float)):
        return math.isclose(float(requested), float(actual), rel_tol=1e-6, abs_tol=1e-6)
    return requested == actual


async def read(session: OscSession, address: str, *args: Any) -> Any:
    """Call a getter and return its unwrapped value."""
    reply = await session.call(address, *args)
    return unwrap(reply, args)


async def call_json(session: OscSession, address: str, *args: Any) -> Any:
    """Call an endpoint that returns a JSON string (verified mutations, browser lists)."""
    reply = await session.call(address, *args)
    value = unwrap(reply, args)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


async def write_and_verify(
    session: OscSession,
    *,
    setter: str,
    setter_args: Sequence[Scalar],
    getter: str,
    expected: Any,
    label: str,
    getter_args: Sequence[Scalar] | None = None,
) -> str:
    """Write, read back through ``getter``, and report the comparison."""
    read_args = tuple(setter_args if getter_args is None else getter_args)
    try:
        await session.send(setter, *setter_args)
    except ConsentDenied as exc:
        return refused(f"{exc}. Nothing was sent.")
    except (OscCallError, UnknownAddressError) as exc:
        return error(str(exc))

    try:
        actual = await read(session, getter, *read_args)
    except (OscCallError, UnknownAddressError) as exc:
        return error(f"wrote {show(expected)} to {label}, but the read-back failed: {exc}")
    if same(expected, actual):
        return f"OK: {label} is {show(actual)}."
    return f"MISMATCH: wrote {show(expected)} to {label}; Live reports {show(actual)}."


async def send_action(session: OscSession, address: str, *args: Scalar) -> str:
    """Send a fire-and-forget action and report that it left, honestly."""
    try:
        await session.send(address, *args)
    except ConsentDenied as exc:
        return refused(f"{exc}. Nothing was sent.")
    except (OscCallError, UnknownAddressError) as exc:
        return error(str(exc))
    return f"SENT, NOT VERIFIED: {address} was sent."


def guard_result(fn: Any) -> Any:
    """Turn a refused or failed call into a result string, never an exception."""

    @functools.wraps(fn)
    async def wrapped(*args: Any, **kwargs: Any) -> str:
        try:
            return await fn(*args, **kwargs)
        except ConsentDenied as exc:
            return refused(f"{exc}. Nothing was sent.")
        except (OscCallError, UnknownAddressError) as exc:
            return error(str(exc))

    return wrapped


class ToolBase:
    """Base for tool groups: every public coroutine returns a result string.

    Subclasses define plain ``async def`` methods; this wraps each one so a consent
    refusal or a transport failure becomes ``REFUSED: ...`` / ``ERROR: ...`` instead of
    an exception escaping to the agent.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for name, value in list(vars(cls).items()):
            if not name.startswith("_") and inspect.iscoroutinefunction(value):
                setattr(cls, name, guard_result(value))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Refused(message)


def check_index(value: int, name: str) -> None:
    if value < 0:
        raise Refused(f"{name} must be 0 or greater.")


def check_range(value: float, low: float, high: float, name: str) -> None:
    if not math.isfinite(value) or not low <= value <= high:
        raise Refused(f"{name} must be between {low:g} and {high:g}, not {value:g}.")


__all__ = [
    "MAX_NOTES_PER_CALL",
    "MAX_TEMPO",
    "MIN_TEMPO",
    "Note",
    "Refused",
    "Scalar",
    "ToolBase",
    "call_json",
    "check_index",
    "check_range",
    "error",
    "read",
    "refused",
    "require",
    "same",
    "send_action",
    "show",
    "subject",
    "unwrap",
    "write_and_verify",
]
