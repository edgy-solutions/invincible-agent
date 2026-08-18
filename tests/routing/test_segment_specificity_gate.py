"""The phone book must be able to say "that token does not identify an asset" (2026-08-17).

THE CONTRACT THIS SEALS. `contracts.baml` instructs the extractor to be RECALL-BIASED —
*"a miss costs more than a spurious extraction — THE ROUTER CAN VERIFY WITH THE PHONE
BOOK."* That is sound engineering, and the phone book never held up its end: a fuzzy match
let `cage`, lifted from the words *"cage values"*, resolve to `publog/p_cage`. Completing
the model's guess is not verifying it. The prompt and the matcher disagreed by
construction, and neither referenced the other.

WHY THIS IS STRUCTURAL AND NOT A SCORE THRESHOLD — the property worth protecting. Measured
2026-08-15/17: the identical query for a NONEXISTENT asset alternated between honest
abstention and a confident answer about a real, different dataset as one candidate's
similarity score moved by **0.006**, with no redeploy. Raising a cutoff would only move a
row from 0.006-from-wrong to 0.012-from-wrong — a wider margin on the same knife edge. A
substring is a substring at every score, so substrate drift cannot flip these decisions.

SCOPE, stated per [[a-green-check-proves-only-its-scope]]:
  IN     the pure rule — which identifiers may name which candidates, and the decision
         table's use of it. Total over the measured corpus cases, both directions.
  OUT    that a live `/resolve` produces these identifiers at all (extraction is upstream),
         and any URN shape without a derivable terminal name — the rule documents its own
         fallback for those rather than pretending to cover them.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agent_fleet.ontology_service.instance_resolution import (  # noqa: E402
    InstanceCandidate,
    candidate_asset_name,
    decide,
    identifier_name_and_qualifiers,
    passes_segment_specificity,
)

URN = "urn:li:dataset:(urn:li:dataPlatform:s3,iagent-minio.publog-lake/publog/p_cage,PROD)"
CUST = "urn:li:dataset:(urn:li:dataPlatform:postgres,prod.sales.customers_raw,PROD)"


# --- MUST RESOLVE: qualified forms the matcher used to reject (7 of 9 failures) -------
@pytest.mark.parametrize("identifier", [
    "p_cage",                                # bare name
    "P_CAGE",                                # case
    "publog.p_cage",                         # dotted qualifier  <- was rejected
    "publog p_cage",                         # space qualifier   <- was rejected
    "publog's p_cage",                       # possessive        <- was rejected
    "minio-svc.publog-lake/publog/p_cage",   # full path
])
def test_qualified_forms_name_the_asset(identifier):
    """A qualifier is corroboration, not an obstacle. These name the asset correctly and
    were refused — the 'too strict' half of the defect."""
    assert passes_segment_specificity(identifier, URN) is True


# --- MUST NOT RESOLVE: the 'too loose' half ------------------------------------------
@pytest.mark.parametrize("identifier,why", [
    ("cage", "a CONTENT WORD from 'cage values' — the measured false positive"),
    ("p_caeg", "a misspelling of a nonexistent asset must not reach a real one"),
    ("publog", "a SCHEMA is a container, not the thing it contains (bare-join-01)"),
])
def test_non_naming_tokens_are_refused(identifier, why):
    assert passes_segment_specificity(identifier, URN) is False, why


def test_a_loose_fuzzy_match_to_a_different_asset_is_refused():
    """owner-03: `customer_silver` resolved to `customers_raw`. Different asset, accepted
    on similarity alone."""
    assert passes_segment_specificity("customer_silver", CUST) is False
    assert passes_segment_specificity("customers_raw", CUST) is True


def test_a_container_segment_is_not_the_asset():
    """`publog` IS a genuine segment of the candidate, which is why plain membership was
    not enough and the rule keys on the TERMINAL name."""
    assert candidate_asset_name(URN) == "p_cage"
    assert "publog" in URN.lower()


def test_env_suffix_is_not_the_asset_name():
    assert candidate_asset_name(URN) == "p_cage"          # not "prod"
    assert candidate_asset_name(CUST) == "customers_raw"


def test_unknown_suffix_makes_the_gate_STRICTER_not_looser():
    """The env list is explicit, so an unlisted suffix stays part of the name and the
    identifier no longer matches — rejecting, never admitting. The safe failure direction
    is class-fallback, matching is_instance_shaped's existing posture."""
    weird = "urn:li:dataset:(urn:li:dataPlatform:s3,publog/p_cage,SANDBOX)"
    assert candidate_asset_name(weird) == "sandbox"
    assert passes_segment_specificity("p_cage", weird) is False


def test_identifier_split_keeps_the_name_last():
    assert identifier_name_and_qualifiers("publog.p_cage") == ("p_cage", ["publog"])
    assert identifier_name_and_qualifiers("p_cage") == ("p_cage", [])
    assert identifier_name_and_qualifiers("") == ("", [])


# --- the decision table actually applies it -------------------------------------------
def _cand(score=0.85):
    return InstanceCandidate(instance_id=URN, class_uri="http://x#Table",
                             label="p_cage", score=score, provider="engine_d")


def test_decision_table_refuses_a_content_word_with_a_DISTINCT_reason():
    d = decide([_cand()], identifier="cage")
    assert d.subject_uri is None
    assert d.provenance["instance_match"] == "not_specific", (
        "folding this into 'empty' would hide every action the gate takes — the phone "
        "book DID know things and refused them"
    )
    assert d.provenance["instance_rejected_n"] == 1


def test_decision_table_still_resolves_a_qualified_name():
    d = decide([_cand()], identifier="publog.p_cage")
    assert d.subject_uri == "http://x#Table"
    assert d.provenance["instance_match"] == "fuzzy"


def test_the_gate_is_SCORE_INDEPENDENT():
    """THE MARGIN REQUIREMENT. A fix that merely widened a threshold would leave the row
    one substrate-drift away from flipping. `cage` must be refused at every score the
    matcher can produce, including a perfect one."""
    for score in (0.70, 0.85, 0.95, 0.99, 1.0):
        d = decide([_cand(score)], identifier="cage")
        assert d.subject_uri is None, f"a content word won at score={score}"


def test_no_identifier_leaves_existing_callers_unchanged():
    """The gate is opt-in on the identifier being present, so callers that never passed
    one behave exactly as before."""
    d = decide([_cand()])
    assert d.subject_uri == "http://x#Table"
