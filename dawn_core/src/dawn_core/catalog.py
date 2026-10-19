"""Read-only index over the generated OSC catalog.

Every address the Remote Script serves appears here exactly once, with its group,
verb, property, argument signature and risk class. Anything not in the catalog is
refused by :class:`dawn_core.session.OscSession`.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from ._catalog_data import ENTRIES
from ._catalog_types import ArgSpec, CatalogEntry, RiskClass, Verb

__all__ = [
    "ArgSpec",
    "CatalogEntry",
    "RiskClass",
    "Verb",
    "by_group",
    "entries",
    "find",
    "groups",
]


def _index(entries: tuple[CatalogEntry, ...]) -> Mapping[str, CatalogEntry]:
    index: dict[str, CatalogEntry] = {}
    for entry in entries:
        if entry.address in index:
            raise RuntimeError(f"duplicate catalog address: {entry.address}")
        index[entry.address] = entry
    return MappingProxyType(index)


_BY_ADDRESS: Mapping[str, CatalogEntry] = _index(ENTRIES)


def entries() -> tuple[CatalogEntry, ...]:
    """Every catalog entry, sorted by address."""
    return ENTRIES


def find(address: str) -> CatalogEntry | None:
    """The entry for an exact address, or ``None`` when the catalog does not serve it."""
    return _BY_ADDRESS.get(address)


def groups() -> tuple[str, ...]:
    """Sorted names of every group present in the catalog."""
    return tuple(sorted({entry.group for entry in ENTRIES}))


def by_group() -> dict[str, tuple[CatalogEntry, ...]]:
    """Entries keyed by group name, each group's entries sorted by address."""
    grouped: dict[str, list[CatalogEntry]] = {name: [] for name in groups()}
    for entry in ENTRIES:
        grouped[entry.group].append(entry)
    return {name: tuple(items) for name, items in grouped.items()}
