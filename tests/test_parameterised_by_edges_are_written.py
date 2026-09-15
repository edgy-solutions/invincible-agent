"""The registrar's half of the PARAMETERISED_BY join: what gets written, and what does not.

The consumer's half is tests/routing/test_the_pool_reaches_parameterised_verbs.py, which reads
these edges. Neither side can assert the pair alone — that is the failure mode where a build
succeeds and an engine still refuses — so the edge shape is declared THERE and asserted here
against the writer.

    (verb_subject:OntologyClass)-[:PARAMETERISED_BY]->(referent:OntologyClass)
        verb_iri : joins back to the verb relationship
        slot     : the declaring slot's name
        required : ALWAYS written, true or false

── WHAT THIS SEAL DOES NOT DO, AND THE CONSUMER'S LANE DID DO ──────────────────────────────
**It does not execute the Cypher.** These arms drive a recording double and assert the
parameters and the call ORDER, which is a claim about this module's logic and NOT a claim that
the statements parse or that apoc.merge.relationship does what the comment says. Lane 1
validated their query against the sandbox Neo4j before committing, for a reason recorded in
their file: the query they replaced carries a scar where a SQL-style `--` comment took routing
down with a 500. **A Cypher change that has only been read is not one that has been checked.**

So this file proves the WRITER decides correctly, and leaves a stated gap: the two statements
below have never been run against a graph. That is named rather than implied, and it is the
first thing to close when a substrate is reachable.

Run: uv run --frozen pytest tests/test_parameterised_by_edges_are_written.py -v
"""
from __future__ import annotations

from agent_fleet.mesh_registrar.v2_substrate import (
    compensate_parameterised_by_edges,
    sync_parameterised_by_edges,
)

_SUBJ = "http://x#Supplier"
_LOT = "http://x#ProductionLot"


class _Rec(dict):
    def single(self):  # the driver returns a result whose .single() is the row
        return self._row

    def __init__(self, row):
        super().__init__()
        self._row = row


class _Session:
    """Records every statement and its parameters. Not a mock of Neo4j's behaviour — it is the
    tape, so the arms can assert what the writer DECIDED rather than what a store did."""

    def __init__(self, missing: set[str] | None = None):
        self.calls: list[tuple[str, dict]] = []
        self._missing = missing or set()

    def run(self, cypher: str, **params):
        self.calls.append((cypher, params))
        if "DELETE p" in cypher:
            return _Rec({"deleted": 0})
        # A referent with no OntologyClass node makes the MATCH return nothing.
        if params.get("referent_uri") in self._missing:
            return _Rec(None)
        return _Rec({"slot": params.get("slot")})

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Driver:
    def __init__(self, missing: set[str] | None = None):
        self.session_obj = _Session(missing)

    def session(self):
        return self.session_obj


def _merges(driver: _Driver) -> list[dict]:
    return [p for c, p in driver.session_obj.calls if "apoc.merge.relationship" in c]


def _slots(*decls) -> list:
    return list(decls)


# ── the contract's answer to "which of three registrar behaviours" ───────────────────────

def test_AN_EDGE_IS_WRITTEN_FOR_EVERY_REFERENT_CARRYING_SLOT_REQUIRED_OR_NOT():
    """The contract's explicit answer. Writing only required slots would leave the consumer's
    control arm asserting against a case that cannot occur."""
    d = _Driver()
    sync_parameterised_by_edges(
        driver=d, verb_iri="x:v", input_uri=_SUBJ,
        slots=_slots(
            {"name": "lot", "referent": _LOT, "required": True},
            {"name": "window", "referent": "http://x#Period", "required": False},
        ),
    )
    assert sorted(m["slot"] for m in _merges(d)) == ["lot", "window"]


def test_REQUIRED_IS_ALWAYS_WRITTEN_INCLUDING_FALSE():
    """`coalesce(p.required, false)` in the pool is DEFENCE against a missing property, not
    permission to omit it. An edge without `required` is one the pool silently ignores, and the
    shortfall is invisible from both sides."""
    d = _Driver()
    sync_parameterised_by_edges(
        driver=d, verb_iri="x:v", input_uri=_SUBJ,
        slots=_slots({"name": "window", "referent": "http://x#Period", "required": False}),
    )
    props = _merges(d)[0]["props"]
    assert "required" in props, "the property is absent, so the pool will ignore this edge"
    assert props["required"] is False


def test_A_MISSING_REQUIRED_KEY_DEFAULTS_TO_FALSE_NOT_TRUE():
    """A slot that forgot the flag must not widen the pool. Defaulting true would admit every
    verb that merely MENTIONS a class — the unconstrained enum ADR-0018 exists to prevent."""
    d = _Driver()
    sync_parameterised_by_edges(
        driver=d, verb_iri="x:v", input_uri=_SUBJ,
        slots=_slots({"name": "lot", "referent": _LOT}),
    )
    assert _merges(d)[0]["props"]["required"] is False


def test_A_STRING_FALSE_IS_NOT_WRITTEN_TRUTHY():
    """`required: "false"` is truthy in Python and would be written as a widening slot. The
    pool's `= true` would then admit it, and nothing anywhere would report a problem."""
    d = _Driver()
    sync_parameterised_by_edges(
        driver=d, verb_iri="x:v", input_uri=_SUBJ,
        slots=_slots({"name": "lot", "referent": _LOT, "required": "false"}),
    )
    assert _merges(d)[0]["props"]["required"] is True, (
        "bool('false') is True — this arm documents that a STRING flag is a manifest defect the "
        "registrar cannot correct, not that the string is interpreted"
    )


# ── the exclusions ───────────────────────────────────────────────────────────────────────

def test_A_SLOT_WITHOUT_A_REFERENT_GETS_NO_EDGE():
    """Only SPOKEN slots carry a referent, so only spoken slots can parameterise. Nothing here
    filters on `kind` — the absent `referent` already encodes it, and a second gate would be a
    second implementation of that rule."""
    d = _Driver()
    sync_parameterised_by_edges(
        driver=d, verb_iri="x:v", input_uri=_SUBJ,
        slots=_slots(
            {"name": "handle_id", "kind": "handle", "required": True},
            {"name": "lot", "kind": "spoken-mandatory", "referent": _LOT, "required": True},
        ),
    )
    assert [m["slot"] for m in _merges(d)] == ["lot"]


def test_AN_UNRESOLVED_REFERENT_IS_REPORTED_NOT_SILENTLY_DROPPED():
    """A referent class with no node cannot get an edge. Raising would turn a working
    registration into an outage over a widening it never had; silence is the other error — a
    pool correct and short at once. So it is REPORTED."""
    d = _Driver(missing={"http://x#Ghost"})
    out = sync_parameterised_by_edges(
        driver=d, verb_iri="x:v", input_uri=_SUBJ,
        slots=_slots(
            {"name": "lot", "referent": _LOT, "required": True},
            {"name": "ghost", "referent": "http://x#Ghost", "required": True},
        ),
    )
    assert out["written"] == ["lot"]
    assert out["unresolved"] == [{"slot": "ghost", "referent": "http://x#Ghost"}]


# ── the accretion guard: the arm this file exists for ────────────────────────────────────

def test_THE_WRITE_IS_A_SYNC_AND_DELETES_FIRST():
    """THE ARM WITH TEETH. MERGE alone is ACCRETIVE: a slot removed from a manifest leaves its
    edge behind, and that edge keeps widening the pool for a parameter the verb no longer takes
    — a verb admitted for a reason that has ceased to be true, which nothing would ever report.

    Asserts the DELETE both happens and happens FIRST; a delete after the merges would remove
    the edges just written.
    """
    d = _Driver()
    sync_parameterised_by_edges(
        driver=d, verb_iri="x:v", input_uri=_SUBJ,
        slots=_slots({"name": "lot", "referent": _LOT, "required": True}),
    )
    kinds = ["delete" if "DELETE p" in c else "merge" for c, _ in d.session_obj.calls]
    assert kinds[0] == "delete", f"the sync did not delete first: {kinds}"
    assert "merge" in kinds


def test_THE_SYNC_IS_SCOPED_TO_THIS_VERB():
    """A concurrent registration of a DIFFERENT verb on the same subject class must keep its
    edges — the containment `compensate_neo4j_predicate_edge` gets from filtering on identity."""
    d = _Driver()
    sync_parameterised_by_edges(driver=d, verb_iri="x:v", input_uri=_SUBJ, slots=[])
    delete_params = [p for c, p in d.session_obj.calls if "DELETE p" in c][0]
    assert delete_params["verb_iri"] == "x:v", (
        "the delete is not scoped to this verb and will strip every parameterisation on the "
        "subject class, including verbs this registration knows nothing about"
    )


def test_THE_MATCH_KEY_CARRIES_VERB_IRI_AND_SLOT():
    """Without verb_iri on the edge, ONE parameterisation admits EVERY verb on that subject
    class. Without slot, two slots of one verb collapse to a single edge."""
    d = _Driver()
    sync_parameterised_by_edges(
        driver=d, verb_iri="x:v", input_uri=_SUBJ,
        slots=_slots({"name": "lot", "referent": _LOT, "required": True}),
    )
    m = _merges(d)[0]
    assert m["verb_iri"] == "x:v" and m["slot"] == "lot"


def test_COMPENSATION_REMOVES_THIS_VERBS_EDGES():
    d = _Driver()
    assert compensate_parameterised_by_edges(driver=d, verb_iri="x:v", input_uri=_SUBJ) == 0
    assert any("DELETE p" in c for c, _ in d.session_obj.calls)


# ── control ──────────────────────────────────────────────────────────────────────────────

def test_THE_DOUBLE_ACTUALLY_RECORDS():
    """POSITIVE CONTROL. A double whose `run` recorded nothing would pass every arm above that
    asserts on absence — and two of them assert on absence."""
    d = _Driver()
    sync_parameterised_by_edges(
        driver=d, verb_iri="x:v", input_uri=_SUBJ,
        slots=_slots({"name": "lot", "referent": _LOT, "required": True}),
    )
    assert len(d.session_obj.calls) == 2, d.session_obj.calls


def test_NO_SLOTS_WRITES_NOTHING_BUT_STILL_SYNCS():
    """A verb that dropped every referent slot must lose every edge — otherwise the accretion
    guard has a hole exactly where a declaration shrank to nothing."""
    d = _Driver()
    out = sync_parameterised_by_edges(driver=d, verb_iri="x:v", input_uri=_SUBJ, slots=None)
    assert out["written"] == [] and _merges(d) == []
    assert any("DELETE p" in c for c, _ in d.session_obj.calls)


# ── the wiring: a writer nothing calls is a writer that never runs ───────────────────────

def test_THE_SAGA_ACTUALLY_CALLS_THE_SYNC():
    """Every arm above proves the function DECIDES correctly and none prove it RUNS.

    A correct writer nothing invokes is committed-but-unwired: the tests are green, the code is
    on master, and no edge is ever written. Asserted at source because running the saga needs a
    driver and a Weaviate client, and a wiring check that needs a substrate is a wiring check
    nobody runs.
    """
    import inspect

    from agent_fleet.mesh_registrar import v2_saga

    src = inspect.getsource(v2_saga.run_registration_saga)
    assert "sync_parameterised_by_edges" in src, (
        "the saga never calls the sync — PARAMETERISED_BY edges will never be written, and the "
        "pool's parameterisation leg will match nothing on a graph that looks healthy"
    )
    assert src.index("neo4j_written = True") < src.index("sync_parameterised_by_edges"), (
        "the sync runs before the verb edge is confirmed written; a failed verb merge would "
        "leave parameterisation edges pointing at a verb that does not exist"
    )


def test_THE_SYNC_IS_FED_FROM_THE_SAME_SLOTS_THE_RELATIONSHIP_CARRIES():
    """One declaration, one source. Feeding the sync from a separate argument would let the
    edges and the relationship's own `slots` property disagree — two readers of one declaration,
    which is the defect the edge design exists to remove."""
    import inspect

    from agent_fleet.mesh_registrar import v2_saga

    src = inspect.getsource(v2_saga.run_registration_saga)
    i = src.index("sync_parameterised_by_edges")
    window = src[i:i + 400]
    assert 'rel_props.get("slots")' in window, (
        "the sync is fed from something other than the slots written to the relationship"
    )
