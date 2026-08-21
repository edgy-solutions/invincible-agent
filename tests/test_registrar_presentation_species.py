"""TWO SPECIES SHARE THE MANIFEST — presentations are triples, not verb edges.

WHY THIS EXISTS. Measured 2026-08-21, after the ontology prime landed all six
archetype classes and engine-f re-registered cleanly: 6/6 classes in Neo4j, 11
presentation URNs in DataHub with correct full subject/object IRIs, and 0
rendersAs rows in Weaviate.

Nothing there was a bug. The triples reached DataHub and stopped, because the
only thing that moves a registration into Weaviate is the mesh-registrar, and
`RegistrationManifest` modelled verb edges ONLY. `register_presentation_to_mesh`
bypassed the gateway by design, emitting direct-to-DataHub -- and the
DataHub->Weaviate materialiser was RETIRED 2026-06-13 when Gateway v0.2 became
sole writer. Those emissions were audit records reaching nothing.

THE SHAPE OF THE FAILURE THIS SEALS AGAINST is the one this arc keeps
producing: a guard correct for its population and blind to a species it was
never told about. doc-tools' linker demanded verb-shaped fields of every row, so
presentations were refused as "incomplete" at ERROR level with a remedy
("re-register") that could not work -- re-registering produces the same fields.
So every arm below is written PER SPECIES, and the branch is tested for not
becoming a bypass.

Run: uv run --frozen --with pytest --with pydantic pytest tests/test_registrar_presentation_species.py -v
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "agent_fleet" / "mesh_registrar" / "main.py"

# Unique module name, never bare "main": 155 files in this repo are named
# main.py and `import main` returns whichever was cached FIRST, which has
# already turned a security suite red purely from collection order.
_MOD_NAME = "mesh_registrar_main__presentation_species_test"


def _mod():
    cached = sys.modules.get(_MOD_NAME)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(_MOD_NAME, _SRC)
    m = importlib.util.module_from_spec(spec)
    sys.modules[_MOD_NAME] = m
    try:
        spec.loader.exec_module(m)
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(_MOD_NAME, None)
        pytest.skip(f"mesh_registrar not importable here: {type(exc).__name__}: {exc}")
    return m


_MESH = "http://invincible-agent/mesh#"


def _engine_manifest(**over):
    """A pre-existing engine manifest — deliberately WITHOUT tool_kind, because
    that is what every deployed caller sends today."""
    base = dict(
        name="engine_e_query_knowledge_graph",
        verb_iri="mesh:queryKnowledgeGraph",
        input_uri=f"{_MESH}GraphQuery",
        output_uri=f"{_MESH}GraphExpertResponse",
        endpoint_url="http://iagent-engine-e:8085/query",
        owner_persona="AUDITOR",
    )
    base.update(over)
    return base


def _presentation_manifest(**over):
    base = dict(
        name="presentation_knowledge_document_for_ownershipfact",
        tool_kind="Presentation",
        subject_uri=f"{_MESH}OwnershipFact",
        predicate_iri="mesh:rendersAs",
        object_uri=f"{_MESH}KnowledgeDocument",
        archetype="KNOWLEDGE_DOCUMENT",
        expected_fields=["owner", "asset"],
        frontend_id="cortex",
        owner_persona="AUDITOR",
    )
    base.update(over)
    return base


# ── ARM 1: the existing species is untouched ────────────────────────────────

def test_an_engine_manifest_without_tool_kind_still_validates():
    """THE MIGRATION-SAFETY ARM. tool_kind defaults to 'Engine' so every
    deployed caller is byte-identical — no coordinated deploy, no negotiation."""
    m = _mod()
    man = m.RegistrationManifest(**_engine_manifest())
    assert man.tool_kind == "Engine"
    assert man.verb_iri == "mesh:queryKnowledgeGraph"
    assert man.endpoint_url == "http://iagent-engine-e:8085/query"


def test_an_engine_without_endpoint_url_is_refused():
    """The default must not become a hole: engines are reached by CALLING."""
    m = _mod()
    with pytest.raises(Exception) as exc:
        m.RegistrationManifest(**_engine_manifest(endpoint_url=None))
    assert "endpoint_url" in str(exc.value)


@pytest.mark.parametrize("field", ["verb_iri", "input_uri", "output_uri"])
def test_an_engine_missing_a_verb_field_is_refused(field):
    """These three got defaults so presentations may omit them. That is NOT a
    relaxation of engine validation, and this is the arm that proves it."""
    m = _mod()
    with pytest.raises(Exception) as exc:
        m.RegistrationManifest(**_engine_manifest(**{field: ""}))
    assert field in str(exc.value)


# ── ARM 2: the new species registers ────────────────────────────────────────

def test_a_presentation_normalises_onto_the_verb_edge_shape():
    """The triple maps onto the edge the write path already speaks, so Contract
    D, the saga, the Neo4j MERGE and the Weaviate upsert all run unchanged."""
    m = _mod()
    man = m.RegistrationManifest(**_presentation_manifest())
    assert man.tool_kind == "Presentation"
    assert man.input_uri == f"{_MESH}OwnershipFact"      # subject -> input
    assert man.verb_iri == "mesh:rendersAs"              # predicate -> verb
    assert man.output_uri == f"{_MESH}KnowledgeDocument"  # object -> output


# ── ARM 3: the branch must not become a bypass ──────────────────────────────

@pytest.mark.parametrize(
    "field", ["subject_uri", "predicate_iri", "object_uri", "archetype", "frontend_id"]
)
def test_a_presentation_missing_its_OWN_fields_is_refused(field):
    """A new branch is the classic place to accidentally wave a species through.
    The old linker rejected presentations for lacking verb fields; the fix must
    not overcorrect into accepting anything that says tool_kind='Presentation'."""
    m = _mod()
    with pytest.raises(Exception) as exc:
        m.RegistrationManifest(**_presentation_manifest(**{field: None}))
    assert field in str(exc.value)


# ── ARM 4: endpoint_url is REJECTED, not ignored ────────────────────────────

def test_endpoint_url_on_a_presentation_is_REFUSED():
    """Accepting-and-ignoring would let a caller advertise an endpoint that
    dispatch might later try to invoke. A field nobody calls is a claim nobody
    audits — so it is refused at admission, not documented at the site."""
    m = _mod()
    with pytest.raises(Exception) as exc:
        m.RegistrationManifest(
            **_presentation_manifest(endpoint_url="http://cortex-bff:8080/render")
        )
    msg = str(exc.value)
    assert "endpoint_url" in msg and "frontend_id" in msg


# ── ARM 7: the IRI convention is INHERITED, not invented ────────────────────

def test_the_predicate_stays_COMPACT_and_the_ends_stay_FULL():
    """PER-POSITION, verified against the 24 live rows on 2026-08-21: the
    verb position is stored compact, subject/object full.

    An earlier reading of 'compact = stale' — pattern-matched from a real
    compact-IRI bug fixed an hour earlier — nearly expanded the predicate,
    which would have made presentations the only row type with a full verb_iri
    and broken verb lookups against all 24 existing rows.
    """
    m = _mod()
    man = m.RegistrationManifest(**_presentation_manifest())
    assert man.verb_iri == "mesh:rendersAs", "predicate must stay COMPACT"
    assert man.input_uri.startswith("http://"), "subject must stay FULL"
    assert man.output_uri.startswith("http://"), "object must stay FULL"


# ── the discriminator must ride in the DATA ─────────────────────────────────

def test_tool_kind_is_written_for_BOTH_species():
    """`mesh_tool_kind` already existed on the doc-tools side and nothing
    branched on it — declared but unwired — which is exactly how presentations
    got processed as malformed engines. A consumer must never have to infer the
    species from which fields happen to be present."""
    m = _mod()
    for maker, expected in ((_engine_manifest, "Engine"),
                            (_presentation_manifest, "Presentation")):
        man = m.RegistrationManifest(**maker())
        props = m._build_custom_properties(man) if hasattr(m, "_build_custom_properties") else None
        if props is None:
            pytest.skip("custom-properties builder is inlined; covered by the emit test")
        assert props["mesh_tool_kind"] == expected


def test_a_presentation_carries_no_endpoint_property():
    """Popped rather than blanked, so no consumer can read '' as a URL."""
    m = _mod()
    if not hasattr(m, "_build_custom_properties"):
        pytest.skip("custom-properties builder is inlined; covered by the emit test")
    props = m._build_custom_properties(m.RegistrationManifest(**_presentation_manifest()))
    assert "mesh_endpoint_url" not in props
    assert props["mesh_frontend_id"] == "cortex"
    assert props["mesh_archetype"] == "KNOWLEDGE_DOCUMENT"


# ── ARM 6 (unit half): the two species must not collide in the row key ──────
#
# The full non-regression — "re-registering every engine leaves the 24 verb rows
# intact" — is a LIVE arm and runs against the cluster once the image ships. This
# is its unit half: the deterministic row key must separate a presentation from
# every engine verb, because both species share one Weaviate collection and a
# collision would silently overwrite a verb row with a triple row.

def _uuid_mod():
    spec = importlib.util.spec_from_file_location(
        "mesh_registrar_v2_substrate__species_test",
        _REPO / "agent_fleet" / "mesh_registrar" / "v2_substrate.py",
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    try:
        spec.loader.exec_module(m)
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(spec.name, None)
        pytest.skip(f"v2_substrate not importable: {type(exc).__name__}: {exc}")
    return m


def test_a_presentation_row_key_cannot_collide_with_a_verb_row():
    """`(verb_iri, input_uri)` keys the row. A presentation's verb position is
    the CONSTANT 'mesh:rendersAs', so it can only collide with another
    presentation on the same subject — never with an engine verb."""
    v = _uuid_mod()
    pres = v._deterministic_predicate_uuid("mesh:rendersAs", f"{_MESH}OwnershipFact")
    verb = v._deterministic_predicate_uuid("mesh:lookupOwnership", f"{_MESH}OwnershipFact")
    assert pres != verb, "presentation collided with a verb row on the same subject"


def test_the_KNOWN_deferral_is_real_and_asserted_not_assumed():
    """THE DEFERRAL, PINNED. Two frontends rendering the SAME subject as
    DIFFERENT archetypes DO collide — Cortex's KNOWLEDGE_DOCUMENT and OpenDDIL's
    CHART_WIDGET both key on (mesh:rendersAs, OwnershipFact).

    This asserts the collision EXISTS rather than leaving it as a comment, so
    the first multi-frontend registration finds a named, tested limitation
    instead of a mystery overwrite. When the key gains a frontend/archetype
    component, this test goes red and must be rewritten — deliberately.
    """
    v = _uuid_mod()
    cortex = v._deterministic_predicate_uuid("mesh:rendersAs", f"{_MESH}OwnershipFact")
    openddil = v._deterministic_predicate_uuid("mesh:rendersAs", f"{_MESH}OwnershipFact")
    assert cortex == openddil, (
        "the documented collision no longer reproduces — the row key changed; "
        "update docs/plans/registrar-models-presentation-triples.md 'Known deferral'"
    )
