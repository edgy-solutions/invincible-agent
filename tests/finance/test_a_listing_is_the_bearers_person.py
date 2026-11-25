"""A finance listing is the verified bearer's person; a body email alone lists nothing.

Ruled by the architect, 2026-11-25, for `/enumerate_instances` and `/resolve_instance`: the
person is the verified token's subject. A body email with no verified bearer lists nothing and
logs `no_identity`. If the two disagree, refuse. `/measure` is unchanged (`_verb_caller`).

Every case runs on BOTH routes. The membership check is a recording double at the name `main`
uses, so "no lookup was made" is asserted on the double's calls. Emails are synthetic.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from agent_fleet.finance_agent import main as engine  # noqa: E402

PROGRAM = "NP-MERIDIAN"
ALICE = "alice@example.test"
DAVE = "dave@example.test"
SVC = "svc:supervisor"
MEMBERS = {ALICE, DAVE}
ROUTES = ["resolve", "enumerate"]
NOT_VERIFIED_MSG = "a finance listing reads the caller from a verified bearer"


class Double:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.raises: Exception | None = None

    def __call__(self, program, caller_id, **kw):
        self.calls.append((program, caller_id))
        if self.raises is not None:
            raise self.raises
        return program == PROGRAM and caller_id in MEMBERS


class Who:
    def __init__(self, authz_id, verified=True, reason=None, raw=None):
        self.authz_id, self.verified = authz_id, verified
        self.reason = reason if reason is not None else ("verified" if verified else "invalid: X")
        self.raw = raw if raw is not None else {}


@pytest.fixture
def double(monkeypatch):
    d = Double()
    monkeypatch.setattr(engine, "can_view_program", d)
    return d


@pytest.fixture
def client():
    with TestClient(engine.app) as c:
        yield c


@pytest.fixture
def bearer(monkeypatch):
    def set_(who):
        monkeypatch.setattr(engine, "_current_caller", lambda: who)
    set_(None)
    return set_


@pytest.fixture(autouse=True)
def _level(caplog):
    caplog.set_level(logging.INFO, logger=engine._reason_log.name)


def _post(client, route, body_email=None):
    if route == "resolve":
        body = {"identifier": engine.STATE.programs[0].name}
        url = "/resolve_instance"
    else:
        body = {"class_uri": engine.FIN + "Program", "limit": 100}
        url = "/enumerate_instances"
    if body_email is not None:
        body["user_email"] = body_email
    return client.post(url, json=body)


def _listed(r):
    assert r.status_code == 200, r.text
    j = r.json()
    return j["candidates"] if "candidates" in j else j["members"]


def _lines(caplog, prefix):
    return [r for r in caplog.records if r.getMessage().startswith(prefix)]


@pytest.mark.parametrize("route", ROUTES)
def test_1_a_body_email_with_no_bearer_lists_nothing_and_says_no_identity(
        route, double, client, bearer, caplog):
    assert _listed(_post(client, route, DAVE)) == []
    empties = _lines(caplog, "fin.")
    assert len(empties) == 1 and "reason=no_identity" in empties[0].getMessage()
    assert empties[0].levelno == logging.WARNING
    assert "body_caller=no_bearer" in empties[0].getMessage()
    # CONTROL: the same member's own verified bearer lists.
    bearer(Who(DAVE))
    assert _listed(_post(client, route, DAVE)), "control: the member's own bearer lists"


@pytest.mark.parametrize("route", ROUTES)
def test_2_a_verified_person_whose_body_names_another_is_refused(
        route, double, client, bearer, caplog):
    bearer(Who(ALICE))
    r = _post(client, route, DAVE)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "caller_mismatch"
    assert double.calls == [], "a refused listing made a membership lookup"
    refused = _lines(caplog, "fin.listing_refused")
    assert len(refused) == 1 and refused[0].levelno == logging.WARNING
    assert refused[0].getMessage() == (
        f"fin.listing_refused route={route} reason=caller_mismatch")
    for rec in caplog.records:
        for banned in (ALICE, DAVE):
            assert banned not in rec.getMessage(), rec.getMessage()


@pytest.mark.parametrize("route", ROUTES)
def test_3_a_difference_only_in_case_or_spaces_is_the_same_person(
        route, double, client, bearer):
    bearer(Who(ALICE))
    assert _listed(_post(client, route, f"  {ALICE.upper()} "))
    assert (PROGRAM, ALICE) in double.calls


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("body", [None, "", "   "])
def test_4_a_verified_bearer_with_an_empty_body_is_the_tokens_subject(
        route, body, double, client, bearer):
    bearer(Who(ALICE))
    assert _listed(_post(client, route, body))
    assert {c for _, c in double.calls} == {ALICE}


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("who, code", [
    (Who(None, verified=False, reason="invalid: ExpiredSignatureError"), "session_expired"),
    (Who(DAVE, verified=False, reason="invalid: ExpiredSignatureError"), "session_expired"),
    (Who(None, verified=False, raw={"exp": time.time() - 60}, reason="invalid: X"),
     "session_expired"),
    (Who(None, verified=False, reason="invalid: InvalidSignatureError"), "bearer_not_verified"),
    (Who(DAVE, verified=False, reason="no-verification-key"), "bearer_not_verified"),
    (Who(None, verified=False, reason="no 'email' claim"), "bearer_not_verified"),
    (Who(None, verified=False, reason="undecodable: DecodeError"), "bearer_not_verified"),
])
def test_5_an_unverified_bearer_is_a_401_and_the_body_is_not_used(
        route, who, code, double, client, bearer, caplog):
    bearer(who)
    r = _post(client, route, DAVE)  # the body names a member: it must not be used
    assert r.status_code == 401, r.text
    d = r.json()["detail"]
    assert d["error"] == code and NOT_VERIFIED_MSG in d["message"]
    assert double.calls == [], "an unverified bearer reached the membership check"
    refused = _lines(caplog, "fin.listing_refused")
    assert [x.getMessage() for x in refused] == [
        f"fin.listing_refused route={route} reason={code}"]
    assert all(x.name.endswith(".reasons") for x in refused)
    assert all(DAVE not in x.getMessage() for x in caplog.records)


@pytest.mark.parametrize("route", ROUTES)
def test_6_a_verified_service_bearer_never_falls_back_to_the_body(
        route, double, client, bearer, caplog):
    bearer(Who(SVC))
    assert _listed(_post(client, route, DAVE)) == []
    assert double.calls == [], "a service reached the membership check"
    empties = _lines(caplog, "fin.")
    assert len(empties) == 1
    msg = empties[0].getMessage()
    assert "reason=service_caller" in msg and "bearer=svc" in msg


@pytest.mark.parametrize("route", ROUTES)
def test_7_an_outage_is_still_a_503_for_a_person_bearer(route, double, client, bearer):
    bearer(Who(ALICE))
    double.raises = httpx.ConnectError("synthetic")
    r = _post(client, route, ALICE)
    assert r.status_code == 503 and "program membership check failed" in r.text


def test_8_measure_is_unchanged_a_service_bearer_acts_for_the_body_person(
        double, client, bearer):
    """The closest existing case: test_9_the_bearer_is_the_caller[SVC, ALICE, 200] in
    test_fin_verbs_honour_program_members.py: a service bearer, the body names the person,
    answered 200 and decided for the body's person."""
    bearer(Who(SVC))
    r = client.post("/measure/fin_burn_rate",
                    json={"params": {"program_id": PROGRAM}, "user_email": ALICE})
    assert r.status_code == 200, r.text
    assert double.calls == [(PROGRAM, ALICE)], double.calls
