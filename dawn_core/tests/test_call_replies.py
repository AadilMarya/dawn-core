"""Call endpoints that reply: handler analysis, the committed flags, and the call tools."""

from __future__ import annotations

import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dawn_core import Consent, OscSession, catalog
from dawn_core import _gen_catalog as gen
from dawn_core.testing import MiniLive
from dawn_core.tools import CatalogTools


def _replies(tmp_path: Path, source: str) -> dict[str, bool | None]:
    """The replies flag of every address that one Remote Script module registers."""
    root = tmp_path / "remote"
    root.mkdir(parents=True, exist_ok=True)
    (root / "mod.py").write_text(source, encoding="utf-8")
    build = gen.build_catalog(root)
    assert build.failing == ()
    return {entry.address: entry.replies for entry in build.entries}


def _handler_with_body(body: str) -> str:
    """A module whose ``init_api`` registers ``_get_a``, and ``_get_a`` runs ``body``."""
    indented = textwrap.indent(textwrap.dedent(body), " " * 8)
    return (
        "class H:\n"
        "    def init_api(self):\n"
        '        self.osc_server.add_handler("/live/x/get/a", self._get_a)\n'
        "\n"
        "    def _get_a(self, params):\n"
        f"{indented}\n"
    )


@pytest.mark.parametrize(
    ("body", "replies"),
    [
        ("return (1,)", True),
        ("return tuple()", True),
        ("return self._value()", True),
        ("if params:\n    return (1,)\nreturn None", True),
        ("return None", False),
        ("return", False),
        ("self.song.tempo = 120.0", False),
        ("def helper():\n    return (1,)\nhelper()", False),
        ("class Inner:\n    def m(self):\n        return (1,)\nreturn None", False),
    ],
)
def test_method_replies_only_when_a_return_gives_a_value(
    tmp_path: Path, body: str, replies: bool
) -> None:
    assert _replies(tmp_path, _handler_with_body(body)) == {"/live/x/get/a": replies}


def test_nested_def_in_init_api_that_returns_a_value_replies(tmp_path: Path) -> None:
    source = (
        "class H:\n"
        "    def init_api(self):\n"
        "        def handle(params):\n"
        "            return (1,)\n"
        '        self.osc_server.add_handler("/live/x/get/a", handle)\n'
    )
    assert _replies(tmp_path, source) == {"/live/x/get/a": True}


def test_nested_def_in_init_api_without_a_return_does_not_reply(tmp_path: Path) -> None:
    source = (
        "class H:\n"
        "    def init_api(self):\n"
        "        def handle(params):\n"
        "            self.logger.info('unfilter')\n"
        '        self.osc_server.add_handler("/live/x/get/a", handle)\n'
    )
    assert _replies(tmp_path, source) == {"/live/x/get/a": False}


def test_bare_name_for_a_module_level_def_is_resolved(tmp_path: Path) -> None:
    source = (
        "def get_a(params):\n"
        "    return (1,)\n"
        "\n"
        "def init_api(self):\n"
        '    self.osc_server.add_handler("/live/x/get/a", get_a)\n'
    )
    assert _replies(tmp_path, source) == {"/live/x/get/a": True}


@pytest.mark.parametrize(
    ("lambda_source", "replies"),
    [("lambda _p: (1,)", True), ("lambda _p: None", False)],
)
def test_lambda_body_is_the_returned_expression(
    tmp_path: Path, lambda_source: str, replies: bool
) -> None:
    source = (
        "class H:\n"
        "    def init_api(self):\n"
        f'        self.osc_server.add_handler("/live/x/get/a", {lambda_source})\n'
    )
    assert _replies(tmp_path, source) == {"/live/x/get/a": replies}


def test_method_inherited_from_a_base_class_in_the_same_file_is_resolved(tmp_path: Path) -> None:
    source = (
        "class Base:\n"
        "    def _get_a(self, params):\n"
        "        return (1,)\n"
        "\n"
        "class H(Base):\n"
        "    def init_api(self):\n"
        '        self.osc_server.add_handler("/live/x/get/a", self._get_a)\n'
    )
    assert _replies(tmp_path, source) == {"/live/x/get/a": True}


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "class H:\n"
            "    def init_api(self):\n"
            "        for handler in [self._get_a]:\n"
            '            self.osc_server.add_handler("/live/x/get/a", handler)\n'
            "    def _get_a(self, params):\n"
            "        return (1,)\n",
            id="loop-variable",
        ),
        pytest.param(
            "class H:\n"
            "    def init_api(self):\n"
            '        self.osc_server.add_handler("/live/x/get/a", partial(self._get_a, 1))\n'
            "    def _get_a(self, params):\n"
            "        return (1,)\n",
            id="partial",
        ),
        pytest.param(
            "from elsewhere import get_a\n"
            "\n"
            "def init_api(self):\n"
            '    self.osc_server.add_handler("/live/x/get/a", get_a)\n',
            id="imported-name",
        ),
        pytest.param(
            "from elsewhere import Base\n"
            "\n"
            "class H(Base):\n"
            "    def init_api(self):\n"
            '        self.osc_server.add_handler("/live/x/get/a", self._get_a)\n',
            id="base-class-from-another-file",
        ),
        pytest.param(
            "class H:\n"
            "    def __init__(self):\n"
            "        self._get_a = make_handler()\n"
            "    def init_api(self):\n"
            '        self.osc_server.add_handler("/live/x/get/a", self._get_a)\n'
            "    def _get_a(self, params):\n"
            "        return (1,)\n",
            id="instance-attribute-shadows-method",
        ),
        pytest.param(
            "class H:\n"
            "    def init_api(self):\n"
            '        self.osc_server.add_handler("/live/x/get/a", self._get_a)\n'
            "    @traced\n"
            "    def _get_a(self, params):\n"
            "        return (1,)\n",
            id="decorated-handler",
        ),
    ],
)
def test_callbacks_that_cannot_be_pinned_to_one_definition_are_unknown(
    tmp_path: Path, source: str
) -> None:
    assert _replies(tmp_path, source) == {"/live/x/get/a": None}


def test_summary_line_counts_true_false_and_unknown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "remote"
    root.mkdir()
    (root / "mod.py").write_text(
        "class H:\n"
        "    def init_api(self):\n"
        '        self.osc_server.add_handler("/live/x/get/a", self._a)\n'
        '        self.osc_server.add_handler("/live/x/set/b", self._b)\n'
        '        self.osc_server.add_handler("/live/x/get/c", partial(self._a))\n'
        "    def _a(self, params):\n"
        "        return (1,)\n"
        "    def _b(self, params):\n"
        "        return None\n",
        encoding="utf-8",
    )
    assert gen.main(["--root", str(root)], output_path=tmp_path / "out.py") == 0
    assert "replies: True=1, False=1, None=1" in capsys.readouterr().out


def test_catalog_entry_replies_defaults_to_unknown() -> None:
    entry = catalog.CatalogEntry(
        address="/live/x/y",
        group="x",
        verb="call",
        prop=None,
        args=(),
        risk="write",
        source="mod.py:1",
    )
    assert entry.replies is None


def test_clips_unfilter_does_not_reply() -> None:
    entry = catalog.find("/live/clips/unfilter")
    assert entry is not None and entry.replies is False


def test_committed_catalog_has_both_replying_and_silent_handlers() -> None:
    values = [entry.replies for entry in catalog.entries()]
    assert values.count(True) > 0
    assert values.count(False) > 0


def _catalog_tools(session: OscSession) -> CatalogTools:
    return CatalogTools(session)


def _received(live: MiniLive, address: str) -> list[tuple[Any, ...]]:
    return [request.args for request in live.requests if request.address == address]


@pytest.mark.asyncio
async def test_calls_without_a_known_reply_never_wait_for_one(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:

        async def no_waiting(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("a call without a known reply must not wait")

        session.call = no_waiting  # type: ignore[method-assign]
        catalog_tools = _catalog_tools(session)
        clips = await catalog_tools.catalog_call("/live/clips/unfilter")
        song = await catalog_tools.catalog_call("/live/song/start_playing")
    assert clips.startswith("SENT, NOT VERIFIED: /live/clips/unfilter")
    assert song.startswith("SENT, NOT VERIFIED: /live/song/start_playing")


@pytest.mark.asyncio
async def test_replying_call_that_never_answers_is_not_verified(
    live_factory: Callable[..., MiniLive],
    ports: tuple[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = live_factory(ports[0], ports[1], silent_addresses=("/live/song/get/tempo",))
    async with OscSession(
        send_port=ports[0], receive_port=ports[1], timeout_seconds=0.3
    ) as session:
        result = await _catalog_tools(session).catalog_call("/live/song/get/tempo")
    assert result.startswith("SENT, NOT VERIFIED: /live/song/get/tempo")
    assert "Live gave no reply in time" in result
    assert _received(live, "/live/song/get/tempo") == [()]


@pytest.mark.asyncio
async def test_replying_call_whose_request_never_left_is_an_error(
    ports: tuple[int, int], free_port: Callable[[], int]
) -> None:
    dead_send = free_port()
    async with OscSession(
        send_port=dead_send, receive_port=ports[1], timeout_seconds=0.2
    ) as session:
        result = await _catalog_tools(session).catalog_call("/live/song/get/tempo")
    assert result.startswith("ERROR: ")
    assert "SENT, NOT VERIFIED" not in result


@pytest.mark.asyncio
async def test_read_only_session_refuses_a_replying_call_before_sending(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    async with OscSession(
        send_port=ports[0], receive_port=ports[1], consent=Consent(read_only=True)
    ) as session:
        result = await _catalog_tools(session).catalog_call(
            "/live/device/set/parameter/value", [0, 0, 0, 0.5]
        )
    assert result.startswith("REFUSED: ")
    assert "Nothing was sent." in result
    assert _received(live, "/live/device/set/parameter/value") == []


@pytest.mark.asyncio
async def test_destructive_replying_call_is_refused_without_consent(
    live: MiniLive, ports: tuple[int, int]
) -> None:
    async with OscSession(send_port=ports[0], receive_port=ports[1]) as session:
        result = await _catalog_tools(session).catalog_call("/live/song/delete_track", [0])
    assert result.startswith("REFUSED: ")
    assert "Nothing was sent." in result
    assert _received(live, "/live/song/delete_track") == []
