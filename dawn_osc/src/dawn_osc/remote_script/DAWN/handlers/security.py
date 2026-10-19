"""Authenticated datagram envelope used by the DAWN Remote Script.

This module deliberately has no Ableton imports.  It mirrors the wire format in
``dawn_osc.security`` so the vendored Remote Script remains a
self-contained install.
"""

from __future__ import absolute_import, print_function, unicode_literals

import hashlib
import hmac
import json
import os
import stat
import struct
import threading
import time

OSC_SECURITY_PROTOCOL = 3
OSC_SESSION_FILENAME = "osc_session.json"

_MAGIC = b"DAWNOSC\0"
_KIND_REQUEST = 1
_KIND_RESPONSE = 2
_KIND_REQUEST_FRAGMENT = 3
_KIND_RESPONSE_FRAGMENT = 4
_HEADER = struct.Struct("!8sBB16sQH")
_MAC_SIZE = hashlib.sha256().digest_size
_MAX_DATAGRAM = 8192
_MAX_PAYLOAD = _MAX_DATAGRAM - _HEADER.size - _MAC_SIZE
_FRAGMENT_HEADER = struct.Struct("!16sHH")
_FRAGMENT_MAX_PAYLOAD = _MAX_PAYLOAD - _FRAGMENT_HEADER.size
_MAX_FRAGMENTS_PER_MESSAGE = 64
_MAX_INFLIGHT_FRAGMENT_MESSAGES = 8
_MAX_REASSEMBLY_BYTES = 512 * 1024
_FRAGMENT_TTL_SECONDS = 5.0
_REPLAY_CACHE_SIZE = 4096


class OscSecurityError(ValueError):
    pass


class _ReplayCache(object):
    def __init__(self, limit=_REPLAY_CACHE_SIZE):
        self._limit = limit
        self._highest = -1
        self._bitmap = 0
        self._mask = (1 << limit) - 1
        self._lock = threading.Lock()

    def accept(self, counter):
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


class _FragmentBuffer(object):
    def __init__(self, total, created_at):
        self.total = total
        self.created_at = created_at
        self.chunks = {}
        self.size = 0


class OscSecuritySession(object):
    def __init__(self, session_id, key):
        self.session_id = session_id
        self.key = key
        self._counter = int(time.time() * 1000000000)
        self._counter_lock = threading.Lock()
        self._request_replays = _ReplayCache()
        self._response_replays = _ReplayCache()
        self._fragments = {}
        self._fragment_bytes = 0
        self._fragment_lock = threading.Lock()

    def _next_counter(self):
        with self._counter_lock:
            self._counter = max(self._counter + 1, int(time.time() * 1000000000))
            return self._counter

    def _reserve_counters(self, count):
        """Reserve counters per batch so reordered fragments remain replay-valid."""
        with self._counter_lock:
            first = max(self._counter + 1, int(time.time() * 1000000000))
            self._counter = first + count - 1
            return range(first, first + count)

    def wrap_response(self, payload):
        return self._wrap(payload, _KIND_RESPONSE)

    def wrap_response_many(self, payload):
        return self._wrap_many(payload, _KIND_RESPONSE)

    def unwrap_request(self, datagram):
        return self._unwrap(datagram, _KIND_REQUEST, self._request_replays)

    def _wrap(self, payload, kind, counter=None):
        if len(payload) > _MAX_PAYLOAD:
            raise OscSecurityError("OSC payload is too large for one authenticated UDP datagram")
        counter = self._next_counter() if counter is None else counter
        header = _HEADER.pack(
            _MAGIC, OSC_SECURITY_PROTOCOL, kind, self.session_id, counter, len(payload)
        )
        mac = hmac.new(self.key, header + payload, hashlib.sha256).digest()
        return header + mac + payload

    def _wrap_many(self, payload, kind):
        if len(payload) <= _MAX_PAYLOAD:
            return [self._wrap(payload, kind)]

        total = (len(payload) + _FRAGMENT_MAX_PAYLOAD - 1) // _FRAGMENT_MAX_PAYLOAD
        if total > _MAX_FRAGMENTS_PER_MESSAGE:
            raise OscSecurityError("OSC payload exceeds authenticated fragment limits")
        fragment_kind = (
            _KIND_REQUEST_FRAGMENT if kind == _KIND_REQUEST else _KIND_RESPONSE_FRAGMENT
        )
        message_id = os.urandom(16)
        counters = self._reserve_counters(total)
        fragments = []
        for index in range(total):
            chunk = payload[index * _FRAGMENT_MAX_PAYLOAD:(index + 1) * _FRAGMENT_MAX_PAYLOAD]
            fragments.append(
                self._wrap(
                    _FRAGMENT_HEADER.pack(message_id, index, total) + chunk,
                    fragment_kind,
                    counter=counters[index],
                )
            )
        return fragments

    def _unwrap(self, datagram, expected_kind, replay_cache):
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
            raise OscSecurityError("unsupported OSC security protocol")
        fragment_kind = (
            _KIND_REQUEST_FRAGMENT
            if expected_kind == _KIND_REQUEST
            else _KIND_RESPONSE_FRAGMENT
        )
        if kind != expected_kind and kind != fragment_kind:
            raise OscSecurityError("OSC security envelope direction mismatch")
        if not hmac.compare_digest(session_id, self.session_id):
            raise OscSecurityError("OSC security session mismatch")
        if payload_len > _MAX_PAYLOAD or len(datagram) != minimum + payload_len:
            raise OscSecurityError("malformed OSC security payload length")
        mac = datagram[_HEADER.size:minimum]
        payload = datagram[minimum:]
        expected_mac = hmac.new(self.key, datagram[:_HEADER.size] + payload, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected_mac):
            raise OscSecurityError("invalid OSC security signature")
        if not replay_cache.accept(counter):
            raise OscSecurityError("replayed OSC datagram")
        if kind == fragment_kind:
            return self._accept_fragment(payload, expected_kind)
        return payload

    def _accept_fragment(self, payload, expected_kind):
        if len(payload) < _FRAGMENT_HEADER.size:
            raise OscSecurityError("malformed OSC fragment")
        message_id, index, total = _FRAGMENT_HEADER.unpack_from(payload)
        if total == 0 or total > _MAX_FRAGMENTS_PER_MESSAGE or index >= total:
            raise OscSecurityError("invalid OSC fragment sequence")
        chunk = payload[_FRAGMENT_HEADER.size:]
        now = time.time()
        key = (expected_kind, message_id)
        with self._fragment_lock:
            self._evict_expired_fragments(now)
            buffer = self._fragments.get(key)
            if buffer is None:
                self._evict_oldest_fragments(1, len(chunk))
                buffer = _FragmentBuffer(total, now)
                self._fragments[key] = buffer
            elif buffer.total != total:
                raise OscSecurityError("conflicting OSC fragment sequence")
            if index in buffer.chunks:
                raise OscSecurityError("duplicate OSC fragment")
            self._evict_oldest_fragments(0, len(chunk), key)
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

    def _evict_expired_fragments(self, now):
        for key, buffer in list(self._fragments.items()):
            if now - buffer.created_at >= _FRAGMENT_TTL_SECONDS:
                self._discard_fragment_buffer(key)

    def _evict_oldest_fragments(self, required_messages, required_bytes, protected_key=None):
        while (
            len(self._fragments) + required_messages > _MAX_INFLIGHT_FRAGMENT_MESSAGES
            or self._fragment_bytes + required_bytes > _MAX_REASSEMBLY_BYTES
        ):
            candidates = [
                (key, buffer)
                for key, buffer in self._fragments.items()
                if key != protected_key
            ]
            if not candidates:
                return
            oldest_key, _oldest_buffer = min(candidates, key=lambda item: item[1].created_at)
            self._discard_fragment_buffer(oldest_key)

    def _discard_fragment_buffer(self, key):
        buffer = self._fragments.pop(key, None)
        if buffer is not None:
            self._fragment_bytes -= buffer.size


def default_session_path():
    override = os.environ.get("DAWN_RUNTIME_DIR", "").strip()
    root = os.path.expanduser(override) if override else os.path.expanduser("~/.dawn/runtime")
    return os.path.join(root, OSC_SESSION_FILENAME)


def _load_session(path):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise OscSecurityError("unable to open OSC session file securely") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OscSecurityError("OSC session path is not a regular file")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise OscSecurityError("OSC session file has the wrong owner")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise OscSecurityError("OSC session file permissions are too broad")
        with os.fdopen(fd, "r") as handle:
            fd = -1
            raw = json.load(handle)
    finally:
        if fd >= 0:
            os.close(fd)
    if int(raw.get("protocol", 0)) != OSC_SECURITY_PROTOCOL:
        raise OscSecurityError("OSC session file uses an unsupported protocol")
    session_id = bytes.fromhex(str(raw["session_id"]))
    key = bytes.fromhex(str(raw["key"]))
    if len(session_id) != 16 or len(key) != 32:
        raise OscSecurityError("OSC session file has invalid credentials")
    return OscSecuritySession(session_id, key)


class SecureOscTransport(object):
    """Reloadable Remote-Script-side session and replay state."""

    def __init__(self, session_path=None):
        self._session_path = session_path or default_session_path()
        self._session = None

    @property
    def session_id_hex(self):
        if self._session is None:
            return None
        return self._session.session_id.hex()

    def _candidate_session_id(self, datagram):
        if len(datagram) < _HEADER.size:
            return None
        try:
            magic, _version, _kind, session_id, _counter, _payload_len = _HEADER.unpack_from(datagram)
        except struct.error:
            return None
        return session_id if magic == _MAGIC else None

    def unwrap_request(self, datagram):
        candidate = self._candidate_session_id(datagram)
        if candidate is None:
            raise OscSecurityError("unsigned OSC datagram")
        if self._session is None or not hmac.compare_digest(candidate, self._session.session_id):
            session = _load_session(self._session_path)
            if not hmac.compare_digest(candidate, session.session_id):
                raise OscSecurityError("OSC security session mismatch")
            self._session = session
        return self._session.unwrap_request(datagram)

    def wrap_response(self, payload):
        if self._session is None:
            raise OscSecurityError("no authenticated OSC session")
        return self._session.wrap_response(payload)

    def wrap_response_many(self, payload):
        if self._session is None:
            raise OscSecurityError("no authenticated OSC session")
        return self._session.wrap_response_many(payload)


__all__ = [
    "OSC_SECURITY_PROTOCOL",
    "OscSecurityError",
    "OscSecuritySession",
    "SecureOscTransport",
    "default_session_path",
]
