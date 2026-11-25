"""An empty `/resolve_instance` or `/enumerate_instances` answer logs one line saying why.

The architect, 2026-11-24: every condition under which resolve returns nothing for a verified
person gets one log line with its reason, and so does a listing that arrives with no identity.
The membership check is replaced at `engine.can_view_program` by a double (the pattern of
`test_fin_enumeration_honours_program_members.py`); the bearer is replaced at
`engine._current_caller`. Every record is read by its parsed `key=value` pairs.
"""
from __future__ import annotations

import logging
import sys

import httpx
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from agent_fleet.finance_agent import main as engine  # noqa: E402

PROGRAM = "NP-MERIDIAN"
ALICE = "alice@example.com"
BOB = "bob@example.com"
PROG = engine.FIN + "Program"
CA = engine.FIN + "ControlAccount"
FUNDING = engine.FIN + "FundingLine"  # a held class with no seed and no declared member
IDENT = "Systems Engineering"  # a ControlAccount label, matches 1.1


class Double:
    def __init__(self):
        self.calls = []

    def __call__(self, program, caller_id, **kw):
        self.calls.append((program, caller_id))
        return (program, caller_id) == (PROGRAM, ALICE)


class Who:
    def __init__(self, authz_id, verified=True):
        self.authz_id, self.verified = authz_id, verified


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


def _records(caplog):
    return [r for r in caplog.records if r.getMessage().startswith(("fin.resolve_empty", "fin.enumerate_empty"))]


def _fields(record):
    event, *pairs = record.getMessage().split(" ")
    out = {"event": event}
    for p in pairs:
        k, v = p.split("=", 1)
        out[k] = v
    return out


def _one(caplog):
    recs = _records(caplog)
    assert len(recs) == 1, [r.getMessage() for r in recs]
    return _fields(recs[0])


def _resolve(client, identifier, **kw):
    r = client.post("/resolve_instance", json={"identifier": identifier, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _enum(client, cls, **kw):
    r = client.post("/enumerate_instances", json={"class_uri": cls, "limit": 100, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_an_empty_identifier_says_so(double, client, bearer, caplog):
    assert _resolve(client, "  ", user_email=ALICE)["candidates"] == []
    f = _one(caplog)
    assert f["event"] == "fin.resolve_empty" and f["reason"] == "empty_identifier"
    assert f["class"] == "-" and f["matched"] == "0" and f["withheld"] == "-"


def test_a_bare_number_without_a_class_says_so(double, client, bearer, caplog):
    assert _resolve(client, "4", user_email=ALICE)["candidates"] == []
    assert _one(caplog)["reason"] == "bare_number_unscoped"


def test_a_class_the_engine_does_not_hold_says_so(double, client, bearer, caplog):
    uri = "http://example.com/other#Widget"
    assert _resolve(client, IDENT, class_uri=uri, user_email=ALICE)["candidates"] == []
    f = _one(caplog)
    assert f["reason"] == "class_not_held" and f["class"] == "Widget"
    caplog.clear()
    assert _enum(client, uri, user_email=ALICE)["outcome"] == "unsupported"
    f = _one(caplog)
    assert f["event"] == "fin.enumerate_empty" and f["reason"] == "class_not_held"


def test_a_class_uri_cannot_forge_a_line_or_a_field(double, client, bearer, caplog):
    # The class URI is the caller's text and its local name is logged: a newline or a space in it
    # would forge a second line or a `key=value` field.
    uri = "http://example.com/other#Widget\nfin.resolve_empty reason=not_a_member x=1"
    assert _resolve(client, IDENT, class_uri=uri, user_email=ALICE)["candidates"] == []
    rec = _records(caplog)
    assert len(rec) == 1
    msg = rec[0].getMessage()
    assert "\n" not in msg and msg.count("reason=") == 1 and " x=" not in msg
    assert _fields(rec[0])["reason"] == "class_not_held"


def test_a_held_class_with_no_members_says_so(double, client, bearer, caplog, monkeypatch):
    # Whether FundingLine holds seed rows depends on the loaded state, so `_members_of` is
    # patched for that ONE class (the others answer as they do).
    real = engine._members_of
    monkeypatch.setattr(engine, "_members_of", lambda u: [] if u == FUNDING else real(u))
    assert FUNDING in engine._RESOLVABLE
    assert _resolve(client, IDENT, class_uri=FUNDING, user_email=ALICE)["candidates"] == []
    f = _one(caplog)
    assert f["reason"] == "class_has_no_members" and f["class"] == "FundingLine"
    caplog.clear()
    assert _enum(client, FUNDING, user_email=ALICE)["members"] == []
    f = _one(caplog)
    assert f["event"] == "fin.enumerate_empty" and f["reason"] == "class_has_no_members"
    assert f["members"] == "0"


def test_no_match_says_what_was_read(double, client, bearer, caplog, monkeypatch):
    assert _resolve(client, "qzxv wkjh", user_email=ALICE)["candidates"] == []
    f = _one(caplog)
    assert f["reason"] == "no_match"
    assert "dataset_urn_set" in f and "declared_instances" in f
    assert f["dataset_urn_set"] == "false"
    caplog.clear()
    monkeypatch.setattr(engine.asset_inputs, "dataset_urn", lambda: "urn:example:synthetic")
    _resolve(client, "qzxv wkjh", user_email=ALICE)
    assert _one(caplog)["dataset_urn_set"] == "true"


def test_a_verified_person_whose_body_is_empty_resolves_as_the_person(double, client, bearer, caplog):
    # Changed by the bearer-first ruling (2026-11-25): this case was `no_identity` when the body
    # alone named the caller. A verified bearer IS the caller, so an empty body resolves as them.
    bearer(Who(ALICE, verified=True))
    assert _resolve(client, IDENT, user_email="")["candidates"]
    assert _records(caplog) == []
    assert (PROGRAM, ALICE) in double.calls


def test_no_bearer_and_an_empty_body_is_named_as_no_identity(double, client, bearer, caplog):
    assert _resolve(client, IDENT, user_email="")["candidates"] == []
    f = _one(caplog)
    assert f["reason"] == "no_identity"
    assert f["bearer"] == "none" and f["verified"] == "-" and f["body_caller"] == "empty"
    assert int(f["matched"]) >= 1


def test_a_service_caller_says_so(double, client, bearer, caplog):
    bearer(Who("svc:supervisor"))
    assert _resolve(client, IDENT, user_email="svc:supervisor")["candidates"] == []
    f = _one(caplog)
    assert f["reason"] == "service_caller" and int(f["matched"]) >= 1


def test_an_unset_directory_says_so(client, bearer, caplog, monkeypatch):
    bearer(Who(ALICE))
    # No Double: the real `can_view_program` runs and answers False for want of a directory.
    monkeypatch.delenv("TOPAZ_DIRECTORY_URL", raising=False)
    assert _resolve(client, IDENT, user_email=ALICE)["candidates"] == []
    assert _one(caplog)["reason"] == "directory_unconfigured"


def test_a_person_who_is_not_a_member_says_so(double, client, bearer, caplog, monkeypatch):
    monkeypatch.setenv("TOPAZ_DIRECTORY_URL", "http://directory.example.invalid")
    bearer(Who(BOB))
    assert _resolve(client, IDENT, user_email=BOB)["candidates"] == []
    f = _one(caplog)
    assert f["reason"] == "not_a_member" and f["body_caller"] == "matches_bearer"


def test_an_undecidable_program_says_so(double, client, bearer, caplog, monkeypatch):
    # Every seeded member has a program (measured), so `_program_of` is patched to None.
    monkeypatch.setattr(engine, "_program_of", lambda c, i: None)
    assert _resolve(client, IDENT, user_email=ALICE)["candidates"] == []
    f = _one(caplog)
    assert f["reason"] == "program_undecidable" and f["withheld"].startswith("program_undecidable:")


def test_mixed_withholding_is_tallied(double, client, bearer, caplog, monkeypatch):
    # One member's program is undecidable (patched), the rest belong to PROGRAM, which BOB is refused.
    real = engine._program_of
    monkeypatch.setattr(engine, "_program_of", lambda c, i: None if i == "1.1" else real(c, i))
    monkeypatch.setenv("TOPAZ_DIRECTORY_URL", "http://directory.example.invalid")
    bearer(Who(BOB))
    assert _enum(client, CA, user_email=BOB)["members"] == []
    f = _one(caplog)
    assert f["reason"] == "withheld_mixed"
    assert "program_undecidable:1" in f["withheld"] and "not_a_member:" in f["withheld"]


def test_a_listing_with_no_identity_says_so(double, client, bearer, caplog):
    assert _enum(client, PROG, user_email="")["members"] == []
    f = _one(caplog)
    assert f["event"] == "fin.enumerate_empty" and f["reason"] == "no_identity"
    assert f["bearer"] == "none" and int(f["members"]) >= 1


def test_the_line_carries_no_identifier_email_or_program(double, client, bearer, caplog):
    seen = []
    bearer(Who(BOB))  # a verified non-member, empty body: a not_a_member line
    _resolve(client, IDENT, user_email="")
    seen.append(_records(caplog)[-1].getMessage())
    bearer(None)
    _resolve(client, IDENT, user_email=BOB)
    seen.append(_records(caplog)[-1].getMessage())
    _enum(client, CA, user_email="")
    seen.append(_records(caplog)[-1].getMessage())
    assert len(seen) == 3
    ids = [m["instance_id"] for m in engine._members_of(CA)] + [m["instance_id"] for m in engine._members_of(PROG)]
    for msg in seen:
        for banned in (IDENT, ALICE, BOB, PROGRAM, *ids):
            assert banned not in msg, (banned, msg)


def test_a_hit_logs_nothing(double, client, bearer, caplog):
    bearer(Who(ALICE))
    assert _resolve(client, IDENT, user_email=ALICE)["candidates"]
    assert _enum(client, CA, user_email=ALICE)["members"]
    assert _records(caplog) == []


def test_too_many_logs_nothing(double, client, bearer, caplog):
    bearer(Who(ALICE))
    r = client.post("/enumerate_instances", json={"class_uri": CA, "limit": 1, "user_email": ALICE})
    assert r.json()["outcome"] == "too_many"
    assert _records(caplog) == []


def _levelno(caplog):
    recs = _records(caplog)
    assert len(recs) == 1, [r.getMessage() for r in recs]
    return recs[0].levelno


def test_the_level_names_a_fault_not_the_normal_case(double, client, bearer, caplog, monkeypatch):
    # The normal case: INFO.
    bearer(Who(ALICE))
    _resolve(client, "qzxv wkjh", user_email=ALICE)  # no_match
    assert _fields(_records(caplog)[0])["reason"] == "no_match"
    assert _levelno(caplog) == logging.INFO
    caplog.clear()
    _resolve(client, IDENT, class_uri="http://example.com/other#Widget", user_email=ALICE)
    assert _fields(_records(caplog)[0])["reason"] == "class_not_held"
    assert _levelno(caplog) == logging.INFO
    caplog.clear()
    monkeypatch.setenv("TOPAZ_DIRECTORY_URL", "http://directory.example.invalid")
    bearer(Who(BOB))
    _resolve(client, IDENT, user_email=BOB)
    assert _fields(_records(caplog)[0])["reason"] == "not_a_member"
    assert _levelno(caplog) == logging.INFO
    caplog.clear()
    bearer(Who(ALICE))
    _resolve(client, "  ", user_email=ALICE)
    assert _fields(_records(caplog)[0])["reason"] == "empty_identifier"
    assert _levelno(caplog) == logging.INFO
    caplog.clear()
    with monkeypatch.context() as m:
        m.setattr(engine, "_program_of", lambda c, i: None)
        _resolve(client, IDENT, user_email=ALICE)
    assert _fields(_records(caplog)[0])["reason"] == "program_undecidable"
    assert _levelno(caplog) == logging.INFO
    caplog.clear()
    # A fault: WARNING.
    bearer(None)
    _resolve(client, IDENT, user_email="")
    assert _fields(_records(caplog)[0])["reason"] == "no_identity"
    assert _levelno(caplog) == logging.WARNING
    caplog.clear()
    bearer(Who("svc:supervisor"))
    _resolve(client, IDENT, user_email="svc:supervisor")
    assert _fields(_records(caplog)[0])["reason"] == "service_caller"
    assert _levelno(caplog) == logging.WARNING
    caplog.clear()
    monkeypatch.delenv("TOPAZ_DIRECTORY_URL", raising=False)
    monkeypatch.undo()  # the real `can_view_program`, answering False for want of a directory
    monkeypatch.delenv("TOPAZ_DIRECTORY_URL", raising=False)
    bearer(Who(ALICE))  # `undo()` reverted the stub too
    _resolve(client, IDENT, user_email=ALICE)
    assert _fields(_records(caplog)[0])["reason"] == "directory_unconfigured"
    assert _levelno(caplog) == logging.WARNING


def test_a_mixed_tally_with_a_fault_is_a_warning(double, client, bearer, caplog, monkeypatch):
    real = engine._program_of
    monkeypatch.setattr(engine, "_program_of", lambda c, i: None if i == "1.1" else real(c, i))
    monkeypatch.setenv("TOPAZ_DIRECTORY_URL", "http://directory.example.invalid")
    # program_undecidable + not_a_member: both the normal case, so INFO.
    bearer(Who(BOB))
    assert _enum(client, CA, user_email=BOB)["members"] == []
    f = _one(caplog)
    assert f["reason"] == "withheld_mixed" and "program_undecidable:1" in f["withheld"]
    assert _levelno(caplog) == logging.INFO
    caplog.clear()
    # program_undecidable + no_identity: one part of the tally is a fault, so WARNING.
    bearer(None)
    assert _enum(client, CA, user_email="")["members"] == []
    f = _one(caplog)
    assert f["reason"] == "withheld_mixed"
    assert "program_undecidable:1" in f["withheld"] and "no_identity:" in f["withheld"]
    assert _levelno(caplog) == logging.WARNING


def test_a_directory_outage_is_logged_and_still_a_503(client, bearer, caplog, monkeypatch):
    def down(program, caller_id, **kw):
        raise httpx.ConnectError("synthetic")

    monkeypatch.setattr(engine, "can_view_program", down)
    monkeypatch.setenv("TOPAZ_DIRECTORY_URL", "http://directory.example.invalid")
    bearer(Who(ALICE))
    seen = []
    r = client.post("/resolve_instance", json={"identifier": IDENT, "user_email": ALICE})
    assert r.status_code == 503 and "program membership check failed" in r.text
    f = _one(caplog)
    assert f["event"] == "fin.resolve_empty" and f["reason"] == "directory_unreachable"
    assert _levelno(caplog) == logging.WARNING
    seen.append(_records(caplog)[0].getMessage())
    caplog.clear()
    r = client.post("/enumerate_instances", json={"class_uri": CA, "limit": 100, "user_email": ALICE})
    assert r.status_code == 503 and "program membership check failed" in r.text
    f = _one(caplog)
    assert f["event"] == "fin.enumerate_empty" and f["reason"] == "directory_unreachable"
    assert _levelno(caplog) == logging.WARNING
    seen.append(_records(caplog)[0].getMessage())
    ids = [m["instance_id"] for m in engine._members_of(CA)] + [m["instance_id"] for m in engine._members_of(PROG)]
    for msg in seen:
        for banned in (IDENT, ALICE, BOB, PROGRAM, *ids):
            assert banned not in msg, (banned, msg)


def test_the_body_is_compared_to_the_bearer_ignoring_case_and_spaces(double, client, bearer, caplog):
    # Gov's E8 seal. A mixed-case bearer holds the `bearer_id.casefold()` side, the padded
    # mixed-case body holds the `.casefold()` and `.strip()` on the body side.
    bearer(Who("Alice@Example.com", verified=True))
    assert _resolve(client, "qzxv wkjh", user_email="  aLICE@example.COM  ")["candidates"] == []
    f = _one(caplog)
    assert f["reason"] == "no_match"
    assert f["bearer"] == "user" and f["verified"] == "true"
    assert f["body_caller"] == "matches_bearer"
    caplog.clear()
    # The control: another person's address reads differs_from_bearer.
    assert _resolve(client, "qzxv wkjh", user_email=BOB)["candidates"] == []
    assert _one(caplog)["body_caller"] == "differs_from_bearer"
