"""The declarations must reach the writer that ACTUALLY writes the graph.

WHY THIS FILE EXISTS, and it is the most expensive lesson of the arc. A projection request
was filed against `doc-tools`' `aitool_linker._build_relationship_properties`, the allowlist
where `mesh_slots` was found being silently dropped. That allowlist is real, the drop was
real — and the code path is **RETIRED**. ADR-0006 §Addendum (2026-06-13) made
`agent_fleet/mesh_registrar` the SOLE writer of predicate edges; doc-tools' sensor was
deactivated and kept only for a manual one-off re-sync.

The live edges prove it: every planning verb edge carries `_tool_urn`, `_input_uri` and
`_output_uri`, which only `v2_substrate.merge_neo4j_predicate_edge` sets, and its property
set matches `_build_rel_props_for_saga` exactly.

THIS REPO HAD ALREADY MEASURED THE SAME DEFECT. `RegistrationManifest`'s own comment:
*"presentations could not go through the gateway at all — they emitted direct-to-DataHub
while the DataHub->Weaviate materialiser was RETIRED, making those emissions audit records
that reached nothing. Measured 2026-08-21: 11 presentation URNs in DataHub, 0 rendersAs rows
in Weaviate."* `mesh_slots` was doing exactly that, eight days later.

So these tests pin the chain at the LIVE writer, by reading the actual functions rather than
trusting either allowlist to be the one that runs.
"""
from __future__ import annotations

import inspect
import json

import pytest

from agent_fleet.planning_agent.slots import slots_for
from iagent_pure.slot_acceptance import accept_slots


def _manifest(**over):
    from agent_fleet.mesh_registrar.main import RegistrationManifest
    base = dict(
        name="engine_p_plan_funding_gap",
        verb_iri="mesh:planFundingGap",
        input_uri="mesh:Portfolio",
        output_uri="mesh:ShortfallGrid",
        endpoint_url="http://engine-p:8000",
        owner_persona="PORTFOLIO_LEAD",
        domains=["PORTFOLIO_PLANNING"],
        cost_class="fast",
        requires_human_approval=False,
        version="0.1.0",
    )
    base.update(over)
    return RegistrationManifest(**base)


def test_the_gateway_manifest_accepts_slots():
    """Join 1 of the live chain. Additive and defaulted, so every existing caller is
    byte-identical."""
    pytest.importorskip("pydantic")
    decl = slots_for("plan_funding_gap")
    assert _manifest().slots == [], "the default must be empty"
    assert _manifest(slots=decl).slots == decl


def test_the_LIVE_allowlist_projects_slots_as_a_json_string():
    """Join 2, and THE GATE. `_build_rel_props_for_saga` is what lands on the Neo4j
    relationship — not doc-tools' `_build_relationship_properties`, which is retired.

    A STRING, because a Neo4j property may hold only primitives or arrays of primitives and
    `slots` is a list of maps. Measured against the sandbox graph in a rolled-back
    transaction: the list-of-maps form is rejected with
    `Neo.ClientError.Statement.TypeError`, the string form is accepted, and a list of
    strings (the `domains` control) is accepted."""
    from agent_fleet.mesh_registrar.main import _build_rel_props_for_saga

    decl = slots_for("plan_funding_gap")
    props = _build_rel_props_for_saga(
        manifest=_manifest(slots=decl), provider="engine_p", tool_urn="urn:li:mlModel:(x)"
    )
    assert isinstance(props["slots"], str), (
        "slots is not a string — the Neo4j write will raise TypeError for every verb "
        "that declares one"
    )
    assert json.loads(props["slots"]) == decl

    # Non-vacuity: `domains` next door IS a list, so this is not "everything is a string".
    assert isinstance(props["domains"], list)


def test_absent_slots_still_project_as_empty_rather_than_missing():
    """`[]` is what the guard reads as declare-nothing-accept-nothing. A MISSING key and an
    empty one must mean the same thing to the consumer, so the key is always written."""
    from agent_fleet.mesh_registrar.main import _build_rel_props_for_saga

    props = _build_rel_props_for_saga(
        manifest=_manifest(), provider="engine_p", tool_urn="urn:li:mlModel:(x)"
    )
    assert props["slots"] == "[]"
    assert accept_slots({"group_by": "initiative"}, props["slots"]).params == {}


def test_the_engine_side_manifest_carries_slots_to_the_GATEWAY_not_only_to_datahub():
    """THE DEFECT THIS FILE IS NAMED FOR, asserted structurally.

    `register_engine_to_mesh` has two exits: the mesh-registrar gateway (LIVE) and a
    direct-to-DataHub emit (AUDIT-ONLY FALLBACK, whose consumer is retired). Setting
    `mesh_slots` on the fallback while omitting it from the gateway call produces a
    registration that looks complete in DataHub and reaches the graph with nothing — the
    exact shape measured on 2026-08-21 as 11 URNs / 0 rows.

    Read out of the source so it cannot pass by a mock agreeing with itself."""
    from agent_fleet.utils import mesh_registration as mr

    sig = inspect.signature(mr._emit_to_registrar)
    assert "slots" in sig.parameters, "the gateway emitter cannot carry declarations at all"

    src = inspect.getsource(mr.register_engine_to_mesh)
    assert "slots=slots" in src, (
        "register_engine_to_mesh does not forward slots to the mesh-registrar gateway — "
        "the declarations reach only the retired DataHub path"
    )
    # ...and the fallback still carries them, so this is parity rather than a swap.
    assert "mesh_slots" in src


def test_the_retired_path_is_not_what_anyone_should_be_pinning():
    """A signpost, not a behaviour test. If doc-tools' linker ever becomes live again this
    fails and someone re-reads ADR-0006 §Addendum before assuming which writer runs."""
    from agent_fleet.mesh_registrar.main import _build_rel_props_for_saga

    doc = inspect.getdoc(_build_rel_props_for_saga) or ""
    assert "aitool_linker" in doc, (
        "the live builder no longer records that it MIRRORS the retired doc-tools "
        "allowlist — that note is the only thing connecting the two for a reader"
    )


# ─────────────────────────────────────────────────────────────────────────────
# THE SEVEN ENUMERATIONS — every hop that names properties one at a time
# ─────────────────────────────────────────────────────────────────────────────

def test_every_hop_that_enumerates_properties_names_slots():
    """A property reaches the router only if EVERY hop that lists field names lists this
    one, and a miss at any hop is indistinguishable from a verb that declares nothing.

    Seven hops were found by tracing the key, and four of them were discovered only after
    an earlier one had already been declared "the gate":

        1. doc-tools `_build_relationship_properties`      RETIRED, fixed anyway
        2. `RegistrationManifest`                          the engine->gateway body
        3. `_build_rel_props_for_saga`                     onto the Neo4j relationship
        4. the DataHub audit custom_props                  parity for the audit record
        5. `_FIND_COMPAT_VERBS_CYPHER` RETURN              the compat walk
        6. `CompatibleVerb`                                the response model
        7. the `CompatibleVerb(...)` constructor           row -> model

    Structural by necessity — 5-7 need a live Neo4j to exercise end to end, and the graph
    read that DID exercise them is a probe, not a test. What this pins is the property no
    unit test can: that no hop silently omits the key."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]

    eo = (root / "agent_fleet/ontology_service/main.py").read_text(encoding="utf-8")
    assert "AS slots" in eo, "hop 5: the compat-walk Cypher does not RETURN slots"
    assert "slots: str" in eo, "hop 6: CompatibleVerb does not declare slots"
    assert "slots=str(row.get(" in eo, "hop 7: the CompatibleVerb constructor drops slots"

    reg = (root / "agent_fleet/mesh_registrar/main.py").read_text(encoding="utf-8")
    assert "slots: List[dict]" in reg, "hop 2: RegistrationManifest does not accept slots"
    assert '"slots": json.dumps' in reg, "hop 3: rel_props does not carry slots to Neo4j"
    assert '"mesh_slots":' in reg, "hop 4: the DataHub audit record omits slots"

    mr = (root / "agent_fleet/utils/mesh_registration.py").read_text(encoding="utf-8")
    assert "slots=slots" in mr, "the engine does not forward slots to the LIVE gateway"


def test_the_response_model_default_is_the_dark_state():
    """An older engine that registers without declaring must produce `"[]"`, which the
    guard reads as declare-nothing-accept-nothing — never `None`, which would crash the
    decode, and never a missing attribute, which would crash the read."""
    # Engine O imports rdflib at module scope; present in its image, not every dev env.
    pytest.importorskip("rdflib")
    from agent_fleet.ontology_service.main import CompatibleVerb

    cv = CompatibleVerb(verb_iri="mesh:x", verb_local="x", input_uri="a", output_uri="b")
    assert cv.slots == "[]"
    assert accept_slots({"group_by": "initiative"}, cv.slots).params == {}
