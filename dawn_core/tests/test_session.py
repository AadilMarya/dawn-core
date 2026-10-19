"""OscSession against MiniLive: refusals before I/O, consent gating, errors and timeouts."""

from __future__ import annotations

import gc
import socket
from collections.abc import Callable

import pytest

from dawn_core import Consent, ConsentDenied, OscCallError, OscSession, UnknownAddressError
from dawn_core.session import RECEIVE_PORT_ENV, SEND_PORT_ENV
from dawn_core.testing import MiniLive
from dawn_core.testing.mini_live import PROTOCOL
from dawn_osc.security import get_process_osc_session


def _sent(live: MiniLive, address: str) -> list[object]:
    return [r for r in live.requests if r.address == address]


def _open_sockets() -> list[object]:
    """Every open socket in the process, for the leak checks."""
    gc.collect()
    return [obj for obj in gc.get_objects() if isinstance(obj, socket.socket) and not obj._closed]


@pytest.mark.asyncio
async def test_ping_and_call_round_trip_through_the_authenticated_envelope(
    live: MiniLive, ports: tuple[int, int], isolated_runtime
) -> None:
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        assert await session.ping() is True
        assert await session.call("/live/song/get/tempo") == (120.0,)
    # The handshake ran first and was answered with the process session's identity.
    assert live.requests[0].address == "/dawn/security/status"
    assert (isolated_runtime / "osc_session.json").exists()


@pytest.mark.asyncio
async def test_handshake_reports_protocol_and_session_identity(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        protocol, session_id, revision, instance = await session.call("/dawn/security/status")
    assert protocol == PROTOCOL
    assert session_id == get_process_osc_session().session_id_hex
    assert revision and instance == live.instance_id


@pytest.mark.asyncio
async def test_unknown_address_is_refused_before_any_datagram(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        with pytest.raises(UnknownAddressError):
            await session.call("/live/song/not_a_real_endpoint")
        with pytest.raises(UnknownAddressError):
            await session.send("/live/track/get/*")
    assert live.requests == []


@pytest.mark.asyncio
async def test_non_primitive_argument_is_refused_before_any_datagram(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        with pytest.raises(TypeError):
            await session.call("/live/track/get/name", object())
    assert live.requests == []


@pytest.mark.asyncio
async def test_missing_reply_raises_osc_call_error_with_the_transport_error(
    ports: tuple[int, int], live_factory: Callable[..., MiniLive]
) -> None:
    live_factory(ports[0], ports[1], silent_addresses=("/live/song/get/tempo",))
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        with pytest.raises(OscCallError) as info:
            await session.call("/live/song/get/tempo", timeout=0.2)
    assert info.value.address == "/live/song/get/tempo"
    assert info.value.detail is not None and "Timed out" in info.value.detail


@pytest.mark.asyncio
async def test_error_reply_from_live_raises_osc_call_error(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    # The catalog serves this address, but the fake does not implement it.
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        with pytest.raises(OscCallError) as info:
            await session.call("/live/clip/get/name", 0, 0, timeout=1.0)
    assert "unknown OSC address" in (info.value.detail or "")


@pytest.mark.asyncio
async def test_send_applies_a_setter_that_a_read_then_confirms(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        await session.send("/live/song/set/tempo", 133.0)
        assert await session.call("/live/song/get/tempo") == (133.0,)
    assert live.tempo == 133.0
    assert _sent(live, "/live/song/set/tempo")


@pytest.mark.asyncio
async def test_send_goes_through_the_transport_public_unacknowledged_send(
    live: MiniLive, ports: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        # The transport is created on first use; nothing is bound before this point.
        assert session._transport is None
        transport = session._require_transport()
        original = transport.send_unacknowledged
        routed: list[str] = []

        async def spy(address: str, *args: object) -> bool:
            routed.append(address)
            return await original(address, *args)

        monkeypatch.setattr(transport, "send_unacknowledged", spy)
        await session.send("/live/song/set/tempo", 128.0)
        assert await session.call("/live/song/get/tempo") == (128.0,)
    assert routed == ["/live/song/set/tempo"]
    assert live.tempo == 128.0


@pytest.mark.asyncio
async def test_destructive_call_is_not_sent_when_consent_is_denied(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        with pytest.raises(ConsentDenied):
            await session.send("/live/song/delete_track", 0)
        with pytest.raises(ConsentDenied):
            await session.call("/live/track/delete_clip", 0, 0)
    assert live.requests == []


@pytest.mark.asyncio
async def test_read_only_session_refuses_writes_but_still_reads(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    async with OscSession(
        send_port=ports[0], receive_port=ports[1], consent=Consent(read_only=True)
    ) as session:
        with pytest.raises(ConsentDenied):
            await session.send("/live/song/set/tempo", 99.0)
        assert await session.call("/live/song/get/tempo") == (120.0,)
    assert live.tempo == 120.0
    assert _sent(live, "/live/song/set/tempo") == []


@pytest.mark.asyncio
async def test_destructive_call_is_sent_once_confirmed(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    seen: list[str] = []

    def confirm(entry, args) -> bool:
        seen.append(entry.address)
        return True

    async with OscSession(
        send_port=ports[0], receive_port=ports[1], consent=Consent(confirm=confirm)
    ) as session:
        await session.send("/live/song/delete_track", 0)
    assert seen == ["/live/song/delete_track"]
    assert _sent(live, "/live/song/delete_track")


@pytest.mark.asyncio
async def test_yes_mode_auto_confirms_destructive_calls(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    async with OscSession(
        send_port=ports[0], receive_port=ports[1], consent=Consent(yes=True)
    ) as session:
        await session.send("/live/song/delete_track", 0)
    assert _sent(live, "/live/song/delete_track")


@pytest.mark.asyncio
async def test_truthy_but_not_true_confirmation_does_not_send(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    async with OscSession(
        send_port=ports[0],
        receive_port=ports[1],
        consent=Consent(confirm=lambda entry, args: 1),  # type: ignore[arg-type,return-value]
    ) as session:
        with pytest.raises(ConsentDenied):
            await session.send("/live/song/delete_track", 0)
    assert _sent(live, "/live/song/delete_track") == []


@pytest.mark.asyncio
async def test_ping_reports_false_when_nothing_is_listening(
    ports: tuple[int, int], free_port: Callable[[], int]
) -> None:
    dead_send = free_port()
    async with OscSession(send_port=dead_send, receive_port=ports[1], timeout_seconds=0.2) as s:
        assert await s.ping(timeout=0.2) is False


@pytest.mark.asyncio
async def test_send_to_nothing_listening_raises_osc_call_error(
    ports: tuple[int, int], free_port: Callable[[], int]
) -> None:
    dead_send = free_port()
    async with OscSession(send_port=dead_send, receive_port=ports[1], timeout_seconds=0.2) as s:
        with pytest.raises(OscCallError):
            await s.send("/live/song/set/tempo", 120.0)


@pytest.mark.asyncio
async def test_unacknowledged_transport_send_returns_false_with_last_error(
    live_factory: Callable[..., MiniLive],
    ports: tuple[int, int],
    free_port: Callable[[], int],
) -> None:
    live_factory(ports[0], ports[1])
    dead_send = free_port()
    async with OscSession(send_port=dead_send, receive_port=ports[1], timeout_seconds=0.2) as s:
        transport = s._require_transport()
        sent = await transport.send_unacknowledged("/live/track/get/volume_db", 0)
        assert sent is False
        assert s.last_error


def test_ports_default_to_dawn_values_and_honour_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SEND_PORT_ENV, raising=False)
    monkeypatch.delenv(RECEIVE_PORT_ENV, raising=False)
    session = OscSession()
    assert (session.send_port, session.receive_port) == (11000, 11001)
    monkeypatch.setenv(SEND_PORT_ENV, "12345")
    monkeypatch.setenv(RECEIVE_PORT_ENV, "12346")
    session = OscSession()
    assert (session.send_port, session.receive_port) == (12345, 12346)
    assert OscSession(send_port=23000).send_port == 23000


def test_out_of_range_port_is_rejected() -> None:
    with pytest.raises(ValueError):
        OscSession(send_port=70000)


@pytest.mark.asyncio
async def test_injected_transport_is_shared_and_not_closed_by_the_session(
    live: MiniLive, ports: tuple[int, int], isolated_runtime
) -> None:
    from dawn_osc import OscTransport

    shared = OscTransport(send_port=ports[0], receive_port=ports[1])
    try:
        async with OscSession(transport=shared) as session:
            assert (session.send_port, session.receive_port) == ports
            assert await session.call("/live/song/get/tempo") == (120.0,)
        # The session did not close the owner's transport: it still answers.
        assert await shared.ping() is True
        async with OscSession(transport=shared, consent=Consent(read_only=True)) as again:
            assert await again.call("/live/song/get/tempo") == (120.0,)
            with pytest.raises(ConsentDenied):
                await again.send("/live/song/set/tempo", 90.0)
    finally:
        await __import__("asyncio").to_thread(shared.close)


def test_injected_transport_is_exclusive_with_ports_timeout_and_security() -> None:
    from dawn_osc import OscTransport

    for kwargs in (
        {"send_port": 23001},
        {"receive_port": 23002},
        {"timeout_seconds": 1.0},
        {"security_session": get_process_osc_session()},
    ):
        shared = OscTransport(send_port=23001, receive_port=23002)
        try:
            with pytest.raises(ValueError, match="transport cannot be combined"):
                OscSession(transport=shared, **kwargs)  # type: ignore[arg-type]
        finally:
            shared.close()


@pytest.mark.asyncio
async def test_constructing_a_session_binds_no_socket_and_close_is_terminal(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    before = {sock.fileno() for sock in _open_sockets()}
    session = OscSession(send_port=ports[0], receive_port=ports[1])
    assert session._transport is None
    assert {sock.fileno() for sock in _open_sockets()} == before
    assert await session.ping() is True
    await session.close()
    for operation in (
        session.call("/live/song/get/tempo", timeout=0.2),
        session.send("/live/song/set/tempo", 99.0),
        session.ping(),
    ):
        with pytest.raises(RuntimeError, match="session is closed"):
            await operation
    await session.close()  # idempotent
