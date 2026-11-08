"""CANONICAL PRODUCT-STRUCTURE VOCABULARY — citations verified, not asserted.

ADR-0035 data plane, packet 2 steps 1 + 4.

  1. EVERY `derivedFrom` CITES SOMETHING THAT EXISTS in the committed S3000L. A citation to an
     invented IRI is WORSE than an empty slot: an empty slot is honest about not knowing; a
     wrong IRI looks like standards alignment and cannot be traced. Step 0 found the real names
     (Breakdown/BreakdownElement, Applicability) precisely because a model authored without
     reading the standard would have invented Assembly/Component/Effectivity and silently
     forfeited three citations while appearing compliant.

  2. THE ACCEPTANCE QUERIES EXIST BEFORE ANY INGESTION. The design's claim is that the model
     can NAME ITS OWN CONFLICTS. A model that cannot express its disagreements looks identical
     to one whose sources happen to agree.

  3. THE OBSOLESCENCE SLICE (ADR-0065 C). Every IOF Core name was read in IOF Core; there is one
     Part node; the configuration is the three ruled views; the lifecycle-status menu is the
     registry's, not an enum here.

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/test_product_structure_vocabulary.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_TTL = (_ROOT / "setup" / "ontologies" / "product_structure_extension.ttl").read_text(encoding="utf-8")
_QUERIES = _ROOT / "setup" / "queries" / "product_structure_acceptance.sparql"

# Verified present in the LIVE SUSTAINMENT graph on 2026-08-01 (773 classes / 373 properties,
# namespace http://www.lksoft.com/s3kl#). Anything cited must be in this set.
_S3000L_VERIFIED = {
    "PartAsDesigned", "Breakdown", "BreakdownElement",
    "BreakdownElementUsageInBreakdown", "ApplicabilityStatement",
    "quantityOfChildElement", "partIdentifier_partNumber", "partIdentifier_oemPartNumber",
}


def test_every_s3000l_citation_names_something_that_exists():
    """The core seal. A cited-but-invented IRI looks like compliance and cannot be traced —
    strictly worse than an honest empty slot."""
    cited = set(re.findall(r"mesh:derivedFrom\s+s3kl:(\w+)", _TTL))
    assert cited, "no S3000L citations at all — the vocabulary lost its standards grounding"
    unknown = cited - _S3000L_VERIFIED
    assert not unknown, (
        f"cited but NOT verified present in the committed S3000L: {sorted(unknown)} — either "
        f"confirm them in the graph and add them here, or leave the slot empty and labelled, "
        f"which is the honest state"
    )


def test_the_ratified_wrong_citation_stays_dead():
    """RATIFICATION OUTCOME, pinned. `ps:revision` briefly cited s3kl:BreakdownElementRevision
    and the domain owner ruled it WRONG: that revisions a POSITION IN A STRUCTURE, ours revisions
    the PART. Removed from the verified set as well as the file, so a future re-citation fails
    the enumeration seal rather than passing unnoticed — a rejected citation that stays
    'available' is a rejection that only held once."""
    # Assert the CITATION FORM, not the bare string — my first version failed on the comment
    # that EXPLAINS the removal, which is the docstring-matching bug again (a keyword check over
    # source matches the prose documenting a rule as readily as a violation of it). The prose is
    # not merely harmless here, it is the record of why the slot is empty and must survive.
    assert "mesh:derivedFrom s3kl:BreakdownElementRevision" not in _TTL
    assert "BreakdownElementRevision" not in _S3000L_VERIFIED
    assert "WRONG in review" in _TTL, "the reason the slot is empty must stay in the file"


def test_the_standards_real_names_are_used_not_invented_synonyms():
    """Step 0's return on investment, pinned."""
    assert "s3kl:BreakdownElement" in _TTL
    assert "s3kl:ApplicabilityStatement" in _TTL, "effectivity must use the standard's own term"
    for invented in ("s3kl:Assembly", "s3kl:Component", "s3kl:Effectivity"):
        assert invented not in _TTL, f"{invented} does not exist in S3000L"


def test_plcs_is_never_cited_as_a_derivedfrom_target():
    """The ancestry claim is architect-asserted and UNVERIFIED — nothing in the ingested triples
    references ISO 10303. It stays a note in the ADR, never a citation, because a citation is a
    claim this file would be making on its own authority."""
    assert not re.search(r"derivedFrom\s+\S*(plcs|10303)", _TTL, re.I)


def test_the_house_bridge_is_labelled_not_cited():
    """The ruled fork. The bridge has no S3000L equivalent, so it must NOT carry a derivedFrom,
    and must say WHY it exists — 'just use the standard's shape' is the tempting wrong answer
    that loses the semantics the process manipulates."""
    bridge = _TTL[_TTL.index("ps:ApprovedSourceRelationship a owl:Class"):]
    bridge = bridge[:bridge.index("ps:forPart")]
    assert "mesh:derivedFrom" not in bridge, "the house bridge cites a standard it is not derived from"
    assert "HOUSE CONVENTION" in _TTL


def test_the_bridge_is_enrichment_over_the_standard_not_a_fork_from_it():
    """The manufacturer side co-populates the S3000L identifier, so a pure-S3000L reader still
    sees the MPN and loses only relationship semantics it never had."""
    assert "partIdentifier_oemPartNumber" in _TTL
    assert "Co-populated" in _TTL
    assert "seeAlso" in _TTL, "the bridge must declare its RELATION to the S3000L identifiers"


def test_part_usage_is_reified_and_says_why():
    """Reification is load-bearing twice: provenance rides on every assertion, and two sources
    must be able to DISAGREE about the same pair rather than collapse into a last-writer-wins
    edge."""
    assert "ps:PartUsage a owl:Class" in _TTL
    assert "REIFIED" in _TTL and "disagree" in _TTL


def test_v1_exclusions_are_named_not_merely_absent():
    """An unnamed absence reads as an oversight; a named one is a decision on the record."""
    for excluded in ("CAD structure", "alternates", "effectivity algebra"):
        assert excluded in _TTL


def test_provenance_fields_are_in_the_vocabulary():
    for f in ("authoritativeSource", "obtainedVia", "asOf", "ingestRun", "standing"):
        assert f"ps:{f}" in _TTL


# ── step 4: the acceptance queries, before any ingestion ───────────────────
def test_the_acceptance_queries_exist():
    assert _QUERIES.exists(), "the model must be able to name its own conflicts BEFORE data"


def test_source_disagreement_is_expressible():
    q = _QUERIES.read_text(encoding="utf-8")
    assert "SOURCE DISAGREEMENT" in q
    assert "obtainedVia" in q and "FILTER" in q


def test_staleness_by_consumer_handles_the_unknown_sentinel():
    """An undateable claim is NOT fresh. Omitting it would silently count it as current — the
    optimistic default this codebase refuses, and the same reason is_stale returns None rather
    than False."""
    q = _QUERIES.read_text(encoding="utf-8")
    assert "STALENESS" in q and "asOf" in q
    assert "undateable" in q, "the undateable bucket is missing — those claims would be dropped"


# ── ADR-0065 C: the obsolescence slice, over IOF Core ──────────────────────
# Read in IOF Core as the prime fetches it (iofoundry/ontology master, core/Core.rdf, 2026-11-08,
# sha256 7e44642681de…). The terms live under .../ontology/construct/. The prime pulls master
# UNPINNED, so this is a reading on a date: a name that leaves upstream is not caught here.
_IOF_VERIFIED = {
    "DesignSpecification", "Assembly", "MaterialProduct", "MaterialArtifact",
    "DescriptiveInformationContentEntity", "PlanSpecification",
    "componentPartOfAtSomeTime", "prescribes",
}
_IOF = "https://spec.industrialontologies.org/ontology/construct/"


def _graph():
    import rdflib
    g = rdflib.Graph()
    g.parse(data=_TTL, format="turtle")
    return g


def _ps(name):
    import rdflib
    return rdflib.URIRef("http://internal/sustainment/product#" + name)


def test_every_iof_name_used_was_read_in_iof_core():
    """The S3000L seal's twin. An IOF IRI nobody read is a citation that looks grounded."""
    used = {str(o)[len(_IOF):] for o in _graph().objects() if str(o).startswith(_IOF)}
    assert used, "the slice lost its IOF Core alignment"
    assert not used - _IOF_VERIFIED, sorted(used - _IOF_VERIFIED)
    assert not any("ontology/core/Core/" in str(o) for o in _graph().objects()), (
        "IOF Core declares its terms under .../construct/; .../core/Core/ is only their isDefinedBy")


def test_there_is_one_part_node_and_assembly_and_end_item_are_roles_of_it():
    """ADR-0065 ruling 1: one Part node. A second Part-like class would be a second identity."""
    import rdflib
    from rdflib import OWL, RDF, RDFS
    g = _graph()
    labelled_part = [s for s in g.subjects(RDF.type, OWL.Class) if str(g.value(s, RDFS.label)) == "Part"]
    assert labelled_part == [_ps("Part")]
    for role in ("Assembly", "EndItem"):
        assert (_ps(role), RDFS.subClassOf, _ps("Part")) in g, role
    # A part number + revision is a design; the material artifact is what it prescribes.
    assert (_ps("Part"), RDFS.subClassOf, rdflib.URIRef(_IOF + "DesignSpecification")) in g


def test_the_configuration_is_exactly_the_three_ruled_views():
    """ADR-0065 ruling 2 names three; a fourth would be a view no verb argument can ask for."""
    from rdflib import OWL
    from rdflib.collection import Collection
    g = _graph()
    members = Collection(g, g.value(_ps("Configuration"), OWL.oneOf))
    assert {str(m).rsplit("#", 1)[1] for m in members} == {"as_designed", "as_built", "as_maintained"}


def test_the_lifecycle_status_menu_is_the_registry_not_an_enum_here():
    """The status values are data a deployment extends (ADR-0065 §3); an enum here is a copy."""
    # Asked of the GRAPH, not the text: the comment that explains why there is no oneOf names it.
    from rdflib import OWL, RDFS, XSD
    g = _graph()
    status = _ps("status")
    assert g.value(status, RDFS.range) == XSD.string
    assert (status, OWL.oneOf, None) not in g
    assert (_ps("LifecycleStatus"), OWL.oneOf, None) not in g
    assert "policy/registry/lifecycle_status.yaml" in str(g.value(status, RDFS.comment))


def test_absent_and_null_lifecycle_status_are_written_apart():
    assert "NOT BEEN ASSESSED" in _TTL and "AND NONE IS KNOWN" in _TTL


def test_the_ltb_decision_carries_the_four_named_fields():
    from rdflib import RDFS
    g = _graph()
    for f in ("ltbQuantity", "ltbBy", "ltbRationale", "ltbApprovedBy", "ltbFor"):
        assert (_ps(f), RDFS.domain, _ps("LtbDecision")) in g, f


def test_the_configurations_writability_claim_matches_the_writer():
    """The file says ps:configuration is NOT YET WRITABLE because the writer's canonical set lacks
    it. When the BOM contract adds it there, this goes red until the comment says so too."""
    from src.iagent.product_writer import CANONICAL_FIELDS
    writable = "configuration" in CANONICAL_FIELDS["PartUsage"]
    assert writable == ("NOT YET WRITABLE" not in _TTL)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
