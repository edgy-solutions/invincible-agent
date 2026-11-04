"""The case-runner routes bound the person they NAME, on the basis that can vouch for the name.

A plain check against `_delegate_principals()[caller]` would refuse every real call (the runner's own
list is only the platform registrar; the steward and the case's principal are the case's), so
`gateway._admit_named_on_case` admits a name on one of three bases:

  declared          on the caller's own delegate list
  seeding_delegate  the case's `seeded_by`, itself a declared delegate
  task_holder       holds a task on THIS case (`human_tasks.holds_task_on_case`)

and refuses anything else 403 `principal_not_declared_for_delegate`; a holder lookup that cannot run
is 503 `authorization_unavailable`, never "not a holder". Every admit and refusal leaves one line on
`iagent.audit.delegate_named` naming the caller AND the name.

No principal is typed: declared pairs are read from the chart values through `_identity_support`, and
the two names that are NOT declared are built here from what is declared, so they cannot collide.

Run: uv run pytest tests/identity/test_the_internal_routes_bound_who_they_name.py -q
"""
from __future__ import annotations

import logging
import types

import pytest

pytest.importorskip("fastapi")

from src.iagent import answer_artifact_writer as aaw  # noqa: E402
from src.iagent import case_summary  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import origin_writer  # noqa: E402
from tests.identity._identity_support import install_delegates, pair_and_outsider  # noqa: E402
from tests.identity.test_a_service_token_cannot_name_a_user_outside_the_delegate_list import (  # noqa: E402
    _client, _login)

RUNNER = gateway._CASE_RUNNER_SERVICE_AUTHZ_ID
AUDIT = "iagent.audit.delegate_named"
CASE = "case-1"


@pytest.fixture(autouse=True)
def _clean():
    yield
    gateway.app.dependency_overrides.clear()


@pytest.fixture
def served(monkeypatch):
    s = install_delegates(monkeypatch)
    assert RUNNER in s
    return s


def _undeclared(served, tag):
    """A person nobody declared: built from the declared set so it cannot collide with one."""
    everyone = set(served) | {p for ps in served.values() for p in ps}
    name = f"{tag}.not-declared@example.invalid"
    assert name not in everyone
    return name


class _Holders:
    """`human_tasks.holds_task_on_case`: who holds a task on which case; records every ask."""

    def __init__(self, monkeypatch, holders=(), raises=None):
        self.holders, self.raises, self.asked = set(holders), raises, []
        monkeypatch.setattr(ht, "holds_task_on_case", self)

    def __call__(self, case_id, person):
        self.asked.append((case_id, person))
        if self.raises:
            raise self.raises
        return (case_id, person) in self.holders


def _audit(caplog, *names):
    """The delegate_named lines, which must carry every name given (the caller AND the person)."""
    lines = [r.getMessage() for r in caplog.records if r.name == AUDIT]
    assert len(lines) == 1, lines
    for n in names:
        assert n in lines[0], (n, lines[0])
    return lines[0]


# -- action-record ----------------------------------------------------------------------------------

class _Artifacts:
    def __init__(self, monkeypatch):
        self.written = []
        outer = self

        class _Sess:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def run(self, *a, **k): return types.SimpleNamespace(single=lambda: {"n": 0})

        class _W:
            def __init__(self, *a, **k): ...

            def write_sync(self, bundle):
                outer.written.append(bundle)
                return types.SimpleNamespace(success=True, error=None)

        monkeypatch.setattr(gateway, "neo4j_driver", types.SimpleNamespace(session=lambda: _Sess()))
        monkeypatch.setattr(aaw, "AnswerArtifactWriter", _W)


def _post_action_record(named, seeded_by=None):
    body = {"record": {"action_id": "a-1", "provenance": {"case_id": CASE}}, "on_behalf_of": named}
    if seeded_by is not None:
        body["seeded_by"] = seeded_by
    _login(RUNNER)
    return _client().post(f"/internal/cases/{CASE}/action-record", json=body)


def test_action_record_a_declared_principal_is_admitted_as_declared(monkeypatch, served, caplog):
    caplog.set_level(logging.INFO, logger=AUDIT)
    art, holders = _Artifacts(monkeypatch), _Holders(monkeypatch)
    declared, _ = pair_and_outsider(served, RUNNER)
    r = _post_action_record(declared)
    assert r.status_code == 200 and len(art.written) == 1, (r.status_code, r.text[:200])
    assert holders.asked == [], "a declared name needs no holder lookup"
    assert "admitted:declared" in _audit(caplog, RUNNER, declared)


def test_action_record_the_seeding_delegate_is_admitted_as_seeding_delegate(
        monkeypatch, served, caplog):
    caplog.set_level(logging.INFO, logger=AUDIT)
    art, holders = _Artifacts(monkeypatch), _Holders(monkeypatch)
    seeder = next(d for d in sorted(served) if d not in served[RUNNER] and d != RUNNER)
    r = _post_action_record(seeder, seeded_by=seeder)
    assert r.status_code == 200 and len(art.written) == 1, (r.status_code, r.text[:200])
    assert holders.asked == []
    assert "admitted:seeding_delegate" in _audit(caplog, RUNNER, seeder)


def test_action_record_a_task_holder_on_the_case_is_admitted_as_task_holder(
        monkeypatch, served, caplog):
    caplog.set_level(logging.INFO, logger=AUDIT)
    art = _Artifacts(monkeypatch)
    holder = _undeclared(served, "holder")
    holders = _Holders(monkeypatch, holders={(CASE, holder)})
    r = _post_action_record(holder)
    assert r.status_code == 200 and len(art.written) == 1, (r.status_code, r.text[:200])
    assert holders.asked == [(CASE, holder)], "asked about THIS case and THIS person"
    assert "admitted:task_holder" in _audit(caplog, RUNNER, holder)


def test_action_record_a_non_holder_is_refused_and_nothing_is_written(monkeypatch, served, caplog):
    caplog.set_level(logging.INFO, logger=AUDIT)
    art = _Artifacts(monkeypatch)
    stranger = _undeclared(served, "stranger")
    holders = _Holders(monkeypatch, holders={(CASE, _undeclared(served, "someone-else"))})
    r = _post_action_record(stranger)
    assert r.status_code == 403, (r.status_code, r.text[:200])
    detail = r.json()["detail"]
    assert detail["error"] == "principal_not_declared_for_delegate" and detail["on_behalf_of"] == stranger
    assert art.written == [] and holders.asked == [(CASE, stranger)]
    assert "refused:principal_not_declared_for_delegate" in _audit(caplog, RUNNER, stranger)


def test_action_record_a_holder_lookup_that_raises_is_503_not_a_refusal_of_a_holder(
        monkeypatch, served, caplog):
    caplog.set_level(logging.INFO, logger=AUDIT)
    art = _Artifacts(monkeypatch)
    person = _undeclared(served, "unknowable")
    _Holders(monkeypatch, holders={(CASE, person)}, raises=RuntimeError("pg is down"))
    r = _post_action_record(person)
    assert r.status_code == 503, (r.status_code, r.text[:200])
    assert r.json()["detail"]["error"] == "authorization_unavailable"
    assert art.written == []
    assert "authorization_unavailable" in _audit(caplog, RUNNER, person)


@pytest.mark.parametrize("blank", ["", "   "])
def test_action_record_a_blank_name_is_never_admitted(monkeypatch, served, blank):
    art, holders = _Artifacts(monkeypatch), _Holders(monkeypatch)
    r = _post_action_record(blank)
    assert r.status_code == 422 and art.written == [] and holders.asked == []


# -- origin/write -----------------------------------------------------------------------------------

def _origin_body(steward, with_case=True):
    body = {
        "artifact_id": "ing-1", "dropped_by": {"authz_id": "dropper.not-checked@example.invalid"},
        "origin": {"owner_domain": "d", "program": "p-1", "obtained_via": "contract_deliverable"},
        "evidence": {"source": "s", "citation": "c"},
        "approval_chain": [{"role": "steward", "approver_sub": steward}],
    }
    if with_case:
        body["case_id"] = CASE
    return body


def _post_origin(monkeypatch, body):
    from agent_fleet.utils.mesh_writers import neo4j_graph
    writes = []
    monkeypatch.setattr(ht, "check_can_view_program", lambda program, who: True)
    monkeypatch.setattr(neo4j_graph, "Neo4jGraphWriter", lambda **kw: object())
    monkeypatch.setattr(origin_writer, "write_origin", lambda resolution, **kw: (
        writes.append(resolution), {"status": "written", "reason": None})[1])

    async def no_filing(*a, **k):
        return None
    monkeypatch.setattr(gateway, "_file_promotion_if_ready", no_filing)
    _login(RUNNER)
    return _client().post("/internal/origin/write", json=body), writes


def test_origin_write_a_holding_steward_is_admitted(monkeypatch, served, caplog):
    caplog.set_level(logging.INFO, logger=AUDIT)
    steward = _undeclared(served, "steward")
    holders = _Holders(monkeypatch, holders={(CASE, steward)})
    r, writes = _post_origin(monkeypatch, _origin_body(steward))
    assert r.status_code == 200 and len(writes) == 1, (r.status_code, r.text[:200])
    assert holders.asked == [(CASE, steward)]
    assert "admitted:task_holder" in _audit(caplog, RUNNER, steward)


def test_origin_write_a_non_holding_steward_is_refused_and_nothing_is_written(
        monkeypatch, served, caplog):
    caplog.set_level(logging.INFO, logger=AUDIT)
    steward = _undeclared(served, "steward")
    _Holders(monkeypatch)
    r, writes = _post_origin(monkeypatch, _origin_body(steward))
    assert r.status_code == 403 and writes == [], (r.status_code, r.text[:200])
    assert r.json()["detail"]["error"] == "principal_not_declared_for_delegate"
    assert "refused:principal_not_declared_for_delegate" in _audit(caplog, RUNNER, steward)


def test_origin_write_a_missing_case_id_is_422_and_nothing_is_written(monkeypatch, served):
    steward = _undeclared(served, "steward")
    holders = _Holders(monkeypatch, holders={(CASE, steward)})
    r, writes = _post_origin(monkeypatch, _origin_body(steward, with_case=False))
    assert r.status_code == 422 and writes == [] and holders.asked == []


# -- summary and seeded-by --------------------------------------------------------------------------

def _post_summary(monkeypatch, seeded_by):
    stored = []
    monkeypatch.setattr(case_summary, "upsert_summary", lambda **kw: stored.append(kw))

    class _Sess:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def run(self, *a, **k): return []

    monkeypatch.setattr(gateway, "neo4j_driver", types.SimpleNamespace(session=lambda: _Sess()))
    _login(RUNNER)
    body = {"state": "closed", "transitions": []}
    if seeded_by is not None:
        body["seeded_by"] = seeded_by
    return _client().post(f"/internal/cases/{CASE}/summary", json=body), stored


def test_summary_a_declared_seeded_by_is_admitted(monkeypatch, served, caplog):
    caplog.set_level(logging.INFO, logger=AUDIT)
    seeder = sorted(served)[0]
    r, stored = _post_summary(monkeypatch, seeder)
    assert r.status_code == 200 and len(stored) == 1, (r.status_code, r.text[:200])
    assert "admitted" in _audit(caplog, RUNNER, seeder)


def test_summary_no_seeded_by_is_admitted(monkeypatch, served):
    r, stored = _post_summary(monkeypatch, None)
    assert r.status_code == 200 and len(stored) == 1, (r.status_code, r.text[:200])


def test_summary_an_undeclared_seeded_by_is_422_and_nothing_is_stored(monkeypatch, served, caplog):
    caplog.set_level(logging.INFO, logger=AUDIT)
    nobody = _undeclared(served, "seeder")
    r, stored = _post_summary(monkeypatch, nobody)
    assert r.status_code == 422 and stored == [], (r.status_code, r.text[:200])
    assert r.json()["detail"]["error"] == "seeded_by_not_a_declared_delegate"
    assert "refused" in _audit(caplog, RUNNER, nobody)


def test_seeded_by_an_undeclared_name_is_422_and_nothing_is_stamped(monkeypatch, served, caplog):
    caplog.set_level(logging.INFO, logger=AUDIT)
    ran = []

    class _Sess:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def run(self, *a, **k): ran.append(a); return types.SimpleNamespace(single=lambda: {"n": 1})

    monkeypatch.setattr(gateway, "neo4j_driver", types.SimpleNamespace(session=lambda: _Sess()))
    nobody = _undeclared(served, "seeder")
    _login(RUNNER)
    r = _client().post(f"/internal/cases/{CASE}/seeded-by", json={"seeded_by": nobody})
    assert r.status_code == 422 and ran == [], (r.status_code, r.text[:200])
    assert "refused" in _audit(caplog, RUNNER, nobody)


# -- /internal/human_tasks/register: the CALLER gate -------------------------------------------------
#
# A person may name only themselves; a service listed in TASK_REGISTER_SERVICES may name anyone.
# `requested_by` is bound as ruled 2026-11-04: self, a listed service, or a declared delegate's principal.

import json  # noqa: E402
from pathlib import Path  # noqa: E402

import yaml  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_LISTED = yaml.safe_load((_ROOT / "helm/invincible-agent/values.yaml").read_text(encoding="utf-8")
                         )["keycloak"]["taskRegisterServices"]
REGISTER = "/internal/human_tasks/register"
_FULL = {"kind": "k", "task_id": "t-1", "audience": "a", "title": "t", "summary": "s",
         "requested_by": "starter@example.invalid"}


def _register(monkeypatch, who, body=None, env=...):
    """POST the register as `who`; returns (response, the kwargs register_task received or None)."""
    seen = []
    monkeypatch.setattr(ht, "register_task", lambda **kw: (seen.append(kw), {"recipients": []})[1])
    if env is not ...:
        if env is None:
            monkeypatch.delenv("TASK_REGISTER_SERVICES", raising=False)
        else:
            monkeypatch.setenv("TASK_REGISTER_SERVICES", env)
    _login(who)
    r = _client().post(REGISTER, json=_FULL if body is None else body)
    return r, (seen[0] if seen else None)


@pytest.fixture
def listed(monkeypatch, served):
    """The chart's listed services in the env the server reads, and one that is NOT a delegate."""
    monkeypatch.setenv("TASK_REGISTER_SERVICES", json.dumps(_LISTED))
    assert gateway._task_register_services() == frozenset(_LISTED)
    plain = [s for s in _LISTED if s not in served]
    assert plain, "the chart lists no service that is not also a delegate: nothing to seal"
    return plain[0]


def test_register_a_person_is_refused_and_nothing_is_registered(monkeypatch, served, listed, caplog):
    caplog.set_level(logging.INFO, logger=AUDIT)
    person, _ = pair_and_outsider(served, RUNNER)
    r, got = _register(monkeypatch, person)
    assert r.status_code == 403 and r.json()["detail"]["error"] == "not_a_delegate", r.text[:200]
    assert got is None
    assert "refused:not_a_delegate" in _audit(caplog, person)


def test_register_a_listed_service_is_admitted_and_requested_by_passes_through(monkeypatch, served, listed):
    r, got = _register(monkeypatch, listed)
    assert r.status_code == 200, r.text[:200]
    assert got["requested_by"] == _FULL["requested_by"]


def test_register_a_declared_delegate_needs_no_listing(monkeypatch, served, listed):
    principal = sorted(served[RUNNER])[0]      # ruled 2026-11-04: a delegate names a principal declared for it
    r, got = _register(monkeypatch, RUNNER, {**_FULL, "requested_by": principal}, env=None)
    assert r.status_code == 200 and got is not None and got["requested_by"] == principal, (
        r.status_code, r.text[:200])
    r, got = _register(monkeypatch, RUNNER, env=None)         # the starter is not declared for it
    assert r.status_code == 403 and got is None, (r.status_code, r.text[:200])


def test_register_an_unlisted_service_is_refused(monkeypatch, served, listed, caplog):
    caplog.set_level(logging.INFO, logger=AUDIT)
    stranger = _undeclared(served, "svc")
    assert stranger not in _LISTED
    r, got = _register(monkeypatch, stranger)
    assert r.status_code == 403 and r.json()["detail"]["error"] == "not_a_delegate"
    assert got is None
    assert "refused:not_a_delegate" in _audit(caplog, stranger)


@pytest.mark.parametrize("env", [None, "", "not json", '{"a": 1}', '[1, 2]', '"svc:x"'],
                         ids=["unset", "blank", "malformed", "object", "non-strings", "string"])
def test_register_unset_and_malformed_env_refuse_a_service_that_is_not_a_delegate(
        monkeypatch, served, listed, env):
    r, got = _register(monkeypatch, listed, env=env)
    assert r.status_code == 403 and r.json()["detail"]["error"] == "not_a_delegate", (env, r.text[:200])
    assert got is None


# -- the one door a person's token can reach: promote_answer_artifact's publish_artifact -----------------

def test_the_promote_publish_step_posts_a_body_the_route_refuses_422_before_the_gate(
        monkeypatch, served, listed):
    """`execute_direct_call` posts {task_id, task_type, capability, user_jwt} and the step declares
    no extra_payload; the route needs audience, title, summary and requested_by. So that call is a 422
    before the handler runs, whoever the caller is: the promote step could not succeed before the gate.
    With a COMPLETE body a person's token naming itself is a 200 and naming another is a 403; a listed service's is a 200."""
    wf = yaml.safe_load((_ROOT / "policy/workflows/promote_answer_artifact.yaml").read_text(encoding="utf-8"))
    [step] = [s for s in wf["steps"] if s["id"] == "publish_artifact"]
    assert step["kind"] == "direct_call" and "extra_payload" not in step, step
    person, _ = pair_and_outsider(served, RUNNER)
    sent = {"task_id": step["id"], "task_type": "direct_call", "capability": step["capability"],
            "user_jwt": "x"}                        # exactly what execute_direct_call builds
    r, got = _register(monkeypatch, person, sent)
    assert r.status_code == 422, (r.status_code, r.text[:300])
    assert {tuple(e["loc"]) for e in r.json()["detail"]} >= {
        ("body", "audience"), ("body", "title"), ("body", "summary")}
    assert got is None
    complete = {**sent, "audience": "a", "title": "t", "summary": "s", "requested_by": person}
    r1, got1 = _register(monkeypatch, person, complete)           # a person naming themselves: admitted
    assert r1.status_code == 200 and got1["requested_by"] == person, (r1.status_code, r1.text[:200])
    r1, got1 = _register(monkeypatch, person, {**complete, "requested_by": _FULL["requested_by"]})
    assert r1.status_code == 403 and got1 is None, (r1.status_code, r1.text[:200])  # naming another: refused
    r2, got2 = _register(monkeypatch, listed, complete)           # control: a listed service
    assert r2.status_code == 200 and got2["task_id"] == step["id"], (r2.status_code, r2.text[:200])
