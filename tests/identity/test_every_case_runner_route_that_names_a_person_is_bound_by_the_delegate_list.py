"""SEAL 1, EXTENDED -- every case-runner route that takes a person's name is bound by the delegate list.

Architect, 2026-11-03: "action-record and every case-runner route that takes a person's name are bound
by the delegate list; the xfails stay strict until Lane 1 builds it."

POPULATION, derived from the app and decided on CONTENT (nothing is listed by hand and then trusted):

  1. CASE-RUNNER ROUTES: every route whose handler is gated on the case-runner identity, found by
     reading the handler for the gate (`_CASE_RUNNER_SERVICE_AUTHZ_ID`), not by path or prefix.
  2. CANDIDATE FIELDS: for every non-GET route in the OpenAPI document, every body/query/path field
     that could carry a person (a name-shaped detector, deliberately wide), AND every opaque
     object/array body field of a case-runner route (a name detector cannot see inside a free dict, so
     each one needs a decision of its own).
  3. Every (route, field) candidate must be DECIDED: DRIVEN below (behaviour asserted), or EXCLUDED
     with a reason. An undecided candidate FAILS the census, so a new route or field cannot arrive
     unsealed. The detector has a positive control: it must find the sites already known.

BEHAVIOUR for each DRIVEN site: the case-runner identity naming a principal that is NOT on its delegate
list must be refused with no effect (the effect is recorded at the point the route would write); a
declared pair is the control that gets in. Declared pairs are read from the chart values and served
through the env the server reads (`tests/identity/_identity_support.py`); none is typed here.

STRICT XFAILS name the ruling. Lane 1's fix PR removes the markers (a fixed route XPASSes, strict turns
that red, which is the signal to delete the marker and keep the seal).

Run: uv run pytest tests/identity/test_every_case_runner_route_that_names_a_person_is_bound_by_the_delegate_list.py -q
"""
from __future__ import annotations

import inspect
import re
import types

import pytest

pytest.importorskip("fastapi")

from src.iagent import case_summary  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import origin_writer  # noqa: E402
from tests.identity._identity_support import install_delegates, pair_and_outsider  # noqa: E402
from tests.identity.test_a_service_token_cannot_name_a_user_outside_the_delegate_list import (  # noqa: E402
    PERSON, _Fx, _client, _login)

RUNNER = gateway._CASE_RUNNER_SERVICE_AUTHZ_ID

RULING = ("RULED DEFECT (architect 2026-11-03: action-record and every case-runner route that takes a "
          "person's name are bound by the delegate list; strict until Lane 1 builds it). ")


@pytest.fixture(autouse=True)
def _clean():
    yield
    gateway.app.dependency_overrides.clear()


# -- the population ---------------------------------------------------------------------------------

def _key(method, path):
    return f"{method.upper()} {path}"


def case_runner_routes() -> set[str]:
    """Routes whose HANDLER carries the case-runner gate (read from the source, not the path)."""
    out = set()
    for r in gateway.app.routes:
        if not hasattr(r, "endpoint"):
            continue
        try:
            src = inspect.getsource(r.endpoint)
        except (OSError, TypeError):
            continue
        if "_CASE_RUNNER_SERVICE_AUTHZ_ID" in src:
            out |= {_key(m, r.path) for m in r.methods}
    return out


_NAMEY = re.compile(
    r"(on_behalf_of|_by$|^by_|approver|owner|assignee|actor|user_id|user_email|^user$|authz|principal|"
    r"reviewer|recipient|email|username|^sub$|initiator|author|launcher|proposer|requester|requested|"
    r"^who|identity|^subject$)", re.I)


def _fields():
    """{route: [(field_path, opaque)]} for every non-GET operation, from the OpenAPI document."""
    spec = gateway.app.openapi()
    schemas = spec["components"]["schemas"]

    def res(s):
        while isinstance(s, dict) and "$ref" in s:
            s = schemas.get(s["$ref"].split("/")[-1], {})
        return s if isinstance(s, dict) else {}

    def walk(s, prefix="", depth=0):
        s = res(s)
        out = []
        for k, v in (s.get("properties") or {}).items():
            v2 = res(v)
            alts = [res(x) for x in (v.get("anyOf") or [])] or [v2]
            kind = "opaque" if any(
                (a.get("type") == "object" and not a.get("properties"))
                or (a.get("type") == "array" and res(a.get("items", {})).get("type") in ("object", None)
                    and not res(a.get("items", {})).get("properties"))
                for a in alts) else "plain"
            out.append((prefix + k, kind))
            for a in alts:
                if depth < 3 and a.get("properties"):
                    out += walk(a, prefix + k + ".", depth + 1)
                items = res(a.get("items", {}))
                if depth < 3 and items.get("properties"):
                    out += walk(items, prefix + k + "[].", depth + 1)
        return out

    rows = {}
    for path, item in spec["paths"].items():
        for m, op in item.items():
            if m.lower() == "get" or not isinstance(op, dict):
                continue
            fs = [(f"{p['in']}:{p['name']}", "plain") for p in op.get("parameters", [])]
            for c in (op.get("requestBody") or {}).get("content", {}).values():
                fs += walk(c.get("schema", {}))
            rows[_key(m, path)] = fs
    return rows


def candidates() -> set[tuple[str, str]]:
    runner = case_runner_routes()
    out = set()
    for route, fs in _fields().items():
        for name, kind in fs:
            leaf = name.split(":")[-1].split(".")[-1].replace("[]", "")
            if _NAMEY.search(leaf) or (route in runner and kind == "opaque"):
                out.add((route, name))
    return out


# -- the drivers ------------------------------------------------------------------------------------

AR = _key("POST", "/internal/cases/{case_id}/action-record")
SB = _key("POST", "/internal/cases/{case_id}/seeded-by")
SM = _key("POST", "/internal/cases/{case_id}/summary")
OW = _key("POST", "/internal/origin/write")
RG = _key("POST", "/internal/human_tasks/register")


class _Sess:
    def __init__(self, fx, rows=None):
        self.fx, self.rows = fx, rows

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def run(self, cypher, *a, **k):
        self.fx.note(k)
        rows = self.rows
        return types.SimpleNamespace(single=lambda: {"n": 1, "id": "x"}, __iter__=None) if rows is None \
            else rows


class _Rows(list):
    def single(self):
        return {"n": 0}


def _neo(monkeypatch, fx):
    monkeypatch.setattr(gateway, "neo4j_driver", types.SimpleNamespace(
        session=lambda: types.SimpleNamespace(
            __enter__=lambda s: s, __exit__=lambda s, *a: False)), raising=False)

    class Session:
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def run(self, cypher, *a, **k):
            fx.note({"cypher": str(cypher)[:40]}, k)
            return _Rows()

    monkeypatch.setattr(gateway, "neo4j_driver", types.SimpleNamespace(session=lambda: Session()))


def _drive_action_record_seeded_by(monkeypatch, who, named):
    from src.iagent import answer_artifact_writer as aaw
    fx = _Fx()
    _neo(monkeypatch, fx)

    class _W:
        def __init__(self, *a, **k): ...

        def write_sync(self, bundle):
            fx.note(repr(bundle))
            return types.SimpleNamespace(success=True, error=None)

    monkeypatch.setattr(aaw, "AnswerArtifactWriter", _W)
    served = gateway._delegate_principals()
    owner, _ = pair_and_outsider(served, RUNNER)      # a valid owner, so only seeded_by varies
    _login(who)
    r = _client().post("/internal/cases/c-1/action-record", json={
        "record": {"action_id": "a-1", "provenance": {"case_id": "c-1"}},
        "on_behalf_of": owner, "seeded_by": named})
    return r, fx


def _drive_seeded_by_stamp(monkeypatch, who, named):
    fx = _Fx()
    _neo(monkeypatch, fx)
    _login(who)
    r = _client().post("/internal/cases/c-1/seeded-by", json={"seeded_by": named})
    return r, fx


def _drive_summary_seeded_by(monkeypatch, who, named):
    fx = _Fx()
    _neo(monkeypatch, fx)
    monkeypatch.setattr(case_summary, "upsert_summary", lambda **kw: fx.note(**kw))
    _login(who)
    r = _client().post("/internal/cases/c-1/summary", json={
        "state": "closed", "transitions": [], "seeded_by": named})
    return r, fx


def _drive_origin_approver(monkeypatch, who, named):
    from agent_fleet.utils.mesh_writers import neo4j_graph
    fx = _Fx()
    monkeypatch.setattr(ht, "check_can_view_program", lambda program, who_: True)
    monkeypatch.setattr(neo4j_graph, "Neo4jGraphWriter", lambda **kw: object())
    monkeypatch.setattr(origin_writer, "write_origin", lambda resolution, **kw: (
        fx.note(repr(kw.get("initiator"))), {"status": "written", "reason": None})[1])

    async def no_filing(*a, **k):
        return None
    monkeypatch.setattr(gateway, "_file_promotion_if_ready", no_filing)
    _login(who)
    r = _client().post("/internal/origin/write", json={
        "case_id": "c-1", "artifact_id": "ing-1", "dropped_by": {"authz_id": PERSON},
        "origin": {"program": "p-1"}, "evidence": {},
        "approval_chain": [{"role": "steward", "approver_sub": named}]})
    return r, fx


def _drive_origin_dropper(monkeypatch, who, named):
    from agent_fleet.utils.mesh_writers import neo4j_graph
    fx = _Fx()
    monkeypatch.setattr(ht, "check_can_view_program", lambda program, who_: (fx.note(who_), True)[1])
    monkeypatch.setattr(neo4j_graph, "Neo4jGraphWriter", lambda **kw: object())
    monkeypatch.setattr(origin_writer, "write_origin", lambda resolution, **kw: {"status": "written"})

    async def no_filing(*a, **k):
        return None
    monkeypatch.setattr(gateway, "_file_promotion_if_ready", no_filing)
    served = gateway._delegate_principals()
    steward, _ = pair_and_outsider(served, RUNNER)
    _login(who)
    r = _client().post("/internal/origin/write", json={
        "case_id": "c-1", "artifact_id": "ing-1", "dropped_by": {"authz_id": named},
        "origin": {"program": "p-1"}, "evidence": {},
        "approval_chain": [{"role": "steward", "approver_sub": steward}]})
    return r, fx


def _drive_register_requested_by(monkeypatch, who, named):
    fx = _Fx()
    monkeypatch.setattr(ht, "register_task", lambda **kw: (fx.note(**kw), {"recipients": []})[1])
    _login(who)
    r = _client().post("/internal/human_tasks/register", json={
        "kind": "k", "task_id": "t-1", "audience": "a", "title": "t", "summary": "s",
        "requested_by": named})
    return r, fx


# (route, field) -> (driver, how the value is bound, expected-today)
#   "principal": a principal declared for the CASE RUNNER (an owner / steward the runner acts for)
#   "delegate":  a declared DELEGATE identity (the seeding delegate), which is what `seeded_by` names
RED, REFUSES = "strict-xfail", "refuses"
DRIVEN = {
    (AR, "on_behalf_of"): None,      # driven in test_a_service_token_cannot_name_a_user_outside_... (xfail there)
    (AR, "seeded_by"): (_drive_action_record_seeded_by, "delegate", REFUSES),
    (SB, "seeded_by"): (_drive_seeded_by_stamp, "delegate", REFUSES),
    (SM, "seeded_by"): (_drive_summary_seeded_by, "delegate", REFUSES),
    (OW, "approval_chain"): (_drive_origin_approver, "principal", REFUSES),
}

# Decided, NOT driven, each with the reason and the check that backs it.
EXCLUDED = {
    (OW, "dropped_by"): "container of dropped_by.authz_id (see below)",
    (OW, "dropped_by.authz_id"): (
        "the person who DROPPED the document: a fact attested to the store and VERIFIED against Topaz "
        "program membership (`check_can_view_program`), not a principal the runner acts for; binding it "
        "to the runner's list would refuse every drop by anyone the runner is not declared for. "
        "EXCLUSION AGREED by the architect 2026-11-03: a program-membership check, not a delegation; "
        "the membership check is the seal, no marker here."),
    (OW, "origin"): "free dict; the handler reads origin.program only (a program key, not a person)",
    (OW, "evidence"): "free dict passed to origin_writer as evidence; the handler reads no person from it",
    (SM, "transitions"): "free list of hop outcomes; the handler reads `outcome` only",
    (AR, "record"): "the action record; the handler reads provenance.case_id only (a case id, not a person)",
    (_key("POST", "/internal/identity/redeem"), "claimed_launcher"): (
        "supervisor-only (403 not_the_redeemer for the case runner, checked below); not reachable"),
}
# Ruled IN as a SEPARATE defect (architect via Chris, 2026-11-03): not a case-runner route, so it has no
# case-runner driver; its legs are the "register" section further down this module.
DRIVEN_BELOW = {(RG, "requested_by")}
# Persona fields name a ROLE (a cell of the entitlement matrix), never a person.
_ROLE_FIELDS = re.compile(r"persona", re.I)


def _decided(route, field):
    leaf = field.split(".")[-1]
    if (route, field) in DRIVEN or (route, field) in EXCLUDED or (route, field) in DRIVEN_BELOW:
        return True
    return bool(_ROLE_FIELDS.search(leaf)) or leaf in ("recipient_scope",)


# the earlier module drives these three and the action-record owner
_EARLIER = {_key("POST", "/human_tasks/{task_id}/act"), _key("POST", "/ingest"),
            _key("POST", "/ingest/events"), AR}


def test_the_detector_has_a_positive_control():
    """It must find the sites we already know take a person; otherwise a quiet census proves nothing."""
    c = candidates()
    for site in [(AR, "on_behalf_of"), (AR, "seeded_by"), (SB, "seeded_by"), (SM, "seeded_by"),
                 (OW, "dropped_by.authz_id"), (OW, "approval_chain"), (RG, "requested_by")]:
        assert site in c, (site, sorted(c))
    assert {SB, SM, OW, AR} <= case_runner_routes(), case_runner_routes()


def test_every_candidate_site_is_decided():
    """UNDECIDED FAILS. A new case-runner route, or a new person-shaped field, must be driven or excluded."""
    undecided = sorted(s for s in candidates()
                       if not _decided(*s) and not (s[0] in _EARLIER and s[1].endswith("on_behalf_of")))
    assert not undecided, undecided


def test_every_decision_still_names_a_real_site():
    c = candidates()
    stale = sorted(s for s in list(DRIVEN) + list(EXCLUDED) if s not in c)
    assert not stale, stale


# -- behaviour --------------------------------------------------------------------------------------

def _pick(served, kind):
    own, outsider = pair_and_outsider(served, RUNNER)
    if kind == "principal":
        return own, outsider
    delegates = sorted(d for d in served if d != RUNNER)
    return delegates[0], outsider        # a declared delegate; a PERSON (not a delegate) is outside


def _mark(expect):
    return [pytest.mark.xfail(strict=True, reason=RULING + "This route records the name it is given "
            "without asking `_delegate_principals()`; Lane 1's fix PR removes this marker.")] \
        if expect == RED else []


_LIVE = sorted((s, v) for s, v in DRIVEN.items() if v is not None)


@pytest.mark.parametrize("site,spec", [pytest.param(s, v, id=f"{s[0]}:{s[1]}") for s, v in _LIVE])
def test_control_a_declared_value_is_admitted(monkeypatch, site, spec):
    served = install_delegates(monkeypatch)
    drive, kind, _ = spec
    declared, _outsider = _pick(served, kind)
    r, fx = drive(monkeypatch, RUNNER, declared)
    assert r.status_code < 500 and fx.has(declared), (site, r.status_code, r.text[:200], fx.seen)


@pytest.mark.parametrize("site,spec", [pytest.param(s, v, id=f"{s[0]}:{s[1]}", marks=_mark(v[2]))
                                       for s, v in _LIVE])
def test_the_case_runner_cannot_name_a_value_outside_its_delegate_list(monkeypatch, site, spec):
    served = install_delegates(monkeypatch)
    drive, kind, _ = spec
    _declared, outsider = _pick(served, kind)
    r, fx = drive(monkeypatch, RUNNER, outsider)
    assert not fx.has(outsider), (
        f"{site}: the case runner got {outsider!r} recorded ({r.status_code}); effects: {fx.seen}")


@pytest.mark.parametrize("site,spec", [pytest.param(s, v, id=f"{s[0]}:{s[1]}") for s, v in _LIVE])
def test_a_caller_that_is_not_the_case_runner_is_refused_at_the_gate(monkeypatch, site, spec):
    """True today on every case-runner-only route: a delegate that is not the runner, naming a value
    declared for the runner, gets nothing recorded."""
    served = install_delegates(monkeypatch)
    drive, kind, _ = spec
    declared, _ = _pick(served, kind)
    other = next(d for d in sorted(served) if d != RUNNER)
    r, fx = drive(monkeypatch, other, declared)
    assert not fx.has(declared) and 400 <= r.status_code < 500, (site, other, r.status_code, fx.seen)


# -- the exclusions are checked, not asserted -------------------------------------------------------

# -- /internal/human_tasks/register: RULED IN as a separate defect ------------------------------------
REG_RULING = ("RULED DEFECT (architect via Chris 2026-11-03, a separate defect from the case-runner "
              "routes): /internal/human_tasks/register needs TWO fixes -- ")
FIX_A = REG_RULING + ("(a) THE CALLER: gate the route on the delegate list / service identity as its "
                      "docstring promises, not on get_current_user alone. Turned by fix (a). "
                      "Lane 1's fix PR removes this marker.")
FIX_B = REG_RULING + ("(b) THE FIELD: requested_by comes from the token, never the body; a differing body "
                      "value is refused with the refusal envelope. Turned by fix (b). "
                      "Lane 1's fix PR removes this marker.")


def _served_refusal(caller, on_behalf_of):
    """The refusal the gateway SERVES for this (caller, named) pair, read from the live function."""
    from fastapi import HTTPException
    try:
        gateway._admit_on_behalf_of(types.SimpleNamespace(authz_id=caller), on_behalf_of)
    except HTTPException as exc:
        return exc.status_code, exc.detail
    raise AssertionError("expected the gateway to refuse this pair")


def test_the_register_route_is_not_a_case_runner_route():
    assert RG not in case_runner_routes()


def test_register_control_a_declared_service_identity_naming_itself_is_admitted(monkeypatch):
    served = install_delegates(monkeypatch)
    svc = next(d for d in sorted(served) if d != RUNNER)
    r, fx = _drive_register_requested_by(monkeypatch, svc, svc)
    assert r.status_code < 400 and fx.has(svc), (svc, r.status_code, r.text[:200], fx.seen)


@pytest.mark.xfail(strict=True, reason=FIX_A)
def test_register_a_plain_user_token_is_refused_at_the_route(monkeypatch):
    """Fix (a). The token is a person (declared, but not a delegate); requested_by is its own, so only
    the CALLER is in question."""
    served = install_delegates(monkeypatch)
    person, _ = pair_and_outsider(served, RUNNER)
    assert person not in served
    r, fx = _drive_register_requested_by(monkeypatch, person, person)
    want_status, want_detail = _served_refusal(person, "someone-else")
    assert not fx.has(person) and r.status_code == want_status and r.json()["detail"]["error"] == \
        want_detail["error"], (r.status_code, r.text[:200], fx.seen)


@pytest.mark.xfail(strict=True, reason=FIX_B)
def test_register_a_body_requested_by_that_differs_from_the_token_is_refused(monkeypatch):
    """Fix (b). The caller IS a declared service identity (passes any gate); the body names someone
    else. register_task must receive the token's identity or nothing."""
    served = install_delegates(monkeypatch)
    svc = next(d for d in sorted(served) if d != RUNNER)
    _own, outsider = pair_and_outsider(served, svc)
    r, fx = _drive_register_requested_by(monkeypatch, svc, outsider)
    want_status, want_detail = _served_refusal(svc, outsider)
    assert not fx.has(outsider) and r.status_code == want_status and \
        r.json()["detail"]["error"] == want_detail["error"], (r.status_code, r.text[:200], fx.seen)


def test_the_excluded_redeem_route_is_not_reachable_by_the_case_runner(monkeypatch):
    install_delegates(monkeypatch)
    _login(RUNNER)
    r = _client().post("/internal/identity/redeem", json={"run_id": "r", "call_id": "c", "claimed_launcher": PERSON})
    assert r.status_code == 403 and r.json()["detail"]["error"] == "not_the_redeemer", r.text[:200]


def test_the_excluded_dropper_is_verified_against_membership_not_acted_for(monkeypatch):
    """Backs the exclusion: dropped_by reaches the membership check and nothing else; the runner's
    acting principal (the steward) is the separate field the seal above binds."""
    served = install_delegates(monkeypatch)
    r, fx = _drive_origin_dropper(monkeypatch, RUNNER, PERSON)
    assert r.status_code < 400 and fx.seen == [f'[["{PERSON}"], {{}}]'], (r.status_code, fx.seen)
