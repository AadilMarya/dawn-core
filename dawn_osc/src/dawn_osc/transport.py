"""OscTransport — authenticated OSC socket, handshake, and request/reply correlation.

This is the dependency-light transport layer: it owns the UDP sockets, the HMAC
session handshake with the Remote Script, protocol gating, bounded in-flight
admission, and tagged request/reply matching.  It knows nothing about tracks,
clips, devices, or verified-mutation bookkeeping; those live in subclasses.

Two locks co-exist in this class:

  _send_thread_lock  (threading.Lock)
      Guards the UDP send socket.  The socket is accessed from the receiver
      callback thread (via _request_sync) AND from asyncio.to_thread workers,
      so it must be a plain threading.Lock — asyncio.Lock cannot be acquired
      from a non-async context.

  _inflight_async_lock  (asyncio.Lock)
      Guards _inflight_count, which is read/written only from async callers
      (_request coroutine).  An asyncio.Lock is correct here because it must
      be awaited and therefore cannot be used in the sync callback path.
      Using threading.Lock here would be wrong because asyncio.Lock is
      non-reentrant from sync callbacks; conversely, threading.Lock cannot
      be awaited.
"""

from __future__ import annotations

import asyncio
import contextvars
import errno
import ipaddress
import re
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_message import OscMessage
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

from .security import (
    OSC_SECURITY_PROTOCOL,
    OSC_SECURITY_STATUS_ADDRESS,
    OscSecurityError,
    OscSecuritySession,
    get_process_osc_session,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_SEND_PORT = 11000
DEFAULT_RECEIVE_PORT = 11001
DEFAULT_TIMEOUT_SECONDS = 1.0
DEFAULT_REQUEST_TIMEOUT = 5.0
PING_TIMEOUT = 1.5
MAX_INFLIGHT_REQUESTS = 10
# Slots of the ceiling held back for verified-mutation receipt traffic, so a
# wide read wave queues behind ordinary slots instead of starving settlement.
RESERVED_SETTLEMENT_SLOTS = 2
_SETTLEMENT_ADDRESSES = frozenset(
    {"/dawn/execute_verified", "/dawn/execute_verified_batch", "/dawn/verified/result"}
)
# How long an authenticated reply stands as proof that Live is still reachable.
# Deliberately short relative to how long a user leaves Live idle, but far longer
# than the gap between two actions in one plan — which is the case that matters,
# because that is where a redundant liveness ping costs a full Live tick per
# action. Liveness is only ever used to *skip* a probe, never to report health:
# a stale value costs one wasted request, never a false "connected".
REACHABLE_WITHOUT_PING_SECONDS = 30.0
# The text recorded when a request was sent and no reply came for its address. Callers
# match on this prefix (dawn_core's replying-call path), so change both together.
REPLY_TIMEOUT_PREFIX = "Timed out waiting for reply from "


def _admission_slot(client: Any, address: str) -> asyncio.Semaphore:
    """The per-client semaphore bounding concurrent requests of this class.

    Created lazily so clients and test doubles that borrow ``_request`` keep
    working without extra construction.
    """
    attr = "_settlement_slots" if address in _SETTLEMENT_ADDRESSES else "_ordinary_slots"
    slot = getattr(client, attr, None)
    if slot is None:
        size = (
            RESERVED_SETTLEMENT_SLOTS
            if attr == "_settlement_slots"
            else MAX_INFLIGHT_REQUESTS - RESERVED_SETTLEMENT_SLOTS
        )
        slot = asyncio.Semaphore(size)
        setattr(client, attr, slot)
    return slot


@dataclass
class _OSCReplyTracker:
    """Holds reply state for one in-flight OSC request."""

    address: str
    event: threading.Event
    reply: list[Any]
    error: Exception | None = None
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)


class _AuthenticatedOSCServer(ThreadingOSCUDPServer):  # type: ignore[misc]
    """Authenticated OSC receiver with a read-only legacy-version detector."""

    # Never share the authenticated receive port with a stale/foreign socket.
    allow_reuse_address = False

    def __init__(
        self,
        server_address: tuple[str, int],
        dispatcher: Dispatcher,
        *,
        security_session: OscSecuritySession,
        on_authenticated: Callable[[], None],
        on_legacy_version: Callable[[tuple[Any, ...], tuple[str, int]], None],
    ) -> None:
        self._security_session = security_session
        self._on_authenticated = on_authenticated
        self._on_legacy_version = on_legacy_version
        super().__init__(server_address, dispatcher)

    def verify_request(self, request: Any, client_address: Any) -> bool:
        try:
            return ipaddress.ip_address(str(client_address[0])).is_loopback
        except ValueError:
            return False

    def process_request(self, request: Any, client_address: Any) -> None:
        data, sock = request
        try:
            payload = self._security_session.unwrap_response(data)
        except OscSecurityError:
            # The only unsigned packet accepted by the app is a read-only
            # /dawn/version reply used to diagnose an installed legacy surface.
            # It is never dispatched as state and cannot authorize a mutation.
            try:
                message = OscMessage(data)
            except Exception:
                return
            if message.address == "/dawn/version":
                self._on_legacy_version(tuple(message.params), client_address)
            return
        self._on_authenticated()
        if payload is None:
            # Fragmented replies are authenticated per datagram, but must not
            # enter the OSC library until the complete payload has been reassembled.
            return
        super().process_request((payload, sock), client_address)


class _SecureSimpleUDPClient(SimpleUDPClient):  # type: ignore[misc]
    """OSC client that authenticates the complete encoded datagram."""

    def __init__(self, address: str, port: int, session: OscSecuritySession) -> None:
        self._security_session = session
        super().__init__(address, port)

    def send(self, content: Any) -> None:
        for secured in self._security_session.wrap_request_many(content.dgram):
            self._sock.sendto(secured, (self._address, self._port))


class OscTransport:
    """Authenticated OSC transport — connection, locking, and request/reply machinery."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        send_port: int = DEFAULT_SEND_PORT,
        receive_port: int = DEFAULT_RECEIVE_PORT,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        *,
        expected_instance_id: str | None = None,
        security_session: OscSecuritySession | None = None,
    ) -> None:
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("DAWN OSC transport is restricted to IPv4 loopback")
        self.host = DEFAULT_HOST
        self.send_port = send_port
        self.receive_port = receive_port
        self.timeout_seconds = timeout_seconds
        self.read_timeout_seconds = timeout_seconds
        self.expected_instance_id = str(expected_instance_id or "").strip().lower() or None
        # Each concurrently connected Remote Script gets an independent replay
        # window.  The credentials remain the same launch-local secret, but a
        # response counter generated by Live A must never suppress a valid
        # response from Live B in a shared replay cache.
        self._security_session = security_session or get_process_osc_session()
        self._secure_ready = False
        self._instance_verified = self.expected_instance_id is None
        self._surface_identity_checked_at: float | None = None
        self._surface_identity_lock = threading.Lock()
        self._surface_instance_id: str | None = None
        self._surface_revision: str | None = None
        self._surface_protocol: str | None = None
        self._legacy_surface_detected = False
        self._legacy_probe_event = threading.Event()
        self._legacy_probe_active_until = 0.0
        self._client = self._build_udp_client()
        # threading.Lock — used in the UDP receiver callback thread. asyncio locks
        # cannot be acquired in a non-async context, so this must stay a plain Lock.
        self._send_thread_lock = threading.Lock()
        self._logger = logger.bind(
            component="ableton.osc_client",
            host=self.host,
            send_port=self.send_port,
            receive_port=self.receive_port,
            expected_instance_id=self.expected_instance_id,
        )
        self._last_error: str | None = None
        self._error_history: list[str] = []
        self._MAX_ERROR_HISTORY = 10
        self._last_ping_result: bool | None = None
        self._inflight_count = 0
        # asyncio.Lock — used exclusively by async callers (_request coroutine).
        # Cannot use threading.Lock here because asyncio.Lock is not re-entrant
        # from sync callbacks; conversely, threading.Lock cannot be awaited.
        self._inflight_async_lock = asyncio.Lock()
        self._pending: dict[str, deque[_OSCReplyTracker]] = {}
        self._pending_lock = threading.Lock()
        self._receiver_started = False
        self._receiver_thread: threading.Thread | None = None
        self._server: _AuthenticatedOSCServer | None = None
        # Monotonic stamp of the last authenticated reply; 0.0 means "never".
        self._last_reply_monotonic = 0.0
        # Nested legacy-state reads share one monotonic wall-clock deadline.
        # Context-local binding keeps unrelated concurrent OSC requests free to
        # use their own normal timeouts.
        self._request_deadline: contextvars.ContextVar[float | None] = contextvars.ContextVar(
            "osc_request_deadline",
            default=None,
        )
        # Fixed-cadence liveness probes retain their detailed failure in
        # ``last_error`` but log only the state transition in ``ping``. This
        # prevents a closed Live instance from producing one warning per
        # low-level timeout while preserving normal request diagnostics.
        self._quiet_failure_logging: contextvars.ContextVar[bool] = contextvars.ContextVar(
            "osc_quiet_failure_logging",
            default=False,
        )
        self._logger.info("osc.client.startup")

    # -- extension points ----------------------------------------------------
    # The transport owns sockets, authentication and request/reply correlation.
    # Embedders override these to attach their own per-request and lifecycle
    # behavior; the defaults do nothing.

    def _before_request_send(self, address: str) -> None:
        """Called under the send lock immediately before a correlated request is sent."""

    def _on_surface_revision_changed(self) -> None:
        """Called when a re-handshake reports a different Remote Script revision."""

    def _on_close(self) -> None:
        """Called at the start of ``close()``, before sockets are released."""

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def surface_revision(self) -> str | None:
        """Deployable revision reported by the authenticated Remote Script."""
        return self._surface_revision

    @property
    def surface_instance_id(self) -> str | None:
        """Authenticated Remote Script slot reported by the security handshake."""

        return self._surface_instance_id

    def remote_script_handshake_signal(self) -> dict[str, Any]:
        """Raw evidence from the most recent handshake/legacy-probe attempt.

        Read-only projection of internal state — never sends anything and
        never mutates. Callers that need to explain *why* the authenticated
        handshake is not currently ready (setup status, repair UI) combine
        this with on-disk reconcile state; see
        ``setup.control_surface.classify_remote_script_state``.

        ``secure_ready`` requires both the authenticated reply and instance
        verification: a Remote Script that answered but reported the wrong
        ``expected_instance_id`` is not a "ready" handshake even though
        ``_secure_ready`` alone would say so.
        """

        return {
            "secure_ready": bool(self._secure_ready and self._instance_verified),
            "legacy_detected": bool(self._legacy_surface_detected),
            "surface_revision": self._surface_revision,
        }

    def start_receiver(self) -> bool:
        """Eagerly reserve DAWN's reply port for the selected DAW lifecycle."""
        return self._ensure_receiver_started()

    async def request(
        self,
        address: str,
        *args: Any,
        timeout_seconds: float | None = None,
    ) -> tuple[Any, ...] | None:
        """Send an OSC query and wait for the reply tuple."""
        return await self._request(address, *args, timeout_seconds=timeout_seconds)

    async def send_unacknowledged(self, address: str, *args: Any) -> bool:
        """Send one OSC message without waiting for a reply. True if the datagram was sent.

        For setters and actions that the Remote Script never answers. The authenticated
        handshake runs before the datagram, exactly as for every send, and the blocking
        socket work runs in a worker thread. A True return means the datagram left the
        socket, not that Live applied it: verify the change with a read. On failure this
        returns False and ``last_error`` holds the reason.
        """
        return await asyncio.to_thread(self._send_message_sync, address, *args)

    def recently_reachable(self) -> bool:
        """True when a recent authenticated reply already proves Live is alive.

        Only ever consulted to skip a *redundant* `/live/test` probe when the
        very next request would prove the same thing. It is never health: a
        false positive costs one request that then fails normally, and callers
        must still handle that failure. See `REACHABLE_WITHOUT_PING_SECONDS`.
        """
        if self._last_reply_monotonic <= 0.0:
            return False
        return (time.monotonic() - self._last_reply_monotonic) < REACHABLE_WITHOUT_PING_SECONDS

    async def ping(self, timeout_seconds: float | None = None) -> bool:
        short_timeout = timeout_seconds if timeout_seconds is not None else PING_TIMEOUT
        quiet_token = self._quiet_failure_logging.set(True)
        try:
            reply = await self._request("/live/test", timeout_seconds=short_timeout)
        finally:
            self._quiet_failure_logging.reset(quiet_token)
        if reply is None:
            ok = False
        elif not reply:
            ok = False
        else:
            ok = any(str(v).strip().lower() == "ok" for v in reply if not str(v).startswith("/"))
        changed = self._last_ping_result is None or self._last_ping_result != ok
        self._last_ping_result = ok
        if changed:
            if ok:
                self._logger.info("osc.ping.ok")
            else:
                self._logger.warning("osc.ping.failed")
        else:
            self._logger.debug("osc.ping.unchanged")
        return ok

    async def _request(
        self, address: str, *args: Any, timeout_seconds: float | None = None
    ) -> tuple[Any, ...] | None:
        effective_timeout = timeout_seconds
        deadline = self._request_deadline.get()
        remaining: float | None = None
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                message = "OSC session fallback deadline exhausted"
                if self._last_error != message:
                    self._record_error(message)
                return None
            requested = self.timeout_seconds if timeout_seconds is None else float(timeout_seconds)
            effective_timeout = max(0.001, min(requested, remaining))

        total_timeout = (effective_timeout or DEFAULT_REQUEST_TIMEOUT) + 1.0
        if remaining is not None:
            total_timeout = max(0.001, min(total_timeout, remaining))

        # Excess requests wait for capacity within their own deadline rather
        # than being refused outright; the wait counts against that deadline.
        slot = _admission_slot(self, address)
        queued_at = time.monotonic()
        try:
            await asyncio.wait_for(slot.acquire(), timeout=total_timeout)
        except TimeoutError:
            self._record_error(f"OSC request queue wait exceeded {total_timeout}s: {address}")
            return None
        total_timeout = max(0.001, total_timeout - (time.monotonic() - queued_at))
        try:
            async with self._inflight_async_lock:
                self._inflight_count += 1
            try:
                reply = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._request_sync, address, *args, timeout_seconds=effective_timeout
                    ),
                    timeout=total_timeout,
                )
                if reply is not None:
                    # Any authenticated reply is liveness proof. Recorded so callers
                    # can skip a dedicated `/live/test` probe they would otherwise
                    # pay a full 100 ms Live tick for — see `recently_reachable`.
                    self._last_reply_monotonic = time.monotonic()
                return reply
            except TimeoutError:
                self._record_error(f"OSC request timed out after {total_timeout}s: {address}")
                return None
            finally:
                async with self._inflight_async_lock:
                    self._inflight_count -= 1
        finally:
            # Released on every exit, including cancellation mid-request.
            slot.release()

    def _send_message_sync(self, address: str, *args: Any) -> bool:
        if not self._establish_secure_transport_sync():
            return False
        with self._send_thread_lock:
            return self._send_with_retry_locked(
                address,
                *args,
                failure_prefix=f"Failed to send OSC message to {self.host}:{self.send_port}",
                unexpected_prefix=(f"Unexpected OSC send failure to {self.host}:{self.send_port}"),
            )

    def _ensure_receiver_started(self) -> bool:
        """Lazy-start the persistent OSC receiver. Returns False if startup failed."""
        if self._receiver_started:
            return True
        with self._pending_lock:
            if self._receiver_started:
                return True
            try:
                self._server = _AuthenticatedOSCServer(
                    (self.host, self.receive_port),
                    Dispatcher(),
                    security_session=self._security_session,
                    on_authenticated=self._mark_secure_ready,
                    on_legacy_version=self._mark_legacy_surface,
                )
            except OSError as exc:
                self._record_bind_error(exc)
                return False

            self._server.dispatcher.map("*", self._handle_reply)
            self._receiver_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._receiver_thread.start()
            self._receiver_started = True
            self._logger.info("osc.persistent_receiver.started")
            return True

    def _handle_reply(self, address: str, *args: Any) -> None:
        # Authentication proves the sender, not which logical read it answers.
        # Bare listener/error broadcasts are diagnostic-only, never FIFO replies.
        if address == "/live/error":
            self._logger.bind(control_surface_error=args).warning("osc.control_surface.error")
        if not args or not isinstance(args[0], str):
            return
        match = re.fullmatch(r"dawn_reply:([0-9a-f]{32})", args[0])
        if match is None:
            return
        request_id = match.group(1)
        values = args[1:]
        target_address = address
        if address == "/live/error":
            if not values or not isinstance(values[0], str) or not values[0].startswith("/"):
                return
            target_address = values[0]
        tracker = None
        with self._pending_lock:
            trackers = self._pending.get(target_address)
            if trackers:
                tracker = next((item for item in trackers if item.request_id == request_id), None)
                if tracker is not None:
                    trackers.remove(tracker)
                    if not trackers:
                        self._pending.pop(target_address, None)
        if tracker is None:
            return
        if address == "/live/error":
            tracker.error = RuntimeError(" ".join(str(value) for value in values))
        else:
            tracker.reply[:] = list(values)
        tracker.event.set()

    def _mark_secure_ready(self) -> None:
        self._secure_ready = True

    def _mark_legacy_surface(
        self,
        _params: tuple[Any, ...],
        client_address: tuple[str, int],
    ) -> None:
        if time.monotonic() > self._legacy_probe_active_until:
            return
        try:
            expected = (self.host, int(self.send_port))
            actual = (str(client_address[0]), int(client_address[1]))
        except (IndexError, TypeError, ValueError):
            return
        if actual != expected:
            return
        self._legacy_surface_detected = True
        self._legacy_probe_event.set()

    def _probe_legacy_surface_sync(self) -> bool:
        """Send one unsigned, read-only version query for upgrade diagnostics."""
        self._legacy_probe_event.clear()
        probe_window = min(0.35, max(0.05, self.timeout_seconds))
        self._legacy_probe_active_until = time.monotonic() + probe_window
        try:
            probe = SimpleUDPClient(self.host, self.send_port)
            try:
                probe.send_message("/dawn/version", [])
            finally:
                probe.close()
            return self._legacy_probe_event.wait(probe_window)
        except Exception:
            return False
        finally:
            self._legacy_probe_active_until = 0.0

    def _establish_secure_transport_sync(self) -> bool:
        # Concurrent reads share one authenticated identity refresh. Live can
        # restart while this desktop client remains alive; its previous revision
        # must not strand writes behind the stale-surface gate indefinitely.
        with self._surface_identity_lock:
            return self._establish_secure_transport_unlocked()

    def _establish_secure_transport_unlocked(self) -> bool:
        checked_at = self._surface_identity_checked_at
        if (
            self._secure_ready
            and self._instance_verified
            and (checked_at is None or time.monotonic() - checked_at < 5.0)
        ):
            return True
        if self._legacy_surface_detected:
            self._record_error(
                "Installed DAWN Control Surface is legacy and unauthenticated; "
                "reinstall the DAWN Remote Script and restart Ableton Live"
            )
            return False
        reply = self._request_sync(
            OSC_SECURITY_STATUS_ADDRESS,
            timeout_seconds=min(0.5, max(0.1, self.timeout_seconds)),
            _skip_security_handshake=True,
        )
        if reply is not None and self._secure_ready:
            # The producer returns (DAWN_PROTOCOL_VERSION, transport_session,
            # surface_revision, instance_id). The session id is not a version.
            # Capture the version so
            # optional endpoints (batched verified writes, 2.6.0+) can be
            # version-gated instead of discovered by timing out.
            self._surface_protocol = str(reply[0]) if reply and isinstance(reply[0], str) else None
            if len(reply) >= 3 and isinstance(reply[2], str):
                revision = str(reply[2])
                if self._surface_revision is not None and revision != self._surface_revision:
                    self._on_surface_revision_changed()
                self._surface_revision = revision
            reported = (
                reply[3].strip().lower() if len(reply) == 4 and isinstance(reply[3], str) else ""
            )
            self._surface_instance_id = reported or None
            try:
                protocol_parts = (self._surface_protocol or "").split(".")
                parts = (
                    tuple(int(part) for part in protocol_parts)
                    if all(part.isascii() and part.isdigit() for part in protocol_parts)
                    else ()
                )
            except ValueError:
                parts = ()
            if (
                len(reply) != 4
                or any(not isinstance(value, str) or not value for value in reply)
                or len(parts) != 3
                or parts < (2, 32, 0)
                or not reported
            ):
                self._instance_verified = False
                self._record_error(
                    "DAWN Control Surface protocol 2.32 with correlated replies is required; "
                    "refresh the Remote Script and restart Ableton Live"
                )
                return False
            if self.expected_instance_id is not None and reported != self.expected_instance_id:
                self._instance_verified = False
                self._record_error(
                    "Authenticated DAWN OSC instance mismatch: expected "
                    f"{self.expected_instance_id}, received {reported}"
                )
                return False
            self._instance_verified = True
            self._surface_identity_checked_at = time.monotonic()
            return True
        # The legacy-surface diagnostic is read-only and remains fail-closed:
        # even when the secure request timed out, a positive probe only changes
        # the upgrade guidance and never authorizes an OSC mutation.
        legacy = self._probe_legacy_surface_sync()
        if legacy:
            message = (
                "Installed DAWN Control Surface is legacy and unauthenticated; "
                "reinstall the DAWN Remote Script and restart Ableton Live"
            )
        else:
            message = (
                "Correlated DAWN Control Surface protocol 2.32 is unavailable "
                f"(authenticated OSC protocol v{OSC_SECURITY_PROTOCOL}); "
                "install or update the DAWN Remote Script, select it in Ableton Live, and "
                "restart Live"
            )
        self._record_error(message)
        return False

    def _discard_pending_tracker(self, address: str, tracker: _OSCReplyTracker) -> None:
        with self._pending_lock:
            trackers = self._pending.get(address)
            if trackers:
                with suppress(ValueError):
                    trackers.remove(tracker)
                if not trackers:
                    self._pending.pop(address, None)

    def _request_sync(
        self,
        address: str,
        *args: Any,
        timeout_seconds: float | None = None,
        _skip_security_handshake: bool = False,
    ) -> tuple[Any, ...] | None:
        if not self._ensure_receiver_started():
            return None

        if not _skip_security_handshake and not self._establish_secure_transport_sync():
            return None

        timeout = self.timeout_seconds if timeout_seconds is None else timeout_seconds
        tracker = _OSCReplyTracker(
            address=address,
            event=threading.Event(),
            reply=[],
        )

        with self._pending_lock:
            if address not in self._pending:
                self._pending[address] = deque()
            self._pending[address].append(tracker)

        try:
            with self._send_thread_lock:
                self._before_request_send(address)
                sent = self._send_with_retry_locked(
                    address,
                    "dawn_request:" + tracker.request_id,
                    *args,
                    failure_prefix=(f"Failed to send OSC request to {self.host}:{self.send_port}"),
                    unexpected_prefix=(
                        f"Unexpected OSC request failure to {self.host}:{self.send_port}"
                    ),
                )
            if not sent:
                return None

            if not tracker.event.wait(timeout):
                self._record_error(f"{REPLY_TIMEOUT_PREFIX}{address}")
                return None

            if tracker.error:
                self._record_error(f"OSC request handling error for {address}", tracker.error)
                return None

            self._last_error = None
            return tuple(tracker.reply)
        finally:
            # Cleanup stale trackers so timed-out/failed requests cannot poison future replies.
            self._discard_pending_tracker(address, tracker)

    def _record_error(self, message: str, exc: Exception | None = None) -> None:
        entry = message + (f" ({exc})" if exc else "")
        self._error_history.append(entry)
        if len(self._error_history) > self._MAX_ERROR_HISTORY:
            self._error_history.pop(0)
        self._last_error = entry
        # A few protocol-only test doubles intentionally bypass ``__init__``
        # to avoid opening a UDP receiver.  Treat the absent optional
        # logging context as the normal (non-quiet) path rather than making
        # the settlement state machine depend on constructor side effects.
        quiet_logging = getattr(self, "_quiet_failure_logging", None)
        if quiet_logging is not None and quiet_logging.get():
            if exc is None:
                self._logger.debug(message)
            else:
                self._logger.bind(error=str(exc)).debug(message)
            return
        if exc is None:
            self._logger.warning(message)
            return
        self._logger.bind(error=str(exc)).warning(message)

    def _record_bind_error(self, exc: OSError) -> None:
        if exc.errno == errno.EADDRINUSE:
            self._record_error(
                f"OSC receive port {self.receive_port} is already in use",
                exc,
            )
            return
        self._record_error(f"Unable to bind OSC receive port {self.receive_port}", exc)

    def _build_udp_client(self) -> SimpleUDPClient:
        return _SecureSimpleUDPClient(self.host, self.send_port, self._security_session)

    def _recreate_send_transport_locked(self) -> None:
        previous = self._client
        with suppress(Exception):
            previous._sock.close()
        self._client = self._build_udp_client()
        self._logger.info("osc.send_transport.recreated")

    def _send_with_retry_locked(
        self,
        address: str,
        *args: Any,
        failure_prefix: str,
        unexpected_prefix: str,
    ) -> bool:
        try:
            self._client.send_message(address, list(args))
            self._last_error = None
            return True
        except OSError as exc:
            first_error: Exception = exc
        except Exception as exc:
            first_error = exc

        retry_log = self._logger.bind(address=address, error=str(first_error))
        quiet_logging = getattr(self, "_quiet_failure_logging", None)
        if quiet_logging is not None and quiet_logging.get():
            retry_log.debug("osc.send_transport.retry_after_reinit")
        else:
            retry_log.warning("osc.send_transport.retry_after_reinit")

        try:
            self._recreate_send_transport_locked()
            self._client.send_message(address, list(args))
        except OSError as exc:
            self._record_error(f"{failure_prefix} after transport reinit", exc)
            return False
        except Exception as exc:
            self._record_error(f"{unexpected_prefix} after transport reinit", exc)
            return False

        self._last_error = None
        self._logger.bind(address=address).info("osc.send_transport.retry_succeeded")
        return True

    def close(self) -> None:
        self._logger.info("osc.client.shutdown")
        self._on_close()
        self._receiver_started = False
        self._secure_ready = False
        self._instance_verified = self.expected_instance_id is None
        self._surface_instance_id = None
        server = self._server
        self._server = None
        if server is not None:
            # shutdown() stops the serve_forever loop and waits for it to exit,
            # so server_close() releases the receive port deterministically and
            # the thread join below returns immediately. Without it the loop
            # lingers, the port can stay bound briefly, and shutdown is slow.
            with suppress(Exception):
                server.shutdown()
            with suppress(Exception):
                server.server_close()
        if self._receiver_thread is not None:
            if self._receiver_thread.is_alive():
                self._receiver_thread.join(timeout=3.0)
                if self._receiver_thread.is_alive():
                    self._logger.warning("osc.receiver_thread.join_timeout")
            self._receiver_thread = None
        with self._pending_lock:
            self._pending.clear()
        with suppress(Exception):
            self._client.close()
        with suppress(Exception):
            self._client._sock.close()
