"""A task is matched to the viewer at READ time, then withheld by label (ADR-0068 s6, built against
the draft at sha e2ae0272, PR #347).

Seals, each with the control that shares its gate and its population:

  S1  recipient by authz_id vs by capability -- the same task reaches a named recipient and a person
      who merely holds `can_act` on its audience; a person with neither, and a barred actor with the
      capability, get nothing.
  S2  a grant change between two reads shows on the second, with no re-registration.
  S3  a task whose object carries a label the viewer lacks is WITHHELD (absent: no key, no id, no
      title in the body) and a routing fault names the task, the addressee and the dimension and
      label; the SAME task with the label granted is the control (served, no fault).
  S4  `approvals[].task` and case admission follow the same rule: a submitter who lacks a label of
      the case reads the case but not the task on it; a holder with no label is refused the 404 on a
      case that has labels and admitted on one that has none.
  S5  the notice status read is open to a reader of the notice who holds no task row.
  S6  the Needs-you counts equal the task list's, per kind, for the same viewer.
  S7  the delegate is admitted by a live row of `policy/queue_delegates.yaml`; an expired row and no
      row are policy refusals naming the binding; the delegated read is marked and audited.

NO persona, group, domain or label VALUE is named in the code under test; the strings here are
fixtures this file supplies.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from collections import Counter
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import case_projection, gateway, human_tasks, ingest_status  # noqa: E402
from tests.test_cases_route import (  # noqa: E402
    _CASE_ONE_INSTANCE, _SPEC1, _FakeRestate, _definition, _user,
)

LABEL = "LBL-ONE"
NOW = int(dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)


class _Store:
    """The task store the real `viewer_tasks` and `record_routing_fault` run against."""

    def __init__(self):
        self.rows: list[dict] = []
        self.faults: dict[tuple, dict] = {}
        self.writes = 0
        self.grants: set[tuple] = set()   # (audience, viewer) pairs that hold can_act

    def add(self, task_id, recipient, *, audience="aud:x", case_id=None, kind="k1", status="pending",
            excludes="[]", workflow_id=None, title="a task", granted=True):
        self.writes += 1
        if granted:   # the recipient was expanded from the audience: still in the group by default
            self.grants.add((audience, recipient))
        self.rows.append({
            "id": f"{task_id}/{recipient}", "kind": kind, "task_id": task_id, "workflow_id": workflow_id,
            "audience": audience, "recipient_id": recipient, "status": status, "title": title,
            "summary": "s", "requested_by": "svc:x", "subject_ref": None, "payload": {},
            "created_at": NOW + len(self.rows), "workflow_service": None, "promise_name": None,
            "case_id": case_id, "decision": None, "acted_by": None, "acted_at": None, "comment": None,
            "excludes": excludes})


class _Cursor:
    def __init__(self, store):
        self.s, self.out = store, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _filters(self, sql, params):
        def ok(r):
            i = 0
            for col, fn in (("case_id = %s", lambda r, p: r["case_id"] == p),
                            ("workflow_id = ANY(%s)", lambda r, p: r["workflow_id"] in p),
                            ("kind = ANY(%s)", lambda r, p: r["kind"] in p),
                            ("audience = ANY(%s)", lambda r, p: r["audience"] in p)):
                if col in sql:
                    if not fn(r, params[i]):
                        return False
                    i += 1
            return True
        return ok

    def execute(self, sql, params=()):
        params = list(params)
        if sql.lstrip().startswith("INSERT INTO routing_fault"):
            tid, who, dim, lbl, route, obo = params[:6]
            k = (tid, who, dim, lbl)
            rec = self.s.faults.setdefault(k, {"task_id": tid, "addressee": who, "dimension": dim,
                                               "label": lbl, "route": route, "on_behalf_of": obo,
                                               "seen_count": 0})
            rec["seen_count"] += 1
            return
        if "DISTINCT ON" in sql:
            status, rest = params[0], params[1:]
            ok = self._filters(sql, rest)
            seen, out = set(), []
            for r in sorted(self.s.rows, key=lambda r: -r["created_at"]):
                if (r["status"] == status and r["excludes"] is not None and ok(r)
                        and r["task_id"] not in seen):
                    seen.add(r["task_id"]); out.append(dict(r))
            self.out = out
            return
        viewer, rest = params[0], params[1:]
        status = None
        if " AND status = %s" in sql:
            status, rest = rest[0], rest[1:]
        ok = self._filters(sql, rest)
        self.out = [dict(r) for r in sorted(self.s.rows, key=lambda r: -r["created_at"])
                    if r["recipient_id"] == viewer and (status is None or r["status"] == status) and ok(r)]

    def fetchall(self):
        return self.out

    def fetchone(self):
        return self.out[0] if self.out else None


class _Conn:
    def __init__(self, store):
        self.s = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, cursor_factory=None):
        return _Cursor(self.s)

    def commit(self):
        pass


@pytest.fixture
def store(monkeypatch):
    s = _Store()
    monkeypatch.setattr(human_tasks, "_pg_connect", lambda: _Conn(s))
    monkeypatch.setattr(human_tasks, "can_act_or_unavailable",
                        lambda audience, viewer: (audience, viewer) in s.grants)
    return s


@pytest.fixture
def labelled(monkeypatch):
    """`{case_id: [labels]}`: what each case's object carries. The runner is not consulted."""
    labels: dict[str, list] = {}

    async def _state(case_id):
        return None if case_id not in labels else ({"case_id": case_id}, None, {})
    monkeypatch.setattr(gateway, "_case_state", _state)
    monkeypatch.setattr(case_projection, "case_labels", lambda case, spec, defs: list(labels[case["case_id"]]))
    return labels


@pytest.fixture
def as_user(monkeypatch):
    # the declaration decoration reads the task-kind seed; it is not what these seals are about
    monkeypatch.setattr(human_tasks, "decorate_with_declarations",
                        lambda rows: [dict(r, declaration={"kind": r["kind"], "declared": False, "archetype": None,
                                                  "badge": None, "title": None, "accepts": [],
                                                  "reason_required": []}) for r in rows])
    def _login(authz_id, domains=()):
        u = _user(authz_id, domains)
        u.email = authz_id
        gateway.app.dependency_overrides[gateway.get_current_user] = lambda: u
        return TestClient(gateway.app)
    yield _login
    gateway.app.dependency_overrides.clear()


def _ids(resp, key="tasks"):
    return sorted(t["task_id"] for t in resp.json()[key])


# -- S1 ---------------------------------------------------------------------------------------

def test_S1_a_recipient_is_matched_by_authz_id_and_a_capability_holder_by_capability(store):
    store.add("t-1", "bob")
    store.grants.add(("aud:x", "carol"))
    by_id = human_tasks.viewer_tasks("bob")
    by_cap = human_tasks.viewer_tasks("carol")
    assert [(r["task_id"], r["matched_by"]) for r in by_id] == [("t-1", human_tasks.MATCH_AUTHZ_ID)]
    assert [(r["task_id"], r["matched_by"]) for r in by_cap] == [("t-1", human_tasks.MATCH_CAPABILITY)]


def test_S1_CONTROL_neither_a_row_nor_the_capability_matches_nothing(store):
    store.add("t-1", "bob")
    store.grants.add(("aud:x", "carol"))
    assert human_tasks.viewer_tasks("dave") == []


def test_S1_CONTROL_a_barred_actor_with_the_capability_is_not_matched(store):
    store.add("t-1", "bob", excludes=json.dumps(["carol"]))
    store.grants.add(("aud:x", "carol"))
    assert human_tasks.viewer_tasks("carol") == []
    store.rows[0]["excludes"] = "[]"            # the same task, the same grant, no bar
    assert [r["task_id"] for r in human_tasks.viewer_tasks("carol")] == ["t-1"]


def test_S1_a_row_that_never_recorded_its_bar_is_not_matched_by_capability(store):
    store.add("t-1", "bob", excludes=None)
    store.grants.add(("aud:x", "carol"))
    assert human_tasks.viewer_tasks("carol") == []      # the bar is UNKNOWN, not "nobody"


# -- S2 ---------------------------------------------------------------------------------------

def test_S2_a_grant_made_between_two_reads_shows_on_the_second_with_no_registration(store):
    store.add("t-1", "bob")
    assert human_tasks.viewer_tasks("carol") == []
    writes = store.writes
    store.grants.add(("aud:x", "carol"))                       # the only thing that changes
    assert [r["task_id"] for r in human_tasks.viewer_tasks("carol")] == ["t-1"]
    assert store.writes == writes, "no row was registered between the two reads"
    store.grants.discard(("aud:x", "carol"))                   # and a revoke shows the same way
    assert human_tasks.viewer_tasks("carol") == []


def test_S2_a_revoked_recipient_row_drops_out_on_the_next_read(store):
    """Every row was expanded from its audience at registration; the row alone grants nothing."""
    store.add("t-1", "bob", granted=False)                   # expanded once; bob has since left the group
    assert human_tasks.viewer_tasks("bob") == []


def test_S2_CONTROL_the_same_recipient_still_in_the_group_still_sees_the_task(store):
    store.add("t-1", "bob")                                  # same row, grant still held
    got = human_tasks.viewer_tasks("bob")
    assert [r["task_id"] for r in got] == ["t-1"] and got[0]["matched_by"] == human_tasks.MATCH_AUTHZ_ID


def test_S2_a_revoke_between_two_reads_shows_on_the_second_with_no_write(store):
    store.add("t-1", "bob")
    writes = store.writes
    assert [r["task_id"] for r in human_tasks.viewer_tasks("bob")] == ["t-1"]
    store.grants.discard(("aud:x", "bob"))
    assert human_tasks.viewer_tasks("bob") == []
    assert store.writes == writes


def test_S2_a_revoked_recipient_is_gone_from_the_route_too(store, labelled, as_user):
    store.add("t-1", "bob", audience="aud:gone", granted=False)
    store.add("t-2", "bob")
    got = as_user("bob").get("/me/human_tasks").json()
    assert [t["task_id"] for t in got["tasks"]] == ["t-2"]


def test_S2_the_route_reads_the_grant_at_each_read(store, labelled, as_user):
    store.add("t-1", "bob")
    c = as_user("carol")
    assert _ids(c.get("/me/queue")) == []
    store.grants.add(("aud:x", "carol"))
    assert _ids(c.get("/me/queue")) == ["t-1"]


# -- S3 ---------------------------------------------------------------------------------------

def test_S3_a_task_whose_label_the_viewer_lacks_is_withheld_and_recorded(store, labelled, as_user, caplog):
    labelled["c-1"] = [LABEL]
    store.add("t-secret", "bob", case_id="c-1", title="the title nobody may see")
    store.add("t-plain", "bob", case_id=None)
    with caplog.at_level(logging.WARNING, logger="iagent.audit.routing_fault"):
        r = as_user("bob").get("/me/human_tasks")
    assert r.status_code == 200
    assert _ids(r) == ["t-plain"]
    assert "t-secret" not in r.text and "nobody may see" not in r.text, "withheld, never redacted"
    assert list(store.faults) == [("t-secret", "bob", gateway.LABEL_DIMENSION, LABEL)]
    line = next(m for m in caplog.messages if m.startswith("routing_fault "))
    for part in ("task=t-secret", "addressee=bob", f"dimension={gateway.LABEL_DIMENSION}", f"label={LABEL}"):
        assert part in line


def test_S3_CONTROL_the_same_task_with_the_label_granted_is_served_and_no_fault(store, labelled, as_user):
    labelled["c-1"] = [LABEL]
    store.add("t-secret", "bob", case_id="c-1")
    r = as_user("bob", domains=[LABEL.lower()]).get("/me/human_tasks")      # case-insensitive
    assert _ids(r) == ["t-secret"]
    assert store.faults == {}


def test_S3_a_capability_match_is_withheld_the_same_way(store, labelled, as_user):
    labelled["c-1"] = [LABEL]
    store.add("t-secret", "bob", case_id="c-1")
    store.grants.add(("aud:x", "carol"))
    assert _ids(as_user("carol").get("/me/queue")) == []
    assert ("t-secret", "carol", gateway.LABEL_DIMENSION, LABEL) in store.faults
    assert _ids(as_user("carol", domains=[LABEL]).get("/me/queue")) == ["t-secret"]


def test_S3_a_failing_fault_write_never_turns_the_withhold_into_a_serve(store, labelled, as_user, monkeypatch):
    labelled["c-1"] = [LABEL]
    store.add("t-secret", "bob", case_id="c-1")

    def boom():
        raise RuntimeError("store down")
    monkeypatch.setattr(human_tasks, "_pg_connect", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(human_tasks, "viewer_tasks", lambda *a, **k: [dict(store.rows[0], matched_by="authz_id")])
    assert _ids(as_user("bob").get("/me/queue")) == []


def test_S3_the_act_and_the_review_batch_use_the_same_withhold(store, labelled, as_user):
    labelled["c-1"] = [LABEL]
    store.add("wf-1", "bob", case_id="c-1", kind="grouped_review", workflow_id="wf-1")
    r = as_user("bob").get("/reviews/wf-1/batch")
    assert r.status_code == 404 and r.json()["detail"]["error"] == "review_not_found"
    assert ("wf-1", "bob", gateway.LABEL_DIMENSION, LABEL) in store.faults


# -- S4 ---------------------------------------------------------------------------------------

def _real_case(monkeypatch, classification, store):
    from agent_fleet.restate_analyst import workflow_definition
    fake = _FakeRestate(case=_CASE_ONE_INSTANCE, spec1=_SPEC1)
    monkeypatch.setattr(gateway.httpx, "AsyncClient", fake)
    monkeypatch.setattr(workflow_definition, "get_workflow_definition",
                        lambda wf_id: _definition(wf_id, classification=classification))
    monkeypatch.setattr(human_tasks, "list_tasks_for_workflows",
                        lambda ids: [r for r in store.rows if r["workflow_id"] in ids])


def _approval_task(resp):
    appr = resp.json().get("approvals") or []
    assert appr, resp.text[:300]
    return appr[0].get("task")


def test_S4_a_submitter_without_the_label_reads_the_case_but_not_the_task_on_it(store, monkeypatch, as_user):
    # `alice` dropped the case (the spec's dropped_by), so can_view_case admits her; she holds a
    # pending task on it, and the case carries a label her cells do not.
    _real_case(monkeypatch, "SAFETY", store)
    store.add("c-1~1:s1", "alice", case_id="c-1", workflow_id="c-1~1")
    r = as_user("alice").get("/cases/c-1")
    assert r.status_code == 200, r.text
    assert _approval_task(r) is None and "task" not in r.json()["approvals"][0]
    assert ("c-1~1:s1", "alice", gateway.LABEL_DIMENSION, "SAFETY") in store.faults


def test_S4_CONTROL_the_same_submitter_with_the_label_granted_gets_the_task(store, monkeypatch, as_user):
    _real_case(monkeypatch, "SAFETY", store)
    store.add("c-1~1:s1", "alice", case_id="c-1", workflow_id="c-1~1")
    r = as_user("alice", ["safety"]).get("/cases/c-1")
    assert r.status_code == 200, r.text
    assert _approval_task(r)["task_id"] == "c-1~1:s1"
    assert store.faults == {}


def test_S4_a_holder_without_the_label_is_refused_the_404_and_recorded(store, monkeypatch, as_user):
    _real_case(monkeypatch, "SAFETY", store)
    store.add("c-1~1:s1", "bob", case_id="c-1", workflow_id="c-1~1")
    r = as_user("bob").get("/cases/c-1")
    assert r.status_code == 404 and r.json()["detail"] == "case not found"
    assert ("c-1~1:s1", "bob", gateway.LABEL_DIMENSION, "SAFETY") in store.faults


def test_S4_CONTROL_the_same_holder_on_a_case_with_no_label_is_admitted(store, monkeypatch, as_user):
    _real_case(monkeypatch, None, store)
    spec = {"trigger": {"dropped_by": {"authz_id": "alice"}}}      # no domain_type: no label
    gateway_fake = _FakeRestate(case=_CASE_ONE_INSTANCE, spec1=spec)
    monkeypatch.setattr(gateway.httpx, "AsyncClient", gateway_fake)
    store.add("c-1~1:s1", "bob", case_id="c-1", workflow_id="c-1~1")
    r = as_user("bob").get("/cases/c-1")
    assert r.status_code == 200, r.text
    assert store.faults == {}


def test_S4_a_capability_holder_is_admitted_to_the_case_by_the_same_rule(store, monkeypatch, as_user):
    _real_case(monkeypatch, None, store)
    monkeypatch.setattr(gateway.httpx, "AsyncClient",
                        _FakeRestate(case=_CASE_ONE_INSTANCE, spec1={"trigger": {}}))
    store.add("c-1~1:s1", "bob", case_id="c-1", workflow_id="c-1~1")
    store.grants.add(("aud:x", "carol"))
    assert as_user("carol").get("/cases/c-1").status_code == 200
    assert as_user("dave").get("/cases/c-1").status_code == 404        # control: neither


# -- S5 ---------------------------------------------------------------------------------------

def _status_route(monkeypatch, store, *, open_task=True, kind="document", submitted_by="dropper"):
    row = {"id": "ing-1", "kind": kind, "status": "extracted", "submitted_by": submitted_by,
           "on_behalf_of": None, "duplicate_of": None, "review_generation": 0, "sha256": "ab" * 32,
           "detail": None, "created_at": 1, "updated_at": 2, "origin_suggestion": None,
           "case_id": None, "content_kind": None, "attempt": 1, "failure": None}

    def _get(ingest_id, *, caller_id, any_caller=False):
        if ingest_id != "ing-1":
            return None
        return dict(row) if any_caller or caller_id == submitted_by else None
    monkeypatch.setattr(ingest_status, "get_status_for", _get)
    monkeypatch.setattr(ingest_status, "get_row", lambda i: dict(row) if i == "ing-1" else None)
    monkeypatch.setattr(human_tasks, "get_task_open_state",
                        lambda tid: {"open": open_task, "audience": "aud:x"})



def test_S5_a_notice_reader_who_holds_no_task_row_reads_the_status(store, monkeypatch, as_user):
    _status_route(monkeypatch, store)
    store.grants.add(("aud:x", "carol"))                    # a reader by capability: no row anywhere
    assert store.rows == []
    r = as_user("carol").get("/ingest/ing-1/status")
    assert r.status_code == 200 and r.json()["ingest_id"] == "ing-1"


def test_S5_CONTROL_a_stranger_gets_the_same_404_as_a_missing_ingest(store, monkeypatch, as_user):
    _status_route(monkeypatch, store)
    stranger = as_user("dave").get("/ingest/ing-1/status")
    missing = as_user("dave").get("/ingest/ing-nope/status")
    assert stranger.status_code == missing.status_code == 404
    assert stranger.json() == missing.json()


def test_S5_a_closed_task_opens_nothing_and_the_dropper_is_unchanged(store, monkeypatch, as_user):
    _status_route(monkeypatch, store, open_task=False)
    store.grants.add(("aud:x", "carol"))
    assert as_user("carol").get("/ingest/ing-1/status").status_code == 404
    assert as_user("dropper").get("/ingest/ing-1/status").status_code == 200


def test_S5_a_viewer_the_notice_read_refuses_is_refused_by_the_status_read(store, monkeypatch, as_user):
    """The status read CALLS the notice gate: for every viewer the two answer alike."""
    import asyncio
    from fastapi import HTTPException

    _status_route(monkeypatch, store)
    store.grants.add(("aud:x", "carol"))
    seen = {}
    for who in ("carol", "dave", "dropper", "erin"):
        try:
            asyncio.run(gateway._ingest_review_access("ing-1", _user(who), "t"))
            gate = True
        except HTTPException:
            gate = False
        seen[who] = (gate, as_user(who).get("/ingest/ing-1/status").status_code == 200)
    assert seen["carol"] == (True, True) and seen["dropper"] == (True, True)
    assert seen["dave"] == (False, False) and seen["erin"] == (False, False)
    assert all(g == st for g, st in seen.values())


def test_S5_an_event_row_is_never_a_status(store, monkeypatch, as_user):
    _status_route(monkeypatch, store, kind=ingest_status.EVENT)
    store.grants.add(("aud:x", "carol"))
    assert as_user("carol").get("/ingest/ing-1/status").status_code == 404


# -- S6 ---------------------------------------------------------------------------------------

def test_S6_needs_you_counts_equal_the_task_list_per_kind(store, labelled, as_user):
    labelled["c-1"] = [LABEL]
    for i, kind in enumerate(["ka", "ka", "kb", "kc", "ka", "kb"]):
        store.add(f"t-{i}", "bob", kind=kind, case_id="c-1" if i in (1, 3) else None)
    for who, doms in (("bob", []), ("bob", [LABEL])):
        c = as_user(who, doms)
        listed = c.get("/me/queue").json()["tasks"]
        needs = c.get("/me/needs_you").json()
        assert needs["counts"] == dict(Counter(t["kind"] for t in listed))
        assert needs["total"] == len(listed)
    # and the label really moved the count (the two reads above are not trivially equal)
    assert as_user("bob", []).get("/me/needs_you").json()["total"] == 4
    assert as_user("bob", [LABEL]).get("/me/needs_you").json()["total"] == 6


def test_S6_the_legacy_listing_and_the_queue_serve_the_same_rows(store, labelled, as_user):
    labelled["c-1"] = [LABEL]
    store.add("t-1", "bob")
    store.add("t-2", "bob", case_id="c-1")
    c = as_user("bob")
    assert _ids(c.get("/me/human_tasks")) == _ids(c.get("/me/queue")) == ["t-1"]


# -- S7 ---------------------------------------------------------------------------------------

def _delegates(tmp_path, monkeypatch, expires_at):
    p = tmp_path / "queue_delegates.yaml"
    rows = ""
    if expires_at is not None:
        rows = (f"- id: qd-1\n  delegator: bob\n  delegate: carol\n  scope: {{kinds: [k1]}}\n"
                f"  expires_at: '{expires_at}'\n  granted_by: bob\n  reason: cover\n  ratified_by: seat/x\n")
    p.write_text("queue_delegates:\n" + (rows or "  []\n") if rows == "" else "queue_delegates:\n" + rows,
                 encoding="utf-8")
    monkeypatch.setenv("QUEUE_DELEGATES_FILE", str(p))


def _future():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat()


def _past():
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()


@pytest.fixture
def cells(monkeypatch):
    held = {}

    async def _c(authz_id):
        return list(held.get(authz_id, []))
    monkeypatch.setattr(gateway, "_cells_of", _c)
    return held


def test_S7_a_live_row_admits_the_delegate_and_the_read_is_marked_and_audited(
        store, labelled, as_user, tmp_path, monkeypatch, cells, caplog):
    _delegates(tmp_path, monkeypatch, _future())
    store.add("t-1", "bob", kind="k1")
    store.add("t-2", "bob", kind="k2")                       # outside the row's scope
    with caplog.at_level(logging.INFO, logger="iagent.audit.queue_read"):
        r = as_user("carol").get("/me/queue", params={"on_behalf_of": "bob"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert _ids(r) == ["t-1"]
    d = body["delegated"]
    assert d["delegated"] is True and d["delegator"] == "bob" and d["delegate"] == "carol"
    assert d["row_id"] == "qd-1" and d["expires_at"]
    line = next(m for m in caplog.messages if "decision=allowed" in m)
    assert "delegate=carol" in line and "delegator=bob" in line and "expires_at=" in line


def test_S7_CONTROL_an_expired_row_is_a_policy_refusal_naming_the_binding(
        store, labelled, as_user, tmp_path, monkeypatch, cells):
    _delegates(tmp_path, monkeypatch, _past())
    store.add("t-1", "bob", kind="k1")
    r = as_user("carol").get("/me/queue", params={"on_behalf_of": "bob"})
    assert r.status_code == 403
    assert "queue_delegates" in r.text and "queue_delegate(bob)" in r.text


def test_S7_CONTROL_no_row_is_the_same_refusal(store, labelled, as_user, tmp_path, monkeypatch, cells):
    _delegates(tmp_path, monkeypatch, None)
    store.add("t-1", "bob", kind="k1")
    r = as_user("carol").get("/me/queue", params={"on_behalf_of": "bob"})
    assert r.status_code == 403 and "queue_delegate(bob)" in r.text
    r2 = as_user("carol").get("/me/needs_you", params={"on_behalf_of": "bob"})
    assert r2.status_code == 403


def test_S7_the_row_is_directional_and_a_direct_read_carries_no_mark(
        store, labelled, as_user, tmp_path, monkeypatch, cells):
    _delegates(tmp_path, monkeypatch, _future())
    store.add("t-1", "carol", kind="k1")
    assert as_user("bob").get("/me/queue", params={"on_behalf_of": "carol"}).status_code == 403
    own = as_user("carol").get("/me/queue")
    assert own.status_code == 200 and own.json()["delegated"] is None


def test_S7_a_delegation_does_not_lend_a_clearance(store, labelled, as_user, tmp_path, monkeypatch, cells):
    _delegates(tmp_path, monkeypatch, _future())
    labelled["c-1"] = [LABEL]
    store.add("t-1", "bob", kind="k1", case_id="c-1")
    cells["bob"] = [LABEL]                                    # the delegator may see it ...
    r = as_user("carol").get("/me/queue", params={"on_behalf_of": "bob"})
    assert r.status_code == 200 and _ids(r) == []             # ... the delegate may not
    assert ("t-1", "carol", gateway.LABEL_DIMENSION, LABEL) in store.faults
    r2 = as_user("carol", [LABEL]).get("/me/queue", params={"on_behalf_of": "bob"})
    assert _ids(r2) == ["t-1"]                                # control: the delegate holds it too


# -- S4b: the two remaining label sites (named-on-case holder, settled-task fallback) ------------

def _named_on_case(monkeypatch, store, labelled, cells, who, *, label_granted):
    import asyncio
    from fastapi import HTTPException

    labelled["c-1"] = [LABEL]
    store.add("t-1", who, case_id="c-1")
    monkeypatch.setattr(gateway, "_delegate_principals", lambda: {})
    if label_granted:
        cells[who] = [LABEL]
    try:
        return asyncio.run(gateway._admit_named_on_case("svc:runner", "c-1", who, None, route="t"))
    except HTTPException as exc:
        return exc.status_code


def test_S4_a_person_the_runner_names_is_not_admitted_as_holder_without_the_cases_label(
        store, labelled, cells, monkeypatch):
    got = _named_on_case(monkeypatch, store, labelled, cells, "bob", label_granted=False)
    assert got != "task_holder" and isinstance(got, int), got
    assert ("t-1", "bob", gateway.LABEL_DIMENSION, LABEL) in store.faults
    assert store.faults[("t-1", "bob", gateway.LABEL_DIMENSION, LABEL)]["on_behalf_of"] == "svc:runner"


def test_S4_CONTROL_the_same_named_holder_with_the_label_is_admitted(store, labelled, cells, monkeypatch):
    assert _named_on_case(monkeypatch, store, labelled, cells, "bob", label_granted=True) == "task_holder"
    assert store.faults == {}


def _act_on_settled(monkeypatch, store, labelled, as_user, *, label_granted):
    labelled["c-1"] = [LABEL]
    settled = {"task_id": "t-9", "status": "approved", "decision": "approved", "acted_by": "carol",
               "acted_at": NOW, "case_id": "c-1", "payload": {}}
    monkeypatch.setattr(human_tasks, "get_task_resolution", lambda task_id, caller_id=None: dict(settled))
    c = as_user("bob", domains=[LABEL] if label_granted else [])
    return c.post("/human_tasks/t-9/act", json={"decision": "approved"})


def test_S4_a_settled_task_on_a_case_whose_label_the_viewer_lacks_is_the_same_404_as_none(
        store, labelled, as_user, monkeypatch):
    r = _act_on_settled(monkeypatch, store, labelled, as_user, label_granted=False)
    assert r.status_code == 404 and "carol" not in r.text, r.text
    assert ("t-9", "bob", gateway.LABEL_DIMENSION, LABEL) in store.faults


def test_S4_CONTROL_the_same_settled_task_with_the_label_names_who_settled_it(
        store, labelled, as_user, monkeypatch):
    r = _act_on_settled(monkeypatch, store, labelled, as_user, label_granted=True)
    assert r.status_code == 409 and r.json()["detail"]["acted_by"] == "carol", r.text
    assert store.faults == {}
