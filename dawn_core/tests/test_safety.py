"""Consent policy: the full read/write/destructive x read_only x confirm x yes matrix."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from dawn_core._catalog_types import CatalogEntry
from dawn_core.safety import Consent, ConsentDenied, deny_all

ARGS: tuple[Any, ...] = (3, "value")

CONFIRM_KINDS = ("default", "true", "false", "truthy", "raises")


def _entry(risk: str) -> CatalogEntry:
    return CatalogEntry(
        address=f"/live/x/{risk}",
        group="x",
        verb="call",
        prop=None,
        args=(),
        risk=risk,  # type: ignore[arg-type]
        source="synthetic.py:1",
    )


def _consent(read_only: bool, yes: bool, kind: str) -> Consent:
    if kind == "default":
        return Consent(read_only=read_only, yes=yes)
    if kind == "true":
        return Consent(read_only=read_only, yes=yes, confirm=lambda e, a: True)
    if kind == "false":
        return Consent(read_only=read_only, yes=yes, confirm=lambda e, a: False)
    if kind == "truthy":
        # Only the literal True counts. Any other truthy value must be refused.
        return Consent(read_only=read_only, yes=yes, confirm=lambda e, a: 1)  # type: ignore[arg-type,return-value]

    def boom(entry: CatalogEntry, args: tuple[Any, ...]) -> bool:
        raise RuntimeError("prompt crashed")

    return Consent(read_only=read_only, yes=yes, confirm=boom)


def _expected_allowed(risk: str, read_only: bool, yes: bool, kind: str) -> bool:
    if risk == "read":
        return True
    if read_only:
        return False
    if risk == "write":
        return True
    # destructive
    if yes:
        return True
    return kind == "true"


MATRIX = list(
    itertools.product(("read", "write", "destructive"), (False, True), (False, True), CONFIRM_KINDS)
)


@pytest.mark.parametrize(
    ("risk", "read_only", "yes", "kind"),
    MATRIX,
    ids=[f"{r}-ro{int(ro)}-yes{int(y)}-{k}" for r, ro, y, k in MATRIX],
)
def test_consent_matrix(risk: str, read_only: bool, yes: bool, kind: str) -> None:
    consent = _consent(read_only, yes, kind)
    expected = _expected_allowed(risk, read_only, yes, kind)
    if expected:
        consent.check(_entry(risk), ARGS)
    else:
        with pytest.raises(ConsentDenied):
            consent.check(_entry(risk), ARGS)


def test_default_consent_allows_reads_and_writes_but_never_destructive() -> None:
    consent = Consent()
    consent.check(_entry("read"), ARGS)
    consent.check(_entry("write"), ARGS)
    with pytest.raises(ConsentDenied) as info:
        consent.check(_entry("destructive"), ARGS)
    assert info.value.risk == "destructive"
    assert info.value.address == "/live/x/destructive"


def test_default_confirm_callback_denies() -> None:
    assert deny_all(_entry("destructive"), ARGS) is False


def test_confirm_receives_the_entry_and_arguments() -> None:
    seen: list[tuple[str, tuple[Any, ...]]] = []

    def record(entry: CatalogEntry, args: tuple[Any, ...]) -> bool:
        seen.append((entry.address, args))
        return True

    Consent(confirm=record).check(_entry("destructive"), ARGS)
    assert seen == [("/live/x/destructive", ARGS)]


def test_raising_confirm_is_a_refusal_with_the_cause_chained() -> None:
    consent = _consent(read_only=False, yes=False, kind="raises")
    with pytest.raises(ConsentDenied) as info:
        consent.check(_entry("destructive"), ARGS)
    assert isinstance(info.value.__cause__, RuntimeError)


def test_unknown_risk_class_fails_closed_even_for_yes() -> None:
    with pytest.raises(ConsentDenied, match="unknown risk class"):
        Consent(yes=True).check(_entry("bogus"), ARGS)


def test_consent_is_immutable() -> None:
    consent = Consent()
    with pytest.raises(AttributeError):
        consent.yes = True  # type: ignore[misc]
