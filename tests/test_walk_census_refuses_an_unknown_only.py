"""`walk_census --only <id>` refuses an id that names no census row, before firing anything.

The filter used to drop it silently, so a run asked for four rows printed `3 pass, 0 fail`
and read as complete. The sample looked like the population.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO / "src"))

import walk_census  # noqa: E402


@pytest.fixture
def no_fire(monkeypatch):
    fired = []

    async def _run(rows, timeout_s):
        fired.append([r.id for r in rows])
        return []

    monkeypatch.setattr(walk_census, "_run", _run)
    monkeypatch.setattr(walk_census, "_deployed_sha", lambda: "test")
    return fired


def test_an_unknown_id_is_refused_and_nothing_is_fired(no_fire, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["walk_census", "--only", "docs-how-do-i-add-an-engine",
                                      "--only", "docs-how-do-i-roll-a-service-abstains"])
    assert walk_census.main() == 2
    assert no_fire == []
    assert "docs-how-do-i-roll-a-service-abstains" in capsys.readouterr().err


def test_known_ids_still_reach_the_fire(no_fire, monkeypatch):
    """The control: the refusal is about the unknown id, not about --only."""
    monkeypatch.setattr(sys, "argv", ["walk_census", "--only", "docs-how-do-i-add-an-engine",
                                      "--only", "docs-how-do-i-roll-a-service"])
    walk_census.main()
    assert no_fire and sorted(no_fire[0]) == ["docs-how-do-i-add-an-engine", "docs-how-do-i-roll-a-service"]
