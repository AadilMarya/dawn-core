"""MiniLive: an in-process stand-in for the DAWN control surface, for offline tests.

It binds the port an :class:`~dawn_core.session.OscSession` sends to and replies
on the port it receives from, using the same authenticated datagram envelope as the
real surface. Dispatch follows the Remote Script:

* a request carrying ``dawn_request:<id>`` gets its reply prefixed with
  ``dawn_reply:<id>``;
* a handler that returns ``None`` sends no reply (most setters do this);
* an unknown address, or a handler that raises, replies with ``/live/error``.

Every request that authenticates is appended to :attr:`MiniLive.requests`. Datagrams
that fail authentication are only counted in :attr:`MiniLive.rejected_datagrams`.
"""

from __future__ import annotations

import re
import socket
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from pythonosc.osc_message import OscMessage
from pythonosc.osc_message_builder import OscMessageBuilder

from dawn_osc.security import OscSecurityError, OscSecuritySession

HOST = "127.0.0.1"
PROTOCOL = "2.32.0"
REVISION = "mini-live-revision"
_REQUEST_TOKEN = re.compile(r"dawn_request:([0-9a-f]{32})")
_Handler = Callable[[tuple[Any, ...]], "tuple[Any, ...] | None"]


@dataclass(frozen=True, slots=True)
class RecordedRequest:
    address: str
    args: tuple[Any, ...]
    correlated: bool


@dataclass(slots=True)
class MiniTrack:
    name: str
    mute: bool
    volume: float


DEFAULT_TRACKS: tuple[MiniTrack, ...] = (
    MiniTrack("Drums", False, 0.85),
    MiniTrack("Bass", False, 0.70),
    MiniTrack("Lead", False, 0.60),
)


class MiniLive:
    """Serve a small in-memory document over the authenticated OSC envelope."""

    SUPPORTED_ADDRESSES: frozenset[str] = frozenset(
        {
            "/live/test",
            "/dawn/security/status",
            "/live/song/get/tempo",
            "/live/song/set/tempo",
            "/live/song/get/is_playing",
            "/live/song/start_playing",
            "/live/song/stop_playing",
            "/live/song/get/num_tracks",
            "/live/track/get/name",
            "/live/track/set/name",
            "/live/track/get/mute",
            "/live/track/set/mute",
            "/live/track/get/volume",
            "/live/track/set/volume",
        }
    )

    def __init__(
        self,
        *,
        session: OscSecuritySession,
        listen_port: int,
        reply_port: int,
        tracks: Iterable[MiniTrack] = DEFAULT_TRACKS,
        tempo: float = 120.0,
        is_playing: bool = False,
        silent_addresses: Iterable[str] = (),
        instance_id: str = "mini-live-1",
    ) -> None:
        """``listen_port`` is the client's send port; ``reply_port`` its receive port.
        Pass ``listen_port=0`` to let the OS choose; read it back from :attr:`listen_port`.
        """
        self._session = session.clone()
        self._listen_port = listen_port
        self._reply_port = reply_port
        self.tracks: list[MiniTrack] = [MiniTrack(t.name, t.mute, t.volume) for t in tracks]
        self.tempo = float(tempo)
        self.is_playing = bool(is_playing)
        self.silent_addresses = frozenset(silent_addresses)
        self.instance_id = instance_id
        self.requests: list[RecordedRequest] = []
        self.rejected_datagrams = 0
        self._handlers: dict[str, _Handler] = {
            "/live/test": lambda _p: ("ok",),
            "/dawn/security/status": lambda _p: (
                PROTOCOL,
                self._session.session_id_hex,
                REVISION,
                self.instance_id,
            ),
            "/live/song/get/tempo": lambda _p: (self.tempo,),
            "/live/song/set/tempo": self._set_tempo,
            "/live/song/get/is_playing": lambda _p: (self.is_playing,),
            "/live/song/start_playing": lambda _p: self._set_playing(True),
            "/live/song/stop_playing": lambda _p: self._set_playing(False),
            "/live/song/get/num_tracks": lambda _p: (len(self.tracks),),
            "/live/track/get/name": lambda p: self._get_track(p, "name"),
            "/live/track/set/name": lambda p: self._set_track(p, "name", str),
            "/live/track/get/mute": lambda p: self._get_track(p, "mute"),
            "/live/track/set/mute": lambda p: self._set_track(p, "mute", bool),
            "/live/track/get/volume": lambda p: self._get_track(p, "volume"),
            "/live/track/set/volume": lambda p: self._set_track(p, "volume", float),
        }
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def serve(self, address: str, handler: _Handler) -> None:
        """Answer one more address, or replace a built-in one, with ``handler``.

        ``handler`` takes the request arguments and returns the reply tuple, or ``None``
        for no reply, exactly like the built-in handlers.
        """
        self._handlers[address] = handler

    # -- lifecycle --------------------------------------------------------

    @property
    def listen_port(self) -> int:
        return self._listen_port

    @property
    def reply_port(self) -> int:
        return self._reply_port

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((HOST, self._listen_port))
        sock.settimeout(0.05)
        self._listen_port = int(sock.getsockname()[1])
        self._sock = sock
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, name="mini-live", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def __enter__(self) -> MiniLive:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    # -- serving ----------------------------------------------------------

    def _serve(self) -> None:
        sock = self._sock
        assert sock is not None
        while not self._stop.is_set():
            try:
                datagram, _ = sock.recvfrom(65536)
            except TimeoutError:
                continue
            except OSError:
                return
            try:
                payload = self._session.unwrap_request(datagram)
            except OscSecurityError:
                self.rejected_datagrams += 1
                continue
            if payload is not None:
                self._dispatch(payload)

    def _dispatch(self, payload: bytes) -> None:
        try:
            message = OscMessage(payload)
        except Exception:
            self.rejected_datagrams += 1
            return
        params = list(message.params)
        prefix: list[str] = []
        correlated = False
        if params and isinstance(params[0], str):
            match = _REQUEST_TOKEN.fullmatch(params[0])
            if match is not None:
                prefix = [f"dawn_reply:{match.group(1)}"]
                correlated = True
                params = params[1:]
        address = message.address
        self.requests.append(RecordedRequest(address, tuple(params), correlated))
        if address in self.silent_addresses:
            return
        handler = self._handlers.get(address)
        if handler is None:
            self._reply("/live/error", (*prefix, address, "unknown OSC address"))
            return
        try:
            values = handler(tuple(params))
        except Exception:
            self._reply("/live/error", (*prefix, address, "handler failed"))
            return
        if values is not None:
            self._reply(address, (*prefix, *values))

    def _reply(self, address: str, values: tuple[Any, ...]) -> None:
        builder = OscMessageBuilder(address=address)
        for value in values:
            builder.add_arg(value)
        dgram = builder.build().dgram
        assert self._sock is not None
        for datagram in self._session.wrap_response_many(dgram):
            self._sock.sendto(datagram, (HOST, self._reply_port))

    # -- handlers ---------------------------------------------------------

    def _set_tempo(self, params: tuple[Any, ...]) -> None:
        self.tempo = float(params[0])

    def _set_playing(self, playing: bool) -> None:
        self.is_playing = playing

    def _get_track(self, params: tuple[Any, ...], attr: str) -> tuple[Any, ...]:
        index = int(params[0])
        return (index, getattr(self.tracks[index], attr))

    def _set_track(self, params: tuple[Any, ...], attr: str, convert: Callable[[Any], Any]) -> None:
        index = int(params[0])
        setattr(self.tracks[index], attr, convert(params[1]))
