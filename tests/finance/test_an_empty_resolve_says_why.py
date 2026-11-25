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
    caplog.set_level(logging.WARNING, logger=engine.log.name)


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


def test_a_verified_person_whose_body_is_empty_is_named_as_no_identity(double, client, bearer, caplog):
    bearer(Who(ALICE, verified=True))
    assert _resolve(client, IDENT, user_email="")["candidates"] == []
    f = _one(caplog)
    assert f["reason"] == "no_identity"
    assert f["bearer"] == "user" and f["verified"] == "true" and f["body_caller"] == "empty"
    assert int(f["matched"]) >= 1


def test_a_service_caller_says_so(double, client, bearer, caplog):
    assert _resolve(client, IDENT, user_email="svc:supervisor")["candidates"] == []
    f = _one(caplog)
    assert f["reason"] == "service_caller" and int(f["matched"]) >= 1


def test_an_unset_directory_says_so(client, bearer, caplog, monkeypatch):
    # No Double: the real `can_view_program` runs and answers False for want of a directory.
    monkeypatch.delenv("TOPAZ_DIRECTORY_URL", raising=False)
    assert _resolve(client, IDENT, user_email=ALICE)["candidates"] == []
    assert _one(caplog)["reason"] == "directory_unconfigured"


def test_a_person_who_is_not_a_member_says_so(double, client, bearer, caplog, monkeypatch):
    monkeypatch.setenv("TOPAZ_DIRECTORY_URL", "http://directory.example.invalid")
    assert _resolve(client, IDENT, user_email=BOB)["candidates"] == []
    f = _one(caplog)
    assert f["reason"] == "not_a_member" and f["body_caller"] == "no_bearer"


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
    bearer(Who(ALICE))
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
    assert _resolve(client, IDENT, user_email=ALICE)["candidates"]
    assert _enum(client, CA, user_email=ALICE)["members"]
    assert _records(caplog) == []


def test_too_many_logs_nothing(double, client, bearer, caplog):
    r = client.post("/enumerate_instances", json={"class_uri": CA, "limit": 1, "user_email": ALICE})
    assert r.json()["outcome"] == "too_many"
    assert _records(caplog) == []
