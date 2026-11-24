"""A program the seed lacks is an INSTANCE ROW a deployment declares, not code.

Arms: the loader (unset is empty, each refusal names the file, a real seed name is refused through
the engine's wiring); the resolver answers the sandbox's declared programs by name at 1.0 and, with
the overlay empty, does not (the control); the enumerator lists one to a member and not to a
non-member; a declared non-Program is withheld from everyone; every declared Program has a
program_members row; values-sandbox.yaml points at a directory that exists; the seed is unchanged.
No program id is typed here: they are read from the sandbox yaml.

Run: uv run --no-sync pytest tests/finance/test_a_program_is_an_instance_row.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.finance_agent import instance_overlays as io  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent.seed import build_seed, check_consistency  # noqa: E402

SANDBOX = REPO / "policy" / "overlays" / "sandbox" / "fin_instances"
MEMBERS = REPO / "policy" / "program_members.yaml"
VALUES = REPO / "helm" / "invincible-agent" / "values-sandbox.yaml"
ENV = "FIN_INSTANCE_OVERLAY_DIRS"
CLASSES = {"Program": "fin#Program", "WorkPackage": "fin#WorkPackage"}

ALICE = "alice@example.com"
CAROL = "carol@example.com"


def _rows(directory: Path) -> list[dict]:
    out = []
    for f in sorted(directory.glob("*.yaml")):
        out += yaml.safe_load(f.read_text(encoding="utf-8"))["instances"]
    return out


def _programs() -> list[dict]:
    rows = [r for r in _rows(SANDBOX) if r["class"] == "Program"]
    assert rows, "the sandbox declares no Program row, so the arms below would check nothing"
    return rows


def _row(**kw) -> dict:
    base = {"class": "Program", "instance_id": "X-ONE", "label": "Label one", "granted_by": "seed",
            "ratified_by": "owner", "reason": "r"}
    base.update(kw)
    return base


def _write(tmp_path: Path, *files: tuple[str, object], sub: str = "d") -> Path:
    d = tmp_path / sub
    d.mkdir(exist_ok=True)
    for name, body in files:
        (d / name).write_text(body if isinstance(body, str) else yaml.safe_dump(body), encoding="utf-8")
    return d


def _load(d: Path, seed=()):
    return io.load_instances(CLASSES, seed, [d])


# -- the loader ----------------------------------------------------------------------------------

def test_unset_is_empty(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert io.load_instances(CLASSES) == ()
    monkeypatch.setenv(ENV, "")
    assert io.load_instances(CLASSES) == ()


def test_a_valid_set_loads_immutable_and_sorted(tmp_path, monkeypatch):
    d = _write(tmp_path, ("a.yaml", {"instances": [_row(instance_id="X-B", label="Beta"),
                                                    _row(instance_id="X-A", label="Alpha")]}),
               ("b.yaml", {"instances": [_row(**{"class": "WorkPackage"}, instance_id="X-C", label="Gamma")]}))
    monkeypatch.setenv(ENV, str(d))
    rows = io.load_instances(CLASSES)
    assert [(r.class_uri, r.instance_id) for r in rows] == [
        ("fin#Program", "X-A"), ("fin#Program", "X-B"), ("fin#WorkPackage", "X-C")]
    with pytest.raises(Exception):
        rows[0].label = "changed"  # frozen


@pytest.mark.parametrize("rows,reason", [
    ([{k: v for k, v in _row().items() if k != "reason"}], "missing"),
    ([_row(extra="x")], "unknown key"),
    ([_row(label="  ")], "non-empty"),
    ([_row(**{"class": "Nope"})], "unknown class"),
    ([_row(), _row(label="Other label")], "already declared"),
    ([_row(), _row(instance_id="X-TWO", label="LABEL ONE")], "collides"),
])
def test_each_refusal_raises_naming_the_file(tmp_path, rows, reason):
    d = _write(tmp_path, ("bad_one.yaml", {"instances": rows}))
    with pytest.raises(io.InstanceOverlayError) as e:
        _load(d)
    assert "bad_one.yaml" in str(e.value) and reason in str(e.value)


def test_a_duplicate_across_files_is_refused(tmp_path):
    d = _write(tmp_path, ("a.yaml", {"instances": [_row()]}),
               ("b.yaml", {"instances": [_row(label="Other label")]}))
    with pytest.raises(io.InstanceOverlayError) as e:
        _load(d)
    assert "b.yaml" in str(e.value) and "a.yaml" in str(e.value)


def test_a_malformed_file_shape_is_refused(tmp_path):
    for body in ("- just a list\n", "instances: notalist\n", "other: []\n", ""):
        d = _write(tmp_path, ("shape.yaml", body), sub="s")
        with pytest.raises(io.InstanceOverlayError) as e:
            _load(d)
        assert "shape.yaml" in str(e.value)


@pytest.mark.parametrize("field,value", [
    ("instance_id", "seed-id"), ("instance_id", "SEED LABEL"),
    ("label", "Seed-ID"), ("label", "seed label"),
])
def test_a_collision_with_the_seed_is_refused_case_insensitively(tmp_path, field, value):
    d = _write(tmp_path, ("c.yaml", {"instances": [_row(**{field: value})]}))
    with pytest.raises(io.InstanceOverlayError) as e:
        _load(d, seed=["SEED-ID", "Seed Label"])
    assert "c.yaml" in str(e.value) and "the seed" in str(e.value)


def test_the_sandbox_set_clears_the_real_seed_names(monkeypatch):
    monkeypatch.setenv(ENV, str(SANDBOX))
    got = engine._load_instances()
    assert {r.instance_id for r in got} == {r["instance_id"] for r in _rows(SANDBOX)}


def _seed_names() -> list[tuple[str, str]]:
    """Names the engine's seed really has, read from it: the Program's id and label, and one control
    account's. A row naming one of these is the collision the loader exists to refuse."""
    p, ca = engine.STATE.programs[0], engine.STATE.control_accounts[0]
    return [("instance_id", p.program_id), ("label", p.name), ("instance_id", ca.ca_id), ("label", ca.name)]


@pytest.mark.parametrize("field,value", _seed_names())
def test_a_real_seed_name_is_refused_through_the_engines_wiring(tmp_path, monkeypatch, field, value):
    """Gov's #468 follow-up 1: the collision check reached through `engine._load_instances`, with a
    name the seed has. The made-up-seed seal above cannot see the engine hand the loader no names;
    this one can. The control: the same file with names the seed lacks loads."""
    d = _write(tmp_path, ("c.yaml", {"instances": [_row(**{field: value})]}))
    monkeypatch.setenv(ENV, str(d))
    with pytest.raises(io.InstanceOverlayError) as e:
        engine._load_instances()
    assert "c.yaml" in str(e.value) and "the seed" in str(e.value)
    monkeypatch.setenv(ENV, str(_write(tmp_path, ("c.yaml", {"instances": [_row()]}), sub="ok")))
    assert [r.instance_id for r in engine._load_instances()] == [_row()["instance_id"]]


# -- the resolver --------------------------------------------------------------------------------

@pytest.fixture
def client():
    with TestClient(engine.app) as c:
        yield c


@pytest.fixture
def allow_all(monkeypatch):
    monkeypatch.setattr(engine, "can_view_program", lambda program, caller, **kw: True)


def _resolve(client, identifier, **kw):
    r = client.post("/resolve_instance", json={"identifier": identifier, "user_email": ALICE, **kw})
    assert r.status_code == 200, r.text
    return r.json()["candidates"]


def test_resolver_answers_each_declared_program_at_1_0_and_the_control_does_not(
        monkeypatch, client, allow_all):
    ids = [r["instance_id"] for r in _programs()]
    monkeypatch.setenv(ENV, str(SANDBOX))
    monkeypatch.setattr(engine, "INSTANCES", engine._load_instances())
    for iid in ids:
        hit = [c for c in _resolve(client, iid) if c["instance_id"] == iid]
        assert hit and hit[0]["class_uri"] == engine.FIN + "Program" and hit[0]["score"] == 1.0, iid
    # CONTROL: same requests, overlay empty.
    monkeypatch.setattr(engine, "INSTANCES", ())
    for iid in ids:
        assert not [c for c in _resolve(client, iid) if c["instance_id"] == iid], iid


# -- the enumerator ------------------------------------------------------------------------------

def test_a_declared_program_is_listed_to_a_member_and_not_to_a_non_member(monkeypatch, client):
    members = yaml.safe_load(MEMBERS.read_text(encoding="utf-8"))["programs"]
    ids = [r["instance_id"] for r in _programs()]
    member = next(m for i in ids for m in members[i]["grant_to"])
    outsider = next(e for e in (CAROL, "nobody@example.com")
                    if all(e not in members[i]["grant_to"] for i in ids))
    monkeypatch.setenv(ENV, str(SANDBOX))
    monkeypatch.setattr(engine, "INSTANCES", engine._load_instances())
    monkeypatch.setattr(
        engine, "can_view_program",
        lambda program, caller, **kw: caller in members.get(program, {}).get("grant_to", []))

    def listed(who):
        r = client.post("/enumerate_instances", json={
            "class_uri": engine.FIN + "Program", "limit": 100, "user_email": who})
        assert r.status_code == 200, r.text
        return {m["instance_id"] for m in r.json()["members"]}

    assert set(ids) <= listed(member)
    assert not set(ids) & listed(outsider)


def test_a_declared_non_program_is_withheld_from_a_caller_who_can_view_every_program(
        tmp_path, monkeypatch, client, allow_all):
    """Gov's #468 follow-up 2, and §7 of docs/contracts/finance-overlays.md: a declared row of any
    class but Program has no program to check, so it is withheld from everyone, even a caller every
    program admits. It fails closed. The control: a declared Program row in the same file is listed
    and resolved to the same caller, and so are the seed's own control accounts."""
    ca_row = _row(**{"class": "ControlAccount", "instance_id": "X-CA-ONE", "label": "Declared account one"})
    prog_row = _row(instance_id="X-PROG-ONE", label="Declared program one")
    monkeypatch.setenv(ENV, str(_write(tmp_path, ("c.yaml", {"instances": [ca_row, prog_row]}))))
    monkeypatch.setattr(engine, "INSTANCES", engine._load_instances())
    assert {(r.class_uri, r.instance_id) for r in engine.INSTANCES} == {
        (engine.FIN + "ControlAccount", "X-CA-ONE"), (engine.FIN + "Program", "X-PROG-ONE")}

    def listed(cls):
        r = client.post("/enumerate_instances", json={
            "class_uri": engine.FIN + cls, "limit": 100, "user_email": ALICE})
        assert r.status_code == 200, r.text
        return {m["instance_id"] for m in r.json()["members"]}

    def resolved(iid):
        return [c for c in _resolve(client, iid) if c["instance_id"] == iid]

    assert "X-CA-ONE" not in listed("ControlAccount")
    assert not resolved("X-CA-ONE")
    # CONTROL: the same caller sees the declared Program and the seed's accounts
    assert "X-PROG-ONE" in listed("Program") and resolved("X-PROG-ONE")
    assert {c.ca_id for c in engine.STATE.control_accounts} <= listed("ControlAccount")


def test_members_of_adds_no_state(monkeypatch):
    before = [p.program_id for p in engine.STATE.programs]
    monkeypatch.setenv(ENV, str(SANDBOX))
    monkeypatch.setattr(engine, "INSTANCES", engine._load_instances())
    got = {m["instance_id"] for m in engine._members_of(engine.FIN + "Program")}
    assert set(before) | {r["instance_id"] for r in _programs()} == got
    assert [p.program_id for p in engine.STATE.programs] == before


# -- the policy and config seals -------------------------------------------------------------------

def test_every_declared_program_has_a_program_members_row():
    members = yaml.safe_load(MEMBERS.read_text(encoding="utf-8"))["programs"]
    for r in _programs():
        row = members.get(r["instance_id"])
        assert row and row.get("grant_to"), (
            f"{r['instance_id']} has no grant_to row in policy/program_members.yaml, so "
            "can_view_program refuses it for everyone and the instance is unreachable")


def test_values_sandbox_points_the_fleet_at_a_directory_that_exists():
    env = yaml.safe_load(VALUES.read_text(encoding="utf-8"))["agentFleet"]["env"]
    assert ENV in env, f"values-sandbox.yaml agentFleet.env does not name {ENV}"
    path = env[ENV]
    assert path.startswith("/app/"), path
    assert (REPO / path[len("/app/"):]).is_dir(), f"{path} is not a directory in the repo"


# -- the seed is unchanged -------------------------------------------------------------------------

def test_the_seed_is_unchanged(monkeypatch):
    assert check_consistency(build_seed()) == []
    monkeypatch.setenv(ENV, str(SANDBOX))
    monkeypatch.setattr(engine, "INSTANCES", engine._load_instances())
    assert [p.program_id for p in engine.STATE.programs] == [p.program_id for p in build_seed().programs]
    assert len(engine.STATE.programs) == 1
