"""dawn_osc - authenticated OSC transport and Remote Script for Ableton Live.

``script_dir()`` is the folder to install as ``DAWN`` inside Live's Remote
Scripts directory; ``OscTransport`` is the Python client that talks to it.
"""

from __future__ import annotations

from pathlib import Path

from .security import OscSecurityError, OscSecuritySession, get_process_osc_session
from .transport import REPLY_TIMEOUT_PREFIX, OscTransport

__all__ = [
    "REPLY_TIMEOUT_PREFIX",
    "OscSecurityError",
    "OscSecuritySession",
    "OscTransport",
    "get_process_osc_session",
    "remote_script_root",
    "script_dir",
]


def remote_script_root() -> Path:
    """Directory that contains the ``DAWN`` Remote Script folder."""
    return Path(__file__).resolve().parent / "remote_script"


def script_dir() -> Path:
    """The Remote Script folder, named ``DAWN`` as Live requires."""
    return remote_script_root() / "DAWN"
