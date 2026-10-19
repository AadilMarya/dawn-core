"""The generated catalog: coverage, lookups, risk review gate, and freshness."""

from __future__ import annotations

import pytest

from dawn_core import _gen_catalog as gen
from dawn_core import catalog
from dawn_core._catalog_types import RISK_CLASSES

CORE_GROUPS = {
    "api",
    "application",
    "clip",
    "clip_slot",
    "clips",
    "dawn",
    "device",
    "live",
    "midimap",
    "scene",
    "song",
    "track",
    "view",
}
# Review gate. Every destructive endpoint is listed here on purpose. If the Remote
# Script adds or reclassifies one, this snapshot must change in the same commit.
EXPECTED_DESTRUCTIVE = frozenset(
    {
        "/live/clip/remove/notes",
        "/live/clip/remove_notes_by_id",
        "/live/clip_slot/delete_clip",
        "/live/song/cue_point/add_or_delete",
        "/live/song/delete_return_track",
        "/live/song/delete_scene",
        "/live/song/delete_track",
        "/live/song/set_or_delete_cue",
        "/live/track/delete_clip",
        "/live/track/delete_device",
    }
)

# Review gate for the *read* class. A handler registered under a read verb is classed
# ``read`` and skips the consent gate, so it must genuinely not mutate. If the Remote
# Script gains a read-verb endpoint that changes state, list it here on purpose — the
# safety layer cannot see inside the handler. Empty by design.
EXPECTED_READ_VERB_MUTATORS: frozenset[str] = frozenset()


def test_catalog_is_large_and_addresses_are_unique_and_sorted() -> None:
    addresses = [entry.address for entry in catalog.entries()]
    assert len(addresses) >= 200
    assert len(addresses) == len(set(addresses))
    assert addresses == sorted(addresses)


def test_every_group_is_covered_and_by_group_matches_groups() -> None:
    grouped = catalog.by_group()
    assert tuple(sorted(grouped)) == catalog.groups()
    assert all(grouped[name] for name in grouped), "a group has no entries"
    assert sum(len(items) for items in grouped.values()) == len(catalog.entries())
    assert CORE_GROUPS <= set(catalog.groups())


@pytest.mark.parametrize(
    ("address", "group", "verb", "prop", "risk"),
    [
        ("/live/test", "live", "test", None, "read"),
        ("/live/song/get/tempo", "song", "get", "tempo", "read"),
        ("/live/song/set/tempo", "song", "set", "tempo", "write"),
        ("/live/song/start_playing", "song", "call", None, "write"),
        ("/live/track/get/name", "track", "get", "name", "read"),
        ("/live/track/set/name", "track", "set", "name", "write"),
        ("/live/track/get/mute", "track", "get", "mute", "read"),
        ("/live/track/get/volume", "track", "get", "volume", "read"),
        ("/live/track/start_listen/mute", "track", "start_listen", "mute", "read"),
        ("/live/track/delete_clip", "track", "call", None, "destructive"),
        ("/dawn/security/status", "dawn", "other", None, "read"),
        ("/dawn/version", "dawn", "other", None, "read"),
    ],
)
def test_known_addresses_have_expected_metadata(
    address: str, group: str, verb: str, prop: str | None, risk: str
) -> None:
    entry = catalog.find(address)
    assert entry is not None, address
    assert (entry.group, entry.verb, entry.prop, entry.risk) == (group, verb, prop, risk)
    assert entry.source.count(":") == 1


def test_track_index_argument_is_typed_on_track_getters_and_setters() -> None:
    name_get = catalog.find("/live/track/get/name")
    name_set = catalog.find("/live/track/set/name")
    assert name_get is not None and name_set is not None
    assert [(a.name, a.kind) for a in name_get.args] == [("track_index", "int")]
    assert [(a.name, a.kind) for a in name_set.args] == [
        ("track_index", "int"),
        ("value", "any"),
    ]


@pytest.mark.parametrize(
    "address", ["/live/track/get/*", "/live/nope", "", "/live/song/get/tempo/", "/LIVE/test"]
)
def test_find_returns_none_for_addresses_not_in_catalog(address: str) -> None:
    assert catalog.find(address) is None


def test_every_risk_value_is_a_known_class() -> None:
    assert {entry.risk for entry in catalog.entries()} <= set(RISK_CLASSES)


def test_destructive_endpoints_match_the_reviewed_snapshot() -> None:
    destructive = {entry.address for entry in catalog.entries() if entry.risk == "destructive"}
    assert destructive == EXPECTED_DESTRUCTIVE


def test_no_read_verb_is_classed_write_or_destructive() -> None:
    for entry in catalog.entries():
        if entry.verb in {"get", "start_listen", "stop_listen", "test"}:
            assert entry.risk == "read", entry.address


def test_read_verb_endpoints_are_reviewed_read_only() -> None:
    # The counterpart of the destructive gate: read-verb handlers skip consent, so any
    # change to the read set must be reviewed here in the same commit.
    mutating = {
        entry.address
        for entry in catalog.entries()
        if entry.verb in {"get", "start_listen", "stop_listen"} and entry.risk != "read"
    }
    assert mutating == EXPECTED_READ_VERB_MUTATORS


def test_committed_catalog_is_fresh_and_fully_resolved() -> None:
    build = gen.build_catalog()
    assert build.failing == (), [u.site for u in build.failing]
    assert build.call_sites > 0
    assert build.concrete_addresses >= len(build.entries)
    assert gen.main(["--check"]) == 0
