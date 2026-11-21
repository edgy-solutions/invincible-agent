"""A follow-on task cannot complete without what it exists to settle (architect 2026-11-19).

    "a follow-on task cannot complete without what it exists to settle: a qualification task names
    the replacement part; a last-time-buy task records quantity and date. At review these are
    optional, and a blank is written as 'not yet identified', never left empty."
    (and, item 2d, the same night: a message never carries a list; lists are a structured field.)

The declaration is a sibling family, `task_completion/` (the SDK's TaskKind forbids extra keys), read
by `src/iagent/task_completion.py`. Product code names no case: F1 censuses that.

  F1 config + census      F2 register writes the blank      F3 act: required      F4 act: types, merge
  F5 authority first      F6 review pass-through            F7 mark_task_resolved SQL
  F8 the validator        F9 the pre-await journal shape    F10 unreadable refuses completion

Run: uv run pytest tests/test_a_follow_on_task_completes_only_with_what_it_settles.py -q
"""
from __future__ import annotations

import ast
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT / "agent_fleet" / "restate_analyst"), str(_ROOT), str(_ROOT / "policy" / "sync")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("restate")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import dispatch_driver  # noqa: E402
import dispatch_plan  # noqa: E402
import grouped_review_workflow as grw  # noqa: E402
import workflow_bulk_resolve as wbr  # noqa: E402

from src.iagent import gateway, human_tasks as ht, task_completion as tc  # noqa: E402
from tests.viewer_double import route_viewer_tasks_through  # noqa: E402

_OVERLAY = _ROOT / "policy" / "overlays" / "sample"
_ROW = _OVERLAY / "task_completion" / "pcn_disposition.yaml"
_KIND = "pcn_disposition"
_QUAL = "dispatchQualification"
_LTB = "dispatchLTB"


def _yaml_row() -> dict:
    return yaml.safe_load(_ROW.read_text(encoding="utf-8"))


def _blank() -> str:
    """The blank text, read from the row, never typed."""
    return tc.get_declarations()[_KIND].blank


def _reset_caches(mp=None):
    tc.reset_cache()
    for mod in (ht,):
        mod._DECLARED_KINDS_CACHE = None
        mod._DECLARED_ROWS.clear()
    for name in ("iagent.task_completion",):
        m = sys.modules.get(name)
        if m is not None:
            m.reset_cache()


@pytest.fixture(autouse=True)
def overlay_env(monkeypatch):
    monkeypatch.setenv("TASK_KIND_OVERLAY_DIRS", str(_OVERLAY / "task_kinds"))
    monkeypatch.setattr(ht, "_SEED_ROWS_CACHE", None, raising=False)
    _reset_caches()
    yield
    _reset_caches()


# ── F1: the config loads, and product code names no case ──────────────────────────────────────

def test_F1_the_real_row_loads_and_the_read_path_carries_it():
    row = _yaml_row()
    decl = tc.get_declarations()[_KIND]
    assert decl.by == row["by"] and decl.blank == row["blank"] and decl.required_on == ("approved",)
    served = ht.declaration_for(_KIND)["completion_fields"]
    assert set(served["fields"]) == {_QUAL, _LTB} == set(row["fields"])
    assert [f["type"] for f in served["fields"][_LTB]] == ["positive_integer", "date"]
    # a kind without the declaration keeps its shape (control)
    assert "completion_fields" not in ht.declaration_for("workflow_ack")


_TOUCHED = (
    "src/iagent/task_completion.py", "src/iagent/human_tasks.py", "src/iagent/gateway.py",
    "agent_fleet/restate_analyst/dispatch_driver.py",
    "agent_fleet/restate_analyst/grouped_review_workflow.py",
    "agent_fleet/restate_analyst/workflow_bulk_resolve.py", "policy/sync/validate_policy.py",
)
# NOT scanned: agent_fleet/restate_analyst/dispatch_plan.py. It was touched (a generic `fields`
# carried onto the task spec) but it is the disposition vocabulary's own home: its queue table
# already named both discriminator values before this change.


def _case_names() -> list[str]:
    row = _yaml_row()
    names = [f["name"] for flds in row["fields"].values() for f in flds]
    return names + list(row["fields"]) + [row["blank"]]


def _hits(text: str) -> list[str]:
    return [n for n in _case_names() if n in text]


def test_F1_product_code_names_no_field_value_or_blank_text():
    assert _hits("x " + _yaml_row()["blank"] + " y"), "the scanner cannot see a hit (positive control)"
    assert _hits("fields.ltb_quantity")
    for rel in _TOUCHED:
        # What this change ADDED names nothing: hits already on master (gateway.py's PCN state
        # vocabulary is an older, separate list) are subtracted; a new file has no baseline.
        base = subprocess.run(["git", "-C", str(_ROOT), "show", f"origin/master:{rel}"],
                              capture_output=True, text=True, encoding="utf-8")
        before = _hits(base.stdout) if base.returncode == 0 else []
        now = _hits((_ROOT / rel).read_text(encoding="utf-8"))
        assert [h for h in now if h not in before] == [], rel


def test_F1_the_task_kind_row_is_unchanged_from_master():
    import subprocess
    rel = "policy/overlays/sample/task_kinds/pcn_disposition.yaml"
    cur = (_ROOT / rel).read_bytes()
    base = subprocess.run(["git", "-C", str(_ROOT), "show", f"origin/master:{rel}"],
                          capture_output=True, check=True).stdout
    assert cur.replace(b"\r\n", b"\n") == base.replace(b"\r\n", b"\n")


# ── the routes, through TestClient ────────────────────────────────────────────────────────────

_USER = type("U", (), {"authz_id": "bob", "sub": "bob", "email": "bob@x", "persona": "P",
                       "entitled_domains": ["D"], "is_authenticated": True})()


@pytest.fixture
def world(monkeypatch, register_rail):
    register_rail(["bob"])
    st = {"resolved": [], "can_act": True, "registered": [], "task": None, "validated_first": []}

    def mark(tid, **kw):
        st["resolved"].append((tid, kw))
        return 1

    monkeypatch.setattr(ht, "mark_task_resolved", mark)
    monkeypatch.setattr(ht, "check_can_act", lambda audience, caller: st["can_act"])
    monkeypatch.setattr(ht, "get_task_resolution", lambda tid, *, caller_id: None)
    monkeypatch.setattr(ht, "register_task",
                        lambda **kw: (st["registered"].append(kw), {"recipients": []})[1])
    monkeypatch.setattr(ht, "list_tasks_for", lambda caller, status="pending": [st["task"]])
    route_viewer_tasks_through(monkeypatch)
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _USER
    with TestClient(gateway.app) as c:
        st["client"] = c
        yield st
    gateway.app.dependency_overrides.clear()


def _task(disposition, fields=None, kind=_KIND):
    payload = {"disposition": disposition}
    if fields is not None:
        payload["fields"] = fields
    return {"task_id": "t-1", "kind": kind, "audience": "procurement", "payload": payload}


def _register(w, disposition, fields=None, kind=_KIND, **extra):
    payload = {"disposition": disposition, **extra}
    if fields is not None:
        payload["fields"] = fields
    r = w["client"].post("/internal/human_tasks/register", json={
        "kind": kind, "task_id": "t-1", "audience": "a", "title": "t", "summary": "s",
        "requested_by": "bob", "payload": payload})
    assert r.status_code == 200, r.text
    return w["registered"][-1]["payload"]


def _act(w, decision="approved", fields=None):
    body = {"decision": decision}
    if fields is not None:
        body["fields"] = fields
    return w["client"].post("/human_tasks/t-1/act", json=body)


def _detail(r):
    return r.json()["detail"]


# ── F2: the register writes the blank, never an empty value ───────────────────────────────────

def test_F2_a_task_with_no_fields_is_written_with_the_blank_text(world):
    p = _register(world, _QUAL, {})
    assert p["fields"] == {"replacement_part": _blank()} and _blank()
    assert p["disposition"] == _QUAL


def test_F2_a_task_with_no_fields_key_is_written_with_the_blank_text(world):
    assert _register(world, _QUAL)["fields"] == {"replacement_part": _blank()}


def test_F2_a_supplied_value_is_kept_stripped_and_an_undeclared_key_is_dropped(world):
    p = _register(world, _QUAL, {"replacement_part": "  AB-1 ", "zzz": "dropped"})
    assert p["fields"] == {"replacement_part": "AB-1"}


@pytest.mark.parametrize("spell", [str.upper, str.title, lambda s: "  " + s.capitalize() + " "])
def test_F2_the_blank_text_in_another_case_is_written_as_the_declared_blank(world, spell):
    """What cortex draws as 'not identified' is the SERVED blank: a reviewer's own capitalisation of
    it is written as the declared text, so it is never drawn as if it were a value."""
    typed = spell(_blank())
    assert typed != _blank(), "the spelling under test must differ from the declared text"
    p = _register(world, _QUAL, {"replacement_part": typed})
    assert p["fields"] == {"replacement_part": _blank()}


def test_F2_every_declared_name_is_written_a_partial_set_is_filled(world):
    p = _register(world, _LTB, {"ltb_quantity": "500"})
    assert p["fields"] == {"ltb_quantity": "500", "ltb_date": _blank()}


def test_F2_a_kind_without_the_declaration_is_unchanged(world):
    p = _register(world, _QUAL, None, kind="workflow_ack")
    assert p == {"disposition": _QUAL}


# ── F3: the act requires them ─────────────────────────────────────────────────────────────────

def test_F3_approving_with_no_fields_is_refused_and_the_names_are_in_the_list(world):
    world["task"] = _task(_QUAL, {"replacement_part": _blank()})
    r = _act(world)
    d = _detail(r)
    assert r.status_code == 422 and d["error"] == "completion_fields_missing"
    assert d["fields"] == ["replacement_part"]
    assert "replacement_part" not in d["message"] and "replacement" not in d["message"].lower()
    assert world["resolved"] == []


def test_F3_approving_with_the_blank_text_is_refused(world):
    world["task"] = _task(_QUAL, {"replacement_part": _blank()})
    r = _act(world, fields={"replacement_part": _blank()})
    assert r.status_code == 422 and _detail(r)["error"] == "completion_fields_missing"


@pytest.mark.parametrize("where", ["act", "review"])
@pytest.mark.parametrize("spell", [str.upper, str.title, lambda s: "  " + s.capitalize() + " "])
def test_F3_the_blank_text_in_another_case_is_still_the_blank(world, where, spell):
    """The blank SAYS nothing was identified, however it is capitalised: typed at review or at act
    as "Not yet identified", it must not stand in for the replacement part the task exists to name."""
    typed = spell(_blank())
    assert typed != _blank(), "the spelling under test must differ from the declared text"
    if where == "act":
        world["task"] = _task(_QUAL, {"replacement_part": _blank()})
        r = _act(world, fields={"replacement_part": typed})
    else:
        world["task"] = _task(_QUAL, {"replacement_part": typed})
        r = _act(world)
    assert r.status_code == 422 and _detail(r)["error"] == "completion_fields_missing", r.text
    assert _detail(r)["fields"] == ["replacement_part"]


def test_F3_approving_with_a_value_records_it(world):
    world["task"] = _task(_QUAL, {"replacement_part": _blank()})
    r = _act(world, fields={"replacement_part": " AB-1 "})
    assert r.status_code == 200, r.text
    assert world["resolved"][0][1]["fields"] == {"replacement_part": "AB-1"}


def test_F3_a_value_recorded_at_review_completes_without_one_at_act(world):
    world["task"] = _task(_QUAL, {"replacement_part": "AB-1"})
    assert _act(world).status_code == 200
    assert world["resolved"][0][1]["fields"] == {"replacement_part": "AB-1"}


def test_F3_rejecting_with_no_fields_passes_and_records_none(world):
    world["task"] = _task(_QUAL, {"replacement_part": _blank()})
    r = _act(world, "rejected", None)
    assert r.status_code == 200, r.text
    assert "fields" not in world["resolved"][0][1]


# ── F4: types, and the merge of review and act ────────────────────────────────────────────────

_LTB_BLANK = lambda: {"ltb_quantity": _blank(), "ltb_date": _blank()}  # noqa: E731


@pytest.mark.parametrize("qty", ["0", "-3", "x", "1.5", ""])
def test_F4_a_bad_quantity_is_invalid_or_missing(world, qty):
    world["task"] = _task(_LTB, _LTB_BLANK())
    r = _act(world, fields={"ltb_quantity": qty, "ltb_date": "2027-03-31"})
    d = _detail(r)
    assert r.status_code == 422 and d["fields"] == ["ltb_quantity"]
    assert d["error"] == ("completion_fields_missing" if qty == "" else "completion_fields_invalid")


def test_F4_an_impossible_date_is_invalid(world):
    world["task"] = _task(_LTB, _LTB_BLANK())
    r = _act(world, fields={"ltb_quantity": "500", "ltb_date": "2026-13-01"})
    assert r.status_code == 422 and _detail(r) == {
        **_detail(r), "error": "completion_fields_invalid", "fields": ["ltb_date"]}


def test_F4_a_compact_date_is_not_iso(world):
    world["task"] = _task(_LTB, _LTB_BLANK())
    r = _act(world, fields={"ltb_quantity": "500", "ltb_date": "20270331"})
    assert r.status_code == 422 and _detail(r)["fields"] == ["ltb_date"]


def test_F4_valid_values_are_recorded(world):
    world["task"] = _task(_LTB, _LTB_BLANK())
    r = _act(world, fields={"ltb_quantity": "500", "ltb_date": "2027-03-31"})
    assert r.status_code == 200, r.text
    assert world["resolved"][0][1]["fields"] == {"ltb_quantity": "500", "ltb_date": "2027-03-31"}


def test_F4_an_integer_quantity_is_accepted(world):
    world["task"] = _task(_LTB, _LTB_BLANK())
    r = _act(world, fields={"ltb_quantity": 500, "ltb_date": "2027-03-31"})
    assert r.status_code == 200, r.text


def test_F4_review_and_act_merge_final_is_act_or_payload(world):
    world["task"] = _task(_LTB, {"ltb_quantity": "500", "ltb_date": _blank()})
    r = _act(world, fields={"ltb_date": "2027-03-31"})
    assert r.status_code == 200, r.text
    assert world["resolved"][0][1]["fields"] == {"ltb_quantity": "500", "ltb_date": "2027-03-31"}


def test_F4_the_act_value_wins_over_the_review_value(world):
    world["task"] = _task(_LTB, {"ltb_quantity": "500", "ltb_date": "2027-03-31"})
    r = _act(world, fields={"ltb_quantity": "700"})
    assert r.status_code == 200
    assert world["resolved"][0][1]["fields"]["ltb_quantity"] == "700"


def test_F4_text_over_120_characters_or_two_lines_is_invalid(world):
    world["task"] = _task(_QUAL, {"replacement_part": _blank()})
    for bad in ("x" * 121, "a\nb"):
        r = _act(world, fields={"replacement_part": bad})
        assert r.status_code == 422 and _detail(r)["error"] == "completion_fields_invalid", bad


# ── F5: authority first ───────────────────────────────────────────────────────────────────────

def test_F5_a_caller_who_cannot_act_gets_the_authority_refusal_not_a_field_refusal(world):
    world["can_act"] = False
    world["task"] = _task(_QUAL, {"replacement_part": _blank()})
    r = _act(world)
    d = _detail(r)
    assert r.status_code == 403 and d["error"] == "not_authorized_to_act"
    assert not str(d["error"]).startswith("completion_fields")
    assert "fields" not in d


# ── F6: the review passes fields through ──────────────────────────────────────────────────────

def _batch():
    return wbr.ReviewBatch(approver="a", items=[
        wbr.PartItem(mpn="P1", subject="http://x/P1", proposed_disposition="archive"),
    ])


def _decision(**ov):
    return {"verdict": "approved", "overrides": {"P1": {"disposition": _QUAL, "reason": "r", **ov}}}


def test_F6_an_override_with_fields_reaches_the_task_spec():
    sub = grw.evaluate_submission(_batch(), _decision(fields={"replacement_part": "AB-1"}),
                                  notice_fingerprint="FP")
    assert sub.accepted, sub.reason
    res = sub.resolutions[0]
    assert res.fields == {"replacement_part": "AB-1"}
    plan = dispatch_plan.plan_dispatch(res, notice_fingerprint="FP")
    assert plan.human_task.fields == {"replacement_part": "AB-1"}
    wire = dispatch_driver.plan_to_payload(plan, requested_by="svc")["human_task"]
    assert wire["fields"] == {"replacement_part": "AB-1"}


def test_F6_an_override_without_fields_is_empty_and_unchanged():
    sub = grw.evaluate_submission(_batch(), _decision(), notice_fingerprint="FP")
    res = sub.resolutions[0]
    assert res.fields == {}
    plan = dispatch_plan.plan_dispatch(res, notice_fingerprint="FP")
    assert plan.human_task.fields == {}
    assert "fields" not in dispatch_driver.plan_to_payload(plan, requested_by="svc")["human_task"]


@pytest.mark.parametrize("bad", [
    "text", ["a"], {"k": 1}, {1: "a"}, {"k": "x" * 121}, {"k": "a\nb"},
    {f"k{i}": "v" for i in range(11)},
])
def test_F6_a_malformed_fields_is_a_refused_submission_never_a_raise(bad):
    sub = grw.evaluate_submission(_batch(), _decision(fields=bad), notice_fingerprint="FP")
    assert sub.accepted is False and sub.reason


def test_F6_ten_fields_of_120_characters_are_accepted():
    ok = {f"k{i}": "v" * 120 for i in range(10)}
    assert grw.evaluate_submission(_batch(), _decision(fields=ok), notice_fingerprint="FP").accepted


def test_F6_the_register_body_carries_disposition_and_fields_in_its_payload(monkeypatch):
    sub = grw.evaluate_submission(_batch(), _decision(fields={"replacement_part": "AB-1"}),
                                  notice_fingerprint="FP")
    plan = dispatch_plan.plan_dispatch(sub.resolutions[0], notice_fingerprint="FP")
    task = dispatch_driver.plan_to_payload(plan, requested_by="svc")["human_task"]
    sent = {}

    class _R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {}

    monkeypatch.setattr(dispatch_driver, "mint_service_token", lambda *a, **k: "t")
    monkeypatch.setattr(dispatch_driver.requests, "post",
                        lambda url, json=None, **k: (sent.update(body=json), _R())[1])
    dispatch_driver._mint_dispatch_task(task)
    assert sent["body"]["payload"]["disposition"] == _QUAL
    assert sent["body"]["payload"]["fields"] == {"replacement_part": "AB-1"}


# ── F7: mark_task_resolved's statement ────────────────────────────────────────────────────────

class _Cur:
    def __init__(self, log):
        self.log, self.rowcount = log, 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.log.append((sql, params))


class _Conn:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _Cur(self.log)

    def commit(self):
        pass


def _resolve(monkeypatch, **kw):
    log = []
    monkeypatch.setattr(ht, "_pg_connect", lambda: _Conn(log))
    ht.mark_task_resolved("t-1", caller_id="bob", decision="approved", **kw)
    return log[0]


def test_F7_with_fields_the_statement_merges_and_the_params_carry_the_json(monkeypatch):
    sql, params = _resolve(monkeypatch, fields={"a": "b"})
    assert "COALESCE(payload,'{}'::jsonb) || jsonb_build_object('fields', %s::jsonb)" in sql
    assert json.dumps({"a": "b"}) in params
    assert sql.count("%s") == len(params)


def test_F7_without_fields_the_statement_is_what_it_was(monkeypatch):
    sql, params = _resolve(monkeypatch)
    assert "payload" not in sql and "jsonb" not in sql
    assert sql.count("%s") == len(params) == 8


# ── F8: the validator ─────────────────────────────────────────────────────────────────────────

def _policy(tmp_path, row_text, accepts="[approved, rejected]"):
    (tmp_path / "task_kinds").mkdir()
    (tmp_path / "task_completion").mkdir()
    (tmp_path / "task_kinds" / "k.yaml").write_text(
        "kind: k\nrenders_as: {badge: B, title: T, archetype: APPROVAL_TASK}\n"
        f"accepts: {accepts}\n", encoding="utf-8")
    (tmp_path / "task_completion" / "k.yaml").write_text(row_text, encoding="utf-8")
    return tmp_path


_GOOD = """kind: k
by: d
required_on: [approved]
blank: "none yet"
fields:
  v:
    - {name: a_b, label: "A", type: text}
"""


def _errors(tmp_path, row_text, **kw):
    import validate_policy
    return validate_policy.task_completion_errors(_policy(tmp_path, row_text, **kw))[0]


def test_F8_the_real_policy_validates_clean():
    import validate_policy
    errs, n = validate_policy.task_completion_errors(_ROOT / "policy")
    assert errs == [] and n >= 1


def test_F8_a_good_row_is_clean(tmp_path):
    assert _errors(tmp_path, _GOOD) == []


@pytest.mark.parametrize("name,edit", [
    ("required_on", lambda s: s.replace("[approved]", "[withdrawn]")),
    ("type", lambda s: s.replace("type: text", "type: float")),
    ("duplicate", lambda s: s.replace("    - {name: a_b", "    - {name: a_b, label: \"A\", type: text}\n    - {name: a_b")),
    ("blank", lambda s: s.replace('blank: "none yet"', 'blank: ""')),
    ("field_name", lambda s: s.replace("a_b", "A-b")),
    ("label", lambda s: s.replace('label: "A"', 'label: ""')),
])
def test_F8_a_bad_row_is_one_error_naming_the_kind(tmp_path, name, edit):
    errs = _errors(tmp_path, edit(_GOOD))
    assert len(errs) == 1 and "'k'" in errs[0], (name, errs)


def test_F8_a_row_for_a_kind_nobody_declares_is_refused(tmp_path):
    errs = _errors(tmp_path, _GOOD.replace("kind: k", "kind: ghost"))
    assert len(errs) == 1 and "ghost" in errs[0]


# ── F9: the journal shape ahead of the await is the master's ──────────────────────────────────
#
# Hard-coded from `git show origin/master:agent_fleet/restate_analyst/main.py` (08ce14f9),
# `_run_grouped_human_await`: every `ctx.*` call, in source order, up to and including the
# `ctx.promise(...).value()` await. No new journal command may go above an existing await.
_MASTER_CTX_SEQUENCE = [
    "ctx.set('batch_items')", "ctx.set('approver')", "ctx.set('notice_fingerprint')",
    "ctx.set('ingest_id')", "ctx.set('notice_id')", "ctx.set('doc_type')",
    "ctx.set('pipeline_version')", "ctx.set('extraction_warnings')", "ctx.set('artifact_uri')",
    "ctx.set(_audience_key(promise_name))", "ctx.key()", "ctx.key()",
    "ctx.run('register_grouped_task')", "ctx.promise(promise_name)",
    "ctx.promise(promise_name, type_hint=dict).value()",
]


def _shape(source: str) -> list[str]:
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_grouped_human_await")
    calls = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = ast.unparse(n.func)
            if f.startswith("ctx."):
                calls.append((n.lineno, n.col_offset, f, ast.unparse(n.args[0]) if n.args else ""))
    calls.sort()
    out = []
    for _, _, f, arg in calls:
        if f.startswith("ctx.promise(") and f.endswith(".value"):
            out.append(f + "()")      # the await itself: nothing after it is pinned here
            break
        out.append(f"{f}({arg})")
    return out


def test_F9_the_ctx_calls_ahead_of_the_await_are_the_masters():
    src = (_ROOT / "agent_fleet" / "restate_analyst" / "main.py").read_text(encoding="utf-8")
    got = _shape(src)
    assert got == _MASTER_CTX_SEQUENCE, got


def test_F9_the_pin_sees_a_new_journal_command_above_the_await():
    src = (_ROOT / "agent_fleet" / "restate_analyst" / "main.py").read_text(encoding="utf-8")
    mutated = src.replace("    ctx.set(\"batch_items\"", "    ctx.set(\"extra_key\", 1)\n    ctx.set(\"batch_items\"", 1)
    assert mutated != src
    assert _shape(mutated) != _MASTER_CTX_SEQUENCE


# ── F10: an unreadable declaration refuses completion (ruled 2026-11-20) ─────────────────────
#
# "an unreadable completion declaration refuses completion with a clear error. It does not warn
# and pass." An UNSET variable is not unreadable: it composes the seed alone, the reading
# `human_tasks._declared_kinds` gives the same variable (a domain species is refused at the kind
# gate).

def _broken_overlay(tmp_path, monkeypatch):
    """The real overlay's task kinds (so the kind gate passes) beside the real completion row with
    one field's type made unknown: the family no longer composes."""
    import shutil
    shutil.copytree(_OVERLAY / "task_kinds", tmp_path / "task_kinds")
    (tmp_path / "task_completion").mkdir()
    text = _ROW.read_text(encoding="utf-8")
    assert "type: positive_integer" in text, "the row under test changed: pick another field"
    (tmp_path / "task_completion" / _ROW.name).write_text(
        text.replace("type: positive_integer", "type: float", 1), encoding="utf-8")
    monkeypatch.setenv("TASK_KIND_OVERLAY_DIRS", str(tmp_path / "task_kinds"))
    _reset_caches()
    return tmp_path


def test_F10_an_unset_variable_composes_the_seed_alone_and_warns(monkeypatch, caplog):
    monkeypatch.delenv("TASK_KIND_OVERLAY_DIRS")
    _reset_caches()
    with caplog.at_level(logging.WARNING, logger=tc.logger.name):
        got = tc.get_declarations()
    assert got == tc.compose_completion(tc.SEED_DIR, [])
    assert _KIND not in got
    assert any("unset" in r.getMessage() for r in caplog.records)


def test_F10_a_malformed_overlay_row_raises_logs_and_is_not_cached(monkeypatch, tmp_path, caplog):
    root = _broken_overlay(tmp_path, monkeypatch)
    with caplog.at_level(logging.ERROR, logger=tc.logger.name):
        with pytest.raises(tc.CompletionDeclarationUnreadable):
            tc.get_declarations()
        with pytest.raises(tc.CompletionDeclarationUnreadable):
            tc.declaration_for_kind(_KIND)
    assert any("could not compose" in r.getMessage() for r in caplog.records)
    # fixed on disk, the next call reads it: nothing unreadable was cached
    (root / "task_completion" / _ROW.name).write_text(_ROW.read_text(encoding="utf-8"),
                                                      encoding="utf-8")
    assert tc.declaration_for_kind(_KIND).blank == _yaml_row()["blank"]


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_F10_the_act_is_refused_with_a_clear_error_when_the_declarations_are_unreadable(
        world, monkeypatch, tmp_path, decision):
    """Every decision, not only the one the row names: with the row unreadable, this process
    cannot tell which decisions complete the task. The refusal says why, and the message carries
    no path and no parse error (those are in the log)."""
    _broken_overlay(tmp_path, monkeypatch)
    world["task"] = _task(_QUAL, {"replacement_part": "AB-1"})
    r = _act(world, decision, {"replacement_part": "AB-1"})
    d = _detail(r)
    assert r.status_code == 409 and d["error"] == "completion_declaration_unreadable", r.text
    assert d["kind"] == _KIND and "completed" in d["message"]
    assert str(tmp_path) not in d["message"] and "float" not in d["message"]
    assert world["resolved"] == []


def test_F10_CONTROL_the_same_act_completes_when_the_row_reads(world):
    """The subject above, differing only in the row: readable, the same act completes."""
    world["task"] = _task(_QUAL, {"replacement_part": "AB-1"})
    r = _act(world, "approved", {"replacement_part": "AB-1"})
    assert r.status_code == 200, r.text
    assert world["resolved"][0][1]["fields"] == {"replacement_part": "AB-1"}


def test_F10_register_and_the_read_path_do_not_raise_when_unreadable(world, monkeypatch, tmp_path):
    """Refusing registration would drop the follow-on task itself: it registers as supplied, and
    the act refuses until the declarations read. The read path omits the key."""
    _broken_overlay(tmp_path, monkeypatch)
    assert _register(world, _QUAL, {"replacement_part": "AB-1"}) == {
        "disposition": _QUAL, "fields": {"replacement_part": "AB-1"}}
    assert "completion_fields" not in ht.declaration_for(_KIND)


def test_F10_a_sibling_is_derived_from_each_overlay_entry_and_a_missing_one_declares_nothing(tmp_path):
    (tmp_path / "a" / "task_kinds").mkdir(parents=True)
    (tmp_path / "b" / "task_kinds").mkdir(parents=True)
    (tmp_path / "b" / "task_completion").mkdir()
    import os
    env = {"TASK_KIND_OVERLAY_DIRS": os.pathsep.join(
        [str(tmp_path / "a" / "task_kinds"), str(tmp_path / "b" / "task_kinds")])}
    assert tc.overlay_dirs_from_env(env) == [tmp_path / "b" / "task_completion"]
    assert tc.overlay_dirs_from_env({}) is None
