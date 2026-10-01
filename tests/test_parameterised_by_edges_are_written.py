"""The registrar's half of the PARAMETERISED_BY join: what gets written, and what does not.

The consumer's half is tests/routing/test_the_pool_reaches_parameterised_verbs.py, which reads
these edges. Neither side can assert the pair alone — that is the failure mode where a build
succeeds and an engine still refuses — so the edge shape is declared THERE and asserted here
against the writer.

    (verb_subject:OntologyClass)-[:PARAMETERISED_BY]->(referent:OntologyClass)
        verb_iri : joins back to the verb relationship
        slot     : the declaring slot's name (comma-joined when several slots name one referent)
        required : ALWAYS written, true or false

── WHERE EACH HALF IS PROVEN (since v0.9.5) ───────────────────────────────────────────────
The registrar no longer holds Cypher. It hands an identity, a filter and a payload to the SDK's
`MeshGraphWriter`, configured by `PARAMETERISED_BY_FAMILY`. So this file drives a RECORDING
WRITER in place of `v2_substrate._writer` and asserts what the registrar DECIDED — which
identity, which filter, which payload, which family, in which order. What the writer then does
with them is sealed in tests/test_mesh_writers_conform.py, offline against a driver double and
LIVE against a scratch label. The gap this file used to name — "the two statements have never
been run against a graph" — is closed there, not here.

Run: uv run --frozen pytest tests/test_parameterised_by_edges_are_written.py -v
"""
from __future__ import annotations

import pytest
from iagent_mesh.interfaces import EdgeIdentity, EdgeIdentityFilter, Initiator
from iagent_mesh.results import MeshResult
from iagent_mesh.write_results import MeshWriteResult

from agent_fleet.mesh_registrar import v2_substrate
from agent_fleet.mesh_registrar.v2_substrate import (
    ENDPOINT_ABSENT,
    PARAMETERISED_BY_FAMILY,
    compensate_parameterised_by_edges,
    sync_parameterised_by_edges,
)

_SUBJ = "http://x#Supplier"
_LOT = "http://x#ProductionLot"


class _Writer:
    """The tape. Not a model of Neo4j — it records what the registrar asked for, in order, and
    answers what the arm configures. `missing` referents answer the writer's ENDPOINT_ABSENT."""

    def __init__(self) -> None:
        self.calls: list = []
        self.families: list = []
        self.missing: set = set()
        self.existing = 0
        self.fail_with = None
        self.count_with = None

    def write_edge(self, initiator, *, identity, payload=None):
        self.calls.append(("write", initiator, identity, dict(payload or {})))
        if identity.object in self.missing:
            return MeshWriteResult.failed(f"{ENDPOINT_ABSENT}: no node for {identity.object}")
        return self.fail_with if self.fail_with is not None else MeshWriteResult.written()

    def delete_edges(self, initiator, *, identity_filter):
        self.calls.append(("delete", initiator, identity_filter, None))
        return MeshWriteResult.written()

    def has_edges(self, initiator, *, identity_filter):
        self.calls.append(("has", initiator, identity_filter, None))
        if self.count_with is not None:
            return self.count_with
        if not self.existing:
            return MeshResult.empty()
        return MeshResult.answered([{"key": "k"}] * self.existing)

    def kinds(self) -> list:
        return [c[0] for c in self.calls]

    def writes(self) -> list:
        return [c for c in self.calls if c[0] == "write"]


@pytest.fixture
def tape(monkeypatch):
    monkeypatch.setenv(v2_substrate.REGISTRAR_ON_BEHALF_OF_ENV, "registrar-owner")
    w = _Writer()

    def _writer(driver, family):
        w.families.append(family)
        return w

    monkeypatch.setattr(v2_substrate, "_writer", _writer)
    return w


def _sync(slots):
    return sync_parameterised_by_edges(
        driver=object(), verb_iri="x:v", input_uri=_SUBJ, tool_urn="urn:A", slots=slots)


# ── the contract's answer to "which of three registrar behaviours" ───────────────────────

def test_AN_EDGE_IS_WRITTEN_FOR_EVERY_REFERENT_CARRYING_SLOT_REQUIRED_OR_NOT(tape):
    """The contract's explicit answer. Writing only required slots would leave the consumer's
    control arm asserting against a case that cannot occur."""
    _sync([{"name": "lot", "referent": _LOT, "required": True},
           {"name": "window", "referent": "http://x#Period", "required": False}])
    assert sorted(c[3]["slot"] for c in tape.writes()) == ["lot", "window"]


def test_REQUIRED_IS_ALWAYS_WRITTEN_INCLUDING_FALSE(tape):
    """`coalesce(p.required, false)` in the pool is DEFENCE against a missing property, not
    permission to omit it. An edge without `required` is one the pool silently ignores, and the
    shortfall is invisible from both sides."""
    _sync([{"name": "window", "referent": "http://x#Period", "required": False}])
    payload = tape.writes()[0][3]
    assert "required" in payload, "the property is absent, so the pool will ignore this edge"
    assert payload["required"] is False


def test_A_MISSING_REQUIRED_KEY_DEFAULTS_TO_FALSE_NOT_TRUE(tape):
    """A slot that forgot the flag must not widen the pool. Defaulting true would admit every
    verb that merely MENTIONS a class — the unconstrained enum ADR-0018 exists to prevent."""
    _sync([{"name": "lot", "referent": _LOT}])
    assert tape.writes()[0][3]["required"] is False


def test_A_STRING_FALSE_IS_WRITTEN_TRUTHY_AND_THAT_IS_A_MANIFEST_DEFECT(tape):
    """`required: "false"` is truthy in Python and is written as a widening slot. This arm
    DOCUMENTS that a string flag is a manifest defect the registrar cannot correct — it does not
    interpret strings — so that a change to interpret them is a decision someone makes on purpose."""
    _sync([{"name": "lot", "referent": _LOT, "required": "false"}])
    assert tape.writes()[0][3]["required"] is True


# ── one edge per referent: what changed at the SDK writer, and why the pool cannot tell ──────

@pytest.mark.parametrize("first,second", [(True, False), (False, True)])
def test_TWO_SLOTS_NAMING_ONE_REFERENT_ARE_ONE_EDGE_REQUIRED_IF_EITHER_IS(tape, first, second):
    """The SDK writer keys an edge on its endpoints and `(verb, key)`, so the old per-slot match
    key cannot be expressed. The pool admits on `required = true` per edge, so the one collapsed
    edge must be required when ANY of its slots is — or a required slot would stop widening the
    pool the moment an optional slot shared its class.

    Both orders, because an `any` written as `last wins` passes one of them."""
    _sync([{"name": "b_lot", "referent": _LOT, "required": first},
           {"name": "a_lot", "referent": _LOT, "required": second}])
    (write,) = tape.writes()
    assert write[3] == {"slot": "a_lot,b_lot", "required": True}


def test_TWO_OPTIONAL_SLOTS_ON_ONE_REFERENT_STAY_OPTIONAL(tape):
    """THE CONTROL FOR THE ARM ABOVE: an aggregation that always answered true would pass it."""
    _sync([{"name": "b", "referent": _LOT, "required": False},
           {"name": "a", "referent": _LOT, "required": False}])
    (write,) = tape.writes()
    assert write[3] == {"slot": "a,b", "required": False}


# ── the exclusions ───────────────────────────────────────────────────────────────────────

def test_A_SLOT_WITHOUT_A_REFERENT_GETS_NO_EDGE(tape):
    """Only SPOKEN slots carry a referent, so only spoken slots can parameterise. Nothing here
    filters on `kind` — the absent `referent` already encodes it, and a second gate would be a
    second implementation of that rule."""
    _sync([{"name": "handle_id", "kind": "handle", "required": True},
           {"name": "lot", "kind": "spoken-mandatory", "referent": _LOT, "required": True}])
    assert [c[3]["slot"] for c in tape.writes()] == ["lot"]


def test_AN_UNRESOLVED_REFERENT_IS_REPORTED_NOT_SILENTLY_DROPPED(tape):
    """A referent class with no node cannot get an edge. Raising would turn a working
    registration into an outage over a widening it never had; silence is the other error — a
    pool correct and short at once. So it is REPORTED."""
    tape.missing = {"http://x#Ghost"}
    out = _sync([{"name": "lot", "referent": _LOT, "required": True},
                 {"name": "ghost", "referent": "http://x#Ghost", "required": True}])
    assert out["written"] == ["lot"]
    assert out["unresolved"] == [{"slot": "ghost", "referent": "http://x#Ghost"}]


@pytest.mark.parametrize("result,word", [
    (MeshWriteResult.failed("ClientError: no procedure apoc.merge.relationship"), "apoc"),
    (MeshWriteResult.unreachable("ServiceUnavailable: bolt down"), "unreachable"),
])
def test_ONLY_AN_ABSENT_ENDPOINT_IS_UNRESOLVED_ANY_OTHER_FAILURE_RAISES(tape, result, word):
    """THE CONTROL FOR THE ARM ABOVE. `unresolved` is keyed on the writer's ENDPOINT_ABSENT
    prefix; a store fault is ALSO not applied and must not be filed as a missing class, or an
    outage reads as a quiet shortfall in the widening. The saga catches the raise and logs it."""
    tape.fail_with = result
    with pytest.raises(RuntimeError, match=word):
        _sync([{"name": "lot", "referent": _LOT, "required": True}])


# ── the accretion guard: the arm this file exists for ────────────────────────────────────

def test_THE_WRITE_IS_A_SYNC_AND_DELETES_FIRST(tape):
    """THE ARM WITH TEETH. MERGE alone is ACCRETIVE: a slot removed from a manifest leaves its
    edge behind, and that edge keeps widening the pool for a parameter the verb no longer takes
    — a verb admitted for a reason that has ceased to be true, which nothing would ever report.

    Asserts the delete both happens and happens BEFORE any write; a delete after the writes
    would remove the edges just written.
    """
    _sync([{"name": "lot", "referent": _LOT, "required": True}])
    kinds = tape.kinds()
    assert "delete" in kinds and "write" in kinds, kinds
    assert kinds.index("delete") < kinds.index("write"), f"the sync did not delete first: {kinds}"


def test_THE_SYNC_IS_SCOPED_TO_THE_PROVIDER_PAIR_NOT_THE_VERB(tape):
    """THE DEFECT LANE 1 CAUGHT, and it was active rather than theoretical.

    ONE VERB CAN HAVE SEVERAL PROVIDERS: `mesh:finVarianceDrivers` is registered by
    `engine_fin_finance` from fin#Program AND by `engine_fin_finance_by_subject` from
    fin#ControlAccount, both declaring `program_id`. Scoped to verb_iri alone, the SECOND
    provider to register deletes the FIRST's parameterisation and writes only its own.

    Asserted on the WHOLE filter, not two of its fields: an extra binding narrows, a missing one
    widens, and only equality sees both.
    """
    _sync([])
    (delete,) = [c for c in tape.calls if c[0] == "delete"]
    assert delete[2] == EdgeIdentityFilter(subject=_SUBJ, verb="x:v", key="urn:A"), (
        "the delete is not scoped to (subject, verb, provider), so registering one provider of a "
        "multi-provider verb silently strips every other provider's parameterisation"
    )


def test_EVERY_WRITER_IS_THE_PARAMETERISED_BY_FAMILY(tape):
    """A correct filter on the wrong family deletes predicate edges. Asserted by identity, not
    equality, so a second dict that drifted from the one the live conformance arm proves cannot
    stand in for it."""
    _sync([{"name": "lot", "referent": _LOT, "required": True}])
    assert tape.families and all(f is PARAMETERISED_BY_FAMILY for f in tape.families)
    assert PARAMETERISED_BY_FAMILY["relationship_type"] == "PARAMETERISED_BY"
    assert PARAMETERISED_BY_FAMILY["verb_property"] == "verb_iri"
    assert PARAMETERISED_BY_FAMILY["key_property"] == "_tool_urn"


def test_THE_IDENTITY_CARRIES_VERB_AND_PROVIDER_AND_RUNS_SUBJECT_TO_REFERENT(tape):
    """Without verb_iri on the edge, ONE parameterisation admits EVERY verb on that subject
    class; without the provider, two providers' edges collapse. The writer sets both identity
    properties from the identity, so the payload must NOT carry them — the writer refuses a
    payload naming an identity field."""
    _sync([{"name": "lot", "referent": _LOT, "required": True}])
    (write,) = tape.writes()
    assert write[2] == EdgeIdentity(subject=_SUBJ, verb="x:v", object=_LOT, key="urn:A")
    assert set(write[3]) == {"slot", "required"}


def test_COMPENSATION_COUNTS_THEN_REMOVES_UNDER_ONE_SCOPE(tape):
    tape.existing = 2
    assert compensate_parameterised_by_edges(
        driver=object(), verb_iri="x:v", input_uri=_SUBJ, tool_urn="urn:A") == 2
    assert tape.kinds() == ["has", "delete"]
    assert tape.calls[0][2] == tape.calls[1][2] == EdgeIdentityFilter(
        subject=_SUBJ, verb="x:v", key="urn:A"), "the count and the delete disagree on scope"


def test_A_COUNT_THAT_CANNOT_BE_READ_RAISES_RATHER_THAN_COUNTING_ZERO(tape):
    """A zero from an unreachable store is the confident-empty answer `MeshResult` exists to
    prevent — and the delete must not run on a scope nobody could read."""
    tape.count_with = MeshResult.unreachable("bolt down")
    with pytest.raises(RuntimeError, match="unreachable"):
        compensate_parameterised_by_edges(
            driver=object(), verb_iri="x:v", input_uri=_SUBJ, tool_urn="urn:A")
    assert "delete" not in tape.kinds()


# ── the identity every call carries ──────────────────────────────────────────────────────

def test_EVERY_CALL_IS_MADE_AS_THE_REGISTRAR_DELEGATE(tape):
    _sync([{"name": "lot", "referent": _LOT, "required": True}])
    who = {c[1] for c in tape.calls}
    assert who == {Initiator(subject="mesh-registrar", kind="delegate",
                             on_behalf_of="registrar-owner")}, who


def test_AN_UNSET_DELEGATE_RAISES_BEFORE_ANYTHING_IS_TOUCHED(tape, monkeypatch):
    monkeypatch.delenv(v2_substrate.REGISTRAR_ON_BEHALF_OF_ENV)
    with pytest.raises(v2_substrate.RegistrarIdentityUnset):
        _sync([{"name": "lot", "referent": _LOT, "required": True}])
    assert tape.calls == []


# ── control ──────────────────────────────────────────────────────────────────────────────

def test_THE_TAPE_ACTUALLY_RECORDS(tape):
    """POSITIVE CONTROL. A tape that recorded nothing would pass every arm above that asserts on
    absence."""
    _sync([{"name": "lot", "referent": _LOT, "required": True}])
    assert tape.kinds() == ["has", "delete", "write"], tape.kinds()


def test_NO_SLOTS_WRITES_NOTHING_BUT_STILL_SYNCS(tape):
    """A verb that dropped every referent slot must lose every edge — otherwise the accretion
    guard has a hole exactly where a declaration shrank to nothing."""
    out = _sync(None)
    assert out["written"] == [] and tape.writes() == []
    assert "delete" in tape.kinds()


# ── the wiring: a writer nothing calls is a writer that never runs ───────────────────────

def test_THE_SAGA_ACTUALLY_CALLS_THE_SYNC():
    """Every arm above proves the function DECIDES correctly and none prove it RUNS.

    A correct writer nothing invokes is committed-but-unwired. Asserted at source because running
    the saga needs a driver and a Weaviate client, and a wiring check that needs a substrate is a
    wiring check nobody runs.
    """
    import inspect

    from agent_fleet.mesh_registrar import v2_saga

    src = inspect.getsource(v2_saga.run_registration_saga)
    assert "sync_parameterised_by_edges" in src, (
        "the saga never calls the sync — PARAMETERISED_BY edges will never be written"
    )
    assert src.index("neo4j_written = True") < src.index("sync_parameterised_by_edges"), (
        "the sync runs before the verb edge is confirmed written"
    )


def test_THE_SYNC_IS_FED_FROM_THE_SAME_SLOTS_THE_RELATIONSHIP_CARRIES():
    """One declaration, one source. Feeding the sync from a separate argument would let the
    edges and the relationship's own `slots` property disagree."""
    import inspect

    from agent_fleet.mesh_registrar import v2_saga

    src = inspect.getsource(v2_saga.run_registration_saga)
    i = src.index("sync_parameterised_by_edges")
    assert 'rel_props.get("slots")' in src[i:i + 400], (
        "the sync is fed from something other than the slots written to the relationship"
    )
