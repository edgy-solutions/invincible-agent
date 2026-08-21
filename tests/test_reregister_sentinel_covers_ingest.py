"""REREGISTER SENTINEL SEAL — the wait must cover EVERY ontology it gates on.

WHAT WENT WRONG (2026-08-21). The helm hook chain sequences prime(10) ->
ontologySeed(15) -> reregister(20), and the chart calls that ordering "a
correctness invariant, not a tunable". But prime does not INGEST; it LAUNCHES
twelve async Dagster runs and exits. The reregister job knows this -- it waits
on a sentinel class before restarting the engines -- yet it waited on exactly
ONE uri, `idp#Dataset`, which prime launches 10th of 12. `mesh_system.ttl` is
launched 12th. So the sentinel went green while the mesh ingest was still
QUEUED, the engines restarted, engine-f registered its presentation triples
against archetype classes that did not exist yet, Contract D refused them
SILENTLY, and the substrate finished with 0 rendersAs rows.

Every job in the chain reported success. The only thing that reported the truth
was counting the rows.

THE SHAPE OF THE BUG is the one this repo keeps re-learning: a guard whose
POPULATION is a hand-picked stand-in rather than the thing it protects. Same
species as the archetype seal reading the capability table instead of a
hand-kept list. One sentinel cannot speak for twelve concurrent ingests.

WHAT THIS SEALS:
  * the sentinel list is plural and the wait requires ALL of it (a single-uri
    wait is what shipped the bug, so its return is what must go red);
  * it names a MESH archetype, not only an idp class -- the mesh ingest is the
    one that loses the race, so omitting it re-opens the exact hole;
  * every uri it names is ACTUALLY DECLARED in mesh_system.ttl. A sentinel
    naming a class that no longer exists never appears, so the wait burns its
    full 900s and then restarts anyway -- degrading silently back to the
    unguarded behaviour. This is the arm that keeps the seal honest when the
    ontology is renamed out from under it.

Run: uv run --frozen --with pytest pytest tests/test_reregister_sentinel_covers_ingest.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_JOB = _REPO / "helm" / "invincible-agent" / "templates" / "engine-reregister-job.yaml"
_VALUES = _REPO / "helm" / "invincible-agent" / "values.yaml"
_TTL = _REPO / "setup" / "ontologies" / "mesh_system.ttl"


def _sentinel_uris() -> list[str]:
    """The configured sentinel set, read from values.yaml as the chart renders it."""
    text = _VALUES.read_text(encoding="utf-8")
    m = re.search(r'^\s*sentinelUri:\s*"([^"]+)"', text, re.MULTILINE)
    assert m, "sentinelUri not found in values.yaml"
    return [s.strip() for s in m.group(1).split(",") if s.strip()]


def test_sentinel_set_is_plural():
    """A single sentinel is what shipped the race; its return must go red."""
    uris = _sentinel_uris()
    assert len(uris) >= 2, f"sentinel must cover >1 ontology, got {uris}"


def test_sentinel_covers_the_mesh_ontology():
    """mesh_system is launched LAST, so it is the ingest that loses the race.

    An idp-only sentinel is precisely the configuration that reported ready
    while the mesh classes were still queued.
    """
    uris = _sentinel_uris()
    assert any("/mesh#" in u for u in uris), f"no mesh sentinel in {uris}"


def test_the_wait_requires_ALL_sentinels_not_any():
    """`if n > 0: ready` over one uri is the bug. The wait must compute what is
    MISSING across the whole set and only proceed when nothing is."""
    src = _JOB.read_text(encoding="utf-8")
    assert 'os.environ["SENTINEL_URI"].split(",")' in src, "sentinel env is not parsed as a list"
    assert "missing = [u for u in sentinels if u not in found]" in src, "wait does not compute misses"
    assert "if not missing:" in src, "wait does not require the FULL set"


@pytest.mark.parametrize("uri", [u for u in _sentinel_uris() if "/mesh#" in u])
def test_every_mesh_sentinel_is_actually_declared(uri):
    """THE HONESTY ARM. A sentinel naming a class the TTL does not declare can
    never appear: the wait burns its timeout and restarts anyway, which is the
    unguarded behaviour wearing a guard's name."""
    local = uri.rsplit("#", 1)[-1]
    ttl = _TTL.read_text(encoding="utf-8")
    assert re.search(rf"\bmesh:{re.escape(local)}\b\s+a\s+owl:Class", ttl), (
        f"sentinel {uri} is not declared as an owl:Class in mesh_system.ttl"
    )
