"""Value types for the OSC catalog. The generated catalog module imports these."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RiskClass = Literal["read", "write", "destructive"]
RISK_CLASSES: tuple[RiskClass, ...] = ("read", "write", "destructive")

Verb = Literal["get", "set", "call", "start_listen", "stop_listen", "test", "other"]
ArgKind = Literal["int", "any"]


@dataclass(frozen=True, slots=True)
class ArgSpec:
    """One positional argument. ``int`` marks an index; ``any`` is untyped."""

    name: str
    kind: ArgKind
    variadic: bool = False


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One OSC address the Remote Script serves.

    ``prop`` is the property path for get/set/listen verbs and ``None`` otherwise.
    ``source`` is ``<file>:<line>`` of the registration that won (last one wins).

    ``replies`` is True when the handler returns a value somewhere, so Live answers a
    correlated request. It is False when the handler never returns a value, and None
    when the generator cannot resolve the handler statically. True does not promise a
    reply on every call: a handler may return a value on some paths only.
    """

    address: str
    group: str
    verb: Verb
    prop: str | None
    args: tuple[ArgSpec, ...]
    risk: RiskClass
    source: str
    replies: bool | None = None
