"""engine-fin lists and resolves only the members of programs the caller can view.

The membership check is replaced at the name `main` uses (`engine.can_view_program`) with a
recording double. The population is derived from `_RESOLVABLE` and `STATE`, never typed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from agent_fleet.finance_agent import main as engine  # noqa: E402
_SYNC = REPO / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))
from program_member_sync import load_programs  # noqa: E402

PROGRAM = "NP-MERIDIAN"
ALICE = "alice@example.com"
CAROL = "carol@example.com"


class Double:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.raises: Exception | None = None
        self.allow_all = False

    def __call__(self, program, caller_id, **kw):
        self.calls.append((program, caller_id))
        if self.raises is not None:
            raise self.raises
        return self.allow_all or (program, caller_id) == (PROGRAM, ALICE)


@pytest.fixture
def double(monkeypatch):
    d = Double()
    monkeypatch.setattr(engine, "can_view_program", d)
    return d


@pytest.fixture
def client():
    with TestClient(engine.app) as c:
        yield c


class _Who:
    def __init__(self, authz_id, verified=True):
        self.authz_id, self.verified = authz_id, verified
        self.reason, self.raw = ("verified" if verified else "invalid: X"), {}


@pytest.fixture
def bearer(monkeypatch):
    """Who the verified bearer says the caller is (a listing decides for the bearer's person,
    ruled 2026-11-25). `bearer(None)` is a request with no bearer."""
    def _set(who):
        monkeypatch.setattr(engine, "_current_caller",
                            lambda: _Who(who) if who is not None else None)
    return _set


def _enum(client, cls, **kw):
    r = client.post("/enumerate_instances", json={"class_uri": cls, "limit": 100, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_1_member_sees_non_member_does_not_for_every_class(double, client, bearer):
    for cls in engine._RESOLVABLE:
        bearer(ALICE)
        mine = _enum(client, cls, user_email=ALICE)
        assert mine["outcome"] == "members" and mine["members"], f"control empty for {cls}"
        bearer(CAROL)
        theirs = _enum(client, cls, user_email=CAROL)
        assert theirs["members"] == [], f"carol sees {cls} members"


def test_2_no_caller_no_members(double, client, bearer):
    cls = engine.FIN + "ControlAccount"
    bearer(None)
    assert _enum(client, cls, user_email="")["members"] == []
    assert _enum(client, cls)["members"] == []  # old-shape body
    # a body naming a service, with no bearer: nobody (the body alone names no one)
    assert _enum(client, cls, user_email="svc:cortex-bff")["members"] == []
    # a verified SERVICE bearer: refused as a service, even where the membership double allows all
    double.allow_all = True
    bearer("svc:cortex-bff")
    assert _enum(client, cls, user_email="svc:cortex-bff")["members"] == []
    bearer(ALICE)
    assert _enum(client, cls, user_email=ALICE)["members"], "control: alice sees members"


def test_3_count_is_taken_after_the_filter(double, client, bearer):
    cls = engine.FIN + "ControlAccount"
    bearer(ALICE)
    a = _enum(client, cls, user_email=ALICE, limit=0)
    assert a["outcome"] == "too_many" and a["count"] > 0
    bearer(CAROL)
    c = _enum(client, cls, user_email=CAROL, limit=0)
    assert c["outcome"] != "too_many", c
    assert c["outcome"] == "members" and c["members"] == [] and c["count"] == 0


def test_4_resolve(double, client, bearer):
    name = engine.STATE.programs[0].name

    def resolve(**kw):
        r = client.post("/resolve_instance", json={"identifier": name, **kw})
        assert r.status_code == 200, r.text
        return r.json()["candidates"]

    bearer(ALICE)
    assert PROGRAM in {c["instance_id"] for c in resolve(user_email=ALICE)}
    bearer(CAROL)
    assert resolve(user_email=CAROL) == []
    bearer(None)
    assert resolve(user_email="") == []


def test_5_outage_is_a_503_on_both_routes(double, client, bearer):
    bearer(ALICE)
    double.raises = httpx.ConnectError("topaz down")
    r = client.post("/enumerate_instances",
                    json={"class_uri": engine.FIN + "Program", "user_email": ALICE})
    assert r.status_code == 503 and "program membership check failed" in r.text
    r = client.post("/resolve_instance",
                    json={"identifier": engine.STATE.programs[0].name, "user_email": ALICE})
    assert r.status_code == 503 and "program membership check failed" in r.text


def test_6_coverage_seal(double):
    assert set(engine._PROGRAM_OF_CLASSES) == set(engine._RESOLVABLE)
    for cls in engine._RESOLVABLE:
        members = engine._members_of(cls)
        assert members, cls
        for m in members:
            assert engine._program_of(cls, m["instance_id"]) is not None, (cls, m)
        assert engine._visible_to(ALICE, members) == members, cls


def test_7_once_per_program(double, client, bearer):
    cls = engine.FIN + "ControlAccount"
    bearer(ALICE)
    mine = _enum(client, cls, user_email=ALICE)
    programs = {c.program_id for c in engine.STATE.control_accounts}
    assert len(mine["members"]) > len(programs)
    assert len(double.calls) == len(programs)


def test_8_policy_seal():
    raw = yaml.safe_load((REPO / "policy" / "program_members.yaml").read_text(encoding="utf-8"))
    records, errors = load_programs(raw)
    assert errors == []
    by_key = {r.key: r for r in records}
    for p in engine.STATE.programs:
        assert p.program_id in by_key, (
            f"{p.program_id} is not in policy/program_members.yaml: without it the finance "
            "canvas menu is empty for everyone")
    assert ALICE in by_key[PROGRAM].grant_to, (
        "without alice in NP-MERIDIAN the finance canvas menu is empty for everyone")
