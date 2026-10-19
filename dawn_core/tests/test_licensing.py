"""Licensing and attribution checks for the workspace.

Read-only and offline. Checks the Apache-2.0 license texts, the package license
metadata, the license blocks copied into the notices files, and that the names of
upstream projects, their authors and private identifiers stay out of everything
except the THIRD_PARTY_NOTICES.md files. Names are assembled from fragments so this
file never contains them as literals.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ("dawn_osc", "dawn_core")
NOTICES = "THIRD_PARTY_NOTICES.md"
APACHE_TITLE = "Apache License"
APACHE_VERSION = "Version 2.0, January 2004"

# Directories never scanned: VCS, environments and tool caches. The vendored OSC library
# (remote_script/DAWN/pythonosc) is pruned by path in iter_text_files. The rest of the
# Remote Script tree is scanned like any other source.
SKIP_DIR_NAMES = frozenset(
    {".git", ".venv", "__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache"}
)
VENDORED_OSC_DIR = "remote_script/DAWN/pythonosc"
SKIP_FILE_NAMES = frozenset({"uv.lock", NOTICES})
# Machine-generated source, excluded from the upstream-name scan (repo-relative prefixes).
# It is still scanned for private identifiers.
GENERATED_PREFIXES: tuple[str, ...] = ()
FENCED_TEXT_BLOCK = re.compile(r"^```text\n(.*?)^```$", re.MULTILINE | re.DOTALL)
# Roots of the whole-word check: the code packages and the root documents. The root notices
# are listed explicitly because the directory walk skips notices files by name.
WHOLE_WORD_SCOPE = (ROOT / "dawn_osc", ROOT / "dawn_core", ROOT / "README.md", ROOT / NOTICES)


def _join(*parts: str) -> str:
    """Assemble a literal from fragments so the whole string never appears in this file."""
    return "".join(parts)


# The OSC library, a runtime dependency. Its requirement lines and imports are exempt.
OSC_PACKAGE = _join("python", "-osc")
# Names of the projects this code was derived from. Each one must also appear in the
# root notices file; test_scanned_names_come_from_root_notices enforces that.
DERIVED_FROM = (
    _join("Ableton", "OSC"),
    OSC_PACKAGE,
)
# Authors and handles named in the notices. They may appear only in the notices as well.
AUTHOR_NAMES = (
    _join("Daniel", " John", " Jones"),
    _join("ideo", "forms"),
    _join("attw", "ad"),
)
# The upstream project name, also caught with a space, underscore or hyphen between words.
_UPSTREAM_PROJECT = re.compile(_join("Ableton", "[ _-]?", "OSC"), re.IGNORECASE)
UPSTREAM_PATTERNS = (
    _UPSTREAM_PROJECT,
    *(re.compile(re.escape(name), re.IGNORECASE) for name in (*DERIVED_FROM[1:], *AUTHOR_NAMES)),
)

# Private identifiers that must not appear anywhere in the repo, generated source included.
PRIVATE_PATTERNS = (
    re.compile(re.escape(_join("dawn", "_py")), re.IGNORECASE),
    re.compile(re.escape(_join("/", "Users", "/"))),
)
# A whole, capitalised word that marks a model tier. Generated source uses it legitimately,
# so it is checked only inside WHOLE_WORD_SCOPE.
WHOLE_WORD_TIER = re.compile(r"\b" + _join("P", "ro") + r"\b")

# The only lines that may name the OSC library: its requirement line in a pyproject, and
# Python imports of the vendored pythonosc package.
_OSC_REQUIREMENT = re.compile(
    r'^\s*"' + re.escape(OSC_PACKAGE) + r'(\[[^\]]*\])?\s*([<>=!~;][^"]*)?",?\s*$'
)
_PYTHONOSC_IMPORT = re.compile(
    r"^\s*(?:from\s+\.*pythonosc(?:\.\w+)*\s+import\b|import\s+pythonosc\b)"
)


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    text: str


def _is_exempt(path: Path, line: str) -> bool:
    if path.name == "pyproject.toml" and _OSC_REQUIREMENT.match(line):
        return True
    return path.suffix == ".py" and _PYTHONOSC_IMPORT.match(line) is not None


def _no_exemption(path: Path, line: str) -> bool:
    return False


def iter_text_files(top: Path, skip_prefixes: tuple[str, ...] = ()) -> Iterator[Path]:
    """Yield candidate files under ``top``, pruning skipped directories.

    A file ``top`` is yielded as given, even a notices file, so one file can be scanned.
    """
    if top.is_file():
        yield top
        return
    for dirpath, dirnames, filenames in os.walk(top):
        base = Path(dirpath)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in SKIP_DIR_NAMES and not (base / d).as_posix().endswith(VENDORED_OSC_DIR)
        )
        for name in sorted(filenames):
            if name in SKIP_FILE_NAMES:
                continue
            path = base / name
            if skip_prefixes and path.relative_to(top).as_posix().startswith(skip_prefixes):
                continue
            yield path


def _display(path: Path, top: Path) -> str:
    """Repo-relative path for a report, or a path relative to the scan root outside the repo."""
    if path.is_relative_to(ROOT):
        return path.relative_to(ROOT).as_posix()
    return path.name if top.is_file() else path.relative_to(top).as_posix()


def scan_for_names(
    top: Path,
    patterns: Iterable[re.Pattern[str]],
    skip_prefixes: tuple[str, ...] = (),
    exempt: Callable[[Path, str], bool] = _no_exemption,
) -> list[Hit]:
    """Return every line under ``top`` (text files only) that matches a pattern and is not exempt."""
    compiled = tuple(patterns)
    hits: list[Hit] = []
    for path in iter_text_files(top, skip_prefixes):
        data = path.read_bytes()
        if b"\0" in data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        rel = _display(path, top)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if exempt(path, line):
                continue
            for pattern in compiled:
                for match in pattern.finditer(line):
                    hits.append(Hit(rel, lineno, match.group(0)))
    return hits


def _describe(hits: list[Hit]) -> str:
    return "\n".join(f"{hit.path}:{hit.line}: {hit.text!r}" for hit in hits)


def test_root_license_is_apache_2_0() -> None:
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    first_lines = [line.strip() for line in text.splitlines() if line.strip()][:2]
    assert first_lines == [APACHE_TITLE, APACHE_VERSION]


def test_package_version_matches_its_metadata() -> None:
    import dawn_core

    pyproject = tomllib.loads((ROOT / "dawn_core" / "pyproject.toml").read_text(encoding="utf-8"))
    assert dawn_core.__version__ == pyproject["project"]["version"]


def test_license_copies_are_byte_identical() -> None:
    expected = (ROOT / "LICENSE").read_bytes()
    for pkg in PACKAGES:
        assert (ROOT / pkg / "LICENSE").read_bytes() == expected, f"{pkg}/LICENSE differs"


@pytest.mark.parametrize("pkg", PACKAGES)
def test_pyproject_declares_apache_and_existing_license_files(pkg: str) -> None:
    pyproject = tomllib.loads((ROOT / pkg / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    assert project["license"] == "Apache-2.0"
    license_files = project["license-files"]
    assert license_files, f"{pkg}: license-files is empty"
    for rel in license_files:
        assert (ROOT / pkg / rel).is_file(), f"{pkg}: license-files entry {rel} is missing"


@pytest.mark.parametrize("pkg", ("dawn_osc",))
def test_bundled_license_blocks_appear_verbatim_in_root_notices(pkg: str) -> None:
    root_notices = (ROOT / NOTICES).read_text(encoding="utf-8")
    blocks = FENCED_TEXT_BLOCK.findall((ROOT / pkg / NOTICES).read_text(encoding="utf-8"))
    assert blocks, f"{pkg}/{NOTICES} has no fenced text license block"
    for block in blocks:
        assert block in root_notices, f"{pkg}/{NOTICES}: a license block is not verbatim in root"


def test_scanned_names_come_from_root_notices() -> None:
    notices = (ROOT / NOTICES).read_text(encoding="utf-8").lower()
    for name in (*DERIVED_FROM, *AUTHOR_NAMES):
        assert name.lower() in notices, "a scanned name is not listed in the root notices"


def test_upstream_names_stay_inside_notices() -> None:
    hits = scan_for_names(ROOT, UPSTREAM_PATTERNS, GENERATED_PREFIXES, _is_exempt)
    assert not hits, "upstream names found outside THIRD_PARTY_NOTICES.md:\n" + _describe(hits)


def test_private_identifiers_stay_out_of_every_tree() -> None:
    hits = scan_for_names(ROOT, PRIVATE_PATTERNS)
    assert not hits, "private identifiers found:\n" + _describe(hits)


def test_whole_word_tier_check_covers_code_packages_and_root_docs() -> None:
    hits = [hit for top in WHOLE_WORD_SCOPE for hit in scan_for_names(top, (WHOLE_WORD_TIER,))]
    assert not hits, "forbidden whole word found in code packages or root docs:\n" + _describe(hits)


def test_remote_script_is_scanned_and_vendored_osc_is_not() -> None:
    scanned = {path.relative_to(ROOT).as_posix() for path in iter_text_files(ROOT)}
    assert "dawn_osc/src/dawn_osc/remote_script/DAWN/manager.py" in scanned
    assert "dawn_osc/src/dawn_osc/remote_script/DAWN/handlers/handler.py" in scanned
    assert not [path for path in scanned if "/remote_script/DAWN/pythonosc/" in path]


def test_scanner_negative_control(tmp_path: Path) -> None:
    planted = tmp_path / "planted.txt"
    planted.write_text(
        f"derived: {DERIVED_FROM[0]}\nprivate: {_join('/', 'Users', '/')}\n"
        f"tier: {_join('P', 'ro')}\n",
        encoding="utf-8",
    )
    patterns = (*UPSTREAM_PATTERNS, *PRIVATE_PATTERNS, WHOLE_WORD_TIER)
    hits = scan_for_names(tmp_path, patterns)
    assert [hit.line for hit in hits] == [1, 2, 3], "planted names were not reported"

    # Notices files are exempt: the same text inside one must produce no new hits.
    (tmp_path / NOTICES).write_text(planted.read_text(encoding="utf-8"), encoding="utf-8")
    hits = scan_for_names(tmp_path, patterns)
    assert {hit.path for hit in hits} == {"planted.txt"}


def test_exemptions_are_narrow(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f'dependencies = [\n    "{OSC_PACKAGE}>=1.8.3",\n]\n', encoding="utf-8"
    )
    (tmp_path / "notes.md").write_text(f'    "{OSC_PACKAGE}>=1.8.3",\n', encoding="utf-8")
    (tmp_path / "module.py").write_text(
        f"from pythonosc.dispatcher import Dispatcher  # {OSC_PACKAGE}\n# built on {OSC_PACKAGE}\n",
        encoding="utf-8",
    )
    hits = scan_for_names(tmp_path, UPSTREAM_PATTERNS, exempt=_is_exempt)
    assert sorted((hit.path, hit.line) for hit in hits) == [("module.py", 2), ("notes.md", 1)]
