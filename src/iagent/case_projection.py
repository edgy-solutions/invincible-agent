"""Pure projection of WorkflowRunner case state into cortex's WorkflowCasePayload.

Source of the runner shapes this module reads: ``agent_fleet/restate_analyst/workflow_runner.py``
(the ``case`` and ``instance_spec`` handlers) and ``agent_fleet/restate_analyst/main.py`` (the
``task = {"id": f"{workflow_id}:{step.id}", ...}`` registration a ``human_await`` step makes --
see its use at ``main.py`` ~line 2166).

Source of the target shape: ``cortex-ui`` ``src/archetypes/workflow-case/contract.ts`` at sha
``2915e36004e1dda7b233358b55a9501963f2bb8c`` -- ``WorkflowCasePayload``, ``CaseInstance``,
``CaseDefinition``, ``CaseDefinitionStep``, ``CaseHistoryEntry``, ``CaseApproval``.

Every function here is pure: it takes runner dicts (already fetched over Restate/SQL by the
route) and returns plain dicts shaped like the contract. No I/O.

── WHAT THIS MODULE DOES NOT SOURCE, AND WHY ──────────────────────────────────────────────────

``instances[].current_stage``: the contract says it "must be ∈ definition.domain_stages" -- no
runner read available to this route names which domain_stage an instance currently sits at (the
case record's ``transitions[].to`` is a definition id or a terminal name, never a domain_stage).
Always ``None``.

``options`` / ``output_artifact``: the case record carries an instance's own ``outputs`` only as
the INPUT to the *next* instance (``instance_spec(n+1)["outputs"]`` holds instance n's results);
the case's LAST instance has no n+1, so its own outputs are not reachable through ``case`` or
``instance_spec`` at all -- only through each instance's ``outbox`` channel, which requires
knowing the channel name per instance (not declared anywhere this route can read generically).
Rather than fabricate a shape the runner state does not hand us, both are emitted empty
(``[]`` / ``None``) for every case. A follow-up that wants real options/artifacts needs to read
each instance's declared ``emit`` channel from its ``WorkflowDefinition`` and call ``outbox``.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional


# ── ENTITLEMENT ─────────────────────────────────────────────────────────────────────────────

def instance1_facts(instance1_spec: Optional[dict]) -> Optional[dict]:
    """The event facts the case opened on, from instance 1's ``trigger`` -- or ``None`` if
    instance 1 has never run (``instance_spec`` returns falsy) or carries no dict trigger."""
    if not instance1_spec:
        return None
    trig = instance1_spec.get("trigger")
    return trig if isinstance(trig, dict) else None


def submitter_authz_id(instance1_spec: Optional[dict]) -> Optional[str]:
    """``facts["dropped_by"]["authz_id"]`` off instance 1's trigger, or ``None`` -- the same
    ``{"authz_id": ...}`` shape ``GET /ingest/{id}/status`` already echoes as ``dropped_by``."""
    facts = instance1_facts(instance1_spec)
    if facts is None:
        return None
    dropped = facts.get("dropped_by")
    if not isinstance(dropped, dict):
        return None
    v = dropped.get("authz_id")
    return v if isinstance(v, str) and v else None


def case_labels(case: dict, instance1_spec: Optional[dict],
                 definitions: dict[str, Any]) -> list[str]:
    """{facts["domain_type"] of instance 1} ∪ {each opened instance's definition.classification,
    non-null} -- case-sensitive as stored; the caller side case-folds when comparing. A case
    with no instances yet (``case["instances"]`` empty) and no instance 1 spec yields ``[]``."""
    labels: set[str] = set()
    facts = instance1_facts(instance1_spec)
    if facts is not None:
        dt = facts.get("domain_type")
        if isinstance(dt, str) and dt:
            labels.add(dt)
    for inst in case.get("instances") or []:
        d = definitions.get(inst.get("definition_id"))
        if d is not None and getattr(d, "classification", None):
            labels.add(d.classification)
    return sorted(labels)


def can_view_case(case: dict, instance1_spec: Optional[dict], definitions: dict[str, Any], *,
                   caller_authz_id: str, caller_domains: "set[str] | list[str]") -> bool:
    """(a) the caller is the submitter OR (b) labels(case) is non-empty and the caller holds an
    entitlement cell whose domain equals EVERY label, case-insensitively. A case with no labels
    and no identifiable submitter (e.g. no instances yet) is visible to no one via (b)."""
    sub = submitter_authz_id(instance1_spec)
    if sub is not None and caller_authz_id == sub:
        return True
    labels = case_labels(case, instance1_spec, definitions)
    if not labels:
        return False
    held = {str(d).casefold() for d in caller_domains}
    return all(lbl.casefold() in held for lbl in labels)


# ── PROJECTION ──────────────────────────────────────────────────────────────────────────────

def _step_payload(step: Any) -> dict:
    """``CaseDefinitionStep`` -- ``title``/``audience`` exist only on some step kinds
    (e.g. ``human_await``); ``getattr(..., default)`` reads ``None`` for the rest rather than
    raising."""
    return {
        "id": step.id,
        "kind": step.kind,
        "title": getattr(step, "title", None),
        "audience": getattr(step, "audience", None),
    }


def _definition_payload(d: Any) -> dict:
    """``CaseDefinition`` -- bound fields only (id, name, participants, domain_stages, steps),
    per the roll spec."""
    return {
        "id": d.id,
        "name": d.name,
        "participants": [{"role": p.get("role")} for p in (d.participants or [])],
        "domain_stages": list(d.domain_stages or []),
        "steps": [_step_payload(s) for s in d.steps],
    }


def _instance_status(case: dict, index: int, total: int) -> str:
    """"completed" for every instance but the last: ``workflow_runner._run_case`` opens
    instance n+1 only after instance n's ``ctx.workflow_call`` returned normally, so every
    earlier instance in the chain necessarily finished. The LAST instance mirrors the case's
    own outcome: ``case["state"] == "failed"`` (the ``TerminalError`` branch records a
    transition ``to="failed"`` but never sets ``case["terminal"]`` -- see ``_run_case``'s
    ``except`` block) means "failed"; ``case["terminal"]`` set means "completed"; neither
    means the case (and so this instance) is still "running"."""
    if index < total - 1:
        return "completed"
    if case.get("state") == "failed":
        return "failed"
    if case.get("terminal"):
        return "completed"
    return "running"


def project_instances(case: dict, definitions: dict[str, Any]) -> list[dict]:
    """``CaseInstance[]``, in chain order. An instance whose definition could not be loaded is
    OMITTED rather than emitted with a fabricated definition -- the route maps that to a 503
    before this ever runs, so this is defensive, not the normal path."""
    insts = case.get("instances") or []
    out = []
    for i, inst in enumerate(insts):
        d = definitions.get(inst.get("definition_id"))
        if d is None:
            continue
        out.append({
            "workflow_id": inst.get("instance_id"),
            "definition": _definition_payload(d),
            "current_stage": None,  # NO SOURCE -- see module docstring.
            "status": _instance_status(case, i, len(insts)),
        })
    return out


def project_history(case: dict) -> list[dict]:
    """``CaseHistoryEntry[]``, in transition order. ``workflow_id`` is the instance CURRENT at
    that transition: walk the transitions in order, tracking ``current`` starting at the case's
    own id; a transition recorded with an explicit ``instance_id`` (``_record``'s kwarg, set
    only by the per-instance loop in ``_run_case``, including its own failure branch after an
    instance has already recorded at least one transition of its own) moves ``current`` to that
    instance for itself and every entry after it, until the next one moves it again. A failure
    that happens before ANY instance has recorded its own transition (e.g. selection failing
    before instance 1 ever opens, or instance 1's own run raising before it produces its first
    recorded transition) is attributed to the case itself, which is the honest reading: no
    instance-scoped transition for it exists yet."""
    out = []
    current = case.get("case_id")
    for t in case.get("transitions") or []:
        inst = t.get("instance_id")
        if inst:
            current = inst
        out.append({
            "at": t.get("at"),
            "workflow_id": current,
            "event": t.get("outcome"),
            "stage": t.get("to"),
            "actor": t.get("by"),
        })
    return out


def _iso_from_epoch_ms(ms: Optional[int]) -> Optional[str]:
    if not isinstance(ms, (int, float)):
        return None
    return _dt.datetime.fromtimestamp(ms / 1000, tz=_dt.timezone.utc).isoformat()


def project_approvals(case: dict, task_rows: list[dict]) -> list[dict]:
    """``CaseApproval[]``, in chain order. One entry per logical task (``human_task_projection``
    carries one ROW PER RECIPIENT of the same task_id; they are collapsed to one entry since
    ``mark_task_resolved`` writes the same decision to all of them). ``step_id`` is recovered by
    stripping the ``"{workflow_id}:"`` prefix every ``human_await`` registration writes
    (``agent_fleet/restate_analyst/main.py``: ``task = {"id": f"{workflow_id}:{step.id}", ...}``,
    carried onto the row via its own ``workflow_id=`` kwarg to ``register_task``). A row whose
    task_id does not carry that exact prefix (e.g. a grouped-review task registered under a
    bare id) is SKIPPED -- the contract requires ``step_id``, and guessing one would be exactly
    the fabrication this module's docstring refuses elsewhere. ``task`` (the live
    ``ApprovalTaskPayload``) is omitted per the roll spec ("omit unless trivially available")."""
    by_task_id: dict[str, dict] = {}
    for row in task_rows:
        tid = row.get("task_id")
        if tid and tid not in by_task_id:
            by_task_id[tid] = row
    out = []
    for inst in case.get("instances") or []:
        wf = inst.get("instance_id")
        if not wf:
            continue
        prefix = f"{wf}:"
        for task_id, row in by_task_id.items():
            if row.get("workflow_id") != wf or not task_id.startswith(prefix):
                continue
            step_id = task_id[len(prefix):]
            if not step_id:
                continue
            pending = row.get("status") == "pending"
            out.append({
                "workflow_id": wf,
                "step_id": step_id,
                "status": "pending" if pending else "decided",
                "decided_by": None if pending else row.get("acted_by"),
                "decision": None if pending else row.get("decision"),
                "reason": None if pending else (row.get("comment") or None),
                "decided_at": None if pending else _iso_from_epoch_ms(row.get("acted_at")),
            })
    return out


def project_workflow_case(case: dict, definitions: dict[str, Any],
                          task_rows: list[dict]) -> dict:
    """Build the ``WorkflowCasePayload`` dict. ``options``/``output_artifact`` are always
    empty/``None`` -- see the module docstring."""
    return {
        "subject_ref": case.get("case_id"),
        "instances": project_instances(case, definitions),
        "history": project_history(case),
        "options": [],
        "approvals": project_approvals(case, task_rows),
        "output_artifact": None,
    }
