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

── WHAT EACH PANEL FIELD READS, AND WHEN IT IS ABSENT ─────────────────────────────────────────

Each field has ONE declared source. Where the source says nothing the field is absent; it is
never guessed, and never emitted empty to look present (an empty list claims "there are none").

``instances[].current_stage`` (``∈ definition.domain_stages``):
  (a) a definition with exactly ONE domain stage: that stage, for any status;
  (b) status ``completed``: the LAST domain stage;
  (c) status ``running`` / ``failed``: the stage declared (``stage:`` on a step) by the last
      BEGUN step. Step 0 is begun once the instance exists; a ``human_await`` is begun iff a task
      row exists for ``{workflow_id}:{step.id}`` (pending or decided); the walk stops at the first
      ``human_await`` with no row, because nothing after an unbegun await can have begun. The
      definition validator admits ``stage`` only on step 0 and on a non-grouped ``human_await``,
      the only beginnings this read-only route can observe;
  (d) otherwise ``None`` -- a multi-stage definition that declares no stage at a begun step.

``definition.steps[].title`` / ``.audience``: the task row's title when one exists for the step
  (rendered at registration); else the declared title if it holds no ``{``; else ``None``.
  ``audience`` holding a ``{`` is ``None``. Templates are never rendered here.

``options``: the ``payload.options`` the decide task was REGISTERED with (the runner resolves the
  step's ``chooses_from`` at registration and carries the list on the task row). Read from the
  LATEST instance (chain order) whose task row carries a list there. Each element becomes
  ``{id: verb, label: label or verb, data: the rest, artifact_uri: None}``; an element with no
  string ``verb`` is skipped. If no row carries options the ``options`` KEY IS OMITTED.

``output_artifact``: the case's newest maintenance ActionRecord -- the record the release writes,
  read by the route (this module does no I/O) and handed in as ``output_artifact``. Its
  ``released_at`` is the record's own ``valid_as_of`` (epoch ms stamped at the write, which is the
  release). ``None`` when the case has no emit step in any opened definition, or no record yet.
  If the store cannot be read the ROUTE answers 503; a null would claim "not released".
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

def _rendered(raw: Any) -> Any:
    """A declared string that still holds a ``{placeholder}`` is NOT shown: ``None`` (cortex falls
    back to the step id). Templates are never rendered here -- this module is pure."""
    return None if isinstance(raw, str) and "{" in raw else raw


def _step_payload(step: Any, workflow_id: Optional[str] = None,
                  titles: Optional[dict] = None) -> dict:
    """``CaseDefinitionStep`` -- ``title``/``audience`` exist only on some step kinds
    (e.g. ``human_await``); ``getattr(..., default)`` reads ``None`` for the rest rather than
    raising. ``title``: the task row's title for ``{workflow_id}:{step.id}`` (rendered at
    registration, so the truth), else the raw title if it holds no ``{``, else ``None``.
    ``audience`` is on no task row, so it is ``None`` whenever it holds a placeholder."""
    row_title = (titles or {}).get(f"{workflow_id}:{step.id}")
    title = row_title if isinstance(row_title, str) and row_title else _rendered(
        getattr(step, "title", None))
    return {
        "id": step.id,
        "kind": step.kind,
        "title": title,
        "audience": _rendered(getattr(step, "audience", None)),
    }


def _definition_payload(d: Any, workflow_id: Optional[str] = None,
                        titles: Optional[dict] = None) -> dict:
    """``CaseDefinition`` -- bound fields only (id, name, participants, domain_stages, steps),
    per the roll spec. Per INSTANCE, because a step title is rendered per instance."""
    return {
        "id": d.id,
        "name": d.name,
        "participants": [{"role": p.get("role")} for p in (d.participants or [])],
        "domain_stages": list(d.domain_stages or []),
        "steps": [_step_payload(s, workflow_id, titles) for s in d.steps],
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


def _begun_stage(d: Any, workflow_id: Optional[str], task_ids: "set[str]") -> Optional[str]:
    """The stage in force at the last BEGUN step of ``d`` (rule (c) of the module docstring)."""
    stage: Optional[str] = None
    for i, step in enumerate(d.steps):
        if getattr(step, "kind", None) == "human_await" and i > 0:
            if f"{workflow_id}:{step.id}" not in task_ids:
                break  # an unbegun await: nothing after it can have begun
        declared = getattr(step, "stage", None)
        if declared:
            stage = declared
    return stage


def _current_stage(d: Any, status: str, workflow_id: Optional[str],
                   task_ids: "set[str]") -> Optional[str]:
    stages = list(d.domain_stages or [])
    if len(stages) == 1:
        return stages[0]
    if status == "completed":
        return stages[-1] if stages else None
    if status in ("running", "failed"):
        return _begun_stage(d, workflow_id, task_ids)
    return None


def _options_of(row: dict) -> Optional[list]:
    payload = row.get("payload")
    opts = payload.get("options") if isinstance(payload, dict) else None
    return opts if isinstance(opts, list) else None


def project_options(case: dict, task_rows: list[dict]) -> Optional[list[dict]]:
    """``CaseOption[]`` from the LATEST instance (chain order) whose task row carries a list at
    ``payload.options``; ``None`` (key omitted by the caller) when no row does."""
    for inst in reversed(case.get("instances") or []):
        wf = inst.get("instance_id")
        if not wf:
            continue
        for row in task_rows:
            if row.get("workflow_id") != wf:
                continue
            opts = _options_of(row)
            if opts is None:
                continue
            out = []
            for o in opts:
                if not isinstance(o, dict) or not isinstance(o.get("verb"), str):
                    continue
                out.append({
                    "id": str(o["verb"]),
                    "label": o.get("label") or o["verb"],
                    "data": {k: v for k, v in o.items() if k not in ("verb", "label")},
                    "artifact_uri": None,
                })
            return out
    return None


def has_emit_step(case: dict, definitions: dict[str, Any]) -> bool:
    """True iff any OPENED instance's definition has an ``emit`` step (so an ActionRecord may
    exist and the route must read the store)."""
    for inst in case.get("instances") or []:
        d = definitions.get(inst.get("definition_id"))
        if d is not None and any(getattr(s, "kind", None) == "emit" for s in d.steps):
            return True
    return False


def release_artifact(case_id: str, records: list[dict]) -> Optional[dict]:
    """``CaseArtifact`` from the NEWEST action record (``valid_as_of``, epoch ms). A record with
    no positive ``valid_as_of`` has no release time and is never dated; it is passed over."""
    dated = [r for r in records if isinstance(r.get("valid_as_of"), (int, float))
             and r["valid_as_of"] > 0]
    if not dated:
        return None
    newest = max(dated, key=lambda r: r["valid_as_of"])
    return {
        "uri": f"/cases/{case_id}/action",
        "label": "Maintenance action record",
        "released_at": _iso_from_epoch_ms(newest["valid_as_of"]),
    }


def project_instances(case: dict, definitions: dict[str, Any],
                      task_rows: Optional[list[dict]] = None) -> list[dict]:
    """``CaseInstance[]``, in chain order. An instance whose definition could not be loaded is
    OMITTED rather than emitted with a fabricated definition -- the route maps that to a 503
    before this ever runs, so this is defensive, not the normal path."""
    insts = case.get("instances") or []
    task_ids = {r.get("task_id") for r in (task_rows or []) if r.get("task_id")}
    titles = {r["task_id"]: r.get("title") for r in (task_rows or [])
              if r.get("task_id") and isinstance(r.get("title"), str) and r["title"]}
    out = []
    for i, inst in enumerate(insts):
        d = definitions.get(inst.get("definition_id"))
        if d is None:
            continue
        status = _instance_status(case, i, len(insts))
        out.append({
            "workflow_id": inst.get("instance_id"),
            "definition": _definition_payload(d, inst.get("instance_id"), titles),
            "current_stage": _current_stage(d, status, inst.get("instance_id"), task_ids),
            "status": status,
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


def project_workflow_case(case: dict, definitions: dict[str, Any], task_rows: list[dict],
                          output_artifact: Optional[dict] = None) -> dict:
    """Build the ``WorkflowCasePayload`` dict. ``output_artifact`` is handed in by the route (this
    module does no I/O); ``options`` is omitted when no task row carries any -- see the module
    docstring."""
    out = {
        "subject_ref": case.get("case_id"),
        "instances": project_instances(case, definitions, task_rows),
        "history": project_history(case),
        "approvals": project_approvals(case, task_rows),
        "output_artifact": output_artifact,
    }
    options = project_options(case, task_rows)
    if options is not None:
        out["options"] = options
    return out
