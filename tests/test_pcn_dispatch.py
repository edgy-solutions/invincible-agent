"""PCN/PDN dispatch effect sealed deterministically — the workflow model consuming its own output.

Proves the three-write plan: graph-state onto the item's node (SUSTAINMENT_INSTANCES), a per-item
HumanTask routed to the disposition's persona queue (the multiplayer moment), archive → no task, and
an unresolved subject skips the graph write honestly. Idempotency keyed by notice × part.

Run:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest pytest ../../tests/test_pcn_dispatch.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_RA = _REPO / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.restate_analyst.workflow_bulk_resolve import ItemResolution  # noqa: E402
from agent_fleet.restate_analyst.pcn_dispatch import plan_dispatch  # noqa: E402


def _res(disposition, *, mpn="NSR01L30NXT5G", subject="http://internal/components/NSR01L30NXT5G",
         needs_review=False, ruleset="rules@v1"):
    return ItemResolution(
        mpn=mpn, subject=subject, disposition=disposition,
        idempotency_key=f"IPCN25300X:{mpn}", needs_review=needs_review,
        override_reason=None, proposed_by_ruleset=ruleset,
    )


def test_qualification_dispatch_writes_state_and_opens_a_task():
    plan = plan_dispatch(_res("dispatchQualification"), notice_fingerprint="IPCN25300X", notice_id="IPCN25300X")
    # graph state
    assert plan.graph_write.subject_iri == "http://internal/components/NSR01L30NXT5G"
    assert plan.graph_write.triples["dispositionState"] == "dispatchQualification"
    assert plan.graph_write.triples["dispositionRef"] == "IPCN25300X:NSR01L30NXT5G"
    assert plan.graph_write.triples["proposedByRuleset"] == "rules@v1"
    # task -> qualification queue
    assert plan.human_task.audience == "qualification"
    assert plan.human_task.kind == "pcn_disposition"
    assert plan.human_task.task_key == "IPCN25300X:NSR01L30NXT5G"   # idempotency: notice × part
    assert plan.human_task.disposition == "dispatchQualification"


def test_ltb_routes_to_procurement():
    plan = plan_dispatch(_res("dispatchLTB"), notice_fingerprint="IPCN25300X")
    assert plan.human_task.audience == "procurement"


def test_alt_sourcing_routes_to_sourcing():
    plan = plan_dispatch(_res("dispatchAltSourcing"), notice_fingerprint="IPCN25300X")
    assert plan.human_task.audience == "sourcing"


def test_archive_writes_state_but_opens_no_task():
    """archive = acknowledge, no human action — state recorded, no queue."""
    plan = plan_dispatch(_res("archive"), notice_fingerprint="IPCN25300X")
    assert plan.graph_write.triples["dispositionState"] == "archive"
    assert plan.human_task is None


def test_unresolved_subject_skips_graph_write_but_still_tasks():
    """A disposition over a subject the resolveInstance step couldn't resolve: skip the graph write
    honestly (can't stamp state on a node you couldn't resolve) but still open the task."""
    plan = plan_dispatch(_res("dispatchLTB", subject=None), notice_fingerprint="IPCN25300X")
    assert plan.graph_write is None
    assert plan.human_task is not None and plan.human_task.subject_ref is None


def test_needs_review_surfaced_in_the_task():
    plan = plan_dispatch(_res("dispatchQualification", needs_review=True), notice_fingerprint="IPCN25300X")
    assert plan.human_task.needs_review is True
    assert "UNVERIFIED" in plan.human_task.summary


def test_graph_write_sparql_targets_the_instances_graph():
    plan = plan_dispatch(_res("dispatchLTB"), notice_fingerprint="IPCN25300X")
    sparql = plan.graph_write.to_sparql()
    assert "GRAPH <http://internal/SUSTAINMENT_INSTANCES>" in sparql
    assert "dispositionState" in sparql and "INSERT DATA" in sparql
