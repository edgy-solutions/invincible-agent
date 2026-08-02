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
    "PartAsDesigned", "Breakdown", "BreakdownElement", "BreakdownElementRevision",
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


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
