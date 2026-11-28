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
import json
import logging
import os
from pathlib import Path

import pytest
import yaml

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
ERIN = "erin@example.com"  # views BOTH programs and the seed
SUFFIX = "~2"
VERSIONS = ("PMB", "EAC-CTR")
ROGUE = "ROGUE-VERSION"


class _Who:
    def __init__(self, authz_id):
        self.authz_id, self.verified, self.reason, self.raw = authz_id, True, "verified", {}

    def require_authz_id(self):
        return self.authz_id


def named(candidate, name):
    """Is `candidate` the thing called `name`? A hierarchy level's member is its PATH (a JSON array of
    names, top level down) and its label the name; any other member's id is its name."""
    ident = candidate["instance_id"]
    if ident == name:
        return True
    return ident.startswith("[") and candidate["label"] == name and json.loads(ident)[-1] == name


class World:
    """One shipped contract served with a two-program asset."""

    def __init__(self, contract, frame, client, gate, bearer, tmp_path):
        self.contract, self.frame, self.client, self.gate, self._bearer = contract, frame, client, gate, bearer
        self.tmp_path = tmp_path
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
        return [c for c in self.candidates(identifier, class_uri, who) if named(c, identifier)]

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
    return (program, who) in {(ONE, ALICE), (TWO, BOB), (seed, ALICE), (seed, BOB), (seed, DAN),
                              (ONE, ERIN), (TWO, ERIN), (seed, ERIN)}


@pytest.fixture(params=["ev_fixture", "program_b"])
def world(request, tmp_path, monkeypatch):
    if request.param == "ev_fixture":
        contract_dir = EV_DIR
        contract, frame = dataset_contracts.load_contract("ev_fixture", EV_DIR), frame_of()
        cal_dirs = [SAMPLE_CAL]
    else:
        contract_dir = B_DIR / "contracts"
        contract, frame = dataset_contracts.load_contract("program_b", contract_dir), b_frame()
        cal_dirs = [B_DIR / "fin_calendar"]
    frame = _two_programs(frame, contract)
    path = tmp_path / "asset.parquet"
    frame.write_parquet(path)
    gate = Gate(pl.scan_parquet(path))
    gate.granted = {ALICE, BOB, CAROL, ERIN}  # DAN holds no grant on the asset
    monkeypatch.setattr(engine.asset_inputs, "_load_client", gate.load)
    monkeypatch.setattr(engine, "can_view_program", lambda program, caller_id, **kw: _views(program, caller_id))
    monkeypatch.setenv("FIN_DATASET_URN", ROW_URN)
    monkeypatch.setenv("FIN_DATASET_BANNER", "SYNTHETIC TEST ASSET - not a real program.")
    monkeypatch.setenv("FIN_DATASET_CONTRACT", request.param)
    monkeypatch.setenv("DATASET_CONTRACT_DIR", str(contract_dir))
    assert engine.asset_inputs.dataset_contract() == contract
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")
    monkeypatch.setenv("FIN_CALENDAR_OVERLAY_DIRS", os.pathsep.join(str(d) for d in cal_dirs))
    fiscal_calendar._cache.clear()

    def bearer(who):
        monkeypatch.setattr(engine, "_current_caller", lambda: _Who(who) if who else None)

    try:
        with TestClient(engine.app) as c:
            yield World(contract, frame, c, gate, bearer, tmp_path)
    finally:
        fiscal_calendar._cache.clear()


ROW_CONTRACT = "row_versions"
ROW_FN = "fin_b_versions_row"
B_LEVELS = ["program_id", "wbs_2", "wbs_3", "wbs_4", "wbs_5", "control_account"]


def _dataset_row():
    """A dataset measure row, as an overlay file would declare it, read under `ROW_CONTRACT`."""
    return {
        "measure_id": ROW_FN, "verb": "xfinbversionsrow", "name": ROW_FN,
        "inputs": {"params": {"program_id": {"required": True}, "version": {"required": True}},
                   "dataset": {"urn": ROW_URN, "banner": "SYNTHETIC test fixture.", "contract": ROW_CONTRACT,
                               "levels": B_LEVELS, "value": "amount", "per_path": "sum"},
                   "other_threshold": "0"},
        "computation": {"module": "agent_fleet.finance_agent.measure_modules.variance_decomposition",
                        "function": "flow_edges", "version": "1.4.0",
                        "derived_from": {"authority": "Test fixture, no external method",
                                         "clause": "A signed sum split down a hierarchy",
                                         "citation": "name-only",
                                         "transcription": "each edge is the signed sum beneath its child"}},
        "render": {"shape": "FLOW_DECOMPOSITION", "value_label": ROW_FN, "unit": "USD"},
        "policy": {"status": "sample", "cells": ["PROGRAM_FINANCE"], "granted_by": "seed",
                   "reason": "a test row over a synthetic fixture"},
    }


def _declare_versions(world, monkeypatch):
    """Declare a dataset ROW whose contract declares versions, loaded the engine's own way: the
    contract dir and the overlay dir set, then `_load_declared()` assigned to `DECLARED`. The
    deployment contract (the world's) stays as it was: it cannot hold a version column."""
    cdir, odir = world.tmp_path / "row_contracts", world.tmp_path / "row_overlay"
    cdir.mkdir()
    odir.mkdir()
    world_dir = EV_DIR if world.contract.contract_id == "ev_fixture" else B_DIR / "contracts"
    (cdir / f"{world.contract.contract_id}.yaml").write_bytes(
        (world_dir / f"{world.contract.contract_id}.yaml").read_bytes())
    doc = yaml.safe_load((B_DIR / "contracts" / "program_b_versions.yaml").read_text(encoding="utf-8"))
    doc["contract_id"] = ROW_CONTRACT
    doc["version_dimension"] = {"column": "version", "values": list(VERSIONS)}
    (cdir / f"{ROW_CONTRACT}.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    (odir / f"{ROW_FN}.yaml").write_text(yaml.safe_dump(_dataset_row(), sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("DATASET_CONTRACT_DIR", str(cdir))
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(odir))
    monkeypatch.setenv("FIN_CALENDAR_OVERLAY_DIRS", os.pathsep.join(
        [os.environ["FIN_CALENDAR_OVERLAY_DIRS"], str(B_DIR / "fin_calendar")]))
    fiscal_calendar._cache.clear()
    rows = engine._load_declared()
    monkeypatch.setattr(engine, "DECLARED", rows)
    assert rows[ROW_FN].contract.versions == VERSIONS
    assert asset_inputs.contract_problems(engine.asset_inputs.dataset_contract()) == []
    assert engine.asset_inputs.dataset_contract().versions == ()
    return rows[ROW_FN].contract


# -- (1) every declared dimension: a member's value resolves, a non-member's does not -------------

def test_1_a_value_present_only_in_the_asset_resolves_for_a_member_of_its_program(world):
    assert world.dims(), "a contract with no dimension proves nothing"
    for column, cls in world.dims():
        value = world.values(column, TWO)[0]
        assert value.endswith(SUFFIX)
        got = world.resolve(value, cls, BOB)
        assert len(got) == 1, (column, cls, got)
        hit = got[0]
        assert hit["score"] == 1.0 and hit["class_uri"] == cls and hit["programs"] == [TWO]
        assert "program" not in hit
        assert hit["provenance"] == {"dataset": ROW_URN, "column": column, "as_of": AS_OF}
        # a person who views the OTHER program does not get it, nor does one who views none
        assert world.resolve(value, cls, ALICE) == [], (column, cls)
        assert world.resolve(value, cls, CAROL) == [], (column, cls)


def test_1_the_asset_is_read_once_per_request_selecting_only_the_scope_and_the_dimensions(world):
    column, cls = world.dims()[0]
    before = len(world.gate.asked)
    world.resolve(world.values(column, TWO)[0], cls, BOB)
    assert len(world.gate.asked) - before == 1


# -- (2) enumerate -------------------------------------------------------------------------------

def test_2_enumerate_lists_the_asset_members_for_a_member_and_none_for_a_non_member(world):
    for column, cls in world.dims():
        mine = {m["label"] for m in world.enumerate(cls, BOB)}
        theirs = {m["label"] for m in world.enumerate(cls, ALICE)}
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
    row_contract = _declare_versions(world, monkeypatch)
    _serve_versions(world, tmp_path)
    cls = engine.FIN + "Version"
    for who, program in ((ALICE, ONE), (BOB, TWO)):
        got = world.resolve(VERSIONS[0], cls, who)
        assert [(c["instance_id"], c["score"], c["class_uri"], c["programs"]) for c in got] == [
            (VERSIONS[0], 1.0, cls, [program])], got
        assert got[0]["provenance"] == {"contract": row_contract.contract_id, "declaration": "version_dimension"}
        assert world.resolve(ROGUE, cls, who) == []
        assert [m["instance_id"] for m in world.enumerate(cls, who)] == sorted(VERSIONS)
    assert world.resolve(VERSIONS[0], cls, CAROL) == [] and world.enumerate(cls, CAROL) == []


def test_3b_with_no_dataset_row_declaring_versions_no_version_is_listed(world, monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "DECLARED", {})
    _serve_versions(world, tmp_path)
    cls = engine.FIN + "Version"
    for who in (ALICE, BOB):
        assert world.enumerate(cls, who) == []
        assert world.resolve(VERSIONS[0], cls, who) == []


# -- (4) a period: the declared calendar ---------------------------------------------------------

def test_4_a_declared_calendar_label_resolves_and_one_outside_it_does_not(world):
    cls = engine.FIN + "FiscalPeriod"
    calendar = fiscal_calendar.calendar_for(world.contract.calendar)
    label = calendar.labels[0]
    got = world.resolve(label, cls, BOB)
    assert [(c["instance_id"], c["score"], c["programs"]) for c in got] == [(label, 1.0, [TWO])], got
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


# -- (10) a value in two programs is ONE entry naming every program the caller views --------------

def _serve(world, frame, name="served.parquet"):
    path = world.tmp_path / name
    frame.write_parquet(path)
    world.gate.frame = pl.scan_parquet(path)


def _asset(candidates):
    """The candidates the ASSET gave (they carry a provenance); a seed member of the same text (the EV
    fixture's ControlAccount `1.1`, a bare id) is another thing and is not counted."""
    return [c for c in candidates if "provenance" in c]


def test_10_a_value_in_two_programs_is_one_entry_naming_every_program_the_caller_views(world):
    scope = world.contract.scope
    one = world.frame.filter(pl.col(scope) == ONE)
    _serve(world, pl.concat([one, one.with_columns(pl.lit(TWO).alias(scope))]))  # NOT suffixed in TWO
    assert world.dims()
    for column, cls in world.dims():
        value = world.values(column, ONE)[0]
        assert not value.endswith(SUFFIX)
        both = _asset(world.resolve(value, cls, ERIN))
        assert len(both) == 1, (column, cls, both)
        assert both[0]["programs"] == [ONE, TWO] and "program" not in both[0], both
        listed = _asset([m for m in world.enumerate(cls, ERIN) if named(m, value)])
        assert len(listed) == 1 and listed[0]["programs"] == [ONE, TWO], (column, cls, listed)
        # the control: the same value for a caller who views one program
        for who, program in ((ALICE, ONE), (BOB, TWO)):
            got = _asset(world.resolve(value, cls, who))
            assert len(got) == 1 and got[0]["programs"] == [program] and "program" not in got[0], (who, got)
        assert _asset(world.resolve(value, cls, CAROL)) == []


# -- (11) a seed or declared id wins over an asset member of the same id --------------------------

PLAIN = {"ev_fixture": "status_period", "program_b": "ipt_1"}  # a column that is no hierarchy level
OBS = engine.FIN + "OBSElement"


def _plain_dimension(world, monkeypatch, value):
    """`PLAIN`'s column declared a dimension of `fin:OBSElement` (a non-hierarchy dimension), every
    row of the asset (both programs) carrying `value` in it."""
    column = PLAIN[world.contract.contract_id]
    assert column not in world.contract.hierarchy
    contract = dataclasses.replace(world.contract, dimensions=((column, "fin:OBSElement"),))
    monkeypatch.setattr(engine.asset_inputs, "dataset_contract", lambda: contract)
    _serve(world, world.frame.with_columns(pl.lit(value).alias(column)))
    assert any(c == column and k == OBS for c, k in asset_inputs.dimension_columns(contract))


def test_11_a_seed_id_equal_to_an_asset_dimension_members_id_is_the_one_candidate(world, monkeypatch):
    seed = engine.STATE.obs[0]
    _plain_dimension(world, monkeypatch, seed.obs_id)
    got = world.resolve(seed.obs_id, OBS, ALICE)
    assert len(got) == 1, got
    assert got[0]["label"] == seed.name and "provenance" not in got[0] and "programs" not in got[0], got


def test_11_a_declared_id_equal_to_an_asset_dimension_members_id_is_the_one_candidate(world, monkeypatch):
    _plain_dimension(world, monkeypatch, "OBS-DECLARED-ASSET")
    row = InstanceRow(class_uri=OBS, instance_id="OBS-DECLARED-ASSET", label="Declared Org Unit",
                      granted_by="owner", ratified_by="owner", reason="test", program=TWO)
    monkeypatch.setattr(engine, "INSTANCES", (row,))
    got = world.resolve("OBS-DECLARED-ASSET", OBS, BOB)
    assert len(got) == 1, got
    assert got[0]["label"] == "Declared Org Unit" and got[0]["programs"] == [TWO], got
    assert got[0]["provenance"] == {"declaration": "instance_overlay"}
    # the asset's member of that id, in ONE, does not appear beside it
    assert world.resolve("OBS-DECLARED-ASSET", OBS, ALICE) == []


# -- (12) a refused asset read is a fault in the log ----------------------------------------------

def test_12_an_unread_asset_logs_asset_unread_at_warning(world, caplog):
    column, cls = world.dims()[0]
    with caplog.at_level(logging.WARNING, logger=engine._reason_log.name):
        world.candidates(world.values(column, ONE)[0], cls, DAN)
    lines = [r for r in caplog.records
             if r.name == engine._reason_log.name and "reason=asset_unread" in r.getMessage()]
    assert lines and all(r.levelno == logging.WARNING for r in lines), _lines(caplog)


# -- (13) the cap counts DISTINCT rows --------------------------------------------------------------

def test_13_an_asset_longer_than_the_cap_in_rows_but_not_in_distinct_rows_gives_its_members(world, monkeypatch):
    columns = [world.contract.scope, *(c for c, _ in world.dims())]
    distinct = world.frame.select(columns).unique().height
    assert world.frame.height > distinct, "the fixture needs repeated rows"
    monkeypatch.setenv(asset_inputs.MAX_ROWS_ENV, str(distinct))
    for column, cls in world.dims():
        value = world.values(column, TWO)[0]
        got = world.resolve(value, cls, BOB)
        assert len(got) == 1 and got[0]["programs"] == [TWO], (column, cls, got)
    # the control: one row under the distinct count is too large, and says so
    monkeypatch.setenv(asset_inputs.MAX_ROWS_ENV, str(distinct - 1))
    column, cls = world.dims()[0]
    assert world.resolve(world.values(column, TWO)[0], cls, BOB) == []


# -- (14) an empty asset is an answer --------------------------------------------------------------

def test_14_an_empty_asset_is_a_200_with_no_asset_members_no_asset_unread_line_and_the_seed(world, caplog):
    _serve(world, world.frame.head(0))
    program = world.seed_program
    with caplog.at_level(logging.DEBUG, logger=engine._reason_log.name):
        for column, cls in world.dims():
            assert world.resolve(world.values(column, TWO)[0], cls, BOB) == []
            assert all("provenance" not in m for m in world.enumerate(cls, BOB)), (column, cls)
        seed = world.candidates(program.name, engine.FIN + "Program", ALICE)
    assert program.program_id in {c["instance_id"] for c in seed}
    assert not [m for m in _lines(caplog) if "asset_unread" in m], _lines(caplog)


# -- (15) null and empty values give no member ------------------------------------------------------

def _dimension_df(contract, rows):
    columns = [contract.scope, *(c for c, _ in asset_inputs.dimension_columns(contract))]
    return pl.DataFrame({c: [r[i] for r in rows] for i, c in enumerate(columns)},
                        schema={c: pl.String for c in columns})


def _members(contract, rows, **kw):
    return asset_inputs.dimension_members(_dimension_df(contract, rows), "urn", contract, AS_OF, **kw)


def _path(*names):
    return json.dumps(list(names), ensure_ascii=False)


def test_15_null_and_empty_values_give_no_member_and_the_other_values_still_do():
    contract = dataset_contracts.load_contract("program_b", B_DIR / "contracts")
    contract = dataclasses.replace(contract, dimensions=(("ipt_1", "fin:OBSElement"),))
    assert [c for c, _ in asset_inputs.dimension_columns(contract)] == [*contract.hierarchy, "ipt_1"]
    good = (ONE, "B-1", "B-1.1", "B-1.1.1", "B-1.1.1.1", "CA-1", "WP-1", "IPT-A")
    null_wbs_2 = (ONE, "B-2", None, "B-2.1.1", "B-2.1.1.1", "CA-2", "WP-2", None)
    empty_wbs_3 = (ONE, "B-3", "B-3.1", "", "B-3.1.1.1", "CA-3", "WP-3", "")
    by = _members(contract, [good, null_wbs_2, empty_wbs_3])
    ids = {cls.rsplit("#", 1)[-1]: {m["instance_id"] for m in ms} for cls, ms in by.items()}
    # a path with a null or empty component at or above a level gives no member for that level
    assert ids["WBSElement"] == {
        _path("B-1"), _path("B-1", "B-1.1"), _path("B-1", "B-1.1", "B-1.1.1"),
        _path("B-1", "B-1.1", "B-1.1.1", "B-1.1.1.1"), _path("B-2"), _path("B-3"), _path("B-3", "B-3.1")}, ids
    assert ids["ControlAccount"] == {_path(*good[1:6])} and ids["WorkPackage"] == {_path(*good[1:7])}, ids
    # a plain dimension's null and empty values give none; its other value does
    assert ids["OBSElement"] == {"IPT-A"}, ids
    for members in by.values():
        assert not [m for m in members if m["instance_id"] in ("", "None") or m["label"] in ("", "None")]


def test_15_a_hierarchy_member_is_its_path_and_one_per_program():
    contract = dataset_contracts.load_contract("program_b", B_DIR / "contracts")
    row = ("B-1", "B-1.1", "B-1.1.1", "B-1.1.1.1", "CA-1", "WP-1")
    by = _members(contract, [(ONE, *row), (ONE, *row), (TWO, *row)])
    wbs = by[engine.FIN + "WBSElement"]
    assert [(m["instance_id"], m["label"], m["program"]) for m in wbs if m["label"] == "B-1.1.1"] == [
        (_path("B-1", "B-1.1", "B-1.1.1"), "B-1.1.1", ONE), (_path("B-1", "B-1.1", "B-1.1.1"), "B-1.1.1", TWO)]
    assert len(wbs) == 2 * 4, wbs


# -- (16) a shared version label names the first contract in contract_id order ----------------------

SHARED = VERSIONS[0]
SHARED_CONTRACTS = (("zz_versions", (SHARED, "ZZ-ONLY")), ("aa_versions", (SHARED, "AA-ONLY")))  # reverse id order
FIRST_IN_ID_ORDER = {SHARED: "aa_versions", "AA-ONLY": "aa_versions", "ZZ-ONLY": "zz_versions"}


def test_16_a_shared_version_label_names_the_first_contract_in_id_order_however_they_arrive():
    contract = dataset_contracts.load_contract("program_b", B_DIR / "contracts")
    df = _dimension_df(contract, [(ONE, "B-1", "B-1.1", "B-1.1.1", "B-1.1.1.1", "CA-1", "WP-1")])
    by = asset_inputs.dimension_members(df, "urn", contract, AS_OF, versions=SHARED_CONTRACTS)
    assert {m["instance_id"]: m["provenance"]["contract"] for m in by[engine.FIN + "Version"]} == FIRST_IN_ID_ORDER


def test_16_two_declared_row_contracts_sharing_a_version_label_name_the_first_in_id_order(world, monkeypatch):
    cdir, odir = world.tmp_path / "two_contracts", world.tmp_path / "two_overlay"
    cdir.mkdir()
    odir.mkdir()
    world_dir = EV_DIR if world.contract.contract_id == "ev_fixture" else B_DIR / "contracts"
    (cdir / f"{world.contract.contract_id}.yaml").write_bytes(
        (world_dir / f"{world.contract.contract_id}.yaml").read_bytes())
    for cid, labels in SHARED_CONTRACTS:
        doc = yaml.safe_load((B_DIR / "contracts" / "program_b_versions.yaml").read_text(encoding="utf-8"))
        doc["contract_id"] = cid
        doc["version_dimension"] = {"column": "version", "values": list(labels)}
        (cdir / f"{cid}.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
        row = _dataset_row()
        row["measure_id"] = row["name"] = f"fin_b_{cid}_row"
        row["verb"] = "x" + cid.replace("_", "") + "row"
        row["inputs"]["dataset"]["contract"] = cid
        (odir / f"{row['measure_id']}.yaml").write_text(yaml.safe_dump(row, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("DATASET_CONTRACT_DIR", str(cdir))
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(odir))
    monkeypatch.setenv("FIN_CALENDAR_OVERLAY_DIRS", os.pathsep.join(
        [os.environ["FIN_CALENDAR_OVERLAY_DIRS"], str(B_DIR / "fin_calendar")]))
    fiscal_calendar._cache.clear()
    rows = engine._load_declared()
    registered = dict(sorted(rows.items(), key=lambda kv: kv[1].contract.contract_id, reverse=True))
    assert [r.contract.contract_id for r in registered.values()] == ["zz_versions", "aa_versions"]
    monkeypatch.setattr(engine, "DECLARED", registered)
    cls = engine.FIN + "Version"
    shared = [c for c in world.candidates(SHARED, cls, ALICE) if c["instance_id"] == SHARED]
    assert [c["provenance"]["contract"] for c in shared] == ["aa_versions"], shared
    assert {m["instance_id"]: m["provenance"]["contract"] for m in world.enumerate(cls, ALICE)} == FIRST_IN_ID_ORDER
