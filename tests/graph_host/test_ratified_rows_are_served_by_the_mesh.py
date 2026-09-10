"""B2 — a graph is reachable because a ratified row admitted it, asserted from the MESH.

ADR-0046 §2 refuses `run_any_graph`, and `agent_fleet/graph_host/` makes that structural: the
host learns a graph exists only from a ratified row. **That is a claim about the host's files.
This file is the other half — the claim about what is REACHABLE**, read from the mesh rather
than from the policy directory, because a file-derived population answers "what did we intend"
and the question is "what can be routed to".

Two directions, and the second is the refusal itself:

  every ratified row IS served          a row that registers nothing is a verb nobody can route
  nothing engine-lg serves is UNRATIFIED   a verb reachable without a row is `run_any_graph`
                                           reconstructed at runtime

The probes come from `tests/_mesh_verbs.py`, extracted at this consumer. **Share how to ask,
never what to conclude** — the population and every assertion below are this lane's, so a red
here names a ratified graph row and a red in the template seal names a template.

── THREE WAYS THIS FILE COULD LIE, AND WHAT STOPS EACH ─────────────────────────────────────

**1. A uniform absent from an instrument.** Eligibility is a CONJUNCTIVE read and each store
holds verbs differently: in Neo4j they are RELATIONSHIP TYPES and there is no `Predicate` node
label; in Weaviate `Predicate` IS a real class. A count of 0 from a label that does not exist is
indistinguishable from a count of 0 from an empty one. The helper queries each store the way
that store holds them, and `assert_checkers_can_say_no` puts a fabricated verb through the same
code path.

**2. A control that skips while its subject passes.** The controls here are called PER STORE
with that store's own gate. A single control gated on both stores skips the moment either is
unavailable — and then the surviving one-store assertion passes with no control behind it, in
exactly the degraded state a control exists for. That is not hypothetical: it happened during
the outage that preceded this file.

**3. A TRUE-AND-USELESS assertion — the one this file had to invent a guard for.** Before
engine-lg is deployed, `finProgramBrief` is absent from the mesh. That absent is *correct*, is
not an instrument artifact, and is not a defect: it is an assertion made before the thing it
asserts about exists, and it is true today and false after a step already scheduled. Reporting
it as a finding would be noise indistinguishable from a real regression. So the seal is gated on
the host actually SERVING, not on the substrate alone — and the gate is a RESPONSE, not a status
field, because a pod reporting `1/1 Running` on a wedged node refuses connections while every
status field reads healthy.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests._mesh_verbs import (
    assert_checkers_can_say_no,
    missing_from_neo4j,
    needs_neo4j,
    needs_weaviate,
    not_eligible_in_weaviate,
    one_sided,
    weaviate_predicates,
)

_ROOT = Path(__file__).resolve().parents[2]
_POLICY = Path(os.environ.get("GRAPH_POLICY_DIR", _ROOT / "policy" / "graphs"))
_GRAPH_HOST_URL = os.environ.get("GRAPH_HOST_URL")


def _host_answers() -> bool:
    """THE GATE IS A RESPONSE, not a status field.

    A pod on a node whose container runtime has wedged reports `1/1 Running` and refuses
    connections; three of its node's four conditions read healthy at the same time. The only
    thing that survived that state was asking a question and getting an answer.
    """
    if not _GRAPH_HOST_URL:
        return False
    try:
        with urllib.request.urlopen(f"{_GRAPH_HOST_URL.rstrip('/')}/health", timeout=10) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


needs_engine_lg = pytest.mark.skipif(
    not _host_answers(),
    reason=("engine-lg is not serving (set GRAPH_HOST_URL and roll it). Before it is deployed a "
            "ratified verb is absent CORRECTLY — asserting that would be true and useless"),
)


def ratified_population() -> list[tuple[str, str, str]]:
    """`(graph_id, verb_iri, verb_local)` for every ratified row. THIS LANE'S population.

    Read through the SDK's loader rather than by parsing yaml here, so the seal quantifies over
    exactly what the host would admit — including composition — and not over a second reading of
    the same directory that could disagree with it.
    """
    from iagent_mesh.graph_manifest import load_manifests

    rows = load_manifests(_POLICY)
    assert rows, (
        f"no ratified rows in {_POLICY} — the population is empty, so every assertion below "
        f"passes by having nothing to check. Instrument, not a clean bill."
    )
    return [(m.graph_id, m.verb, m.verb.split(":", 1)[1]) for m in rows]


# ── CONTROLS, ONE PER STORE, EACH SHARING ITS SUBJECT'S GATE ────────────────────────────────

@needs_neo4j
def test_the_neo4j_checker_can_say_no():
    assert_checkers_can_say_no(neo4j=True, weaviate=False)


@needs_weaviate
def test_the_weaviate_checker_can_say_no():
    assert_checkers_can_say_no(neo4j=False, weaviate=True)


def test_the_population_is_not_empty():
    """Runs unconditionally: it needs no mesh, and every mesh assertion is vacuous without it."""
    assert ratified_population()


# ── THE SEAL: every ratified row is reachable ───────────────────────────────────────────────

@needs_engine_lg
@needs_neo4j
def test_every_ratified_row_is_a_verb_in_neo4j():
    missing = missing_from_neo4j(ratified_population())
    assert not missing, (
        "a ratified row admitted a graph the mesh cannot route to. The host serves it, the "
        "policy directory declares it, and no verb edge exists — so the row registers, reports "
        "accepted, and never matches:\n  " + "\n  ".join(f"{g}: {v}" for g, v in missing)
    )


@needs_engine_lg
@needs_weaviate
def test_every_ratified_row_is_eligible_in_weaviate():
    missing = not_eligible_in_weaviate(ratified_population())
    assert not missing, (
        "a ratified row is absent or incomplete in Weaviate's Predicate class. Eligibility is "
        "conjunctive, so this verb cannot be selected however healthy Neo4j looks:\n  "
        + "\n  ".join(f"{g}: {v}" for g, v, _ in missing)
    )


@needs_engine_lg
@needs_neo4j
@needs_weaviate
def test_no_ratified_row_is_one_sided():
    """The hardest of the three to diagnose from a symptom, which is why it is its own test."""
    sided = one_sided(ratified_population())
    assert not sided, (
        "a ratified row is present in ONE store only — it registers, reports accepted, and "
        "never matches. Nothing goes red anywhere else:\n  "
        + "\n  ".join(f"{g}: {v}" for g, v, _ in sided)
    )


# ── THE REFUSAL, VERIFIED FROM THE MESH RATHER THAN THE FILESYSTEM ──────────────────────────

@needs_engine_lg
@needs_weaviate
def test_nothing_engine_lg_serves_is_unratified():
    """ADR-0046 §2, asserted where it matters: from what is REACHABLE.

    The host refusing to load an unratified module is a claim about its own files. This asks
    the registry instead — every verb whose endpoint points at engine-lg must correspond to a
    ratified row. A verb reachable without one is `run_any_graph` reconstructed at runtime,
    whatever the code says, and it is exactly what a stale registration after a row is deleted
    would look like.
    """
    ratified_verbs = {local for _g, _iri, local in ratified_population()}
    serving = {
        local: p for local, p in weaviate_predicates().items()
        if "engine-lg" in (p.get("endpoint_url") or "")
    }
    assert serving, (
        "no verb in the registry points at engine-lg — instrument or an unrolled host, not "
        "evidence that nothing unratified is served"
    )
    unratified = sorted(set(serving) - ratified_verbs)
    assert not unratified, (
        "engine-lg serves verbs that NO ratified row admits. Either a row was deleted without "
        "the registration being compensated, or something registered outside the manifest "
        "path — which is the refusal ADR-0046 §2 exists to make structural:\n  "
        + "\n  ".join(unratified)
    )
