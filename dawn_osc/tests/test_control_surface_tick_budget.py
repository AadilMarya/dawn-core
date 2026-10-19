"""Regression coverage for the Live control-surface tick work bound."""

from __future__ import annotations

import errno
import importlib
import logging
import sys
import types
from collections import deque

import dawn_osc


def _load_isolated_osc_modules() -> tuple[type, int, float, type]:
    """Load the vendored server without importing Ableton-only handlers.

    ``handlers.__init__`` imports every Live handler, which is correct in
    Ableton but unavailable in ordinary pytest.  The server itself has no Live
    dependency, so give its relative imports a small synthetic package tree.
    """
    root = dawn_osc.script_dir()
    package = "_dawn_tick_budget_test"
    top = types.ModuleType(package)
    top.__path__ = [str(root)]
    osc = types.ModuleType(package + ".handlers")
    osc.__path__ = [str(root / "handlers")]
    sys.modules[package] = top
    sys.modules[package + ".handlers"] = osc
    server_module = importlib.import_module(package + ".handlers.osc_server")
    builder_module = importlib.import_module(package + ".pythonosc.osc_message_builder")
    return (
        server_module.OSCServer,
        server_module.MAX_MESSAGES_PER_TICK,
        server_module.MAX_TICK_SECONDS,
        builder_module.OscMessageBuilder,
    )


OSCServer, MAX_MESSAGES_PER_TICK, MAX_TICK_SECONDS, OscMessageBuilder = _load_isolated_osc_modules()


class _PassThroughSecurity:
    def unwrap_request(self, payload: bytes) -> bytes:
        return payload

    def wrap_response_many(self, payload: bytes) -> list[bytes]:
        return [payload]


class _DatagramSocket:
    def __init__(self, datagrams: list[bytes]) -> None:
        self._datagrams = list(datagrams)

    def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
        if not self._datagrams:
            raise BlockingIOError(errno.EAGAIN, "would block")
        return self._datagrams.pop(0), ("127.0.0.1", 12000)


def _message() -> bytes:
    builder = OscMessageBuilder("/dawn/test")
    return builder.build().dgram


def _server(datagrams: list[bytes]) -> OSCServer:
    # Construct without binding a real socket: CI/sandbox environments may
    # prohibit even loopback binds, and this regression targets tick scheduling.
    server = object.__new__(OSCServer)
    server._local_addr = ("127.0.0.1", 0)
    server._remote_addr = ("127.0.0.1", 12001)
    server._response_port = 12001
    server._security = _PassThroughSecurity()
    server._callbacks = {}
    server._pending_messages = deque()
    server._socket = _DatagramSocket(datagrams)
    server.logger = logging.getLogger("dawn.tick-budget-test")
    server._last_tick_processed = 0
    server._last_tick_deferred = 0
    server._last_tick_oldest_deferred_seconds = 0.0
    server._overload_dropped_messages = 0
    # A deterministic clock lets this regression cover the message bound
    # without depending on local test-machine scheduling.
    server._clock = lambda: 0.0
    return server


def test_process_defers_burst_to_later_live_ticks() -> None:
    seen: list[tuple[object, ...]] = []
    server = _server([_message() for _ in range(MAX_MESSAGES_PER_TICK + 2)])
    server.add_handler("/dawn/test", lambda params: seen.append(params))

    server.process()

    assert len(seen) == MAX_MESSAGES_PER_TICK
    assert server._last_tick_processed == MAX_MESSAGES_PER_TICK
    assert server._last_tick_deferred == 0

    server.process()

    assert len(seen) == MAX_MESSAGES_PER_TICK + 2


def test_remaining_tick_seconds_is_published_for_handlers_that_loop() -> None:
    """`_process_pending` and the receive loop only re-check the deadline BETWEEN
    messages, so a handler that applies N mutations inside one message (the
    verified batch) is invisible to them and must consult the budget itself."""
    server = _server([_message()])
    now = [0.0]
    server._clock = lambda: now[0]
    seen: list[float] = []

    def _handler(_params):
        seen.append(server.remaining_tick_seconds())
        now[0] += 0.004

    server.add_handler("/dawn/test", _handler)

    # Outside a tick there is no deadline to report; callers must not be starved.
    assert server.remaining_tick_seconds() == MAX_TICK_SECONDS

    server.process()

    assert seen == [MAX_TICK_SECONDS], "handler sees the live budget, not a constant"
    # The deadline is released once the tick ends.
    assert server.remaining_tick_seconds() == MAX_TICK_SECONDS


def test_remaining_tick_seconds_shrinks_as_the_tick_is_consumed() -> None:
    server = _server([_message(), _message()])
    now = [0.0]
    server._clock = lambda: now[0]
    seen: list[float] = []

    def _handler(_params):
        seen.append(round(server.remaining_tick_seconds(), 6))
        now[0] += 0.005

    server.add_handler("/dawn/test", _handler)
    server.process()

    assert seen == [MAX_TICK_SECONDS, round(MAX_TICK_SECONDS - 0.005, 6)]
