"""Consent policy for OSC calls, decided from the catalog risk class.

Rules, applied per call:

* ``read``        -- always allowed.
* ``write``       -- allowed unless the session is ``read_only``.
* ``destructive`` -- refused when ``read_only``. Otherwise allowed only when ``yes``
                     is set, or when the ``confirm`` callback returns exactly ``True``.
                     The default callback denies, so a bare ``Consent()`` never
                     permits a destructive call. ``yes`` takes precedence over
                     ``confirm``: setting it skips the callback entirely.

Any unknown risk class, any exception raised by ``confirm``, and any non-``True``
answer is a refusal. A coroutine function is a non-``True`` answer, so ``confirm`` must
be synchronous. The policy fails closed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ._catalog_types import CatalogEntry

ConfirmFn = Callable[[CatalogEntry, tuple[Any, ...]], bool]


class ConsentDenied(PermissionError):
    """The consent policy refused an OSC call. No request was sent."""

    def __init__(self, address: str, risk: str, reason: str) -> None:
        super().__init__(f"{risk} call to {address} denied: {reason}")
        self.address = address
        self.risk = risk
        self.reason = reason


def deny_all(entry: CatalogEntry, args: tuple[Any, ...]) -> bool:
    """Default confirmation callback: refuses every destructive call."""
    return False


@dataclass(frozen=True, slots=True)
class Consent:
    """Per-session consent. Construct once and pass to :class:`OscSession`."""

    read_only: bool = False
    yes: bool = False
    confirm: ConfirmFn = deny_all

    def check(self, entry: CatalogEntry, args: tuple[Any, ...]) -> None:
        """Raise :class:`ConsentDenied` unless the call may be sent."""
        risk = entry.risk
        if risk == "read":
            return
        if risk not in ("write", "destructive"):
            raise ConsentDenied(entry.address, risk, "unknown risk class")
        if self.read_only:
            raise ConsentDenied(entry.address, risk, "session is read-only")
        if risk == "write":
            return
        if self.yes:
            return
        try:
            answer = self.confirm(entry, args)
        except Exception as exc:
            raise ConsentDenied(entry.address, risk, "confirmation callback failed") from exc
        if answer is not True:
            raise ConsentDenied(entry.address, risk, "not confirmed")


__all__ = ["ConfirmFn", "Consent", "ConsentDenied", "deny_all"]
