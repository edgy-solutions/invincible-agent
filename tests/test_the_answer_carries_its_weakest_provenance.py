"""The answer envelope carries the weakest provenance it drew on (ADR-0041 §7).

What this seals:
  * THE WEAKEST RUNG WINS, by the tuple's own order, for every pair of rungs.
  * AN UNREADABLE BLOCK IS `unstamped`, WEAKER THAN `user-drop`, AND COUNTED. Skipping it is
    the laundering the label exists to prevent, so each unreadable form is paired with a
    `direct` source and must still pull the label down.
  * PROMOTION CLEARS "UNVERIFIED" AND LEAVES THE RUNG. A promoted drop still arrived by hand.
  * AN UNNAMEABLE DROP IS COUNTED, NOT DROPPED.
  * THE FIFTH RUNG EXISTS HERE, spelled as the SDK spells it (ADR-0041 §2).

Run: uv run --frozen pytest tests/test_the_answer_carries_its_weakest_provenance.py -q
"""
from __future__ import annotations

import itertools

import pytest

from src.iagent import provenance
from src.iagent.envelope_label import RANKING, UNSTAMPED, envelope_label

A = "sha256:" + "aa" * 32
B = "sha256:" + "bb" * 32


def _src(via, ingest_id=None, **over):
    block = provenance.make_provenance(
        authoritative_source="vendor-x", obtained_via=via, as_of=provenance.AS_OF_UNKNOWN,
        ingested_at="2026-09-30T00:00:00Z", ingest_run="run-1", standing="supervised")
    block.update(over)
    out = {"provenance": block}
    if ingest_id is not None:
        out["ingest_id"] = ingest_id
    return out


def test_an_answer_over_vouched_sources_is_labelled_by_its_weakest_rung():
    lab = envelope_label([_src("direct"), _src("etl"), _src("warehouse")])
    assert lab["weakest_obtained_via"] == "warehouse"
    assert lab["unverified_user_contributed"] is False
    assert lab["contributing_ingest_ids"] == [] and lab["sources"] == 3


def test_ONE_unpromoted_drop_among_direct_sources_labels_the_whole_answer():
    lab = envelope_label([_src("direct"), _src("user-drop", A), _src("direct")])
    assert lab["weakest_obtained_via"] == "user-drop"
    assert lab["unverified_user_contributed"] is True
    assert lab["contributing_ingest_ids"] == [A]


def test_a_PROMOTED_drop_is_no_longer_unverified_but_its_rung_is_unchanged():
    lab = envelope_label([_src("direct"), _src("user-drop", A)], promoted={A})
    assert lab["weakest_obtained_via"] == "user-drop"
    assert lab["unverified_user_contributed"] is False
    assert lab["contributing_ingest_ids"] == []


def test_only_the_UNPROMOTED_ids_are_named_sorted_and_once():
    lab = envelope_label([_src("user-drop", B), _src("user-drop", A), _src("user-drop", B),
                          _src("user-drop", "sha256:" + "cc" * 32)],
                         promoted={"sha256:" + "cc" * 32})
    assert lab["contributing_ingest_ids"] == [A, B]


def test_an_ingest_id_on_a_VOUCHED_source_is_not_a_contribution():
    lab = envelope_label([_src("manual-export", A)])
    assert lab["contributing_ingest_ids"] == [] and lab["unverified_user_contributed"] is False


@pytest.mark.parametrize("bad", [
    {},                                                  # no block
    {"provenance": None},
    {"provenance": {"obtained_via": "direct"}},          # incomplete
    "not-a-source",
    None,
], ids=["no-block", "null-block", "incomplete", "string", "none"])
def test_an_UNREADABLE_block_is_unstamped_and_pulls_a_direct_answer_down(bad):
    lab = envelope_label([_src("direct"), bad])
    assert lab["weakest_obtained_via"] == UNSTAMPED
    assert lab["unstamped_sources"] == 1 and lab["sources"] == 2


def test_an_UNKNOWN_rung_is_unstamped_not_skipped():
    lab = envelope_label([_src("direct"), _src("direct", obtained_via="email")])
    assert lab["weakest_obtained_via"] == UNSTAMPED and lab["unstamped_sources"] == 1


def test_UNSTAMPED_is_weaker_than_an_unpromoted_drop_and_the_drop_is_still_named():
    lab = envelope_label([_src("user-drop", A), {}])
    assert lab["weakest_obtained_via"] == UNSTAMPED
    assert lab["contributing_ingest_ids"] == [A]


@pytest.mark.parametrize("iid", [None, "", "   "])
def test_a_drop_with_no_ingest_id_is_COUNTED_and_still_unverified(iid):
    src = _src("user-drop")
    if iid is not None:
        src["ingest_id"] = iid
    lab = envelope_label([_src("direct"), src], promoted={A})
    assert lab["unverified_user_contributed"] is True
    assert lab["unidentified_user_contributed"] == 1 and lab["contributing_ingest_ids"] == []


def test_an_answer_that_drew_on_NOTHING_claims_no_rung():
    lab = envelope_label([])
    assert lab["weakest_obtained_via"] is None
    assert lab["sources"] == 0 and lab["unverified_user_contributed"] is False


# Built from the tuple itself, NOT from RANKING: a pair list derived from the order under test
# cannot see that order being inverted.
@pytest.mark.parametrize("near,far", list(itertools.combinations(provenance.OBTAINED_VIA + (UNSTAMPED,), 2)))
def test_for_EVERY_pair_the_farther_rung_wins_in_either_order(near, far):
    s = {r: (_src(r) if r != UNSTAMPED else {}) for r in (near, far)}
    assert envelope_label([s[near], s[far]])["weakest_obtained_via"] == far
    assert envelope_label([s[far], s[near]])["weakest_obtained_via"] == far


# ── THE FIFTH RUNG ────────────────────────────────────────────────────────────────────────────

def test_the_ranking_is_the_tuple_with_unstamped_past_the_far_end():
    assert RANKING == provenance.OBTAINED_VIA + (UNSTAMPED,)
    assert provenance.OBTAINED_VIA[-1] == provenance.USER_DROP == "user-drop"


def test_a_writer_can_STAMP_user_drop():
    block = _src("user-drop")["provenance"]
    provenance.validate_provenance(block)
    assert block["obtained_via"] == "user-drop"


def test_the_rung_tuple_AGREES_with_the_SDKs_copy():
    """Live once the SDK tag carrying iagent_mesh.provenance (lane/ca b68926a) is pinned."""
    sdk = pytest.importorskip("iagent_mesh.provenance")
    assert provenance.OBTAINED_VIA == sdk.OBTAINED_VIA
