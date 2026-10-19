"""OscSession: the one gate between the agent and Ableton Live.

Every call is checked in this order, before any datagram leaves:

1. the address must exist in the generated catalog (:class:`UnknownAddressError`);
2. every argument must be a plain bool, int, float or str (:class:`TypeError`);
3. the consent policy must allow the entry's risk class (:class:`ConsentDenied`).

Two send paths exist because the Remote Script answers a request only when its
handler returns a value. Most setters and actions return nothing:

* :meth:`OscSession.call` is a correlated request that waits for a reply. Use it for
  reads, for ``test`` and ``other`` endpoints, and for the few writes that reply
  (for example verified mutations). If no reply arrives, it raises
  :class:`OscCallError`, even when Live did apply the change.
* :meth:`OscSession.send` is fire-and-forget. Use it for setters and actions. Confirm
  the result with a read afterwards.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from dawn_osc import OscSecuritySession, OscTransport
from dawn_osc.transport import DEFAULT_RECEIVE_PORT, DEFAULT_SEND_PORT, DEFAULT_TIMEOUT_SECONDS

from . import catalog
from .safety import Consent

SEND_PORT_ENV = "DAWN_CORE_OSC_SEND_PORT"
RECEIVE_PORT_ENV = "DAWN_CORE_OSC_RECEIVE_PORT"
_ARG_TYPES = (bool, int, float, str)


class UnknownAddressError(LookupError):
    """The address is not in the generated catalog, so it is never sent."""

    def __init__(self, address: str) -> None:
        super().__init__(f"address is not in the DAWN catalog: {address!r}")
        self.address = address


class OscCallError(RuntimeError):
    """The request got no reply, or the send failed. ``detail`` is the transport's last error."""

    def __init__(self, address: str, detail: str | None) -> None:
        super().__init__(f"no reply from {address}: {detail or 'unknown error'}")
        self.address = address
        self.detail = detail


def _port(value: int | None, env_name: str, default: int) -> int:
    if value is None:
        raw = os.environ.get(env_name)
        value = int(raw) if raw else default
    port = int(value)
    if not 0 < port < 65536:
        raise ValueError(f"port out of range: {port}")
    return port


class OscSession:
    """Authenticated, catalog-gated, consent-checked link to a running Live instance."""

    def __init__(
        self,
        *,
        send_port: int | None = None,
        receive_port: int | None = None,
        timeout_seconds: float | None = None,
        consent: Consent | None = None,
        security_session: OscSecuritySession | None = None,
        transport: OscTransport | None = None,
    ) -> None:
        """Ports default to ``$DAWN_CORE_OSC_SEND_PORT`` and ``..._RECEIVE_PORT``,
        else to the DAWN defaults (11000 and 11001).

        ``transport`` lets a host application that already holds the link to Live share it.
        Only one client can own the reply port, so a second transport would fail to bind.
        The session then uses that transport as given and never closes it: the owner does.
        A transport is exclusive with ports, a timeout and a security session, because
        the transport already carries those.

        The session binds no socket until the first call: constructing it to inspect the
        consent or the ports is free, and abandoning it leaks nothing.
        """
        self._consent = consent or Consent()
        self._transport: OscTransport | None
        if transport is not None:
            if (
                send_port is not None
                or receive_port is not None
                or timeout_seconds is not None
                or security_session is not None
            ):
                raise ValueError(
                    "transport cannot be combined with send_port, receive_port, "
                    "timeout_seconds or security_session"
                )
            self._transport = transport
            self._owns_transport = False
            self._send_port = transport.send_port
            self._receive_port = transport.receive_port
        else:
            self._owns_transport = True
            self._send_port = _port(send_port, SEND_PORT_ENV, DEFAULT_SEND_PORT)
            self._receive_port = _port(receive_port, RECEIVE_PORT_ENV, DEFAULT_RECEIVE_PORT)
            self._transport = None
        self._transport_config = (
            DEFAULT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds,
            None if transport is not None else security_session,
        )
        self._closed = False

    def _ensure_transport(self) -> OscTransport:
        """The transport, created on first use; a session owns exactly one."""
        if self._transport is None:
            timeout_seconds, security_session = self._transport_config
            self._transport = OscTransport(
                send_port=self._send_port,
                receive_port=self._receive_port,
                timeout_seconds=timeout_seconds,
                security_session=security_session,
            )
        return self._transport

    # -- properties -------------------------------------------------------

    @property
    def send_port(self) -> int:
        return self._send_port

    @property
    def receive_port(self) -> int:
        return self._receive_port

    @property
    def last_error(self) -> str | None:
        return None if self._transport is None else self._transport.last_error

    @property
    def consent(self) -> Consent:
        """The policy every call on this session is checked against."""
        return self._consent

    # -- lifecycle --------------------------------------------------------

    async def __aenter__(self) -> OscSession:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Release the transport this session created. A shared transport is left open.

        Closing is terminal: a closed session refuses every further call. Idempotent.
        """
        if self._closed:
            return
        self._closed = True
        if self._owns_transport and self._transport is not None:
            await asyncio.to_thread(self._transport.close)

    # -- calls ------------------------------------------------------------

    async def call(self, address: str, *args: Any, timeout: float | None = None) -> tuple[Any, ...]:
        """Send a correlated request and return the reply tuple.

        Raises :class:`OscCallError` when no reply arrives within ``timeout`` seconds,
        and :class:`RuntimeError` when the session is closed.
        """
        self._authorize(address, args)
        reply = await self._require_transport().request(address, *args, timeout_seconds=timeout)
        if reply is None:
            transport = self._transport
            raise OscCallError(address, None if transport is None else transport.last_error)
        return tuple(reply)

    async def send(self, address: str, *args: Any) -> None:
        """Send an unanswered datagram. Raises :class:`OscCallError` if it cannot be sent,
        and :class:`RuntimeError` when the session is closed."""
        self._authorize(address, args)
        transport = self._require_transport()
        sent = await transport.send_unacknowledged(address, *args)
        if not sent:
            raise OscCallError(address, transport.last_error)

    async def ping(self, timeout: float | None = None) -> bool:
        """True when Live answers ``/live/test`` with ``ok``.

        Never raises for a Live that does not answer; it does raise on a closed session.
        """
        return await self._require_transport().ping(timeout_seconds=timeout)

    # -- internals --------------------------------------------------------

    def _require_transport(self) -> OscTransport:
        if self._closed:
            raise RuntimeError("the session is closed")
        return self._ensure_transport()

    def _authorize(self, address: str, args: tuple[Any, ...]) -> None:
        if self._closed:
            raise RuntimeError("the session is closed")
        entry = catalog.find(address)
        if entry is None:
            raise UnknownAddressError(address)
        for arg in args:
            if not isinstance(arg, _ARG_TYPES):
                raise TypeError(
                    f"argument for {address} must be bool, int, float or str, "
                    f"not {type(arg).__name__}"
                )
        self._consent.check(entry, args)


__all__ = [
    "OscCallError",
    "OscSession",
    "RECEIVE_PORT_ENV",
    "SEND_PORT_ENV",
    "UnknownAddressError",
]
