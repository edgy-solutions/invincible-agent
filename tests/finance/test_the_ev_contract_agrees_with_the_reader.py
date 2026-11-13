"""contracts/ev_fixture.yaml says what the governed read refuses on; one reader still holds its own copy.

A dataset measure row's read loads the contract and enforces it (`dataset_contracts`, ruled
2026-11-10). The `FIN_DATASET_URN` read (`state_from_rows`) still holds its constants, so until it
reads the contract too there are two homes for one claim, and the contract is the one that goes on
passing after the reader changes. So every fact
the contract states about the reader is read FROM the reader here: its column sets, the rule ids
it raises (found by the form `ContractViolation("<id>"` in its source, so a new refusal site is a
red until the contract names it), its period vocabulary and its row cap. The reader's source is two
files since the contract checks moved to the shared reader (`agent_fleet/utils/dataset_contracts.py`):
`asset_inputs` and that module, and the rules are read from both.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_the_ev_contract_agrees_with_the_reader.py
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from agent_fleet.finance_agent import asset_inputs, entities
from agent_fleet.utils import dataset_contracts

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "ev_fixture.yaml"
DATASET_OVERLAYS = ROOT / "policy" / "overlays" / "sample" / "measure_verbs"
SANDBOX_VALUES = ROOT / "helm" / "invincible-agent" / "values-sandbox.yaml"
LIVE_CASE = ROOT / "tests" / "sandbox_e2e" / "variance_set_live.yaml"
RAISED = re.compile(r"""ContractViolation\(\s*["']([a-z_]+)["']""")
READER_SOURCES = (Path(asset_inputs.__file__), Path(dataset_contracts.__file__))


@pytest.fixture(scope="module")
def contract():
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _columns(c):
    return {col["name"]: col for col in c["columns"]}


def test_the_required_columns_are_the_readers_fixed_set(contract):
    cols = _columns(contract)
    assert {n for n, col in cols.items() if col["required"]} == set(asset_inputs.COLUMNS)
    for n in asset_inputs.STRING_COLUMNS:
        assert cols[n]["type"] == "string", n
    for n in asset_inputs.NUMERIC_COLUMNS:
        assert cols[n]["type"] in ("numeric", "integer"), n


def test_a_required_column_is_already_produced(contract):
    # A required column the fixture does not yet carry would refuse every read.
    unproduced = [n for n, col in _columns(contract).items() if col["required"] and not col["produced_since"]]
    assert not unproduced


def test_every_rule_the_reader_raises_is_named_and_none_is_invented(contract):
    raised = {r for p in READER_SOURCES for r in RAISED.findall(p.read_text(encoding="utf-8"))}
    assert set(contract["rules"]) == raised


def test_the_rule_detector_sees_the_form():
    # Positive control: a planted call in either quoting, across a line break, is found.
    src = 'raise ContractViolation(\n    "planted_rule", "m")\nraise ContractViolation(\'other\', "m")'
    assert RAISED.findall(src) == ["planted_rule", "other"]


def test_the_period_vocabulary_and_row_cap_are_the_readers(contract):
    assert contract["period"]["vocabulary"] == "FISCAL_PERIODS"
    assert getattr(entities, contract["period"]["vocabulary"]) is asset_inputs.FISCAL_PERIODS
    cap = contract["limits"]["max_rows"]
    assert (cap["env"], cap["default"]) == (asset_inputs.MAX_ROWS_ENV, asset_inputs.DEFAULT_MAX_ROWS)


def test_every_name_the_contract_uses_is_a_declared_column(contract):
    cols = _columns(contract)
    named = {*contract["grain"], contract["scope"], contract["period"]["column"], contract["status_period"]}
    for col in cols.values():
        named |= set(col.get("constant_within", ())) | set(col.get("additive_over", ()))
    for dep in contract["dependencies"]:
        named |= {dep["by"], *dep["determines"]}
    assert named <= set(cols), sorted(named - set(cols))


def test_the_dataset_overlays_name_this_contracts_urn_and_banner(contract):
    files = sorted(DATASET_OVERLAYS.rglob("*.yaml"))
    rows = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in files]
    datasets = [r["inputs"]["dataset"] for r in rows if isinstance(r, dict) and "dataset" in r.get("inputs", {})]
    assert datasets, "positive control: some sample row reads a dataset"
    assert any("per_period" in ds for ds in datasets), "positive control: a series row is held"
    for ds in datasets:
        assert (ds["urn"], ds["banner"]) == (contract["dataset"]["urn"], contract["dataset"]["banner"])
        cols = _columns(contract)
        if "per_period" in ds:          # drawn as series: tests/finance/test_a_dataset_series_row_*
            named = [ds["scope"], ds["period"], *ds["per_period"].values(), *ds.get("per_program", {}).values(),
                     *([ds["status"]] if "status" in ds else [])]
            assert set(named) <= set(cols), ds
            continue
        value = ds["value"]
        named = value["minus"] if isinstance(value, dict) else [value]
        assert set(ds["levels"]) | set(named) <= set(cols), ds


def test_the_sandbox_flag_names_this_contracts_asset(contract):
    # The flag is the only place the running engine learns the URN; a typo there reads nothing.
    env = yaml.safe_load(SANDBOX_VALUES.read_text(encoding="utf-8"))["engineFinance"]["env"]
    assert (env["FIN_DATASET_URN"], env["FIN_DATASET_BANNER"]) == (contract["dataset"]["urn"], contract["dataset"]["banner"])
    live = yaml.safe_load(LIVE_CASE.read_text(encoding="utf-8"))
    assert live["asset"] == contract["dataset"]["urn"]
    assert live["banner_must_say"].lower() in env["FIN_DATASET_BANNER"].lower()
