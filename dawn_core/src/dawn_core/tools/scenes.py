"""Scene tools: create, launch, rename."""

from __future__ import annotations

from ..session import OscCallError, OscSession, UnknownAddressError
from ._helpers import (
    Refused,
    ToolBase,
    check_index,
    error,
    read,
    refused,
    send_action,
    write_and_verify,
)


class SceneTools(ToolBase):
    """Tools that operate on a Session scene."""

    def __init__(self, session: OscSession) -> None:
        self.session = session

    async def create_scene(self, index: int | None = None) -> str:
        """Create a scene, optionally at a 0-based position; omit ``index`` to append."""
        if index is not None:
            try:
                check_index(index, "scene index")
            except Refused as exc:
                return refused(str(exc))
        session = self.session
        try:
            before = int(await read(session, "/live/song/get/num_scenes"))
            await session.send("/live/song/create_scene", *(() if index is None else (index,)))
            after = int(await read(session, "/live/song/get/num_scenes"))
        except (OscCallError, UnknownAddressError, TypeError, ValueError) as exc:
            return error(str(exc))
        if after == before + 1:
            return f"OK: created a scene; the Set now has {after} scenes."
        return f"MISMATCH: asked for a new scene; scene count went {before} -> {after}."

    async def launch_scene(self, scene_index: int) -> str:
        """Fire a scene. Launch quantization may delay the start."""
        try:
            check_index(scene_index, "scene_index")
        except Refused as exc:
            return refused(str(exc))
        return await send_action(self.session, "/live/scene/fire", scene_index)

    async def rename_scene(self, scene_index: int, name: str) -> str:
        """Rename a scene, then read the name back."""
        try:
            check_index(scene_index, "scene_index")
            if not name.strip():
                raise Refused("scene name must not be empty.")
        except Refused as exc:
            return refused(str(exc))
        return await write_and_verify(
            self.session,
            setter="/live/scene/set/name",
            setter_args=(scene_index, name),
            getter="/live/scene/get/name",
            getter_args=(scene_index,),
            expected=name,
            label=f"scene.name scene_index={scene_index}",
        )


__all__ = ["SceneTools"]
