"""Track tools: create, rename, mix, mute/solo/arm, delete."""

from __future__ import annotations

from typing import Literal

from ..session import OscCallError, OscSession, UnknownAddressError
from ._helpers import (
    Refused,
    ToolBase,
    check_index,
    check_range,
    error,
    read,
    refused,
    write_and_verify,
)


class TrackTools(ToolBase):
    """Tools that operate on one track."""

    def __init__(self, session: OscSession) -> None:
        self.session = session

    async def create_track(
        self,
        kind: Literal["midi", "audio"] = "midi",
        index: int | None = None,
        name: str | None = None,
    ) -> str:
        """Create a MIDI or audio track, optionally at a position and with a name.

        ``index`` is 0-based; omit it to append. Returns the new track's index.
        """
        if index is not None:
            try:
                check_index(index, "track index")
            except Refused as exc:
                return refused(str(exc))
        address = f"/live/song/create_{kind}_track"
        session = self.session
        try:
            before = int(await read(session, "/live/song/get/num_tracks"))
            await session.send(address, *(() if index is None else (index,)))
            after = int(await read(session, "/live/song/get/num_tracks"))
        except (OscCallError, UnknownAddressError, TypeError, ValueError) as exc:
            return error(str(exc))
        if after != before + 1:
            return f"MISMATCH: asked for a new {kind} track; track count went {before} -> {after}."
        new_index = after - 1 if index is None else index
        if name:
            renamed = await self.rename_track(new_index, name)
            if not renamed.startswith("OK"):
                return f"{renamed} (the new track is at index {new_index})"
        return f"OK: created {kind} track at index {new_index}."

    async def rename_track(self, track_index: int, name: str) -> str:
        """Rename a track, then read the name back."""
        try:
            check_index(track_index, "track_index")
            if not name.strip():
                raise Refused("track name must not be empty.")
        except Refused as exc:
            return refused(str(exc))
        return await write_and_verify(
            self.session,
            setter="/live/track/set/name",
            setter_args=(track_index, name),
            getter="/live/track/get/name",
            getter_args=(track_index,),
            expected=name,
            label=f"track.name track_index={track_index}",
        )

    async def set_track_pan(self, track_index: int, pan: float) -> str:
        """Set a track's pan from -1.0 (left) to 1.0 (right), then read it back."""
        try:
            check_index(track_index, "track_index")
            check_range(pan, -1.0, 1.0, "pan")
        except Refused as exc:
            return refused(str(exc))
        return await write_and_verify(
            self.session,
            setter="/live/track/set/panning",
            setter_args=(track_index, pan),
            getter="/live/track/get/panning",
            getter_args=(track_index,),
            expected=pan,
            label=f"track.panning track_index={track_index}",
        )

    async def set_track_mute(self, track_index: int, muted: bool) -> str:
        """Mute or unmute a track, then read it back."""
        try:
            check_index(track_index, "track_index")
        except Refused as exc:
            return refused(str(exc))
        return await write_and_verify(
            self.session,
            setter="/live/track/set/mute",
            setter_args=(track_index, muted),
            getter="/live/track/get/mute",
            getter_args=(track_index,),
            expected=muted,
            label=f"track.mute track_index={track_index}",
        )

    async def set_track_solo(self, track_index: int, soloed: bool) -> str:
        """Solo or unsolo a track, then read it back."""
        try:
            check_index(track_index, "track_index")
        except Refused as exc:
            return refused(str(exc))
        return await write_and_verify(
            self.session,
            setter="/live/track/set/solo",
            setter_args=(track_index, soloed),
            getter="/live/track/get/solo",
            getter_args=(track_index,),
            expected=soloed,
            label=f"track.solo track_index={track_index}",
        )

    async def set_track_arm(self, track_index: int, armed: bool) -> str:
        """Arm or disarm a track for recording, then read it back."""
        try:
            check_index(track_index, "track_index")
        except Refused as exc:
            return refused(str(exc))
        return await write_and_verify(
            self.session,
            setter="/live/track/set/arm",
            setter_args=(track_index, armed),
            getter="/live/track/get/arm",
            getter_args=(track_index,),
            expected=armed,
            label=f"track.arm track_index={track_index}",
        )

    async def delete_track(self, track_index: int) -> str:
        """Delete a track. Destructive: confirm the target with get_session first."""
        try:
            check_index(track_index, "track_index")
        except Refused as exc:
            return refused(str(exc))
        session = self.session
        try:
            before = int(await read(session, "/live/song/get/num_tracks"))
            await session.send("/live/song/delete_track", track_index)
            after = int(await read(session, "/live/song/get/num_tracks"))
        except (OscCallError, UnknownAddressError, TypeError, ValueError) as exc:
            return error(str(exc))
        if after == before - 1:
            return f"OK: deleted track {track_index}; track count is now {after}."
        return (
            f"MISMATCH: asked to delete track {track_index}; track count went {before} -> {after}."
        )


__all__ = ["TrackTools"]
