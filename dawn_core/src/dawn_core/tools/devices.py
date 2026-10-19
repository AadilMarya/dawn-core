"""Device tools: list, set a parameter, toggle."""

from __future__ import annotations

import json
from typing import Any

from ..session import OscCallError, OscSession, UnknownAddressError
from ._helpers import (
    Refused,
    ToolBase,
    check_index,
    error,
    read,
    refused,
    same,
    show,
)


class DeviceTools(ToolBase):
    """Tools that operate on a track's devices."""

    def __init__(self, session: OscSession) -> None:
        self.session = session

    async def list_devices(self, track_index: int) -> str:
        """List a track's devices in chain order, with each device's name and class.

        Returns JSON: ``[{"index": 0, "name": "...", "class_name": "..."}]``.
        """
        try:
            check_index(track_index, "track_index")
        except Refused as exc:
            return refused(str(exc))
        session = self.session
        try:
            names = _as_list(await read(session, "/live/track/get/devices/name", track_index))
            classes = _as_list(
                await read(session, "/live/track/get/devices/class_name", track_index)
            )
        except (OscCallError, UnknownAddressError) as exc:
            return error(str(exc))
        devices = [
            {
                "index": index,
                "name": name,
                "class_name": classes[index] if index < len(classes) else None,
            }
            for index, name in enumerate(names)
        ]
        return json.dumps(devices, ensure_ascii=False)

    async def set_device_parameter(
        self,
        track_index: int,
        device_index: int,
        parameter: str | int,
        value: float,
    ) -> str:
        """Set a device parameter by name or index, then read the value back.

        Names are matched case-insensitively. The value must be inside the parameter's
        reported minimum and maximum.
        """
        try:
            check_index(track_index, "track_index")
            check_index(device_index, "device_index")
        except Refused as exc:
            return refused(str(exc))
        session = self.session
        names = _as_list(
            await read(session, "/live/device/get/parameters/name", track_index, device_index)
        )
        minimum = _as_list(
            await read(session, "/live/device/get/parameters/min", track_index, device_index)
        )
        maximum = _as_list(
            await read(session, "/live/device/get/parameters/max", track_index, device_index)
        )
        parameter_index = _resolve_parameter(parameter, names)
        if parameter_index is None:
            return refused(
                f"device {device_index} has no parameter {parameter!r}; "
                f"available: {', '.join(str(n) for n in names)}"
            )
        if parameter_index < len(minimum) and parameter_index < len(maximum):
            low, high = float(minimum[parameter_index]), float(maximum[parameter_index])
            if not low <= float(value) <= high:
                return refused(
                    f"parameter {names[parameter_index]!r} is {low:g} to {high:g}, "
                    f"not {float(value):g}."
                )
        display = str(names[parameter_index]) if parameter_index < len(names) else str(parameter)
        await session.send(
            "/live/device/set/parameter/value",
            track_index,
            device_index,
            parameter_index,
            float(value),
        )
        actual = await read(
            session,
            "/live/device/get/parameter/value",
            track_index,
            device_index,
            parameter_index,
        )
        if same(value, actual):
            return f"OK: device {device_index} parameter {display!r} is {show(actual)}."
        return (
            f"MISMATCH: wrote {show(value)} to device {device_index} parameter "
            f"{display!r}; Live reports {show(actual)}."
        )

    async def toggle_device(self, track_index: int, device_index: int, enabled: bool) -> str:
        """Switch a device on or off through its "Device On" parameter, then read it back."""
        return await self.set_device_parameter(
            track_index, device_index, 0, 1.0 if enabled else 0.0
        )


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    if value is None:
        return []
    return [value]


def _resolve_parameter(parameter: str | int, names: list[Any]) -> int | None:
    if isinstance(parameter, int) and not isinstance(parameter, bool):
        return parameter if 0 <= parameter < len(names) else None
    wanted = str(parameter).strip().casefold()
    for index, name in enumerate(names):
        if str(name).strip().casefold() == wanted:
            return index
    for index, name in enumerate(names):
        if str(name).strip().casefold().startswith(wanted):
            return index
    return None


__all__ = ["DeviceTools"]
