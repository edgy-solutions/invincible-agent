"""The shared reader refuses a null in a `nullable: false` column and a NaN or infinity in a numeric
or float column, for every contract (ruled 2026-11-16: "the shared reader enforces null_value (a
column declared nullable: false) and non_finite (a numeric or float column) for every contract").

Over `agent_fleet.utils.dataset_contracts` only, with small contracts written to `tmp_path`.

Run: .venv/Scripts/python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/test_the_reader_refuses_nulls_and_non_finite_values.py
"""
from __future__ import annotations

import pytest
import yaml

pl = pytest.importorskip("polars")

from agent_fleet.utils import dataset_contracts as dc  # noqa: E402


def _contract(tmp_path, columns, rules=None, cid="c"):
    doc = {"contract_id": cid, "grain": ["k"], "scope": "none", "columns": columns}
    if rules is not None:
        doc["rules"] = rules
    (tmp_path / f"{cid}.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return dc.load_contract(cid, tmp_path)


def _cols(**extra):
    base = [{"name": "k", "type": "string", "required": True}]
    return base + [{"name": n, "type": t, **kw} for n, (t, kw) in extra.items()]


def test_nullable_false_is_read_in_declaration_order(tmp_path):
    c = _contract(tmp_path, _cols(z=("string", {"nullable": False}), a=("string", {}),
                                  m=("float", {"nullable": True}), b=("integer", {"nullable": False})))
    assert c.non_nullable == ("z", "b")


@pytest.mark.parametrize("bad", ["no", 0])
def test_a_nullable_that_is_not_a_boolean_is_refused_at_load(tmp_path, bad):
    with pytest.raises(ValueError, match=r"has nullable .* it is true or false") as ei:
        _contract(tmp_path, _cols(a=("string", {"nullable": bad})))
    assert "'a'" in str(ei.value)


def test_a_null_in_a_non_nullable_column_is_null_value(tmp_path):
    c = _contract(tmp_path, _cols(a=("string", {"nullable": False}), b=("string", {})))
    frame = pl.DataFrame({"k": ["1", "2"], "a": ["x", None], "b": ["y", "z"]})
    with pytest.raises(dc.ContractViolation) as ei:
        dc.check_contract_values(frame, c)
    assert ei.value.rule == "null_value" and ei.value.message == "null value(s) in column a"
    # the control: the same null in a column that declares nothing about nullability passes
    dc.check_contract_values(pl.DataFrame({"k": ["1", "2"], "a": ["x", "w"], "b": ["y", None]}), c)


@pytest.mark.parametrize("kind", ["float", "numeric"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_nan_or_infinity_in_a_float_or_numeric_column_is_non_finite(tmp_path, kind, bad):
    c = _contract(tmp_path, _cols(v=(kind, {})))
    with pytest.raises(dc.ContractViolation) as ei:
        dc.check_contract_values(pl.DataFrame({"k": ["1", "2"], "v": [1.0, bad]}), c)
    assert ei.value.rule == "non_finite" and ei.value.message == "non-finite number(s) in column v"
    dc.check_contract_values(pl.DataFrame({"k": ["1", "2"], "v": [1.0, 2.0]}), c)


def test_a_string_column_is_never_checked_and_an_integer_numeric_passes(tmp_path):
    c = _contract(tmp_path, _cols(s=("string", {}), n=("numeric", {})))
    dc.check_contract_values(pl.DataFrame({"k": ["1"], "s": ["nan"], "n": pl.Series([1], dtype=pl.Int64)}), c)


def test_the_values_run_before_the_key(tmp_path):
    c = _contract(tmp_path, _cols(a=("string", {"nullable": False})))
    dup_null = pl.DataFrame({"k": ["1", "1"], "a": ["x", None]})
    with pytest.raises(dc.ContractViolation) as ei:
        dc.check_contract_rows(dup_null, c)
    assert ei.value.rule == "null_value"
    # the control: the same duplicate, the null removed
    with pytest.raises(dc.ContractViolation) as ei:
        dc.check_contract_rows(pl.DataFrame({"k": ["1", "1"], "a": ["x", "y"]}), c)
    assert ei.value.rule == "duplicate_key"


def test_a_non_nullable_column_the_frame_does_not_carry_passes(tmp_path):
    c = _contract(tmp_path, _cols(a=("string", {"nullable": False})))
    assert "a" in c.non_nullable and "a" not in c.required
    dc.check_contract_rows(pl.DataFrame({"k": ["1", "2"]}), c)


def test_nullable_names_the_declared_columns_not_declared_non_nullable(tmp_path):
    c = _contract(tmp_path, _cols(z=("string", {}), a=("string", {"nullable": False}),
                                  m=("float", {"nullable": True})))
    assert dc.nullable(c, ["z", "a", "m", "k", "ghost"]) == ["k", "m", "z"]


def test_the_two_rules_are_the_readers_and_a_block_may_name_them(tmp_path):
    assert {"null_value", "non_finite"} <= set(dc.RULES)
    assert not {"null_value", "non_finite"} & dc.PRODUCER_CHECKED
    c = _contract(tmp_path, _cols(), rules={"null_value": "m1", "non_finite": "m2"})
    assert dc.unknown_rules(c) == []
