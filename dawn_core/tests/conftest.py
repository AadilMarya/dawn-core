"""Shared fixtures. Every test runs offline, with its own runtime dir and free ports."""

from __future__ import annotations

import socket
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from dawn_core.testing import MiniLive, MiniTrack
from dawn_osc.security import reset_process_osc_session_for_tests, start_osc_session


def free_udp_port() -> int:
    """An OS-allocated loopback UDP port that is free at the moment of the call."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the OSC session file at a per-test directory, never at ~/.dawn."""
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("DAWN_RUNTIME_DIR", str(runtime))
    reset_process_osc_session_for_tests()
    yield runtime
    reset_process_osc_session_for_tests()


@pytest.fixture
def ports() -> tuple[int, int]:
    """``(send_port, receive_port)`` as seen by the client: Live listens on the first."""
    first = free_udp_port()
    second = free_udp_port()
    while second == first:
        second = free_udp_port()
    return first, second


@pytest.fixture
def free_port() -> Callable[[], int]:
    return free_udp_port


@pytest.fixture
def live_factory(
    isolated_runtime: Path,
) -> Iterator[Callable[..., MiniLive]]:
    """Start MiniLive servers on the given ports; all are stopped at teardown."""
    started: list[MiniLive] = []

    def make(
        listen_port: int,
        reply_port: int,
        *,
        tracks: tuple[MiniTrack, ...] | None = None,
        silent_addresses: tuple[str, ...] = (),
    ) -> MiniLive:
        session = start_osc_session()
        kwargs = {} if tracks is None else {"tracks": tracks}
        server = MiniLive(
            session=session,
            listen_port=listen_port,
            reply_port=reply_port,
            silent_addresses=silent_addresses,
            **kwargs,
        )
        server.start()
        started.append(server)
        return server

    yield make
    for server in started:
        server.stop()


@pytest.fixture
def live(ports: tuple[int, int], live_factory: Callable[..., MiniLive]) -> MiniLive:
    return live_factory(ports[0], ports[1])
