"""An OPT-IN double for tests that stand in for the recipient-keyed inbox reads.

`human_tasks.viewer_tasks` (ADR-0068 s6) is the one read every route serves a viewer's tasks from.
Many older tests replace `human_tasks.list_tasks_for` (the pending queue) or
`human_tasks.holds_task_on_case` (the case admission) and mean "these are the caller's rows".
A test that still means that calls `route_viewer_tasks_through(monkeypatch)` AFTER installing its
double: `viewer_tasks` then answers from the double (no store, no Topaz, no capability match).

This is a call a test makes, not a fixture that runs for every test: a test that replaces neither
gets the real `viewer_tasks`, and the seals of the read-time match
(tests/test_a_task_is_matched_to_the_viewer_at_read_time.py) never use this module. The rows a
holds-double answers carry the asked case_id, so the label gate runs on them like on any row.
"""
from __future__ import annotations

import sys


def route_viewer_tasks_through(monkeypatch, *, a_case_with_no_label: bool = False) -> None:
    for name in ("iagent.human_tasks", "src.iagent.human_tasks"):
        ht = sys.modules.get(name)
        if ht is None or not hasattr(ht, "viewer_tasks"):
            continue
        _route(monkeypatch, ht)
    if a_case_with_no_label:
        _a_case_that_carries_no_label(monkeypatch)


def _route(monkeypatch, ht) -> None:
    list_double, holds_double = ht.list_tasks_for, ht.holds_task_on_case

    def viewer_tasks(viewer_id, *, status=ht.PENDING, case_id=None, workflow_ids=None,
                     kinds=None, audiences=None):
        if status is None and case_id:  # the admission double
            held = holds_double(case_id, viewer_id)
            return ([{"task_id": "double", "case_id": case_id, "status": "pending"}]
                    if held else [])
        rows = list(list_double(viewer_id, status=ht.PENDING))
        if workflow_ids:
            rows = [r for r in rows if r.get("workflow_id") in set(workflow_ids)]
        if kinds:
            rows = [r for r in rows if r.get("kind") in set(kinds)]
        return rows

    monkeypatch.setattr(ht, "viewer_tasks", viewer_tasks)


def _a_case_that_carries_no_label(monkeypatch) -> None:
    """A holds-double answers rows that name their case, so the label gate reads that case. A test
    that doubled the admission did not stand a case up; this one carries no label, so the gate
    passes and the test goes on being about what it was about. Pass
    `a_case_with_no_label=True` to get it; a test that already stands a case up (a runner double
    behind `gateway.httpx`) leaves it off and keeps its own."""
    for gname, cname in (("iagent.gateway", "iagent.case_projection"),
                         ("src.iagent.gateway", "src.iagent.case_projection")):
        gw, cp = sys.modules.get(gname), sys.modules.get(cname)
        if gw is None or cp is None or getattr(gw._case_state, "__module__", None) != gw.__name__:
            continue

        async def _state(case_id):
            return {"case_id": case_id}, None, {}
        monkeypatch.setattr(gw, "_case_state", _state)
        monkeypatch.setattr(cp, "case_labels", lambda case, spec, defs: [])
