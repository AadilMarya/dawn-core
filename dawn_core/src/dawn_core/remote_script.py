"""Install the packaged Remote Script into Live's Remote Scripts folder.

The install is transactional. The tree is copied into a staging folder beside the target,
any existing ``DAWN`` is moved aside, the staged copy is renamed into place, and the result is
compared with the packaged tree. A failure at any step puts the old copy back.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import dawn_osc
from dawn_osc.security import osc_session_path
from dawn_osc.transport import DEFAULT_HOST

from .safety import Consent
from .session import OscSession

SCRIPT_NAME = "DAWN"
NEXT_STEP = (
    "Next: restart Live, then select DAWN under Settings > Link, Tempo & MIDI > Control Surface."
)
# Names Live and macOS write into an installed tree that are not part of the deployable
# tree: bytecode beside imported sources, `manager.start_logging`'s logs/, the instance
# config, and Finder/AppleDouble metadata. Kept identical to the Remote Script's own
# revision digest (`DAWN/__init__.py`: _REVISION_PRUNED_DIRS/_REVISION_SKIPPED_FILES) --
# comparing any of them would make an install Live has used report "differs" forever.
_PRUNED_DIR_NAMES = frozenset({"__pycache__", ".git", "logs"})
_SKIPPED_FILE_NAMES = frozenset({"dawn_instance.json", ".DS_Store", "Icon\r"})
_SKIPPED_SUFFIXES = (".pyc", ".pyo")
_SKIPPED_PREFIXES = ("._",)
_IGNORED = shutil.ignore_patterns("__pycache__", "*.pyc")


class ScriptInstallError(RuntimeError):
    """The install was refused or failed, and the destination was left as it was."""


REMOTE_SCRIPTS_ENV = "DAWN_CORE_REMOTE_SCRIPTS_DIR"


def default_remote_scripts_dir() -> Path:
    """Live's Remote Scripts folder for this platform.

    ``$DAWN_CORE_REMOTE_SCRIPTS_DIR`` wins when set. Otherwise the path follows Ableton's
    per-platform User Library: ``Music/Ableton`` on macOS, ``Documents/Ableton`` elsewhere.
    """
    override = os.environ.get(REMOTE_SCRIPTS_ENV)
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Music" / "Ableton" / "User Library" / "Remote Scripts"
    return Path.home() / "Documents" / "Ableton" / "User Library" / "Remote Scripts"


def packaged_script_dir() -> Path:
    return dawn_osc.script_dir()


def _is_deployable(name: str) -> bool:
    """Whether one filename is part of the deployable tree (mirrors the script's digest)."""
    if name in _SKIPPED_FILE_NAMES or name.endswith(_SKIPPED_SUFFIXES):
        return False
    return not name.startswith(_SKIPPED_PREFIXES)


def script_tree(root: Path) -> Mapping[str, bytes]:
    """Relative POSIX path to contents for every deployable file under ``root``.

    Bytecode, Live's logs and instance config, and macOS metadata are excluded by the
    same rules as the Remote Script's revision digest, so an install that Live has
    already used still compares equal to the packaged tree.
    """
    tree: dict[str, bytes] = {}
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in _PRUNED_DIR_NAMES)
        base = Path(directory)
        for name in filenames:
            if not _is_deployable(name):
                continue
            path = base / name
            tree[path.relative_to(root).as_posix()] = path.read_bytes()
    return tree


def script_matches(installed: Path) -> bool:
    """True when ``installed`` holds exactly the packaged Remote Script."""
    if not installed.is_dir():
        return False
    return script_tree(installed) == script_tree(packaged_script_dir())


def _backup_path(dest_root: Path, stamp: str) -> Path:
    candidate = dest_root / f"{SCRIPT_NAME}.bak-{stamp}"
    counter = 2
    while candidate.exists() or candidate.is_symlink():
        candidate = dest_root / f"{SCRIPT_NAME}.bak-{stamp}-{counter}"
        counter += 1
    return candidate


def install_script(
    dest_root: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
) -> list[str]:
    """Install the Remote Script as ``dest_root/DAWN``. Returns the steps taken or planned.

    An existing ``DAWN`` is refused unless ``force`` is set. With ``force`` it is moved to
    ``DAWN.bak-<timestamp>`` first. ``dry_run`` checks everything and writes nothing.
    """
    source = packaged_script_dir()
    if not source.is_dir():
        raise ScriptInstallError(f"packaged Remote Script not found at {source}")
    target = dest_root / SCRIPT_NAME
    exists = target.exists() or target.is_symlink()
    if exists and not force:
        raise ScriptInstallError(
            f"{target} already exists; re-run with --force to replace it "
            "(the old copy is kept as DAWN.bak-<timestamp>)"
        )

    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    backup = _backup_path(dest_root, stamp) if exists else None
    steps = [f"copy {source} to {target}"]
    if backup is not None:
        steps.insert(0, f"move existing {target} to {backup}")
    if dry_run:
        return [f"would {step}" for step in steps]

    dest_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".DAWN-install-", dir=dest_root))
    try:
        staged = staging / SCRIPT_NAME
        shutil.copytree(source, staged, ignore=_IGNORED)
        if backup is not None:
            os.replace(target, backup)
        try:
            os.replace(staged, target)
            if not script_matches(target):
                raise ScriptInstallError(f"{target} does not match the packaged script after copy")
        except BaseException:
            _roll_back(target, backup)
            raise
    except OSError as exc:
        raise ScriptInstallError(f"install into {dest_root} failed: {exc}") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return [*steps, f"installed {SCRIPT_NAME} into {dest_root}"]


def _roll_back(target: Path, backup: Path | None) -> None:
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target, ignore_errors=True)
    elif target.exists() or target.is_symlink():
        target.unlink()
    if backup is not None and (backup.exists() or backup.is_symlink()):
        os.replace(backup, target)


@dataclass(frozen=True, slots=True)
class Check:
    """One installation or connectivity check."""

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class InstallReport:
    """The result of :func:`check_install`; ``ok`` is true when every check passed."""

    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def lines(self) -> list[str]:
        return [f"{'PASS' if check.ok else 'FAIL'}  {check.detail}" for check in self.checks]


def _check_script(dest_root: Path) -> Check:
    target = dest_root / SCRIPT_NAME
    if not target.is_dir():
        return Check("script", False, f"Remote Script not installed at {target}")
    if not script_matches(target):
        return Check("script", False, f"{target} differs from the packaged Remote Script")
    return Check("script", True, f"Remote Script at {target} matches the packaged copy")


async def _check_live(
    *,
    send_port: int | None,
    receive_port: int | None,
    timeout: float | None,
    consent: Consent | None,
) -> Check:
    policy = consent or Consent(read_only=True)
    async with OscSession(
        send_port=send_port,
        receive_port=receive_port,
        timeout_seconds=timeout,
        consent=policy,
    ) as session:
        answered = await session.ping()
        port = session.send_port
    if answered:
        return Check("live", True, f"Live answered /live/test on {DEFAULT_HOST}:{port}")
    return Check(
        "live",
        False,
        f"Live did not answer /live/test on {DEFAULT_HOST}:{port}; select DAWN under "
        "Settings > Link, Tempo & MIDI > Control Surface and make sure Live is running",
    )


def _check_session_file() -> Check:
    path = osc_session_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Check("session", False, f"no OSC session file at {path}")
    except (OSError, ValueError) as exc:
        return Check("session", False, f"OSC session file at {path} is unreadable: {exc}")
    if not isinstance(payload, dict) or not payload.get("session_id"):
        return Check("session", False, f"OSC session file at {path} is malformed")
    return Check("session", True, f"OSC session file readable at {path}")


async def check_install_async(
    dest_root: Path | str | None = None,
    *,
    ping: bool = True,
    send_port: int | None = None,
    receive_port: int | None = None,
    timeout: float | None = None,
    consent: Consent | None = None,
) -> InstallReport:
    """Check the Remote Script install, Live connectivity and the session file.

    ``ping=False`` skips the network check. The session file check runs after the ping so a
    missing file is created by a successful first connection.
    """
    dest = Path(dest_root).expanduser() if dest_root is not None else default_remote_scripts_dir()
    checks = [_check_script(dest)]
    if ping:
        checks.append(
            await _check_live(
                send_port=send_port,
                receive_port=receive_port,
                timeout=timeout,
                consent=consent,
            )
        )
    checks.append(_check_session_file())
    return InstallReport(tuple(checks))


def check_install(
    dest_root: Path | str | None = None,
    *,
    ping: bool = True,
    send_port: int | None = None,
    receive_port: int | None = None,
    timeout: float | None = None,
    consent: Consent | None = None,
) -> InstallReport:
    """Synchronous :func:`check_install_async`; use the async form inside a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            check_install_async(
                dest_root,
                ping=ping,
                send_port=send_port,
                receive_port=receive_port,
                timeout=timeout,
                consent=consent,
            )
        )
    raise RuntimeError("check_install() cannot run inside an event loop; use check_install_async()")


__all__ = [
    "Check",
    "InstallReport",
    "NEXT_STEP",
    "REMOTE_SCRIPTS_ENV",
    "SCRIPT_NAME",
    "ScriptInstallError",
    "check_install",
    "check_install_async",
    "default_remote_scripts_dir",
    "install_script",
    "packaged_script_dir",
    "script_matches",
    "script_tree",
]
