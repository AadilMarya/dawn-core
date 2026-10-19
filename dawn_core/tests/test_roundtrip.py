"""Every address MiniLive supports round-trips through OscSession and matches the catalog."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from dawn_core import OscSession, catalog
from dawn_core.testing import MiniLive
from dawn_core.testing.mini_live import PROTOCOL
from dawn_osc.security import get_process_osc_session

Scenario = Callable[[OscSession, MiniLive], Awaitable[None]]


async def _get_then_check(session: OscSession, address: str, *args: object, want: tuple) -> None:
    reply = await session.call(address, *args)
    assert len(reply) == len(want)
    for got, expected in zip(reply, want, strict=True):
        if isinstance(expected, float):
            assert got == pytest.approx(expected, rel=1e-6)
        else:
            assert got == expected


async def _test_ok(session: OscSession, live: MiniLive) -> None:
    assert await session.call("/live/test") == ("ok",)


async def _security_status(session: OscSession, live: MiniLive) -> None:
    protocol, session_id, revision, instance = await session.call("/dawn/security/status")
    assert protocol == PROTOCOL
    assert session_id == get_process_osc_session().session_id_hex
    assert revision and instance == live.instance_id


async def _tempo_get(session: OscSession, live: MiniLive) -> None:
    await _get_then_check(session, "/live/song/get/tempo", want=(120.0,))


async def _tempo_set(session: OscSession, live: MiniLive) -> None:
    await session.send("/live/song/set/tempo", 131.0)
    await _get_then_check(session, "/live/song/get/tempo", want=(131.0,))
    assert live.tempo == 131.0


async def _is_playing_get(session: OscSession, live: MiniLive) -> None:
    await _get_then_check(session, "/live/song/get/is_playing", want=(False,))


async def _start_playing(session: OscSession, live: MiniLive) -> None:
    await session.send("/live/song/start_playing")
    await _get_then_check(session, "/live/song/get/is_playing", want=(True,))


async def _stop_playing(session: OscSession, live: MiniLive) -> None:
    await session.send("/live/song/start_playing")
    await session.send("/live/song/stop_playing")
    await _get_then_check(session, "/live/song/get/is_playing", want=(False,))


async def _num_tracks(session: OscSession, live: MiniLive) -> None:
    await _get_then_check(session, "/live/song/get/num_tracks", want=(3,))


async def _track_name_get(session: OscSession, live: MiniLive) -> None:
    await _get_then_check(session, "/live/track/get/name", 1, want=(1, "Bass"))


async def _track_name_set(session: OscSession, live: MiniLive) -> None:
    await session.send("/live/track/set/name", 1, "Sub")
    await _get_then_check(session, "/live/track/get/name", 1, want=(1, "Sub"))


async def _track_mute_get(session: OscSession, live: MiniLive) -> None:
    await _get_then_check(session, "/live/track/get/mute", 0, want=(0, False))


async def _track_mute_set(session: OscSession, live: MiniLive) -> None:
    await session.send("/live/track/set/mute", 0, True)
    await _get_then_check(session, "/live/track/get/mute", 0, want=(0, True))


async def _track_volume_get(session: OscSession, live: MiniLive) -> None:
    await _get_then_check(session, "/live/track/get/volume", 2, want=(2, 0.6))


async def _track_volume_set(session: OscSession, live: MiniLive) -> None:
    await session.send("/live/track/set/volume", 2, 0.25)
    await _get_then_check(session, "/live/track/get/volume", 2, want=(2, 0.25))


SCENARIOS: dict[str, Scenario] = {
    "/live/test": _test_ok,
    "/dawn/security/status": _security_status,
    "/live/song/get/tempo": _tempo_get,
    "/live/song/set/tempo": _tempo_set,
    "/live/song/get/is_playing": _is_playing_get,
    "/live/song/start_playing": _start_playing,
    "/live/song/stop_playing": _stop_playing,
    "/live/song/get/num_tracks": _num_tracks,
    "/live/track/get/name": _track_name_get,
    "/live/track/set/name": _track_name_set,
    "/live/track/get/mute": _track_mute_get,
    "/live/track/set/mute": _track_mute_set,
    "/live/track/get/volume": _track_volume_get,
    "/live/track/set/volume": _track_volume_set,
}


def test_every_supported_address_is_in_the_catalog_and_has_a_scenario() -> None:
    supported = MiniLive.SUPPORTED_ADDRESSES
    assert supported <= {entry.address for entry in catalog.entries()}
    assert supported == set(SCENARIOS)


@pytest.mark.parametrize("address", sorted(MiniLive.SUPPORTED_ADDRESSES))
@pytest.mark.asyncio
async def test_supported_address_round_trips(
    address: str, live: MiniLive, ports: tuple[int, int]
) -> None:
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        await SCENARIOS[address](session, live)
    assert any(r.address == address for r in live.requests)
