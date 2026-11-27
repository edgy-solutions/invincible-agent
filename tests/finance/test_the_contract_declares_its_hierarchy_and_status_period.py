"""A contract may declare its `status_period` and its `hierarchy` (ruled 2026-11-25).

The shared reader (ADR-0066) holds the SHAPE of both keys and refuses a bad one at load, naming the
key and the column; the roles of a hierarchy's levels are engine-fin's (`asset_inputs.hierarchy_levels`).
Every refusal case is a mutation of the SHIPPED `ev_fixture.yaml`, so the accepting control is the
unmutated file: the same fixture, a different declaration.

Run: uv run --no-sync pytest -c pyproject.toml --rootdir=. -p no:cacheprovider -p no:langsmith_plugin tests/finance/test_the_contract_declares_its_hierarchy_and_status_period.py
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_fleet.finance_agent import asset_inputs
from agent_fleet.utils import dataset_contracts

REPO = Path(__file__).resolve().parents[2]
EV = REPO / "contracts" / "ev_fixture.yaml"
B = REPO / "tests" / "fixtures" / "fin_program_b" / "contracts" / "program_b.yaml"


def _raw(path: Path = EV) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load(raw: dict, tmp_path: Path):
    path = tmp_path / f"{raw['contract_id']}.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return dataset_contracts.load_contract(raw["contract_id"], tmp_path)


def _column(raw: dict, name: str) -> dict:
    return next(c for c in raw["columns"] if c["name"] == name)


# -- the accepting controls ---------------------------------------------------------------------

def test_the_shipped_contracts_declare_what_the_reader_parses():
    ev = dataset_contracts.load_contract("ev_fixture", EV.parent)
    assert ev.status_column == "status_period"
    assert ev.hierarchy == ("control_account", "work_package")
    b = dataset_contracts.load_contract("program_b", B.parent)
    assert b.hierarchy == ("wbs_1", "wbs_2", "wbs_3", "wbs_4", "control_account", "work_package")
    assert b.status_column is None


def test_a_contract_declaring_neither_key_still_loads(tmp_path):
    raw = _raw()
    del raw["status_period"], raw["hierarchy"]
    contract = _load(raw, tmp_path)
    assert contract.status_column is None and contract.hierarchy == ()
    assert asset_inputs.hierarchy_levels(contract) == ()


# -- the roles are engine-fin's: the last two are shipped, the rest is declared depth (Q4) -------

def test_q4_the_wbs_depth_is_declared_zero_for_the_ev_fixture_and_four_for_program_b():
    ev = dataset_contracts.load_contract("ev_fixture", EV.parent)
    b = dataset_contracts.load_contract("program_b", B.parent)
    ev_levels, b_levels = asset_inputs.hierarchy_levels(ev), asset_inputs.hierarchy_levels(b)
    assert ev_levels == (("control_account", "control_account"), ("work_package", "work_package"))
    assert [r for _, r in ev_levels].count("wbs") == 0
    assert [r for _, r in b_levels].count("wbs") == 4
    assert [r for _, r in b_levels][-2:] == ["control_account", "work_package"]
    assert [c for c, _ in b_levels] == list(b.hierarchy)


# -- status_period -------------------------------------------------------------------------------

@pytest.mark.parametrize("name,mutate,said", [
    ("not_a_declared_column", lambda r: r.update(status_period="no_such_column"), "is not a declared column"),
    ("not_a_string_column", lambda r: _column(r, "status_period").update(type="integer"),
     "a status period column is a string"),
    ("nullable", lambda r: _column(r, "status_period").pop("nullable"), "is nullable"),
    ("not_determined_by_the_scope", lambda r: r.update(dependencies=[
        d for d in r["dependencies"] if d["by"] != "program_id"]), "not declared determined by the scope"),
    ("scope_none", lambda r: r.update(scope="none"), "declared under `scope: none`"),
])
def test_a_bad_status_period_is_refused_at_load_naming_key_and_column(name, mutate, said, tmp_path):
    raw = _raw()
    mutate(raw)
    with pytest.raises(ValueError) as exc:
        _load(raw, tmp_path)
    assert "status_period" in str(exc.value)
    assert said in str(exc.value), str(exc.value)  # the case's OWN refusal, not a later check's


# -- hierarchy -----------------------------------------------------------------------------------

@pytest.mark.parametrize("name,value,said", [
    ("not_a_list", "control_account", "at least 2 distinct column names"),
    ("one_column", ["work_package"], "at least 2 distinct column names"),
    ("a_duplicate", ["work_package", "work_package"], "at least 2 distinct column names"),
    ("an_undeclared_column", ["control_account", "no_such_column", "work_package"], "is not a declared column"),
    ("the_scope", ["program_id", "control_account", "work_package"], "is the scope"),
    ("not_a_string_column", ["control_account", "period_number", "work_package"], "a level column is a string"),
    ("the_last_does_not_determine_the_rest", ["work_package", "control_account"],
     "the last level determines every other"),
])
def test_a_bad_hierarchy_is_refused_at_load_naming_the_key(name, value, said, tmp_path):
    raw = _raw()
    raw["columns"].append({"name": "period_number", "type": "integer", "required": False, "nullable": False})
    raw["hierarchy"] = value
    with pytest.raises(ValueError) as exc:
        _load(raw, tmp_path)
    assert "hierarchy" in str(exc.value)
    assert said in str(exc.value), str(exc.value)  # the case's OWN refusal, not a later check's


def test_a_nullable_or_personal_hierarchy_column_is_refused(tmp_path):
    raw = _raw()
    _column(raw, "control_account").pop("nullable")
    with pytest.raises(ValueError, match="hierarchy"):
        _load(raw, tmp_path)
    raw = _raw()
    raw["columns"].append({"name": "lead", "type": "string", "required": False, "nullable": False,
                           "personal_data": True})
    wp = next(d for d in raw["dependencies"] if d["by"] == "work_package")
    wp["determines"] = [*wp["determines"], "lead"]
    raw["hierarchy"] = ["control_account", "lead", "work_package"]
    # a personal column cannot be a dependency's (the reader's own rule refuses it first), so the
    # last-determines rule can never hold for one: the refusal is the reader's, naming the column
    with pytest.raises(ValueError, match="personal_data"):
        _load(raw, tmp_path)
    del raw["columns"][-1]["personal_data"]  # the control: the same contract, the column not personal
    assert _load(raw, tmp_path).hierarchy == ("control_account", "lead", "work_package")


def test_the_control_for_the_hierarchy_refusals_is_the_same_contract_unmutated(tmp_path):
    raw = _raw()
    raw["columns"].append({"name": "period_number", "type": "integer", "required": False, "nullable": False})
    assert _load(raw, tmp_path).hierarchy == ("control_account", "work_package")


# -- a projected read relaxes the row checks only when it says so ---------------------------------

def test_a_whole_row_read_missing_a_key_column_still_fails_and_only_a_projection_is_relaxed():
    """`check_contract_rows(..., projected=True)` is the lookups' read: it selected only the columns
    it names, so the duplicate-key check holds over what it carries. The DEFAULT is every other
    engine's whole-row read, where a frame missing a key column is an error, never a skipped check.
    Same frame, same contract; only the declaration of the read differs."""
    import polars as pl

    ev = dataset_contracts.load_contract("ev_fixture", EV.parent)
    missing = [k for k in ev.key if k != ev.scope]
    assert missing, "CONTROL FAILED: the ev_fixture key is only its scope, so nothing is left out"
    df = pl.DataFrame({ev.scope: ["P1", "P1"], ev.status_column: ["P03", "P03"]})
    assert not set(missing) & set(df.columns)
    with pytest.raises(Exception):
        dataset_contracts.check_contract_rows(df, ev)
    dataset_contracts.check_contract_rows(df, ev, projected=True)
