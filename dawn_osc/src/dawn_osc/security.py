"""Authenticated datagram envelope for the local DAWN OSC transport.

The DAWN Remote Script still receives and emits ordinary OSC payloads internally.
Only the UDP datagram boundary is wrapped, which keeps every existing handler API
unchanged while preventing unauthenticated local/LAN processes from driving Live.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import struct
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

OSC_SECURITY_PROTOCOL = 3
OSC_SECURITY_STATUS_ADDRESS = "/dawn/security/status"
OSC_SESSION_FILENAME = "osc_session.json"

_MAGIC = b"DAWNOSC\0"
_KIND_REQUEST = 1
_KIND_RESPONSE = 2
_KIND_REQUEST_FRAGMENT = 3
_KIND_RESPONSE_FRAGMENT = 4
_HEADER = struct.Struct("!8sBB16sQH")
_MAC_SIZE = hashlib.sha256().digest_size
_MAX_DATAGRAM = 8_192
_MAX_PAYLOAD = _MAX_DATAGRAM - _HEADER.size - _MAC_SIZE
_FRAGMENT_HEADER = struct.Struct("!16sHH")
_FRAGMENT_MAX_PAYLOAD = _MAX_PAYLOAD - _FRAGMENT_HEADER.size
_MAX_FRAGMENTS_PER_MESSAGE = 64
_MAX_INFLIGHT_FRAGMENT_MESSAGES = 8
_MAX_REASSEMBLY_BYTES = 512 * 1024
_FRAGMENT_TTL_SECONDS = 5.0
_REPLAY_CACHE_SIZE = 4_096


class OscSecurityError(ValueError):
    """The OSC security envelope is missing, invalid, or replayed."""


class _ReplayCache:
    def __init__(self, limit: int = _REPLAY_CACHE_SIZE) -> None:
        self._limit = limit
        self._highest = -1
        self._bitmap = 0
        self._mask = (1 << limit) - 1
        self._lock = threading.Lock()

    def accept(self, counter: int) -> bool:
        with self._lock:
            if counter > self._highest:
                shift = counter - self._highest
                self._bitmap = 1 if shift >= self._limit else ((self._bitmap << shift) | 1)
                self._bitmap &= self._mask
                self._highest = counter
                return True
            distance = self._highest - counter
            if distance >= self._limit:
                return False
            bit = 1 << distance
            if self._bitmap & bit:
                return False
            self._bitmap |= bit
            return True


@dataclass(slots=True)
class _FragmentBuffer:
    total: int
    created_at: float
    chunks: dict[int, bytes] = field(default_factory=dict)
    size: int = 0


@dataclass(slots=True)
class OscSecuritySession:
    """One per-DAWN-launch OSC authentication session."""

    session_id: bytes
    key: bytes
    owner_pid: int
    created_at: float
    _counter: int = field(default_factory=time.time_ns, repr=False)
    _counter_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _request_replays: _ReplayCache = field(default_factory=_ReplayCache, repr=False)
    _response_replays: _ReplayCache = field(default_factory=_ReplayCache, repr=False)
    _fragments: dict[tuple[int, bytes], _FragmentBuffer] = field(default_factory=dict, repr=False)
    _fragment_bytes: int = field(default=0, repr=False)
    _fragment_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def session_id_hex(self) -> str:
        return self.session_id.hex()

    def clone(self) -> OscSecuritySession:
        """Return the same credentials with independent counters/replay state."""
        return OscSecuritySession(
            session_id=self.session_id,
            key=self.key,
            owner_pid=self.owner_pid,
            created_at=self.created_at,
        )

    def _next_counter(self) -> int:
        with self._counter_lock:
            self._counter = max(self._counter + 1, time.time_ns())
            return self._counter

    def _reserve_counters(self, count: int) -> range:
        """Reserve counters per batch so reordered fragments remain replay-valid."""
        with self._counter_lock:
            first = max(self._counter + 1, time.time_ns())
            self._counter = first + count - 1
            return range(first, first + count)

    def wrap_request(self, payload: bytes) -> bytes:
        return self._wrap(payload, _KIND_REQUEST)

    def wrap_response(self, payload: bytes) -> bytes:
        return self._wrap(payload, _KIND_RESPONSE)

    def wrap_request_many(self, payload: bytes) -> list[bytes]:
        """Wrap a request as one or more independently authenticated datagrams."""
        return self._wrap_many(payload, _KIND_REQUEST)

    def wrap_response_many(self, payload: bytes) -> list[bytes]:
        """Wrap a response as one or more independently authenticated datagrams."""
        return self._wrap_many(payload, _KIND_RESPONSE)

    def unwrap_request(self, datagram: bytes) -> bytes | None:
        return self._unwrap(datagram, _KIND_REQUEST, self._request_replays)

    def unwrap_response(self, datagram: bytes) -> bytes | None:
        return self._unwrap(datagram, _KIND_RESPONSE, self._response_replays)

    def _wrap(self, payload: bytes, kind: int, *, counter: int | None = None) -> bytes:
        if len(payload) > _MAX_PAYLOAD:
            raise OscSecurityError(
                f"OSC payload is too large for one authenticated UDP datagram ({len(payload)} bytes)"
            )
        counter = self._next_counter() if counter is None else counter
        header = _HEADER.pack(
            _MAGIC,
            OSC_SECURITY_PROTOCOL,
            kind,
            self.session_id,
            counter,
            len(payload),
        )
        mac = hmac.new(self.key, header + payload, hashlib.sha256).digest()
        return header + mac + payload

    def _wrap_many(self, payload: bytes, kind: int) -> list[bytes]:
        if len(payload) <= _MAX_PAYLOAD:
            return [self._wrap(payload, kind)]

        total = (len(payload) + _FRAGMENT_MAX_PAYLOAD - 1) // _FRAGMENT_MAX_PAYLOAD
        if total > _MAX_FRAGMENTS_PER_MESSAGE:
            raise OscSecurityError("OSC payload exceeds authenticated fragment limits")
        fragment_kind = _KIND_REQUEST_FRAGMENT if kind == _KIND_REQUEST else _KIND_RESPONSE_FRAGMENT
        message_id = secrets.token_bytes(16)
        counters = self._reserve_counters(total)
        return [
            self._wrap(
                _FRAGMENT_HEADER.pack(message_id, index, total)
                + payload[index * _FRAGMENT_MAX_PAYLOAD : (index + 1) * _FRAGMENT_MAX_PAYLOAD],
                fragment_kind,
                counter=counters[index],
            )
            for index in range(total)
        ]

    def _unwrap(
        self, datagram: bytes, expected_kind: int, replay_cache: _ReplayCache
    ) -> bytes | None:
        minimum = _HEADER.size + _MAC_SIZE
        if len(datagram) < minimum:
            raise OscSecurityError("unsigned OSC datagram")
        try:
            magic, version, kind, session_id, counter, payload_len = _HEADER.unpack_from(datagram)
        except struct.error as exc:
            raise OscSecurityError("malformed OSC security envelope") from exc
        if magic != _MAGIC:
            raise OscSecurityError("unsigned OSC datagram")
        if version != OSC_SECURITY_PROTOCOL:
            raise OscSecurityError(f"unsupported OSC security protocol {version}")
        fragment_kind = (
            _KIND_REQUEST_FRAGMENT if expected_kind == _KIND_REQUEST else _KIND_RESPONSE_FRAGMENT
        )
        if kind not in {expected_kind, fragment_kind}:
            raise OscSecurityError("OSC security envelope direction mismatch")
        if not hmac.compare_digest(session_id, self.session_id):
            raise OscSecurityError("OSC security session mismatch")
        if payload_len > _MAX_PAYLOAD or len(datagram) != minimum + payload_len:
            raise OscSecurityError("malformed OSC security payload length")
        mac = datagram[_HEADER.size : minimum]
        payload = datagram[minimum:]
        expected_mac = hmac.new(
            self.key, datagram[: _HEADER.size] + payload, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(mac, expected_mac):
            raise OscSecurityError("invalid OSC security signature")
        if not replay_cache.accept(counter):
            raise OscSecurityError("replayed OSC datagram")
        if kind == fragment_kind:
            return self._accept_fragment(payload, expected_kind)
        return payload

    def _accept_fragment(self, payload: bytes, expected_kind: int) -> bytes | None:
        if len(payload) < _FRAGMENT_HEADER.size:
            raise OscSecurityError("malformed OSC fragment")
        message_id, index, total = _FRAGMENT_HEADER.unpack_from(payload)
        if total == 0 or total > _MAX_FRAGMENTS_PER_MESSAGE or index >= total:
            raise OscSecurityError("invalid OSC fragment sequence")
        chunk = payload[_FRAGMENT_HEADER.size :]
        now = time.monotonic()
        key = (expected_kind, message_id)
        with self._fragment_lock:
            self._evict_expired_fragments(now)
            buffer = self._fragments.get(key)
            if buffer is None:
                self._evict_oldest_fragments(required_messages=1, required_bytes=len(chunk))
                buffer = _FragmentBuffer(total=total, created_at=now)
                self._fragments[key] = buffer
            elif buffer.total != total:
                raise OscSecurityError("conflicting OSC fragment sequence")
            if index in buffer.chunks:
                raise OscSecurityError("duplicate OSC fragment")
            self._evict_oldest_fragments(
                required_messages=0,
                required_bytes=len(chunk),
                protected_key=key,
            )
            if self._fragment_bytes + len(chunk) > _MAX_REASSEMBLY_BYTES:
                self._discard_fragment_buffer(key)
                raise OscSecurityError("OSC fragment exceeds reassembly buffer limit")
            buffer.chunks[index] = chunk
            buffer.size += len(chunk)
            self._fragment_bytes += len(chunk)
            if len(buffer.chunks) != buffer.total:
                return None
            assembled = b"".join(buffer.chunks[chunk_index] for chunk_index in range(total))
            self._discard_fragment_buffer(key)
            return assembled

    def _evict_expired_fragments(self, now: float) -> None:
        for key, buffer in list(self._fragments.items()):
            if now - buffer.created_at >= _FRAGMENT_TTL_SECONDS:
                self._discard_fragment_buffer(key)

    def _evict_oldest_fragments(
        self,
        *,
        required_messages: int,
        required_bytes: int,
        protected_key: tuple[int, bytes] | None = None,
    ) -> None:
        while (
            len(self._fragments) + required_messages > _MAX_INFLIGHT_FRAGMENT_MESSAGES
            or self._fragment_bytes + required_bytes > _MAX_REASSEMBLY_BYTES
        ):
            candidates = [
                (key, buffer) for key, buffer in self._fragments.items() if key != protected_key
            ]
            if not candidates:
                return
            oldest_key, _ = min(candidates, key=lambda item: item[1].created_at)
            self._discard_fragment_buffer(oldest_key)

    def _discard_fragment_buffer(self, key: tuple[int, bytes]) -> None:
        buffer = self._fragments.pop(key, None)
        if buffer is not None:
            self._fragment_bytes -= buffer.size


_PROCESS_SESSION: OscSecuritySession | None = None
_PROCESS_LOCK = threading.Lock()


def _runtime_dir() -> Path:
    """Directory holding the session file; the Remote Script reads the same path.

    Honors ``DAWN_RUNTIME_DIR`` (tests and embedders redirect it); otherwise
    ``~/.dawn/runtime``.
    """
    override = os.environ.get("DAWN_RUNTIME_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".dawn" / "runtime"


def _atomic_write_json(path: Path, obj: object, *, mode: int, **json_kwargs: object) -> None:
    """Write *obj* as JSON via a same-directory temp file, fsync, chmod, then rename.

    The session file is replaced atomically so a reader never sees a torn file.
    """
    data = json.dumps(obj, **json_kwargs).encode("utf-8")  # type: ignore[arg-type]
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def osc_session_path() -> Path:
    return _runtime_dir() / OSC_SESSION_FILENAME


def _validate_session_stat(path: Path, info: os.stat_result) -> None:
    if os.name != "posix":
        return
    if not stat.S_ISREG(info.st_mode):
        raise OscSecurityError(f"OSC session path is not a regular file: {path}")
    if info.st_uid != os.getuid():
        raise OscSecurityError(f"OSC session file is not owned by the current user: {path}")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise OscSecurityError(f"OSC session file permissions are too broad: {path}")


def load_osc_session(path: Path | None = None) -> OscSecuritySession:
    session_path = path or osc_session_path()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(session_path, flags)
    except OSError as exc:
        raise OscSecurityError(f"Unable to open OSC session file securely: {session_path}") from exc
    try:
        _validate_session_stat(session_path, os.fstat(fd))
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            raw = json.load(handle)
    finally:
        if fd >= 0:
            os.close(fd)
    if int(raw.get("protocol", 0)) != OSC_SECURITY_PROTOCOL:
        raise OscSecurityError("OSC session file uses an unsupported protocol")
    try:
        session_id = bytes.fromhex(str(raw["session_id"]))
        key = bytes.fromhex(str(raw["key"]))
        owner_pid = int(raw["pid"])
        created_at = float(raw["created_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OscSecurityError("OSC session file is malformed") from exc
    if len(session_id) != 16 or len(key) != 32 or owner_pid <= 0:
        raise OscSecurityError("OSC session file has invalid credentials")
    return OscSecuritySession(session_id, key, owner_pid, created_at)


def start_osc_session(*, path: Path | None = None) -> OscSecuritySession:
    """Create and publish this process's per-launch OSC session atomically."""
    global _PROCESS_SESSION
    session_path = path or osc_session_path()
    with _PROCESS_LOCK:
        if _PROCESS_SESSION is not None and _PROCESS_SESSION.owner_pid == os.getpid():
            return _PROCESS_SESSION
        session = OscSecuritySession(
            secrets.token_bytes(16), secrets.token_bytes(32), os.getpid(), time.time()
        )
        session_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            os.chmod(session_path.parent, 0o700)
        payload = {
            "protocol": OSC_SECURITY_PROTOCOL,
            "session_id": session.session_id_hex,
            "key": session.key.hex(),
            "pid": session.owner_pid,
            "created_at": session.created_at,
        }
        _atomic_write_json(
            session_path,
            payload,
            separators=(",", ":"),
            sort_keys=True,
            mode=0o600,
        )
        _PROCESS_SESSION = session
        return session


def get_process_osc_session() -> OscSecuritySession:
    """Load the active app session, creating it only when no app owns one.

    Normal desktop/headless startup calls :func:`start_osc_session` explicitly.
    The lazy path preserves standalone CLI/tests without rotating another live
    DAWN process's credentials.
    """
    global _PROCESS_SESSION
    with _PROCESS_LOCK:
        if _PROCESS_SESSION is not None:
            return _PROCESS_SESSION
        try:
            _PROCESS_SESSION = load_osc_session()
            return _PROCESS_SESSION
        except (FileNotFoundError, OSError, OscSecurityError, json.JSONDecodeError):
            pass
    return start_osc_session()


def reset_process_osc_session_for_tests() -> None:
    global _PROCESS_SESSION
    with _PROCESS_LOCK:
        _PROCESS_SESSION = None


__all__ = [
    "OSC_SECURITY_PROTOCOL",
    "OSC_SECURITY_STATUS_ADDRESS",
    "OscSecurityError",
    "OscSecuritySession",
    "get_process_osc_session",
    "load_osc_session",
    "osc_session_path",
    "reset_process_osc_session_for_tests",
    "start_osc_session",
]
