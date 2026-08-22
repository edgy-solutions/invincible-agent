"""FOUR registries must know an archetype's name. This is the test that enumerates them.

THE SHAPE, MEASURED FOUR TIMES IN ONE ARC. A new archetype name must be told to N places, and
N kept being discovered AT RUNTIME, by a refusal, one place at a time:

  1. the ONTOLOGY            mesh_system.ttl — Contract D needs both triple ends declared
  2. the COMPONENT CONTRACT  a `.contract.ts` export beside the renderer
  3. the REGISTRY BINDING    DERIVED_BINDINGS, mapping subject_uri -> archetype
  4. the ADMISSION VOCAB     capability_admission.KNOWN_ARCHETYPES

Every miss was found by something REFUSING rather than by a check:

  2026-08-21  mesh:EffectSet, mesh:CoverageGapSet — no ontology class. Caught in a minute by
              test_planning_classes_are_declared, because that seal existed.
  2026-08-22  PERIOD_SERIES / THRESHOLD_GRID / MATRIX_GRID / DELTA_SET — refused at the
              admission door: "a frontend cannot advertise a render the backend has no name
              for." Registry 4 had never been enumerated.
  2026-08-22  GROUPED_REVIEW / APPROVAL_TASK — Contract D refused their SUBJECT ends. The
              archetypes were declared; their subjects were not.

Each guard was RIGHT and each fired at deploy time, after a commit, against a cluster. This
test moves all four checks to commit time, where a name costs nothing to add and everything to
discover late.

WHY IT LIVES WITH THE PLANNING TESTS RATHER THAN BESIDE THE ADMISSION MODULE. It asserts an
agreement ACROSS repos and layers, and the planning lane is where the cross-repo mirror already
lives (see test_planning_classes_are_declared's cross-repo note). Moving it later is fine;
having it is the point.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

rdflib = pytest.importorskip("rdflib", reason="ontology parsing needs rdflib")
from rdflib.namespace import OWL, RDF  # noqa: E402

sys.path.insert(0, str(_ROOT / "agent_fleet" / "presentation_agent"))
from capability_admission import KNOWN_ARCHETYPES  # noqa: E402

_TTL = _ROOT / "setup" / "ontologies" / "mesh_system.ttl"
_MESH = "http://invincible-agent/mesh#"
_BINDINGS = _ROOT.parent / "cortex-ui" / "src" / "registry" / "assembleCapabilities.ts"

# One binding row: subject_uri -> object_uri. Both ends are what Contract D checks.
_ROW = re.compile(
    r'subject_uri:\s*"(?P<subject>[^"]+)"\s*,\s*\n\s*object_uri:\s*"(?P<object>[^"]+)"',
    re.MULTILINE,
)
# The archetype name a contract declares.
_ARCHETYPE = re.compile(r'archetype:\s*"(?P<name>[A-Z_]+)"')


def _declared_classes() -> set[str]:
    g = rdflib.Graph()
    g.parse(str(_TTL), format="turtle")
    return {str(s) for s in g.subjects(RDF.type, OWL.Class)}


def _expand(iri: str) -> str:
    return iri.replace("mesh:", _MESH, 1) if iri.startswith("mesh:") else iri


def _binding_rows() -> list[tuple[str, str]]:
    if not _BINDINGS.is_file():
        pytest.skip("cortex-ui is not a sibling on disk; the cross-repo half cannot run here")
    text = _BINDINGS.read_text(encoding="utf-8")
    return [(m.group("subject"), m.group("object")) for m in _ROW.finditer(text)]


def _contract_archetypes() -> set[str]:
    d = _ROOT.parent / "cortex-ui" / "src" / "components"
    if not d.is_dir():
        pytest.skip("cortex-ui is not a sibling on disk")
    names: set[str] = set()
    for f in d.rglob("*.contract.ts"):
        names |= {m.group("name") for m in _ARCHETYPE.finditer(f.read_text(encoding="utf-8"))}
    return names


def test_the_populations_are_inhabited():
    """Positive control. Any of these coming back empty makes every assertion below pass over
    nothing — this file's own subject, applied to itself."""
    assert len(KNOWN_ARCHETYPES) >= 10, "the admission vocabulary shrank or moved"
    assert len(_declared_classes()) >= 30, "the ontology parse returned almost nothing"
    assert len(_binding_rows()) >= 10, "the DERIVED_BINDINGS regex matched almost nothing"


def test_every_bound_archetype_is_in_the_ADMISSION_VOCABULARY():
    """Registry 4. The miss that refused all four planning archetypes on 2026-08-22 —
    declared in the ontology, exported as contracts, bound in the registry, and unknown to the
    one gate that reads a registration."""
    missing = sorted(_contract_archetypes() - set(KNOWN_ARCHETYPES))
    assert not missing, (
        f"archetype(s) a component contract declares but capability_admission does not know: "
        f"{missing}.\nA registration naming them is REFUSED AT THE DOOR with "
        f"'a frontend cannot advertise a render the backend has no name for' — correctly. "
        f"Add them to KNOWN_ARCHETYPES."
    )


def test_every_binding_SUBJECT_end_is_a_declared_class():
    """Registry 1, subject side. The miss that refused GROUPED_REVIEW and APPROVAL_TASK:
    their archetypes were declared and their SUBJECTS were not, and Contract D checks both."""
    declared = _declared_classes()
    missing = sorted({s for s, _ in _binding_rows() if _expand(s) not in declared})
    assert not missing, (
        f"binding subject_uri(s) with no owl:Class in mesh_system.ttl: {missing}.\n"
        f"Contract D refuses the triple on its SUBJECT end and the rejection reads as "
        f"'gateway-rejected-REFUSED', which points at the registration rather than at the "
        f"missing declaration."
    )


def test_every_binding_OBJECT_end_is_a_declared_class():
    """Registry 1, object side. Already covered for the planning archetypes by
    test_planning_classes_are_declared; asserted here over the WHOLE binding table so a row
    added by anyone is checked, not just the ones this lane wrote."""
    declared = _declared_classes()
    missing = sorted({o for _, o in _binding_rows() if _expand(o) not in declared})
    assert not missing, (
        f"binding object_uri(s) with no owl:Class in mesh_system.ttl: {missing}. "
        f"Contract D refuses on the OBJECT end."
    )


def test_the_accidental_pass_is_named_so_it_stops_hiding_things():
    """WHY THE SUBJECT-END GAP STAYED INVISIBLE, pinned as a fact rather than a memory.

    `mesh:InstancesByProperty` and `mesh:WorkflowObservation` use the SAME IRI for subject and
    object, so declaring the archetype declared both ends BY ACCIDENT. Those two registered
    successfully on 2026-08-22 while GROUPED_REVIEW and APPROVAL_TASK were refused — and had
    all four shared that shape, nothing would have pointed at the subject end at all.

    This test does not forbid the shape; it asserts we still KNOW which rows have it, so a
    future all-green cannot be produced by coincidence again.
    """
    same = sorted({s for s, o in _binding_rows() if s == o})
    assert same, "no subject==object rows found — the regex or the table changed shape"
    # Not an assertion about correctness: a record that these rows prove less than the others.
    assert len(same) < len(_binding_rows()), (
        "EVERY binding now has subject == object. If that is real the subject-end check above "
        "can no longer fail, and it is proving nothing — re-derive it before trusting a green."
    )
