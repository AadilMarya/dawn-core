"""DAWN — a DAWN-branded fork of the upstream OSC control surface.

The `/live/*` surface is the upstream handler fork. DAWN adds exactly two endpoints on
top: `/dawn/version` (diagnostics) and `/dawn/security/status` (the HMAC
handshake used by the DAWN transport). There is no verified-mutation layer,
session snapshot, browser loader, master/return handler, or arrangement writer
in this open surface; those belong to the private surface.

The upstream project is MIT licensed; attribution lives in THIRD_PARTY_NOTICES.md.
"""

from __future__ import absolute_import, print_function, unicode_literals

import hashlib
import os

try:
    from .handlers.constants import DAWN_INSTANCE_ID
except ImportError:  # pragma: no cover - only for file-level tests outside Live
    DAWN_INSTANCE_ID = "ableton-1"

DAWN_PROTOCOL_VERSION = "2.32.0"
_SURFACE_REVISION = None

_REVISION_PRUNED_DIRS = ("__pycache__", ".git", "logs")
_REVISION_SKIPPED_FILES = ("dawn_instance.json", ".DS_Store", "Icon\r")
_REVISION_SKIPPED_SUFFIXES = (".pyc", ".pyo")
_REVISION_SKIPPED_PREFIXES = ("._",)


def _is_revisioned_file(name):
    """Return whether one filename contributes to the deployable digest."""
    if name in _REVISION_SKIPPED_FILES:
        return False
    if name.endswith(_REVISION_SKIPPED_SUFFIXES):
        return False
    return not name.startswith(_REVISION_SKIPPED_PREFIXES)


def _surface_revision():
    """Stable digest of the deployable Remote Script tree.

    Computed eagerly at import so the revision describes the bytes Live loaded,
    not a later desktop-side repair. Kept Python-2-compatible because Live still
    loads Remote Scripts in its own runtime.
    """
    global _SURFACE_REVISION
    if _SURFACE_REVISION is not None:
        return _SURFACE_REVISION
    digest = hashlib.sha256()
    root = os.path.dirname(os.path.abspath(__file__))
    try:
        for directory, names, files in os.walk(root):
            names[:] = sorted(name for name in names if name not in _REVISION_PRUNED_DIRS)
            for name in sorted(files):
                if not _is_revisioned_file(name):
                    continue
                path = os.path.join(directory, name)
                relative = os.path.relpath(path, root).replace(os.sep, "/")
                digest.update(relative.encode("utf-8"))
                digest.update(b"\0")
                with open(path, "rb") as handle:
                    while True:
                        chunk = handle.read(65536)
                        if not chunk:
                            break
                        digest.update(chunk)
        _SURFACE_REVISION = digest.hexdigest()
    except Exception:
        _SURFACE_REVISION = "unavailable"
    return _SURFACE_REVISION


_surface_revision()

try:
    from .manager import Manager as _BaseManager
except Exception:  # pragma: no cover - file-level tests outside Live
    class _BaseManager(object):
        def __init__(self, _c_instance):
            self.osc_server = None

        def show_message(self, _message):
            return None

        def reload_imports(self):
            return None


class DAWN(_BaseManager):
    """The open DAWN control surface: upstream handlers plus the DAWN HMAC handshake."""

    def __init__(self, c_instance):
        super(DAWN, self).__init__(c_instance)
        self._started = True
        self._register_dawn_endpoints()
        if hasattr(self, "show_message"):
            self.show_message(
                "DAWN: control surface ready (protocol {})".format(DAWN_PROTOCOL_VERSION)
            )

    def _register_dawn_endpoints(self):
        """Register the two DAWN metadata endpoints on top of the OSC surface."""
        osc_server = getattr(self, "osc_server", None)
        if osc_server is None or not hasattr(osc_server, "add_handler"):
            return
        osc_server.add_handler("/dawn/version", self._handle_dawn_version)
        osc_server.add_handler("/dawn/security/status", self._handle_security_status)

    def _handle_dawn_version(self, _params):
        return (DAWN_PROTOCOL_VERSION,)

    def _handle_security_status(self, _params):
        """Authenticated handshake; unsigned datagrams never reach handlers."""
        transport = getattr(getattr(self, "osc_server", None), "_security", None)
        session_id = getattr(transport, "session_id_hex", None)
        return (
            DAWN_PROTOCOL_VERSION,
            session_id or "",
            _surface_revision(),
            DAWN_INSTANCE_ID,
        )

    def reload_imports(self):
        super(DAWN, self).reload_imports()
        self._register_dawn_endpoints()


def create_instance(c_instance):
    return DAWN(c_instance)
