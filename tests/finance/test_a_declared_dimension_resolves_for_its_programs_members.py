"""A declared dimension's values resolve for the members of their program (engine-fin).

A contract declares its dimensions (the hierarchy's columns, and `dimensions`); the engine reads
them from the asset, ONCE per listing request, AS THE CALLER, and offers each distinct value as a
member of the program its row belongs to. A version and a fiscal period are never searched in the
data: their members are the contract's declared version list and its declared calendar's labels.

Population: every (column, class) `asset_inputs.dimension_columns(contract)` returns, over BOTH
shipped contracts (the EV fixture and Program B's), read from the declaration and never typed. The
asset holds two programs; one person views each, one views neither, and one views the seed program
but holds no grant on the asset.

Run: uv run --no-sync pytest -c pyproject.toml --rootdir=. -p no:cacheprovider -p no:langsmith_plugin tests/finance/test_a_declared_dimension_resolves_for_its_programs_members.py
"""
from __future__ import annotations

import dataclasses
import logging
import os
from pathlib import Path

import pytest

pl = pytest.importorskip("polars")

from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.finance_agent import asset_inputs, fiscal_calendar  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent.instance_overlays import InstanceRow  # noqa: E402
from agent_fleet.utils import dataset_contracts  # noqa: E402
from tests.finance.test_a_flow_row_draws_to_its_declared_depth import b_frame  # noqa: E402
from tests.finance.test_fin_inputs_resolver import (  # noqa: E402,F401
    AS_OF, _clean_env, frame_of, token,
)
from tests.finance.test_variance_decomposition_over_the_ev_fixture import Gate, ROW_URN  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
EV_DIR = REPO / "contracts"
B_DIR = REPO / "tests" / "fixtures" / "fin_program_b"
SAMPLE_CAL = REPO / "policy" / "overlays" / "sample" / "fin_calendar"

ONE, TWO = "PRG-ONE", "PRG-TWO"
ALICE, BOB, CAROL, DAN = "alice@example.com", "bob@example.com", "carol@example.com", "dan@example.com"
SUFFIX = "~2"
VERSIONS = ("PMB", "EAC-CTR")
ROGUE = "ROGUE-VERSION"


class _Who:
    def __init__(self, authz_id):
        self.authz_id, self.verified, self.reason, self.raw = authz_id, True, "verified", {}

    def require_authz_id(self):
        return self.authz_id


class World:
    """One shipped contract served with a two-program asset."""

    def __init__(self, contract, frame, client, gate, bearer):
        self.contract, self.frame, self.client, self.gate, self._bearer = contract, frame, client, gate, bearer
        self.seed_program = engine.STATE.programs[0]

    def dims(self):
        return asset_inputs.dimension_columns(self.contract)

    def values(self, column, program):
        return sorted(self.frame.filter(pl.col(self.contract.scope) == program)[column].unique().to_list())

    def post(self, route, body, who):
        self._bearer(who)
        headers = {"Authorization": f"Bearer {token(who)}"} if who else {}
        r = self.client.post(route, json={**body, "user_email": who or ""}, headers=headers)
        assert r.status_code == 200, r.text
        return r.json()

    def resolve(self, identifier, class_uri, who):
        """The candidates for exactly `identifier` (a looser tier may add neighbours; they are not the question)."""
        return [c for c in self.candidates(identifier, class_uri, who) if c["instance_id"] == identifier]

    def candidates(self, identifier, class_uri, who):
        return self.post("/resolve_instance", {"identifier": identifier, "class_uri": class_uri}, who)["candidates"]

    def enumerate(self, class_uri, who):
        return self.post("/enumerate_instances", {"class_uri": class_uri, "limit": 10_000}, who)["members"]


def _two_programs(frame, contract):
    first = frame.with_columns(pl.lit(ONE).alias(contract.scope))
    second = frame.with_columns(pl.lit(TWO).alias(contract.scope), *[
        (pl.col(c) + SUFFIX).alias(c) for c, _ in asset_inputs.dimension_columns(contract)])
    return pl.concat([first, second])


def _views(program, who):
    seed = engine.STATE.programs[0].program_id
    return (program, who) in {(ONE, ALICE), (TWO, BOB), (seed, ALICE), (seed, BOB), (seed, DAN)}


@pytest.fixture(params=["ev_fixture", "program_b"])
def world(request, tmp_path, monkeypatch):
    if request.param == "ev_fixture":
        contract, frame = dataset_contracts.load_contract("ev_fixture", EV_DIR), frame_of()
        cal_dirs = [SAMPLE_CAL]
    else:
        contract, frame = dataset_contracts.load_contract("program_b", B_DIR / "contracts"), b_frame()
        cal_dirs = [B_DIR / "fin_calendar"]
    frame = _two_programs(frame, contract)
    path = tmp_path / "asset.parquet"
    frame.write_parquet(path)
    gate = Gate(pl.scan_parquet(path))
    gate.granted = {ALICE, BOB, CAROL}  # DAN holds no grant on the asset
    monkeypatch.setattr(engine.asset_inputs, "_load_client", gate.load)
    monkeypatch.setattr(engine.asset_inputs, "dataset_contract", lambda: contract)
    monkeypatch.setattr(engine, "can_view_program", lambda program, caller_id, **kw: _views(program, caller_id))
    monkeypatch.setenv("FIN_DATASET_URN", ROW_URN)
    monkeypatch.setenv("FIN_DATASET_BANNER", "SYNTHETIC TEST ASSET - not a real program.")
    monkeypatch.setenv("FIN_DATASET_CONTRACT", "ev_fixture")
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")
    monkeypatch.setenv("FIN_CALENDAR_OVERLAY_DIRS", os.pathsep.join(str(d) for d in cal_dirs))
    fiscal_calendar._cache.clear()

    def bearer(who):
        monkeypatch.setattr(engine, "_current_caller", lambda: _Who(who) if who else None)

    try:
        with TestClient(engine.app) as c:
            yield World(contract, frame, c, gate, bearer)
    finally:
        fiscal_calendar._cache.clear()


def _with_versions(world, monkeypatch):
    contract = dataclasses.replace(world.contract, version_column="version", versions=VERSIONS)
    monkeypatch.setattr(engine.asset_inputs, "dataset_contract", lambda: contract)
    return contract


# -- (1) every declared dimension: a member's value resolves, a non-member's does not -------------

def test_1_a_value_present_only_in_the_asset_resolves_for_a_member_of_its_program(world):
    assert world.dims(), "a contract with no dimension proves nothing"
    for column, cls in world.dims():
        value = world.values(column, TWO)[0]
        assert value.endswith(SUFFIX)
        got = [c for c in world.resolve(value, cls, BOB) if c["instance_id"] == value]
        assert len(got) == 1, (column, cls, got)
        hit = got[0]
        assert hit["score"] == 1.0 and hit["class_uri"] == cls and hit["program"] == TWO
        assert hit["provenance"] == {"dataset": ROW_URN, "column": column, "as_of": AS_OF}
        # a person who views the OTHER program does not get it, nor does one who views none
        assert [c for c in world.resolve(value, cls, ALICE) if c["instance_id"] == value] == [], (column, cls)
        assert [c for c in world.resolve(value, cls, CAROL) if c["instance_id"] == value] == [], (column, cls)


def test_1_the_asset_is_read_once_per_request_selecting_only_the_scope_and_the_dimensions(world):
    column, cls = world.dims()[0]
    before = len(world.gate.asked)
    world.resolve(world.values(column, TWO)[0], cls, BOB)
    assert len(world.gate.asked) - before == 1


# -- (2) enumerate -------------------------------------------------------------------------------

def test_2_enumerate_lists_the_asset_members_for_a_member_and_none_for_a_non_member(world):
    for column, cls in world.dims():
        mine = {m["instance_id"] for m in world.enumerate(cls, BOB)}
        theirs = {m["instance_id"] for m in world.enumerate(cls, ALICE)}
        assert set(world.values(column, TWO)) <= mine, (column, cls)
        assert not set(world.values(column, TWO)) & theirs, (column, cls)
        assert set(world.values(column, ONE)) <= theirs, (column, cls)
        assert world.enumerate(cls, CAROL) == [], (column, cls)


# -- (3) a version: the declaration, never the data ----------------------------------------------

def _serve_versions(world, tmp_path):
    """The asset's own `version` column carries the declared values AND one the contract does not list."""
    frame = world.frame.with_columns(pl.lit(VERSIONS[0]).alias("version"))
    frame = pl.concat([frame, frame.head(1).with_columns(pl.lit(ROGUE).alias("version"))])
    assert ROGUE in frame["version"].to_list()
    path = tmp_path / "versioned.parquet"
    frame.write_parquet(path)
    world.gate.frame = pl.scan_parquet(path)


def test_3_a_declared_version_resolves_and_one_only_the_data_carries_does_not(world, monkeypatch, tmp_path):
    _with_versions(world, monkeypatch)
    _serve_versions(world, tmp_path)
    cls = engine.FIN + "Version"
    for who, program in ((ALICE, ONE), (BOB, TWO)):
        got = world.resolve(VERSIONS[0], cls, who)
        assert [(c["instance_id"], c["score"], c["class_uri"], c["program"]) for c in got] == [
            (VERSIONS[0], 1.0, cls, program)], got
        assert got[0]["provenance"] == {"contract": world.contract.contract_id, "declaration": "version_dimension"}
        assert world.resolve(ROGUE, cls, who) == []
        assert [m["instance_id"] for m in world.enumerate(cls, who)] == sorted(VERSIONS)
    assert world.resolve(VERSIONS[0], cls, CAROL) == [] and world.enumerate(cls, CAROL) == []


# -- (4) a period: the declared calendar ---------------------------------------------------------

def test_4_a_declared_calendar_label_resolves_and_one_outside_it_does_not(world):
    cls = engine.FIN + "FiscalPeriod"
    calendar = fiscal_calendar.calendar_for(world.contract.calendar)
    label = calendar.labels[0]
    got = world.resolve(label, cls, BOB)
    assert [(c["instance_id"], c["score"], c["program"]) for c in got] == [(label, 1.0, TWO)], got
    assert got[0]["provenance"] == {"contract": world.contract.contract_id, "declaration": "calendar",
                                    "calendar_id": calendar.calendar_id}
    assert world.resolve("FY99-99", cls, BOB) == []
    assert [m["instance_id"] for m in world.enumerate(cls, ALICE)] == sorted(calendar.labels)
    assert world.enumerate(cls, CAROL) == []


# -- (5) a declared non-Program instance that names its program ----------------------------------

def test_5_a_declared_instance_naming_a_program_resolves_for_its_members_only(world, monkeypatch):
    cls = engine.FIN + "OBSElement"
    row = dict(class_uri=cls, instance_id="OBS-DECLARED-9", label="Declared Org Unit",
               granted_by="owner", ratified_by="owner", reason="test")
    monkeypatch.setattr(engine, "INSTANCES", (InstanceRow(**row, program=TWO),))
    assert [c["instance_id"] for c in world.resolve("OBS-DECLARED-9", cls, BOB)] == ["OBS-DECLARED-9"]
    assert world.resolve("OBS-DECLARED-9", cls, ALICE) == []
    monkeypatch.setattr(engine, "INSTANCES", (InstanceRow(**row),))
    assert world.resolve("OBS-DECLARED-9", cls, BOB) == []  # no program: withheld, as today
    assert "OBS-DECLARED-9" not in {m["instance_id"] for m in world.enumerate(cls, BOB)}


# -- (6) positive control: a seed value still resolves -------------------------------------------

def test_6_a_seed_value_still_resolves(world):
    program = world.seed_program
    got = world.candidates(program.name, engine.FIN + "Program", ALICE)
    assert program.program_id in {c["instance_id"] for c in got}


# -- (7) an unread asset: the seed and the declarations answer, with a reason line ---------------

def _lines(caplog):
    return [r.getMessage() for r in caplog.records if r.name == engine._reason_log.name]


def test_7_no_bearer_is_a_200_with_no_asset_members_and_says_why(world, caplog):
    column, cls = world.dims()[0]
    with caplog.at_level(logging.INFO, logger=engine._reason_log.name):
        got = world.resolve(world.values(column, TWO)[0], cls, None)
    assert got == []
    assert any("reason=asset_unread" in m and "code=no_bearer" in m for m in _lines(caplog)), _lines(caplog)
    assert world.gate.asked == [] or all(urn == ROW_URN for _, urn in world.gate.asked)


def test_7_a_caller_with_no_grant_on_the_asset_keeps_the_seed_and_loses_the_asset_members(world, caplog):
    column, cls = world.dims()[0]
    program = world.seed_program
    with caplog.at_level(logging.INFO, logger=engine._reason_log.name):
        seed = world.candidates(program.name, engine.FIN + "Program", DAN)
        asset = world.candidates(world.values(column, ONE)[0], cls, DAN)
    assert program.program_id in {c["instance_id"] for c in seed}
    assert asset == [] or all("provenance" not in c for c in asset)
    lines = [m for m in _lines(caplog) if "reason=asset_unread" in m]
    assert lines and all("code=access_denied" in m for m in lines), _lines(caplog)
    assert all(world.values(column, ONE)[0] not in m and ROW_URN not in m for m in lines)


def test_7_no_dataset_configured_reads_nothing(world, monkeypatch):
    monkeypatch.delenv("FIN_DATASET_URN")
    column, cls = world.dims()[0]
    before = len(world.gate.asked)
    assert world.resolve(world.values(column, TWO)[0], cls, BOB) == []
    assert len(world.gate.asked) == before


# -- (8) a dimension needs a scope ---------------------------------------------------------------

@pytest.mark.parametrize("keys", ["dimensions", "hierarchy", "version_dimension"])
def test_8_a_contract_under_scope_none_declaring_a_dimension_is_refused(world, keys):
    only = dataclasses.replace(
        world.contract, scope=None, **{
            "dimensions": {"dimensions": (("work_package", "fin:WorkPackage"), ), "hierarchy": (),
                           "version_column": None, "versions": ()},
            "hierarchy": {"dimensions": (), "hierarchy": ("work_package",),
                          "version_column": None, "versions": ()},
            "version_dimension": {"dimensions": (), "hierarchy": (), "version_column": "version",
                                  "versions": VERSIONS}}[keys])
    problems = [p for p in asset_inputs.contract_problems(only) if p.startswith("dimension_without_scope")]
    assert len(problems) == 1 and keys in problems[0], problems
    # the accepting control: the same keys under the contract's own scope raise no such problem
    scoped = dataclasses.replace(only, scope=world.contract.scope)
    assert not [p for p in asset_inputs.contract_problems(scoped) if p.startswith("dimension_without_scope")]


def test_8_a_dimensions_class_engine_fin_does_not_resolve_is_refused_naming_column_and_class(world):
    column = next(c for c in world.contract.types
                  if c not in world.contract.hierarchy and c != world.contract.scope)
    contract = dataclasses.replace(world.contract, dimensions=((column, "fin:NoSuchClass"),))
    problems = [p for p in asset_inputs.contract_problems(contract) if "NoSuchClass" in p]
    assert len(problems) == 1 and repr(column) in problems[0], problems
    ok = dataclasses.replace(world.contract, dimensions=((column, "fin:OBSElement"),))
    assert not [p for p in asset_inputs.contract_problems(ok) if column in p and "resolve" in p]


# -- (9) one map ---------------------------------------------------------------------------------

def test_9_the_program_of_classes_are_the_resolvable_classes():
    assert set(engine._PROGRAM_OF_CLASSES) == set(engine._RESOLVABLE)
    assert {engine.FIN + "Version", engine.FIN + "FiscalPeriod"} <= set(engine._RESOLVABLE)
    assert {engine.FIN + "Version", engine.FIN + "FiscalPeriod"} <= set(engine._NO_VERB_BY_DESIGN)
