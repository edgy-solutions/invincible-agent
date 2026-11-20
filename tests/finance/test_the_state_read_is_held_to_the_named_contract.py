"""The FIN_DATASET_URN read is held to the contract the deployment names (FIN_DATASET_CONTRACT), whole.

Not to a column set engine-fin fixes: the read selects every contract column the asset carries and
`state_from_rows` refuses the contract's key and dependencies with the shared reader's ids, as a
dataset row's read does. The roles engine-fin needs are held at load (`contract_problems`); the
grain and the dependencies beyond them are the contract's to say.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider \
    tests/finance/test_the_state_read_is_held_to_the_named_contract.py
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pl = pytest.importorskip("polars")

from agent_fleet.finance_agent import asset_inputs, seed  # noqa: E402
from agent_fleet.utils import dataset_contracts  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
URN = "urn:li:dataset:(urn:li:dataPlatform:file,fin_test_asset,TEST)"
PROGRAM = seed.PROGRAM_ID
RETIRED = ("duplicate_work_package_period", "program_name_not_unique", "program_bac_not_unique",
           "work_package_in_two_accounts")


def _ev():
    return dataset_contracts.load_contract("ev_fixture", CONTRACTS)


def _frame():
    s = seed.build_seed()
    ca_of = {w.wp_id: w.ca_id for w in s.work_packages}
    prog = s.programs[0]
    return pl.DataFrame([
        {"program_id": prog.program_id, "program_name": prog.name, "program_bac": prog.bac,
         "control_account": ca_of[f.wp_id], "work_package": f.wp_id, "period": f.period,
         "bcws": f.bcws, "bcwp": f.bcwp, "acwp": f.acwp}
        for f in s.facts
    ])


def _read(frame, contract):
    df = asset_inputs.read_rows(lambda urn: frame.lazy(), URN, PROGRAM, None, contract)
    return asset_inputs.state_from_rows(df, PROGRAM, contract)


def _status(frame, varying: bool):
    """`frame` carrying `status_period`, which the contract declares determined by program_id."""
    first = pl.int_range(pl.len()) == 0
    value = pl.when(first & pl.lit(varying)).then(pl.lit("FY26-02")).otherwise(pl.lit("FY26-03"))
    return frame.with_columns(value.alias("status_period"))


def test_an_optional_contract_column_that_breaks_a_dependency_is_refused():
    ev = _ev()
    assert "program_id" in ev.determined_by("status_period")
    with pytest.raises(asset_inputs.ContractViolation) as ei:
        _read(_status(_frame(), varying=True), ev)
    assert ei.value.rule == "not_determined_by" and "status_period" in ei.value.message
    # the control: a constant status_period, the same rows, is served
    state = _read(_status(_frame(), varying=False), ev)
    assert state.programs and state.facts


def test_a_null_in_an_optional_column_the_state_does_not_read_is_served():
    """`null_value` is over the columns the read USES (the roles), as the dataset reads check only
    the columns a row names: a declared optional column the state is not built from may be null."""
    ev = _ev()
    assert "eac" in ev.types and "eac" not in ev.required
    with_eac = _frame().with_columns(pl.lit(None, dtype=pl.Int64).alias("eac"))
    assert _read(with_eac, ev).facts
    # the control: the same null in a role is refused
    with pytest.raises(asset_inputs.ContractViolation) as ei:
        _read(_frame().with_columns(pl.lit(None, dtype=pl.Int64).alias("bcws")), ev)
    assert ei.value.rule == "null_value" and "bcws" in ei.value.message


def test_the_contract_not_a_constant_decides_the_key(tmp_path):
    doc = yaml.safe_load((CONTRACTS / "ev_fixture.yaml").read_text(encoding="utf-8"))
    doc["contract_id"] = "by_package"
    doc["grain"] = ["work_package"]
    (tmp_path / "by_package.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    by_package = dataset_contracts.load_contract("by_package", tmp_path)
    assert asset_inputs.contract_problems(by_package) == []
    frame = _frame()
    wp = frame["work_package"][0]
    assert frame.filter(pl.col("work_package") == wp).height > 1, "two periods of one work package"
    with pytest.raises(asset_inputs.ContractViolation) as ei:
        _read(frame, by_package)
    assert ei.value.rule == "duplicate_key"
    # the control: the same rows under the EV grain are served
    assert _read(frame, _ev()).facts


_RAISES = r"""ContractViolation\(\s*["'](%s)["']"""


def _retired_raised(source: str) -> list[str]:
    return re.findall(_RAISES % "|".join(RETIRED), source)


def test_the_reader_raises_none_of_the_retired_rule_ids():
    assert _retired_raised(Path(asset_inputs.__file__).read_text(encoding="utf-8")) == []
    assert not set(RETIRED) & asset_inputs.RULES
    # positive control: the detector finds a planted raise, in either quoting and across a line
    planted = ('raise ContractViolation(\n    "program_name_not_unique", "m")\n'
               "ContractViolation('duplicate_work_package_period', \"m\")")
    assert _retired_raised(planted) == ["program_name_not_unique", "duplicate_work_package_period"]
