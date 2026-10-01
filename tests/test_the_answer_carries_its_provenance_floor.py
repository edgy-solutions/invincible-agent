"""The answer carries its provenance floor: the weakest provenance it drew on (ADR-0041 §7).

What this seals:
  * THE RULED SHAPE: exactly `{obtained_via, ingest_ids, unidentified}`, on every call.
  * THE WEAKEST RUNG WINS, by the tuple's own order, for every pair of rungs.
  * AN UNREADABLE BLOCK IS `unstamped`, WEAKER THAN `user-drop`, AND COUNTED. Skipping it is
    the laundering the floor exists to prevent, so each unreadable form is paired with a
    `direct` source and must still pull the floor down.
  * PROMOTION REMOVES THE ID AND LEAVES THE RUNG. A promoted drop still arrived by hand.
  * AN UNNAMEABLE DROP IS COUNTED IN `unidentified`, NOT DROPPED.
  * THE ID IS READ FROM THE BLOCK, and only from the block (ruled 2026-09-30). An id riding
    beside the block, the carriage this replaced, is not read.
  * THE FIFTH RUNG EXISTS HERE, and a writer can stamp `ingest_id` into the block.

Run: uv run --frozen pytest tests/test_the_answer_carries_its_provenance_floor.py -q
"""
from __future__ import annotations

import itertools

import pytest

from src.iagent import provenance
from src.iagent.provenance_floor import FIELDS, RANKING, UNSTAMPED, provenance_floor

A = "sha256:" + "aa" * 32
B = "sha256:" + "bb" * 32
C = "sha256:" + "cc" * 32


def _src(via, ingest_id=None, **over):
    block = provenance.make_provenance(
        authoritative_source="vendor-x", obtained_via=via, as_of=provenance.AS_OF_UNKNOWN,
        ingested_at="2026-09-30T00:00:00Z", ingest_run="run-1", standing="supervised",
        ingest_id=ingest_id)
    block.update(over)
    return {"provenance": block}


def _floor(sources, **kw):
    out = provenance_floor(sources, **kw)
    assert tuple(out) == FIELDS == ("obtained_via", "ingest_ids", "unidentified")
    return out


def test_an_answer_over_vouched_sources_is_floored_at_its_weakest_rung():
    assert _floor([_src("direct"), _src("etl"), _src("warehouse")]) == {
        "obtained_via": "warehouse", "ingest_ids": [], "unidentified": 0}


def test_ONE_unpromoted_drop_among_direct_sources_floors_the_whole_answer():
    assert _floor([_src("direct"), _src("user-drop", A), _src("direct")]) == {
        "obtained_via": "user-drop", "ingest_ids": [A], "unidentified": 0}


def test_a_PROMOTED_drop_leaves_ingest_ids_but_its_rung_is_unchanged():
    assert _floor([_src("direct"), _src("user-drop", A)], promoted={A}) == {
        "obtained_via": "user-drop", "ingest_ids": [], "unidentified": 0}


def test_only_the_UNPROMOTED_ids_are_named_sorted_and_once():
    out = _floor([_src("user-drop", B), _src("user-drop", A), _src("user-drop", B),
                  _src("user-drop", C)], promoted={C})
    assert out["ingest_ids"] == [A, B]


def test_an_ingest_id_on_a_VOUCHED_source_is_not_a_contribution():
    out = _floor([_src("manual-export", A)])
    assert out["ingest_ids"] == [] and out["unidentified"] == 0


@pytest.mark.parametrize("bad", [
    {},                                                  # no block
    {"provenance": None},
    {"provenance": {"obtained_via": "direct"}},          # incomplete
    "not-a-source",
    None,
], ids=["no-block", "null-block", "incomplete", "string", "none"])
def test_an_UNREADABLE_block_is_unstamped_and_pulls_a_direct_answer_down(bad):
    assert _floor([_src("direct"), bad])["obtained_via"] == UNSTAMPED


def test_an_UNKNOWN_rung_is_unstamped_not_skipped():
    assert _floor([_src("direct"), _src("direct", obtained_via="email")])["obtained_via"] \
        == UNSTAMPED


def test_UNSTAMPED_is_weaker_than_an_unpromoted_drop_and_the_drop_is_still_named():
    assert _floor([_src("user-drop", A), {}]) == {
        "obtained_via": UNSTAMPED, "ingest_ids": [A], "unidentified": 0}


@pytest.mark.parametrize("iid", [None, "", "   "])
def test_a_drop_with_no_ingest_id_is_COUNTED_in_unidentified(iid):
    src = _src("user-drop")
    if iid is not None:
        src["provenance"]["ingest_id"] = iid        # past the constructor, which refuses it
    out = _floor([_src("direct"), src], promoted={A})
    assert out == {"obtained_via": "user-drop", "ingest_ids": [], "unidentified": 1}


def test_an_id_riding_BESIDE_the_block_is_not_read():
    src = _src("user-drop")
    src["ingest_id"] = A
    assert _floor([src]) == {"obtained_via": "user-drop", "ingest_ids": [], "unidentified": 1}


def test_an_answer_that_drew_on_NOTHING_claims_no_rung():
    assert _floor([]) == {"obtained_via": None, "ingest_ids": [], "unidentified": 0}


# Built from the tuple itself, NOT from RANKING: a pair list derived from the order under test
# cannot see that order being inverted.
@pytest.mark.parametrize("near,far", list(itertools.combinations(provenance.OBTAINED_VIA + (UNSTAMPED,), 2)))
def test_for_EVERY_pair_the_farther_rung_wins_in_either_order(near, far):
    s = {r: (_src(r) if r != UNSTAMPED else {}) for r in (near, far)}
    assert _floor([s[near], s[far]])["obtained_via"] == far
    assert _floor([s[far], s[near]])["obtained_via"] == far


# ── THE BLOCK ─────────────────────────────────────────────────────────────────────────────────

def test_the_ranking_is_the_tuple_with_unstamped_past_the_far_end():
    assert RANKING == provenance.OBTAINED_VIA + (UNSTAMPED,)
    assert provenance.OBTAINED_VIA[-1] == provenance.USER_DROP == "user-drop"


def test_a_writer_can_STAMP_user_drop_and_its_ingest_id():
    block = _src("user-drop", A)["provenance"]
    provenance.validate_provenance(block)
    assert block["obtained_via"] == "user-drop" and block["ingest_id"] == A


def test_a_block_with_no_ingest_id_does_not_carry_the_key():
    assert "ingest_id" not in _src("direct")["provenance"]


@pytest.mark.parametrize("iid", ["", "   ", 7])
def test_the_constructor_refuses_a_BLANK_or_non_string_ingest_id(iid):
    with pytest.raises(provenance.ProvenanceIncomplete, match="ingest_id"):
        _src("user-drop", iid)


def test_the_rung_tuple_AGREES_with_the_SDKs_copy():
    """Live once the SDK tag carrying iagent_mesh.provenance (lane/ca b68926a) is pinned."""
    sdk = pytest.importorskip("iagent_mesh.provenance")
    assert provenance.OBTAINED_VIA == sdk.OBTAINED_VIA
