"""Seal for two checks in `steward_correction.validate_row_edits` that no test reached (mutant
survived, 2026-10-25): with the server-authored batch in hand, a `deleted` or `corrected` row whose
mpn is not a row of this review is refused ("nothing to delete" / "nothing to correct"). Without
these, a steward can DELETE an edge, or re-key one, for a part the review never listed, and the
write is a no-op that reports success (the MATCH finds nothing).

Controls share the gate and the population: the same call with a listed mpn is accepted, and the
same unknown mpn is accepted when no batch is supplied (the payload-local mode), so the refusal is
the batch rule and nothing else.
"""
import pytest

from agent_fleet.restate_analyst import steward_correction as sc

BATCH = ["A", "B", "C"]
EV = {"note": "n"}


def _del(m):
    return {"deleted": [{"mpn": m, "reason": "r"}]}


def _cor(m):
    return {"corrected": [{"mpn": m, "corrected_mpn": "Z9", "evidence": "e"}]}


@pytest.mark.parametrize("make", [_del, _cor])
def test_CONTROL_a_listed_mpn_is_accepted(make):
    sc.validate_row_edits(make("b"), extracted_mpns=BATCH)


@pytest.mark.parametrize("make", [_del, _cor])
def test_CONTROL_without_a_batch_the_payload_local_rules_accept_it(make):
    sc.validate_row_edits(make("NOT-LISTED"))


@pytest.mark.parametrize("make,fragment", [(_del, "nothing to delete"), (_cor, "nothing to correct")])
def test_an_mpn_that_is_not_a_row_of_this_review_is_refused(make, fragment):
    with pytest.raises(sc.EditRefusal, match=fragment):
        sc.validate_row_edits(make("NOT-LISTED"), extracted_mpns=BATCH)
