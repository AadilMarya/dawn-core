"""The catalog generator on synthetic sources: expansion rules, failure modes, risk rules."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from dawn_core import _gen_catalog as gen


def _build(tmp_path: Path, source: str) -> gen.CatalogBuild:
    root = tmp_path / "remote"
    root.mkdir(parents=True, exist_ok=True)
    (root / "mod.py").write_text(textwrap.dedent(source), encoding="utf-8")
    return gen.build_catalog(root)


def _addresses(build: gen.CatalogBuild) -> set[str]:
    return {entry.address for entry in build.entries}


def test_percent_loop_over_local_list_expands_each_value(tmp_path: Path) -> None:
    build = _build(
        tmp_path,
        """
        class H:
            def init_api(self):
                methods = ["start", "stop"]
                for method in methods:
                    self.osc_server.add_handler("/live/clip/%s" % method, cb)
                self.osc_server.add_handler("/live/test", cb)
        """,
    )
    assert build.failing == ()
    assert _addresses(build) == {"/live/clip/start", "/live/clip/stop", "/live/test"}
    assert build.call_sites == 2
    assert build.concrete_addresses == 3


def test_nested_loops_over_concatenated_lists_multiply(tmp_path: Path) -> None:
    build = _build(
        tmp_path,
        """
        names_r = ["a", "b"]
        def init_api(self):
            names_rw = ["c"]
            for kind in ("get", "set"):
                for prop in names_r + names_rw + ["d"]:
                    self.osc_server.add_handler("/live/song/%s/%s" % (kind, prop), cb)
        """,
    )
    assert build.failing == ()
    assert len(build.entries) == 2 * 4
    assert "/live/song/set/d" in _addresses(build)


def test_range_fstring_and_format_are_expanded(tmp_path: Path) -> None:
    build = _build(
        tmp_path,
        """
        def init(self):
            for i in range(2):
                self.osc_server.add_handler(f"/live/scene/{i}/x", cb)
            self.osc_server.add_handler("/live/a/{}".format("b"), cb)
        """,
    )
    assert build.failing == ()
    assert _addresses(build) == {"/live/scene/0/x", "/live/scene/1/x", "/live/a/b"}


def test_loop_over_unknown_iterable_fails_only_the_loop_dependent_site(tmp_path: Path) -> None:
    build = _build(
        tmp_path,
        """
        def init(self):
            for name in load_names():
                self.osc_server.add_handler("/live/track/%s" % name, cb)
                self.osc_server.add_handler("/live/test", cb)
        """,
    )
    assert _addresses(build) == {"/live/test"}
    assert len(build.failing) == 1
    assert build.failing[0].site.expr == "'/live/track/%s' % name"
    assert "name" in build.failing[0].reason


def test_unresolvable_address_expression_is_reported(tmp_path: Path) -> None:
    build = _build(
        tmp_path,
        """
        def init(self):
            self.osc_server.add_handler(compute_address(), cb)
        """,
    )
    assert _addresses(build) == set()
    assert [u.reason for u in build.failing] == ["depends on unresolved name(s): compute_address"]


def test_statically_empty_loop_registers_nothing_and_is_not_unresolved(tmp_path: Path) -> None:
    build = _build(
        tmp_path,
        """
        def init(self):
            methods = []
            for method in methods:
                self.osc_server.add_handler("/live/track/%s" % method, cb)
        """,
    )
    assert build.failing == ()
    assert build.entries == ()
    assert build.call_sites == 1


def test_last_registration_for_an_address_wins(tmp_path: Path) -> None:
    build = _build(
        tmp_path,
        """
        def init(self):
            self.osc_server.add_handler("/live/test", first)
            self.osc_server.add_handler("/live/test", second)
        """,
    )
    (entry,) = build.entries
    assert entry.source == "mod.py:4"
    assert build.duplicate_addresses == ("/live/test",)


def test_callback_variable_exposes_the_wrapper_for_signature(tmp_path: Path) -> None:
    build = _build(
        tmp_path,
        """
        def init(self):
            callback = create_track_callback(self._set_property, "mute")
            self.osc_server.add_handler("/live/track/set/mute", callback)
        """,
    )
    (entry,) = build.entries
    assert [(a.name, a.kind) for a in entry.args] == [("track_index", "int"), ("value", "any")]
    assert entry.verb == "set" and entry.prop == "mute"


def test_conditional_callback_with_one_wrapper_is_recognised(tmp_path: Path) -> None:
    build = _build(
        tmp_path,
        """
        def init(self):
            callback = (special if flag else create_scene_callback(self._get_property, "x"))
            self.osc_server.add_handler("/live/scene/get/x", callback)
        """,
    )
    (entry,) = build.entries
    assert [(a.name, a.kind) for a in entry.args] == [("scene_index", "int")]


def test_partial_helper_registration_takes_no_extra_args_for_getters(tmp_path: Path) -> None:
    build = _build(
        tmp_path,
        """
        def init(self):
            self.osc_server.add_handler("/live/song/get/tempo", partial(self._get_property, self.song, "tempo"))
            self.osc_server.add_handler("/live/song/set/tempo", partial(self._set_property, self.song, "tempo"))
        """,
    )
    by_address = {e.address: e for e in build.entries}
    assert by_address["/live/song/get/tempo"].args == ()
    assert [(a.name, a.kind) for a in by_address["/live/song/set/tempo"].args] == [("value", "any")]


def test_allowlisted_unresolved_site_does_not_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(gen.ALLOWED_UNRESOLVED, "mod.py:3", "fixture: deliberately opaque")
    build = _build(
        tmp_path,
        """
        def init(self):
            self.osc_server.add_handler(compute(), cb)
        """,
    )
    assert len(build.unresolved) == 1
    assert build.unresolved[0].allowed is True
    assert build.failing == ()


@pytest.mark.parametrize(
    ("address", "verb", "risk"),
    [
        ("/live/track/delete_clip", "call", "destructive"),
        ("/live/clip/remove_notes_by_id", "call", "destructive"),
        ("/live/song/stop_all_clips", "call", "write"),
        ("/live/song/set_or_delete_cue", "call", "destructive"),
        ("/live/arrangement_clip/set/notes", "set", "destructive"),
        ("/live/clip/compare_replace/notes_rich", "call", "destructive"),
        ("/live/arrangement_clip/crop", "call", "destructive"),
        ("/live/track/get/deleted_flag", "get", "read"),
        ("/live/track/undelete_me", "call", "write"),
        ("/live/clip/add/notes", "call", "write"),
        ("/live/track/set/name_guarded", "set", "write"),
        ("/live/song/start_playing", "call", "write"),
        ("/live/test", "test", "read"),
        ("/dawn/security/status", "other", "read"),
        ("/dawn/execute_verified", "call", "write"),
        ("/dawn/verified/result", "other", "write"),
        ("/dawn/startup", "other", "write"),
    ],
)
def test_risk_rules(address: str, verb: str, risk: str) -> None:
    assert gen.classify_risk(address, verb) == risk


def test_classify_address_splits_group_verb_and_property() -> None:
    assert gen.classify_address("/live/track/get/devices/name") == (
        "track",
        "get",
        "devices/name",
    )
    assert gen.classify_address("/live/song/create_midi_track") == ("song", "call", None)
    assert gen.classify_address("/dawn/get/session_snapshot") == (
        "dawn",
        "get",
        "session_snapshot",
    )


def test_main_check_fails_when_stale_and_passes_when_fresh(tmp_path: Path) -> None:
    root = tmp_path / "remote"
    root.mkdir()
    (root / "mod.py").write_text(
        'def init(self):\n    self.osc_server.add_handler("/live/test", cb)\n',
        encoding="utf-8",
    )
    output = tmp_path / "_catalog_data.py"
    assert gen.main(["--root", str(root), "--check"], output_path=output) == 1
    build = gen.build_catalog(root)
    output.write_text(gen.render(build.entries), encoding="utf-8")
    assert gen.main(["--root", str(root), "--check"], output_path=output) == 0


def test_main_check_fails_on_unresolved_even_when_module_is_fresh(tmp_path: Path) -> None:
    root = tmp_path / "remote"
    root.mkdir()
    (root / "mod.py").write_text(
        "def init(self):\n    self.osc_server.add_handler(compute(), cb)\n",
        encoding="utf-8",
    )
    output = tmp_path / "_catalog_data.py"
    output.write_text(gen.render(()), encoding="utf-8")
    assert gen.main(["--root", str(root), "--check"], output_path=output) == 1


def test_render_is_deterministic_and_carries_the_generated_header(tmp_path: Path) -> None:
    build = _build(
        tmp_path,
        """
        def init(self):
            self.osc_server.add_handler("/live/test", cb)
        """,
    )
    text = gen.render(build.entries)
    assert text == gen.render(build.entries)
    assert text.startswith("# generated - do not edit.")
