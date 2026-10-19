"""The catalog escape hatch.

The curated tools cover the common musical operations. This one reaches every address
the Remote Script serves, with the same catalog lookup and consent check.
"""

from __future__ import annotations

import json

from dawn_osc import REPLY_TIMEOUT_PREFIX

from .. import catalog
from ..safety import ConsentDenied
from ..session import OscCallError, OscSession, UnknownAddressError
from ._helpers import Scalar, ToolBase, error, refused, show, unwrap


class CatalogTools(ToolBase):
    """One tool that can call any catalog address."""

    def __init__(self, session: OscSession) -> None:
        self.session = session

    async def catalog_call(self, address: str, args: list[Scalar] | None = None) -> str:
        """Call any address in the DAWN OSC catalog.

        Use this for the long tail the curated tools do not cover. ``address`` must be an
        exact catalog address (for example ``/live/song/tap_tempo``). ``args`` are the
        positional OSC arguments. Read the value back afterwards unless the reply is
        included in the result.
        """
        entry = catalog.find(address)
        if entry is None:
            return refused(f"{address!r} is not in the DAWN catalog.")
        call_args = tuple(args or ())
        session = self.session
        # Getters always answer; an action only when the catalog proved it replies.
        expects_reply = entry.verb in {"get", "test"} or entry.replies is True
        try:
            if expects_reply:
                reply = await session.call(address, *call_args)
                return json.dumps(
                    {"address": address, "reply": unwrap(reply, call_args)},
                    ensure_ascii=False,
                )
            await session.send(address, *call_args)
        except ConsentDenied as exc:
            return refused(f"{exc}. Nothing was sent.")
        except OscCallError as exc:
            if session.last_error and session.last_error.startswith(REPLY_TIMEOUT_PREFIX):
                return (
                    f"SENT, NOT VERIFIED: {address} was sent with {show(list(call_args))}; "
                    "Live gave no reply in time. Read the affected value back."
                )
            return error(str(exc))
        except UnknownAddressError as exc:
            return error(str(exc))
        return (
            f"SENT, NOT VERIFIED: {address} was sent with {show(list(call_args))}; "
            "read the affected value back."
        )


__all__ = ["CatalogTools"]
