#--------------------------------------------------------------------------------
# Constants used by the handlers
#--------------------------------------------------------------------------------

from __future__ import absolute_import, print_function, unicode_literals

import json
import os
import re

# Keep the default literals here: desktop contract tests compare them with the
# default DAWN slot.  Every installed copy still reads its own adjacent
# ``dawn_instance.json`` and overrides identity/ports at import time, so a slot
# other than the default stays a configuration change rather than a code change.
OSC_LISTEN_PORT = 11000
OSC_RESPONSE_PORT = 11001
DAWN_INSTANCE_ID = "ableton-1"

_INSTANCE_ID_RE = re.compile(r"^ableton-[1-9][0-9]*$")
_INSTANCE_CONFIG_FILENAME = "dawn_instance.json"


def _valid_port(value):
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def _load_instance_config():
    """Read only this installed script copy's bounded local slot config.

    The desktop installer owns the file.  Invalid/missing data deliberately
    leaves the backwards-compatible primary slot intact rather than widening a
    socket or accepting an ambiguous identity.
    """

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), _INSTANCE_CONFIG_FILENAME)
    try:
        with open(path, "r") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    instance_id = str(payload.get("instance_id") or "").strip().lower()
    listen_port = _valid_port(payload.get("osc_listen_port"))
    response_port = _valid_port(payload.get("osc_response_port"))
    if not _INSTANCE_ID_RE.match(instance_id) or listen_port is None or response_port is None:
        return None
    if listen_port == response_port:
        return None
    return instance_id, listen_port, response_port


_configured = _load_instance_config()
if _configured is not None:
    DAWN_INSTANCE_ID, OSC_LISTEN_PORT, OSC_RESPONSE_PORT = _configured
