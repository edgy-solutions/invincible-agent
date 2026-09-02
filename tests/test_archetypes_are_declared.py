"""Every archetype a presentation registers must be DECLARED in the ontology.

THE DEFECT THIS PREVENTS, measured 2026-08-21: ADR-0017 registers presentation
capabilities as (subject_uri, mesh:rendersAs, object_uri) where the object is an archetype
IRI. Those IRIs were referenced across the ADR, the capability table, and every registration
Engine F emits at startup -- and DECLARED NOWHERE. Contract D (ADR-0019) requires both triple
endpoints to pre-exist as :OntologyClass nodes and refuses to auto-MERGE them, so every
presentation registration was rejected on its object end. Correctly: the gate was right and
the declaration was missing.

Same species as mesh:DispositionReview -- a URI named by a registration and declared by
nothing. Green in every conversation, impossible in every fresh substrate, and invisible until
someone tried to use the path. THIS TEST IS THE GUARD THAT CASE DID NOT HAVE.

It reads the CAPABILITY TABLE, not a hand-kept list, so adding a capability with an
undeclared archetype fails here rather than at registration time in a cluster.

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/test_archetypes_are_declared.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

rdflib = pytest.importorskip("rdflib", reason="ontology parsing needs rdflib")
from rdflib.namespace import OWL, RDF, RDFS  # noqa: E402

from agent_fleet.presentation_agent.capabilities import (  # noqa: E402
    PRESENTATION_CAPABILITIES,
)

_MESH = rdflib.Namespace("http://invincible-agent/mesh#")

# ── WIDENED 2026-09-01: THIS SEAL WAS `mesh:`-ONLY AT BOTH ENDS ────────────────────────
#
# It read ONE file (`mesh_system.ttl`) and expanded ONE prefix (`mesh:`) — correct and
# indistinguishable from a general rule for as long as every capability was a `mesh:` one.
# Engine F (ADR-0045) registered the first `fin:` subjects and this seal reported all six as
# "registered but not declared" while they were declared, correctly, in
# `setup/ontologies/finance_extension.ttl` — a TTL the prime seeds and this test never read.
#
# A FALSE RED IS STILL A BROKEN SEAL. Had the finance classes genuinely been undeclared, this
# test could not have told anyone: it reports the same failure either way. It was measuring
# "is it in mesh_system.ttl", and calling that "is it declared".
#
# Both narrownesses are now derived rather than restated: the class set comes from the TTLs
# the PRIME MANIFEST actually seeds, and the prefix map comes from what those files bind.
_PRIME = _ROOT / "setup" / "prime_databases.py"


def _seeded_ttls() -> list:
    """The TTLs the prime actually seeds — the same derivation as
    tests/planning/test_archetype_registries_agree.py, and for the same reason."""
    rels = re.findall(r'"path":\s*"(ontologies/[^"]+\.ttl)"', _PRIME.read_text(encoding="utf-8"))
    assert rels, "prime_databases.py's ONTOLOGIES manifest parsed to nothing — regex is stale"
    return [_ROOT / "setup" / r for r in rels]


def _graph():
    g = rdflib.Graph()
    for ttl in _seeded_ttls():
        if ttl.exists():
            g.parse(str(ttl), format="turtle")
    return g


def _declared_classes(g):
    return {str(s) for s in g.subjects(RDF.type, OWL.Class)}


def _prefix_bindings() -> dict:
    """prefix -> {namespaces it is bound to}, collected PER FILE.

    ⛔ NOT from the merged graph. `product_structure_extension.ttl` binds `mesh:` to
    `http://internal/mesh#` while `mesh_system.ttl` binds it to `http://invincible-agent/mesh#`,
    so a merged read is last-binding-wins and would silently mark every `mesh:` row undeclared
    — a hardcoded constant replaced by a MORE GENERAL derivation that is LESS CORRECT. Per file,
    so a conflict stays visible as a conflict.
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


#: Resolved here rather than by whichever file parsed last.
_AUTHORITATIVE = {"mesh": str(_MESH)}


def _expand(compact: str) -> str:
    """`mesh:ChartWidget` / `fin:BurnRateSeries` -> the full IRI, using the prefixes the seeded
    TTLs actually declare. The registration writes compact form and the ontology declares full
    — the compact-vs-full hazard, at the declaration boundary."""
    if ":" not in compact or compact.startswith("http"):
        return compact
    prefix, _, local = compact.partition(":")
    if prefix in _AUTHORITATIVE:
        return f"{_AUTHORITATIVE[prefix]}{local}"
    bound = _prefix_bindings().get(prefix) or set()
    return f"{next(iter(bound))}{local}" if len(bound) == 1 else compact


def test_every_registered_ARCHETYPE_is_declared():
    """The object end of every rendersAs triple. This is the one that was failing."""
    g = _graph()
    declared = _declared_classes(g)
    missing = sorted(
        {c["object_uri"] for c in PRESENTATION_CAPABILITIES if _expand(c["object_uri"]) not in declared}
    )
    assert not missing, (
        f"{len(missing)} archetype(s) registered but NOT declared in mesh_system.ttl: {missing}.\n"
        f"Contract D will reject the presentation on its object end, and the rejection will "
        f"read as 'incomplete' rather than 'undeclared'. Declare the class; do not weaken "
        f"the gate."
    )


def test_every_registered_SUBJECT_shape_is_declared():
    """The other end. These were already fine, and pinning them keeps the pair honest --
    a future output shape can go undeclared exactly as easily."""
    g = _graph()
    declared = _declared_classes(g)
    missing = sorted(
        {c["subject_uri"] for c in PRESENTATION_CAPABILITIES if _expand(c["subject_uri"]) not in declared}
    )
    assert not missing, f"output shape(s) registered but not declared: {missing}"


def test_archetypes_hang_off_their_OWN_parent_not_Response():
    """An archetype is not a payload. mesh:DatasetAnalysisReport is a thing an engine
    PRODUCES; mesh:ChartWidget is a way a client can DRAW it. Forcing archetypes under
    mesh:Response would make the graph say a rendering kind is an engine output."""
    g = _graph()
    archetypes = {str(s) for s in g.subjects(RDFS.subClassOf, _MESH.Archetype)}
    assert archetypes, "no classes declared under mesh:Archetype"
    for c in PRESENTATION_CAPABILITIES:
        obj = _expand(c["object_uri"])
        assert obj in archetypes, f"{c['object_uri']} is declared but not under mesh:Archetype"
        assert (rdflib.URIRef(obj), RDFS.subClassOf, _MESH.Response) not in g, (
            f"{c['object_uri']} is subclassed under mesh:Response — an archetype is a "
            f"TREATMENT, not a payload"
        )


def test_the_universal_archetype_is_declared():
    """KNOWLEDGE_DOCUMENT is the fallback slice 4 routes an unsatisfiable payload to. If its
    class is missing, the ONE archetype that must always be available is the one that cannot
    register."""
    assert _expand("mesh:KnowledgeDocument") in _declared_classes(_graph())
