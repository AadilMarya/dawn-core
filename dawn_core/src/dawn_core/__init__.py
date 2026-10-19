"""DAWN Core — an open-source AI music agent for Ableton Live.

    from dawn_core import MusicAgent, OscSession, Consent

    async with OscSession(consent=Consent()) as live:
        agent = MusicAgent("openai:gpt-4o", session=live)
        result = await agent.run("build a 4-bar deep house groove at 122")

The agent is the product. It is built from three small pieces:

* :class:`~dawn_core.session.OscSession` — the catalog-gated, consent-checked link to Live;
* :mod:`dawn_core.tools` — curated musical tools with read-back verification;
* :mod:`dawn_core.prompt` — the producer's taste and working method.

Swap the model, the expertise subset or the tool list without changing the rest.
"""

from . import catalog
from .agent import MusicAgent, build_agent
from .prompt import (
    DEFAULT_SECTIONS,
    SYSTEM_PROMPT,
    available_sections,
    compose_system_prompt,
)
from .remote_script import (
    Check,
    InstallReport,
    check_install,
    check_install_async,
    default_remote_scripts_dir,
    install_script,
)
from .safety import Consent, ConsentDenied
from .session import OscCallError, OscSession, UnknownAddressError
from .tools import Note, build_tools, tool_names

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_SECTIONS",
    "SYSTEM_PROMPT",
    "Check",
    "Consent",
    "ConsentDenied",
    "InstallReport",
    "MusicAgent",
    "Note",
    "OscCallError",
    "OscSession",
    "UnknownAddressError",
    "available_sections",
    "build_agent",
    "build_tools",
    "catalog",
    "check_install",
    "check_install_async",
    "compose_system_prompt",
    "default_remote_scripts_dir",
    "install_script",
    "tool_names",
    "__version__",
]
