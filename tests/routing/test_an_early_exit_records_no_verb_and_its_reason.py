"""An early exit of `execute_subtask` records that there was NO verb, and why.

`execute_subtask` returned at four points before the `subtask_slots_decision` materialization, so
the gateway's `resolved_intent` kept /route_intent's extraction: an answer with no verb carried
neither a verb nor any record of why. Each exit now emits one materialization with
`verb_iri == ""`, a `disposition` and a `no_verb_reason`. The gateway reader carries the reason
and never lets a no-verb record overwrite a routed one.

a1-a4 drive the four exits; a5 is the control (routed path: same gate, different decision).
b1-b3 drive the gateway reader's real branch body. c1 loads the sandbox approval workflows
through the real loader.
"""
from __future__ import annotations

import ast
import json
import logging
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.iagent.defs import dynamic_supervisor as ds  # noqa: E402

_ASSET = "subtask_slots_decision"
_GW = (_REPO / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")


# ── doubles ──────────────────────────────────────────────────────────────────

class _Stop(BaseException):
    """Aborts the routed path right after its materialization (a5)."""


class _Log:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _Ctx:
    run_id = "run-1"
    log = _Log()

    def __init__(self, stop_after_slots: bool = False):
        self.events = []
        self._stop = stop_after_slots

    def get_mapping_key(self):
        return "task_0"

    def log_event(self, ev):
        key = list(ev.asset_key.path)
        self.events.append((key, {k: v.value for k, v in ev.metadata.items()}))
        if self._stop and key == [_ASSET]:
            raise _Stop()

    def slots(self):
        return [m for k, m in self.events if k == [_ASSET]]


class _Cfg:
    user_query = "how concentrated is purchasing on lot 4"
    user_persona = "PORTFOLIO_LEAD"
    user_email = "alice@example.com"
    trace_id = "t"
    session_id = "s"
    thread_id = "th"
    entitled_domains = ["MAINTENANCE"]
    entity_refs = None
    pre_resolved = None
    predicate_fallback_score_threshold = 0.5
    slots = None
    spoken_slot = ""
    spoken_answer = ""
    bound_slots = None


_TASK = {"sub_query": "how concentrated is purchasing on lot 4"}
_TEL = {"fallback_reason": "subject_unknown", "subject_uri": "mesh:Lot",
        "subject_instance_id": "4", "subject_instance_label": "Lot 4"}


@pytest.fixture
def drive(monkeypatch):
    fallbacks = []

    def _run(status, predicate, telemetry, ctx=None):
        ctx = ctx or _Ctx()
        monkeypatch.setattr(ds, "_classify_route",
                            lambda *a, **k: (status, predicate, telemetry))
        monkeypatch.setattr(ds, "_log_subtask_route_assets", lambda *a, **k: None)
        monkeypatch.setattr(
            ds, "_call_engine_a_fallback",
            lambda *a, **k: fallbacks.append(k) or {"route_status": "fallback"},
        )
        try:
            out = ds.execute_subtask.compute_fn.decorated_fn(ctx, _Cfg(), dict(_TASK))
        except _Stop:
            out = None
        return ctx, out

    _run.fallbacks = fallbacks
    return _run


def _one(ctx):
    got = ctx.slots()
    assert len(got) == 1, f"expected exactly one {_ASSET}, got {len(got)}"
    return got[0]


# ── a1-a4: the four exits ────────────────────────────────────────────────────

def test_a1_infra_error_records_no_verb(drive):
    ctx, _ = drive(ds._ROUTING_INFRA_ERROR, None, dict(_TEL, fallback_reason="engine_o_down"))
    md = _one(ctx)
    assert md["verb_iri"] == ""
    assert md["disposition"] == "infra_error"
    assert md["no_verb_reason"] == "routing_infra_error"
    assert md["fallback_detail"] == "engine_o_down"
    assert md["rejected_verb_iri"] == ""


def test_a2_abstain_records_no_verb(drive):
    ctx, _ = drive(ds._ROUTING_NO_MATCH, None,
                   dict(_TEL, fallback_reason="no_verb_classified", candidate_verbs=["mesh:a"]))
    md = _one(ctx)
    assert md["verb_iri"] == ""
    assert md["disposition"] == "abstain"
    assert md["no_verb_reason"] == "no_verb_classified"
    assert md["fallback_detail"] == "no_verb_classified"
    assert md["rejected_verb_iri"] == ""
    assert md["subject_instance_label"] == "Lot 4"


def test_a3_no_predicate_matched_records_no_verb(drive):
    ctx, _ = drive(ds._ROUTING_NO_MATCH, None, dict(_TEL, fallback_reason="subject_unknown"))
    md = _one(ctx)
    assert md["verb_iri"] == ""
    assert md["disposition"] == "fallback"
    assert md["no_verb_reason"] == "no_predicate_matched"
    assert md["fallback_detail"] == "subject_unknown"
    assert md["rejected_verb_iri"] == ""
    assert len(drive.fallbacks) == 1  # the fallback itself is still called


def test_a4_low_confidence_records_no_verb_and_the_rejected_one(drive):
    pred = {"verb_iri": "mesh:rejectedVerb", "score": 0.1, "endpoint": "http://x"}
    ctx, _ = drive(ds._ROUTING_MATCHED, pred, dict(_TEL, fallback_reason=""))
    md = _one(ctx)
    assert md["verb_iri"] == ""          # the rejected verb is NEVER the verb
    assert md["disposition"] == "fallback"
    assert md["no_verb_reason"] == "low_confidence"
    assert md["fallback_detail"] == ""
    assert md["rejected_verb_iri"] == "mesh:rejectedVerb"
    assert len(drive.fallbacks) == 1


# ── a5: the control ──────────────────────────────────────────────────────────

def test_a5_the_routed_path_still_carries_a_verb_and_no_reason(drive):
    pred = {"verb_iri": "mesh:goodVerb", "score": 0.9, "endpoint": "http://x",
            "owner_persona": "ANALYST"}
    ctx, _ = drive(ds._ROUTING_MATCHED, pred, dict(_TEL, fallback_reason=""),
                   ctx=_Ctx(stop_after_slots=True))
    md = _one(ctx)
    assert md["verb_iri"] == "mesh:goodVerb"
    assert md["no_verb_reason"] == ""
    assert md["rejected_verb_iri"] == ""
    assert set(md) >= {"no_verb_reason", "fallback_detail", "rejected_verb_iri"}


# ── b1-b3: the gateway reader (its real branch body, executed) ───────────────

def _reader():
    for n in ast.walk(ast.parse(_GW)):
        if isinstance(n, ast.If) and _ASSET in ast.unparse(n.test):
            body = "\n".join(ast.unparse(s) for s in n.body)
            src = "for mat in mats:\n" + "\n".join("    " + ln for ln in body.splitlines())
            return compile(src, "<gateway reader>", "exec")
    raise AssertionError("no gateway branch for " + _ASSET)


def _read(records):
    ns = {
        "mats": records, "_metadata_dict": lambda m: m, "json": json,
        "logger": logging.getLogger("t"), "run_id": "r",
        "_artifact_bundle": {"resolved_intent": {"mode": "extract", "entity_refs": []}},
        "_resolved_from_routed": False,
    }
    exec(_reader(), ns)
    return ns["_artifact_bundle"]["resolved_intent"]


_NOVERB = {"verb_iri": "", "disposition": "abstain", "no_verb_reason": "no_verb_classified",
           "fallback_detail": "subject_unknown", "rejected_verb_iri": "",
           "accepted_slots": "{}", "refused_slots": "[]"}
_ROUTED = {"verb_iri": "mesh:goodVerb", "disposition": "route",
           "accepted_slots": json.dumps({"a": 1}), "refused_slots": "[]"}


def test_b1_a_lone_no_verb_record_maps_with_its_reason():
    ri = _read([dict(_NOVERB, rejected_verb_iri="mesh:r")])
    assert ri["verb_iri"] == ""
    assert ri["no_verb_reason"] == "no_verb_classified"
    assert ri["fallback_detail"] == "subject_unknown"
    assert ri["rejected_verb_iri"] == "mesh:r"
    assert "mode" not in ri  # replaced the extraction, as a routed one does


def test_b2_a_no_verb_record_after_a_routed_one_leaves_the_routed_verb():
    ri = _read([_ROUTED, _NOVERB])
    assert ri["verb_iri"] == "mesh:goodVerb"
    assert ri["no_verb_reason"] == ""


def test_b3_a_routed_record_after_a_no_verb_one_ends_routed():
    ri = _read([_NOVERB, _ROUTED])
    assert ri["verb_iri"] == "mesh:goodVerb"
    assert ri["no_verb_reason"] == ""
    assert ri["accepted_slots"] == {"a": 1}


# ── c1: sandbox approvals wait 72 hours ──────────────────────────────────────

@pytest.mark.parametrize("name", ["maint_fault_propose", "maint_supervisor_review"])
def test_c1_sandbox_approvals_wait_72_hours(name):
    from agent_fleet.restate_analyst.workflow_definition import load_workflow_definition

    d = load_workflow_definition(
        _REPO / "policy" / "overlays" / "openddil-lab" / "workflows" / f"{name}.yaml"
    )
    awaits = [s for s in d.steps if s.kind == "human_await"]
    assert awaits, "no approval step found"
    for s in awaits:
        assert s.deadline_seconds == 259200, (name, s.id, s.deadline_seconds)
