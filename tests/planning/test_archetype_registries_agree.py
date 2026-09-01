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

# ⛔ THE SEAL READ ONE FILE AND REPORTED SIX FALSE GAPS (2026-08-31).
#
# `_TTL` was `mesh_system.ttl` alone. When Engine F's bindings landed, all six `fin:` subject
# ends read as undeclared — and every one of them IS declared, in
# `setup/ontologies/finance_extension.ttl`, and live in the graph. Engine F declares its own
# response shapes in its own namespace and its own file DELIBERATELY (a domain extension does
# not write into the platform namespace); the seal predated that and assumed one file.
#
# A seal that reports six gaps that do not exist is worse than one that reports none: it
# trains its reader to discount it, and the three REAL failures in the same run — the missing
# admission entries and the missing object-end classes — were sitting right beside them.
#
# DERIVED FROM THE PRIME MANIFEST, which is the authoritative statement of what actually gets
# seeded. A new domain extension is covered the day it is added to that list, with no edit
# here — the same remedy as test_service_enumerations_agree and
# test_mirror_covers_the_build_matrix: where the thing cannot be derived, derive the
# population it must cover.
def _seeded_ttls() -> list:
    manifest = (_ROOT / "setup" / "prime_databases.py").read_text(encoding="utf-8")
    rels = re.findall(r'"path":\s*"(ontologies/[^"]+\.ttl)"', manifest)
    assert rels, "prime_databases.py's ONTOLOGIES manifest parsed to nothing — regex is stale"
    return [_ROOT / "setup" / r for r in rels]
_MESH = "http://invincible-agent/mesh#"
_BINDINGS = _ROOT.parent / "cortex-ui" / "src" / "registry" / "assembleCapabilities.ts"

# One binding row: subject_uri -> object_uri. Both ends are what Contract D checks.
_ROW = re.compile(
    r'subject_uri:\s*"(?P<subject>[^"]+)"\s*,\s*\n\s*object_uri:\s*"(?P<object>[^"]+)"',
    re.MULTILINE,
)
# The archetype name a contract declares.
_ARCHETYPE = re.compile(r'archetype:\s*"(?P<name>[A-Z_]+)"')


def _seeded_graph():
    """Every seeded TTL parsed into one graph, so both the classes AND the prefix map come
    from the files rather than from this module's memory."""
    g = rdflib.Graph()
    for ttl in _seeded_ttls():
        if ttl.exists():
            g.parse(str(ttl), format="turtle")
    return g


def _declared_classes() -> set[str]:
    """Every owl:Class across the TTLs the prime actually seeds — not one file."""
    return {str(s) for s in _seeded_graph().subjects(RDF.type, OWL.Class)}


def _prefix_bindings() -> dict:
    """prefix -> {namespace IRIs it is bound to}, collected PER FILE.

    ⛔ DERIVED FROM A MERGED GRAPH IS WRONG HERE, and this is the third narrowness in one
    seal (2026-08-31). Collecting namespaces from one merged rdflib graph is LAST-BINDING-WINS:
    `product_structure_extension.ttl` binds `mesh:` to `http://internal/mesh#` while
    `mesh_system.ttl` and `finance_extension.ttl` bind it to `http://invincible-agent/mesh#`,
    so the merge silently produced the wrong namespace and EVERY `mesh:` row reported as
    undeclared — a hardcoded constant replaced by a more general derivation that was less
    correct.

    Per file, so a conflict is VISIBLE as a conflict rather than resolved by file order.
    """
    out: dict = {}
    for ttl in _seeded_ttls():
        if not ttl.exists():
            continue
        g = rdflib.Graph()
        g.parse(str(ttl), format="turtle")
        for prefix, ns in g.namespaces():
            if prefix:
                out.setdefault(prefix, set()).add(str(ns))
    return out


#: Prefixes this module knows authoritatively. A prefix bound two ways across the seeded set
#: is resolved HERE rather than by whichever file parsed last — and `test_no_seeded_prefix_is
#: _bound_two_ways` makes the conflict itself visible instead of letting this quietly paper
#: over it.
_AUTHORITATIVE = {"mesh": _MESH}


def _expand(iri: str) -> str:
    """`fin:Foo` -> the full IRI, using the prefixes the seeded TTLs actually declare."""
    if ":" not in iri or iri.startswith("http"):
        return iri
    prefix, _, local = iri.partition(":")
    if prefix in _AUTHORITATIVE:
        return f"{_AUTHORITATIVE[prefix]}{local}"
    bound = _prefix_bindings().get(prefix) or set()
    return f"{next(iter(bound))}{local}" if len(bound) == 1 else iri


def test_no_seeded_prefix_is_bound_two_ways():
    """One prefix, two namespaces, across files the prime seeds TOGETHER.

    FOUND 2026-08-31 by this seal's own prefix derivation. Not fatal to the bindings — TTL
    prefixes are file-local, so each file's classes resolve correctly — but it means the
    token `mesh:` denotes different things in different seeded files, and any tool that
    merges them (this seal did) silently picks one.

    xfail rather than a hard failure: `product_structure_extension.ttl` is another lane's and
    whether `http://internal/mesh#` is deliberate is theirs to rule. Recorded so it is a known
    fact rather than a surprise the next merger meets.
    """
    conflicts = {p: sorted(v) for p, v in _prefix_bindings().items() if len(v) > 1}
    if conflicts:
        pytest.xfail(f"prefix(es) bound to more than one namespace across seeded TTLs: "
                     f"{conflicts} — see docs/plans/, filed for the owning lane")


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
        f"binding subject_uri(s) with no owl:Class in any SEEDED ttl: {missing}.\n"
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
        f"binding object_uri(s) with no owl:Class in any SEEDED ttl: {missing}. "
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
