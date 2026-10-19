"""Standalone checks: dawn_osc imports only the stdlib and its declared dependencies."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import dawn_osc

SRC = Path(__file__).resolve().parents[1] / "src"
PKG = SRC / "dawn_osc"
ALLOWED_THIRD_PARTY = frozenset({"dawn_osc", "loguru", "pythonosc"})


def _host_sources() -> list[Path]:
    # The Remote Script runs inside Live and carries its own vendored code, so it is out of scope.
    return sorted(
        path
        for path in PKG.rglob("*.py")
        if "remote_script" not in path.parts and "__pycache__" not in path.parts
    )


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names.add(node.module.partition(".")[0])
    return names


def test_script_dir_is_the_remote_script_folder() -> None:
    script = dawn_osc.script_dir()
    assert script.is_dir()
    assert (script / "__init__.py").is_file()
    assert (script / "manager.py").is_file()


def test_package_imports_only_stdlib_and_declared_dependencies() -> None:
    sources = _host_sources()
    assert sources, "no dawn_osc source files found"
    offenders: dict[str, list[str]] = {}
    for path in sources:
        unexpected = sorted(
            name
            for name in _top_level_imports(path)
            if name not in sys.stdlib_module_names and name not in ALLOWED_THIRD_PARTY
        )
        if unexpected:
            offenders[str(path.relative_to(SRC))] = unexpected
    assert offenders == {}


def test_importing_dawn_osc_loads_no_other_dawn_package() -> None:
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(SRC)!r})\n"
        "import dawn_osc\n"
        "print([m for m in sys.modules if m.startswith('dawn_') and m != 'dawn_osc'"
        " and not m.startswith('dawn_osc.')])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", result.stdout
