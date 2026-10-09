"""Pure-function seal for `src/iagent/case_projection.py` -- the WorkflowRunner case ->
cortex `WorkflowCasePayload` projection and its entitlement gate, for `GET /cases/{case_id}`
(roll #20 item 3). No Restate, no Postgres: every input here is a plain dict/object the route
would have already fetched.

Run: uv run --frozen pytest -q tests/test_case_projection.py
"""
from __future__ import annotations

from types import SimpleNamespace

from src.iagent import case_projection as cp


def _step(id, kind, title=None, audience=None):
    ns = SimpleNamespace(id=id, kind=kind)
    if title is not None:
        ns.title = title
    if audience is not None:
        ns.audience = audience
    return ns


def _definition(id, *, name=None, classification=None, participants=None,
                domain_stages=None, steps=None):
    return SimpleNamespace(
        id=id, name=name or id, classification=classification,
        participants=participants or [], domain_stages=domain_stages or [],
        steps=steps or [_step("s1", "human_await", title="Approve", audience="aud:x")],
    )


def _case(*, case_id="case-1", instances=None, transitions=None, state=None, terminal=None):
    return {
        "case_id": case_id, "instances": instances or [], "transitions": transitions or [],
        "state": state, "terminal": terminal,
    }


def _spec1(facts):
    return {"trigger": facts}


# ── CONTRACT FIELD NAMES (cortex-ui src/archetypes/workflow-case/contract.ts @
#    2915e36004e1dda7b233358b55a9501963f2bb8c) ────────────────────────────────────────────────

_WORKFLOW_CASE_PAYLOAD_FIELDS = {
    "subject_ref", "instances", "history", "options", "approvals", "output_artifact",
}
_CASE_INSTANCE_FIELDS = {"workflow_id", "definition", "current_stage", "status"}
_CASE_DEFINITION_FIELDS = {"id", "name", "participants", "domain_stages", "steps"}
_CASE_DEFINITION_STEP_FIELDS = {"id", "kind", "title", "audience"}
_CASE_HISTORY_ENTRY_FIELDS = {"at", "workflow_id", "event", "stage", "actor"}
_CASE_APPROVAL_FIELDS = {
    "workflow_id", "step_id", "status", "decided_by", "decision", "reason", "decided_at",
}


def test_payload_keys_are_exactly_the_contract_fields():
    case = _case(
        instances=[{"n": 1, "instance_id": "case-1~1", "definition_id": "def-a"}],
        transitions=[{"from": None, "outcome": "received", "to": "received", "by": "system",
                      "at": "t0"}],
        terminal="done",
    )
    defs = {"def-a": _definition("def-a")}
    payload = cp.project_workflow_case(case, defs, task_rows=[])
    assert set(payload.keys()) == _WORKFLOW_CASE_PAYLOAD_FIELDS
    assert payload["instances"], "need at least one instance to check its keys"
    inst = payload["instances"][0]
    assert set(inst.keys()) == _CASE_INSTANCE_FIELDS
    assert set(inst["definition"].keys()) == _CASE_DEFINITION_FIELDS
    assert set(inst["definition"]["steps"][0].keys()) == _CASE_DEFINITION_STEP_FIELDS
    assert payload["history"], "need at least one history entry to check its keys"
    assert set(payload["history"][0].keys()) == _CASE_HISTORY_ENTRY_FIELDS


def test_approval_keys_are_exactly_the_contract_fields():
    case = _case(instances=[{"n": 1, "instance_id": "wf-1", "definition_id": "def-a"}])
    rows = [{"task_id": "wf-1:s1", "workflow_id": "wf-1", "status": "pending",
             "decision": None, "acted_by": None, "acted_at": None, "comment": None}]
    out = cp.project_approvals(case, rows)
    assert len(out) == 1
    assert set(out[0].keys()) == _CASE_APPROVAL_FIELDS


# ── ENTITLEMENT: SUBMITTER ─────────────────────────────────────────────────────────────────

def test_submitter_sees_even_with_no_matching_domain():
    case = _case(instances=[{"n": 1, "instance_id": "wf-1", "definition_id": "def-a"}])
    spec1 = _spec1({"domain_type": "SAFETY", "dropped_by": {"authz_id": "alice"}})
    defs = {"def-a": _definition("def-a", classification="SAFETY")}
    assert cp.can_view_case(case, spec1, defs, caller_authz_id="alice",
                            caller_domains=["NOTHING_MATCHING"])


def test_RED_CHECK_a_non_submitter_with_no_matching_domain_is_refused():
    """Red-check for the submitter arm: with the submitter check's `==` flipped to `!=` (what
    the test above would also pass under, if the submitter branch were broken the OTHER way),
    a caller who is neither the submitter nor entitled must still be refused."""
    case = _case(instances=[{"n": 1, "instance_id": "wf-1", "definition_id": "def-a"}])
    spec1 = _spec1({"domain_type": "SAFETY", "dropped_by": {"authz_id": "alice"}})
    defs = {"def-a": _definition("def-a", classification="SAFETY")}
    assert not cp.can_view_case(case, spec1, defs, caller_authz_id="mallory",
                                caller_domains=["NOTHING_MATCHING"])


# ── ENTITLEMENT: LABELS ────────────────────────────────────────────────────────────────────

def test_entitled_in_all_labels_sees():
    case = _case(instances=[
        {"n": 1, "instance_id": "wf-1", "definition_id": "def-a"},
        {"n": 2, "instance_id": "wf-2", "definition_id": "def-b"},
    ])
    spec1 = _spec1({"domain_type": "aviation", "dropped_by": {"authz_id": "alice"}})
    defs = {"def-a": _definition("def-a", classification="SAFETY"),
            "def-b": _definition("def-b", classification=None)}
    # labels = {"aviation", "SAFETY"} -- caller holds both, case-insensitively.
    assert cp.can_view_case(case, spec1, defs, caller_authz_id="bob",
                            caller_domains=["AVIATION", "safety"])


def test_missing_one_label_is_refused():
    case = _case(instances=[
        {"n": 1, "instance_id": "wf-1", "definition_id": "def-a"},
        {"n": 2, "instance_id": "wf-2", "definition_id": "def-b"},
    ])
    spec1 = _spec1({"domain_type": "aviation", "dropped_by": {"authz_id": "alice"}})
    defs = {"def-a": _definition("def-a", classification="SAFETY"),
            "def-b": _definition("def-b", classification=None)}
    # caller holds AVIATION but not SAFETY -- one of two required labels missing.
    assert not cp.can_view_case(case, spec1, defs, caller_authz_id="bob",
                                caller_domains=["AVIATION"])


def test_no_labels_and_not_submitter_is_refused():
    case = _case(instances=[])  # no instances -> no facts, no classifications -> labels == []
    assert cp.case_labels(case, None, {}) == []
    assert not cp.can_view_case(case, None, {}, caller_authz_id="bob",
                                caller_domains=["ANYTHING"])


def test_RED_CHECK_empty_labels_pass_vacuously_if_the_all_check_is_broken():
    """Red-check for the `labels` emptiness guard: `all(... for lbl in [])` is vacuously True in
    Python, so a `can_view_case` that dropped the `if not labels: return False` guard would let
    ANY caller view ANY unentitled, non-submitted case. Pin the guard directly."""
    case = _case(instances=[])
    assert cp.case_labels(case, None, {}) == []
    # Without the guard this would be True (vacuous `all([])`); with it, False.
    assert cp.can_view_case(case, None, {}, caller_authz_id="anyone",
                            caller_domains=[]) is False


# ── HISTORY ─────────────────────────────────────────────────────────────────────────────────

def test_history_order_and_workflow_id_attribution():
    case = _case(case_id="case-9", transitions=[
        {"from": None, "outcome": "received", "to": "received", "by": "system", "at": "t0"},
        {"from": "received", "outcome": "triaged", "to": "triaged", "by": "system", "at": "t1"},
        {"from": "def-a", "outcome": "approved", "to": "def-b", "by": "alice", "at": "t2",
         "instance_id": "case-9~1"},
        {"from": "def-b", "outcome": "approved", "to": "closed", "by": "bob", "at": "t3",
         "instance_id": "case-9~2"},
    ])
    hist = cp.project_history(case)
    assert [h["at"] for h in hist] == ["t0", "t1", "t2", "t3"]
    # Before any instance-tagged transition, the subject is the CASE itself.
    assert hist[0]["workflow_id"] == "case-9"
    assert hist[1]["workflow_id"] == "case-9"
    # From its own transition onward, each instance is attributed correctly.
    assert hist[2]["workflow_id"] == "case-9~1"
    assert hist[3]["workflow_id"] == "case-9~2"
    assert [h["event"] for h in hist] == ["received", "triaged", "approved", "approved"]
    assert [h["stage"] for h in hist] == ["received", "triaged", "def-b", "closed"]
    assert [h["actor"] for h in hist] == ["system", "system", "alice", "bob"]


def test_RED_CHECK_a_failure_before_any_instance_opened_attributes_to_the_case():
    """Red-check: if `project_history` defaulted `current` to the LAST instance id seen anywhere
    instead of tracking it forward from the case id, this would misattribute a pre-instance
    failure. Here no transition ever carries an `instance_id`, so every entry must read the
    case's own id, never `None` and never a fabricated instance."""
    case = _case(case_id="case-5", transitions=[
        {"from": None, "outcome": "received", "to": "received", "by": "system", "at": "t0"},
        {"from": "received", "outcome": "failed", "to": "failed", "by": "system", "at": "t1"},
    ])
    hist = cp.project_history(case)
    assert all(h["workflow_id"] == "case-5" for h in hist)


# ── INSTANCE STATUS DERIVATION ────────────────────────────────────────────────────────────

def test_instance_status_non_last_is_completed_last_running_by_default():
    case = _case(instances=[
        {"n": 1, "instance_id": "wf-1", "definition_id": "def-a"},
        {"n": 2, "instance_id": "wf-2", "definition_id": "def-a"},
    ], state=None, terminal=None)
    defs = {"def-a": _definition("def-a")}
    insts = cp.project_instances(case, defs)
    assert insts[0]["status"] == "completed"
    assert insts[1]["status"] == "running"


def test_instance_status_last_completed_when_terminal_set():
    case = _case(instances=[{"n": 1, "instance_id": "wf-1", "definition_id": "def-a"}],
                terminal="approved")
    defs = {"def-a": _definition("def-a")}
    insts = cp.project_instances(case, defs)
    assert insts[0]["status"] == "completed"


def test_instance_status_last_failed_when_state_failed():
    case = _case(instances=[{"n": 1, "instance_id": "wf-1", "definition_id": "def-a"}],
                state="failed", terminal=None)
    defs = {"def-a": _definition("def-a")}
    insts = cp.project_instances(case, defs)
    assert insts[0]["status"] == "failed"


def test_RED_CHECK_terminal_checked_before_running_default():
    """Red-check: if the derivation checked `state == "failed"` AFTER falling through to
    "running" (i.e. dropped the elif ordering), a failed case's last instance would read
    "running" instead of "failed". Pin both outcomes are reachable and distinct."""
    case_failed = _case(instances=[{"n": 1, "instance_id": "wf-1", "definition_id": "def-a"}],
                        state="failed", terminal=None)
    case_running = _case(instances=[{"n": 1, "instance_id": "wf-1", "definition_id": "def-a"}],
                         state="selected", terminal=None)
    defs = {"def-a": _definition("def-a")}
    assert cp.project_instances(case_failed, defs)[0]["status"] == "failed"
    assert cp.project_instances(case_running, defs)[0]["status"] == "running"


def test_current_stage_is_always_null():
    case = _case(instances=[{"n": 1, "instance_id": "wf-1", "definition_id": "def-a"}],
                terminal="x")
    defs = {"def-a": _definition("def-a")}
    insts = cp.project_instances(case, defs)
    assert insts[0]["current_stage"] is None


# ── APPROVALS ───────────────────────────────────────────────────────────────────────────────

def test_approvals_mapped_pending_and_decided():
    case = _case(instances=[{"n": 1, "instance_id": "wf-1", "definition_id": "def-a"}])
    rows = [
        # Two recipient rows for the SAME pending task -- must collapse to one entry.
        {"task_id": "wf-1:s1", "workflow_id": "wf-1", "status": "pending",
         "decision": None, "acted_by": None, "acted_at": None, "comment": None},
        {"task_id": "wf-1:s1", "workflow_id": "wf-1", "status": "pending",
         "decision": None, "acted_by": None, "acted_at": None, "comment": None},
        # A decided task on a different step.
        {"task_id": "wf-1:s2", "workflow_id": "wf-1", "status": "approved",
         "decision": "approved", "acted_by": "alice", "acted_at": 1700000000000,
         "comment": "looks fine"},
    ]
    out = cp.project_approvals(case, rows)
    by_step = {a["step_id"]: a for a in out}
    assert set(by_step) == {"s1", "s2"}
    assert by_step["s1"]["status"] == "pending"
    assert by_step["s1"]["decided_by"] is None
    assert by_step["s2"]["status"] == "decided"
    assert by_step["s2"]["decided_by"] == "alice"
    assert by_step["s2"]["decision"] == "approved"
    assert by_step["s2"]["reason"] == "looks fine"
    assert by_step["s2"]["decided_at"] is not None


def test_approvals_skip_a_task_id_with_no_workflow_prefix():
    """A row whose task_id was never `f'{workflow_id}:{step_id}'` (e.g. a bare grouped-review
    id) must be skipped, never emitted with a guessed step_id."""
    case = _case(instances=[{"n": 1, "instance_id": "wf-1", "definition_id": "def-a"}])
    rows = [{"task_id": "some-bare-id", "workflow_id": "wf-1", "status": "pending",
             "decision": None, "acted_by": None, "acted_at": None, "comment": None}]
    assert cp.project_approvals(case, rows) == []


def test_RED_CHECK_approvals_scoped_to_the_right_workflow_id():
    """Red-check: if `project_approvals` matched on task_id prefix alone (without also checking
    `row["workflow_id"] == wf`), a row whose `workflow_id` COLUMN disagrees with its own task_id
    prefix (a data inconsistency -- stale/corrupt row, never produced by a well-formed
    registration) would still be trusted. The explicit column check must refuse it rather than
    take the prefix's word for which instance the row belongs to."""
    case = _case(instances=[{"n": 1, "instance_id": "wf-1", "definition_id": "def-a"}])
    rows = [{"task_id": "wf-1:s1", "workflow_id": "wf-OTHER", "status": "pending",
             "decision": None, "acted_by": None, "acted_at": None, "comment": None}]
    assert cp.project_approvals(case, rows) == []


# ── OPTIONS / OUTPUT_ARTIFACT: ALWAYS EMPTY (NOT SOURCED FROM THE RUNNER) ───────────────────

def test_options_and_output_artifact_are_always_empty():
    case = _case(instances=[{"n": 1, "instance_id": "wf-1", "definition_id": "def-a"}],
                terminal="x")
    defs = {"def-a": _definition("def-a")}
    payload = cp.project_workflow_case(case, defs, task_rows=[{"task_id": "wf-1:s1",
                                                                "workflow_id": "wf-1",
                                                                "status": "pending"}])
    assert payload["options"] == []
    assert payload["output_artifact"] is None
