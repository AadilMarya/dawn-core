"""The system prompt, composed from short musical doctrine sections.

The prompt is the agent's taste and working method. It is deliberately explicit: read
before writing, one change at a time, verify every write, and choose musical defaults
instead of interviewing the user.
"""

from __future__ import annotations

from collections.abc import Sequence
from importlib.resources import files

DEFAULT_SECTIONS: tuple[str, ...] = (
    "persona",
    "production",
    "arrangement",
    "mixing",
    "sound_design",
    "ableton",
)

# Always present, whichever expertise subset the caller asks for.
ALWAYS: tuple[str, ...] = ("persona", "ableton")


def available_sections() -> tuple[str, ...]:
    """Names that can be passed to ``expertise``."""
    return DEFAULT_SECTIONS


def _read(section: str) -> str:
    resource = files(__package__).joinpath(f"{section}.md")
    return resource.read_text(encoding="utf-8").strip()


def compose_system_prompt(expertise: Sequence[str] | None = None) -> str:
    """Compose the system prompt from the doctrine sections.

    ``expertise`` selects sections. ``persona`` and ``ableton`` are always included;
    unknown names raise ``ValueError``. ``None`` selects every section.
    """
    if expertise is None:
        selected = DEFAULT_SECTIONS
    else:
        requested = {str(name).strip().casefold() for name in expertise}
        unknown = sorted(requested - set(DEFAULT_SECTIONS))
        if unknown:
            raise ValueError(
                f"unknown expertise section(s): {', '.join(unknown)}; "
                f"choose from {', '.join(DEFAULT_SECTIONS)}"
            )
        chosen = requested | set(ALWAYS)
        selected = tuple(name for name in DEFAULT_SECTIONS if name in chosen)
    return "\n\n".join(_read(name) for name in selected).strip() + "\n"


SYSTEM_PROMPT = compose_system_prompt()


__all__ = [
    "ALWAYS",
    "DEFAULT_SECTIONS",
    "SYSTEM_PROMPT",
    "available_sections",
    "compose_system_prompt",
]
