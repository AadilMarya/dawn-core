"""The prompt is part of the product: its sections, budget and doctrine."""

from __future__ import annotations

import pytest

from dawn_core.prompt import (
    ALWAYS,
    DEFAULT_SECTIONS,
    SYSTEM_PROMPT,
    available_sections,
    compose_system_prompt,
)


def test_default_sections_are_the_six_doctrine_files() -> None:
    assert DEFAULT_SECTIONS == (
        "persona",
        "production",
        "arrangement",
        "mixing",
        "sound_design",
        "ableton",
    )
    assert available_sections() == DEFAULT_SECTIONS


def test_default_prompt_has_the_operating_doctrine() -> None:
    assert "music producer and mix engineer" in SYSTEM_PROMPT
    assert "Read the target before you change it" in SYSTEM_PROMPT
    assert "Trust only a result that starts with `OK`" in SYSTEM_PROMPT
    assert "SENT, NOT VERIFIED" in SYSTEM_PROMPT
    assert "MISMATCH" in SYSTEM_PROMPT
    assert "0-based" in SYSTEM_PROMPT
    assert "one bar is 4 beats" in SYSTEM_PROMPT


def test_prompt_stays_within_the_token_budget() -> None:
    # Four characters per token is a deliberately rough upper bound.
    assert len(SYSTEM_PROMPT) <= 10_000


def test_expertise_selects_sections_and_keeps_the_anchors() -> None:
    prompt = compose_system_prompt(["mixing"])
    assert "Mixing doctrine" in prompt
    assert "Arrangement doctrine" not in prompt
    assert "Sound design doctrine" not in prompt
    assert "Persona" in prompt
    assert "Ableton Live" in prompt
    for name in ALWAYS:
        assert name in DEFAULT_SECTIONS
    assert compose_system_prompt(["mixing"]) == prompt


def test_expertise_is_case_insensitive_and_deduplicated() -> None:
    assert compose_system_prompt(["Mixing", "mixing"]) == compose_system_prompt(["mixing"])


def test_unknown_expertise_raises() -> None:
    with pytest.raises(ValueError, match="unknown expertise"):
        compose_system_prompt(["teleportation"])


def test_sections_are_in_a_stable_order() -> None:
    prompt = compose_system_prompt()
    positions = [
        prompt.index(title)
        for title in (
            "# Persona",
            "# Production doctrine",
            "# Arrangement doctrine",
            "# Mixing doctrine",
            "# Sound design doctrine",
            "# Ableton Live",
        )
    ]
    assert positions == sorted(positions)
