"""The transactional install, without the CLI around it."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import dawn_core.remote_script as remote_script
import dawn_osc
from dawn_core.remote_script import (
    SCRIPT_NAME,
    ScriptInstallError,
    install_script,
    script_matches,
    script_tree,
)


def test_install_writes_no_bytecode(tmp_path: Path) -> None:
    install_script(tmp_path)
    installed = tmp_path / SCRIPT_NAME
    assert not list(installed.rglob("__pycache__"))
    assert not list(installed.rglob("*.pyc"))


def test_install_leaves_no_staging_folder_behind(tmp_path: Path) -> None:
    install_script(tmp_path)
    assert sorted(path.name for path in tmp_path.iterdir()) == [SCRIPT_NAME]


def test_a_failed_swap_restores_the_previous_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_script(tmp_path)
    previous = tmp_path / SCRIPT_NAME / "README.md"
    previous.write_text("previous copy", encoding="utf-8")

    monkeypatch.setattr(remote_script, "script_matches", lambda installed: False)
    with pytest.raises(ScriptInstallError, match="does not match the packaged script"):
        install_script(tmp_path, force=True)

    assert previous.read_text(encoding="utf-8") == "previous copy"
    assert sorted(path.name for path in tmp_path.iterdir()) == [SCRIPT_NAME]


def test_a_backup_name_never_overwrites_an_older_backup(tmp_path: Path) -> None:
    stamp = datetime(2026, 10, 8, 12, 0, 0)
    install_script(tmp_path)
    install_script(tmp_path, force=True, now=stamp)
    install_script(tmp_path, force=True, now=stamp)
    backups = sorted(path.name for path in tmp_path.iterdir() if ".bak-" in path.name)
    assert backups == ["DAWN.bak-20261008-120000", "DAWN.bak-20261008-120000-2"]


def test_dry_run_plans_the_backup_and_the_copy(tmp_path: Path) -> None:
    install_script(tmp_path)
    steps = install_script(tmp_path, force=True, dry_run=True)
    assert steps[0].startswith("would move existing ")
    assert steps[1].startswith("would copy ")
    assert (tmp_path / SCRIPT_NAME).is_dir()
    assert len(list(tmp_path.iterdir())) == 1


def test_script_tree_matches_the_packaged_folder_after_install(tmp_path: Path) -> None:
    install_script(tmp_path)
    assert script_tree(tmp_path / SCRIPT_NAME) == script_tree(dawn_osc.script_dir())


def test_live_runtime_files_do_not_make_an_install_look_different(tmp_path: Path) -> None:
    """Live writes bytecode, logs/ and dawn_instance.json into the installed folder, and
    macOS drops Finder metadata there; the comparison must skip exactly what the script's
    own revision digest skips, or an install Live has used reports "differs" forever."""
    install_script(tmp_path)
    installed = tmp_path / SCRIPT_NAME
    (installed / "logs").mkdir()
    (installed / "logs" / "dawn_osc.log").write_text("live wrote this", encoding="utf-8")
    (installed / "dawn_instance.json").write_text('{"instance": "ableton-1"}', encoding="utf-8")
    (installed / ".DS_Store").write_bytes(b"\x00finder")
    (installed / "._track.py").write_bytes(b"\x00appledouble")
    (installed / "__pycache__").mkdir()
    (installed / "__pycache__" / "manager.cpython-311.pyc").write_bytes(b"\x00pyc")

    assert script_matches(installed)
    assert script_tree(installed) == script_tree(dawn_osc.script_dir())


def test_default_remote_scripts_dir_honours_the_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(remote_script.REMOTE_SCRIPTS_ENV, str(tmp_path))
    assert remote_script.default_remote_scripts_dir() == tmp_path


def test_check_install_reports_a_missing_script(tmp_path: Path) -> None:
    report = remote_script.check_install(tmp_path, ping=False)
    checks = {check.name: check for check in report.checks}
    assert checks["script"].ok is False
    assert report.ok is False
    assert report.lines()[0].startswith("FAIL")


def test_check_install_accepts_a_matching_install(tmp_path: Path) -> None:
    install_script(tmp_path)
    report = remote_script.check_install(tmp_path, ping=False)
    checks = {check.name: check for check in report.checks}
    assert checks["script"].ok is True
    assert checks["script"].detail.startswith("Remote Script at")
