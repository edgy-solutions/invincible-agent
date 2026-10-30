"""The weakest-rung claim of a steward-written edge must reach the read (path (a), gap a2).

`promotion_stores._WRITE_EDGE_CYPHER` stamps `obtained_via='steward-corrected'` (plus corrected_by,
extracted_value, evidence) on the `Component -[SUBJECT_TO]-> SustainmentNotice` EDGE. The read that
answers "what parts does this notice name" (`notice_parts.NOTICE_PARTS_CYPHER`) matches that edge
ANONYMOUSLY and keeps only `c.mpn`; each source's `obtained_via` is then copied from the NOTICE's
block. So a part a steward typed in is reported with the notice's rung (for example `user-drop`),
stronger than the edge's, and `provenance_floor` (weakest rung wins) never sees the sixth rung.

Form check on the query text, because the row the read returns has no per-part column to assert on:
the relationship must be bound to a variable and its `obtained_via` read. The control proves the
matcher is not blind: it finds the SUBJECT_TO match in the same text. Strict xfail; `--runxfail`
shows it red. Owner of the fix: ontology_service (not saf).
"""
import re

import pytest

from agent_fleet.ontology_service import notice_parts as np_

_REL = re.compile(r"-\[(\w*):SUBJECT_TO\]->")


def test_CONTROL_the_query_has_one_subject_to_match():
    assert len(_REL.findall(np_.NOTICE_PARTS_CYPHER)) == 1


@pytest.mark.xfail(strict=True, reason="GAP a2: the SUBJECT_TO edge's obtained_via is never read")
def test_the_notice_parts_read_carries_each_edges_own_rung():
    (var,) = _REL.findall(np_.NOTICE_PARTS_CYPHER)
    assert var, "the SUBJECT_TO edge is matched anonymously"
    assert f"{var}.obtained_via" in np_.NOTICE_PARTS_CYPHER
