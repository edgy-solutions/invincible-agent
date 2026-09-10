"""SEAL 1's OTHER HALF — a template's verbs must be REGISTERED, read from the mesh, not the file.

ADR-0050 acceptance 1 is *"a template referencing an undeclared verb FAILS AT MERGE"*. What the
CI job delivers is the **shape** gate: `verb: "not a verb iri"` is refused by the schema. That is
not the whole seal, and the gap is the expensive half — a template naming a well-formed verb that
**no engine serves** passes a file-only check, merges, and produces an empty panel at seed time.
That is this system's recurring shape: the row registers, reports accepted, and never matches.

WHY THIS CANNOT BE THE CI JOB. Verb existence is a fact about the running mesh, and the merge-time
job is hermetic by design (seconds, no cluster, no network — which is what earns it its
`pull_request` trigger). So seal 1 is honestly TWO checks in two places, and saying so is better
than pretending one covers both:

    shape      — schema, at merge, hermetic          .github/workflows/validate-canvas-templates.yml
    existence  — the mesh, where the mesh is reachable   THIS FILE

ELIGIBILITY IS A CONJUNCTIVE READ, AND CHECKING ONE SIDE IS THE DEFECT ITSELF. `principles/
select-from-authorized-set.md` states the mechanical form: *a verb is eligible only if it appears
in BOTH Neo4j and Weaviate.* A verb present in Neo4j alone is exactly the "registers, reports
accepted, never matches" failure — so this file asserts BOTH, and a one-sided pass is a failure
here rather than a green.

── THE NEGATIVE CONTROL IS NOT OPTIONAL ────────────────────────────────────────────────────────
A check that has only ever seen its expected answer has not been shown able to give another.
`test_the_checkers_can_say_no` runs a verb that cannot exist through the SAME code path and
requires it to come back absent. Without it, a query with a wrong label — which is precisely how
this file's first draft failed, returning a confident uniform NOT FOUND for all five verbs
because it matched `:Predicate` nodes in a graph whose verbs are RELATIONSHIP TYPES — reads as a
finding instead of a broken instrument.

── THE QUERIES AND CONTROLS NOW LIVE IN `tests/_mesh_verbs.py` ─────────────────────────────────
Extracted at the SECOND consumer (a ratified-graph-rows check needs the same probes), because
this repo has already paid for extracting at the third. **The controls moved WITH the queries,
and that is the design rather than a tidying choice.** The argument against sharing is that a
broken helper reddens two files and neither owns it — true for a helper extracted without its
controls, and it inverts once they come along:

    controls red                              -> the INSTRUMENT is broken; the helper owns it
    controls green, assertions below red      -> the DATA is bad; THIS file owns it

Copied controls are worse on both counts, because a copy can drift until it stops discriminating
and still passes — drift in a control is invisible by construction. What stays here: the
population (`template_verbs`) and every claim made about it, so a red still names a template.

── SKIPPING MUST NOT READ AS PASSING ───────────────────────────────────────────────────────────
Without a reachable mesh these tests SKIP. A skip is not a pass, and the CI job does not run
them, so nothing here should be cited as evidence the verbs exist unless it actually ran. The
recorded run is in `docs/plans/canvas-templates-slice-1.md`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests._mesh_verbs import (
    assert_checkers_can_say_no,
    missing_from_neo4j,
    needs_neo4j,
    needs_weaviate,
    not_eligible_in_weaviate,
    one_sided,
    unreachable_from_subject,
)

_ROOT = Path(__file__).resolve().parents[2]
_CANVAS_DIR = _ROOT / "policy" / "canvases"


# ── THE POPULATION — the only part that is this file's ──────────────────────────────────────
def template_verbs() -> list[tuple[str, str, str]]:
    """`(template_id, verb_iri, verb_local)` for every ratified template."""
    yaml = pytest.importorskip("yaml")
    out = []
    files = sorted(_CANVAS_DIR.glob("*.yaml"))
    assert files, "no ratified templates found — the glob or the directory moved"
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for panel in doc["panels"]:
            iri = panel["verb"]
            out.append((doc["template_id"], iri, iri.split(":", 1)[1]))
    return out


# ── THE CONTROLS — one shared implementation, PER STORE, run in THIS file's environment ─────
#
# SPLIT PER STORE, and the reason is a live near-miss rather than symmetry. The first version
# gated one control on BOTH stores. Tonight Weaviate is down and Neo4j is up, so that control
# SKIPPED while `test_every_template_verb_exists_in_neo4j` PASSED — a green with no control
# behind it, in exactly the degraded state a control exists for. A control must share its
# subject's gate, or partial availability silently buys back the vacuous pass.
@needs_neo4j
def test_the_neo4j_checker_can_say_no():
    """If this reddens, the Neo4j INSTRUMENT is broken and the Neo4j assertion below says
    nothing either way. Shared implementation with the ratified-graph consumer so it cannot
    drift in one of them; invoked here so it runs where this file's assertions run."""
    assert_checkers_can_say_no(neo4j=True, weaviate=False)


@needs_weaviate
def test_the_weaviate_checker_can_say_no():
    """Same, for the Weaviate half."""
    assert_checkers_can_say_no(neo4j=False, weaviate=True)


# ── THE ASSERTIONS — this file's claims about its own population ────────────────────────────
@needs_neo4j
def test_every_template_verb_exists_in_neo4j():
    missing = missing_from_neo4j(template_verbs())
    assert not missing, (
        "a ratified template names a verb the mesh does not serve. It would merge, seed, and "
        f"render an EMPTY panel: {missing}")


@needs_weaviate
def test_every_template_verb_is_registration_complete_in_weaviate():
    problems = not_eligible_in_weaviate(template_verbs())
    assert not problems, f"template verbs are not eligible on the Weaviate side: {problems}"


@needs_neo4j
@needs_weaviate
def test_eligibility_is_conjunctive():
    """BOTH stores, per select-from-authorized-set. A one-sided presence is the defect."""
    problems = one_sided(template_verbs())
    assert not problems, (
        "a template verb is present in one store and not the other — it will register, report "
        f"accepted, and never match: {problems}")


# ── REACHABILITY — seal 1's actual property, added 2026-09-10 ───────────────────────────────
@needs_neo4j
@needs_weaviate
def test_every_template_verb_is_reachable_from_its_subject():
    """A verb that EXISTS but no subject can walk to produces the same empty panel as a missing
    one, and `missing_from_neo4j` cannot see the difference — it asks a GLOBAL existence
    question (`CALL db.relationshipTypes()`).

    Added after run B: that global check passed for all eleven verbs while `/resolve` excluded
    every one of their subjects with `reason: "no_verb_in_scope"`. The edges turned out to be
    intact, so the pass was correct **by luck rather than by measurement**. This asks the
    question the router actually asks.
    """
    problems = unreachable_from_subject(template_verbs())
    assert not problems, (
        "a template verb exists as a relationship type but is unreachable from any subject it "
        f"is registered against — it would merge, seed, and render an EMPTY panel: {problems}")


@needs_neo4j
@needs_weaviate
def test_the_reachability_checker_can_say_no():
    """Its own control, sharing its subjects' gate. A verb that cannot exist must come back as a
    problem through the SAME code path, or a green above means only that the query ran."""
    problems = unreachable_from_subject([("control", "mesh:planNotAVerbAtAll", "planNotAVerbAtAll")])
    assert problems, (
        "the reachability check reported a fabricated verb as reachable — it is not "
        "discriminating, and every green it gives is vacuous")
