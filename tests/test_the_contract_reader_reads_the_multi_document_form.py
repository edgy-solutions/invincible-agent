"""The shared contract reader reads the multi-document form, `scope: none`, the new types, and holds
the refusal rules once (architect rulings 2026-11-11 and 2026-11-14). Every contract declares its
scope column, or `scope: none` for none, and the reader never assumes scope means program; the
shared reader reads dag-tools' multi-document template so the template check and the engine use ONE
parser (`load_contracts`), with `timestamp`, `date` and `array<string>` (one token, no general
`array<T>`) added; and refusal rules live once, in the reader, apply to every contract, and a
contract's `rules` block carries messages only, so leaving a rule out of it disables nothing.

Run: .venv/Scripts/python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider \
     tests/test_the_contract_reader_reads_the_multi_document_form.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from agent_fleet.utils import dataset_contracts as dc

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "tests" / "fixtures" / "dag_tools_mfg_trace" / "mfg_trace.yaml"
IDS = ["dim_part", "bom_edge", "bom_closure", "serial_unit", "as_built_edge", "as_built_closure",
       "test_result", "test_measurement", "test_catalog", "ingest_status"]


def _doc(cid, **over):
    d = {"contract_id": cid, "scope": "s",
         "columns": [{"name": "s", "type": "string", "required": True},
                     {"name": "v", "type": "string"}],
         "grain": ["s"]}
    d.update(over)
    return d


def _write(tmp_path, *docs, name="demo"):
    (tmp_path / f"{name}.yaml").write_text("---\n".join(yaml.safe_dump(d) for d in docs), encoding="utf-8")
    return tmp_path / f"{name}.yaml"


def _load(tmp_path, doc, cid="demo"):
    _write(tmp_path, doc)
    return dc.load_contract(cid, tmp_path)


def test_the_template_parses_whole():
    """A copy for the parser's seal (dag-tools commit 398d82d); Lane 1's CI check pins the live template."""
    got = dc.load_contracts(TEMPLATE)
    assert list(got) == [f"mfg_trace.{i}" for i in IDS]
    assert {k for c in got.values() for k in c.types.values()} <= dc.TYPES


def test_TRIPWIRE_THE_TEMPLATE_NAMES_RULES_NO_READER_RAISES():
    """`key_not_unique` is this reader's `duplicate_key` under dag-tools' name, which dag-tools
    renames (ruled 2026-11-14). When the rename lands, this goes red: re-vendor the template, and
    this set becomes empty."""
    got = dc.load_contracts(TEMPLATE)
    assert {r for c in got.values() for r in dc.unknown_rules(c)} == {"key_not_unique"}


def test_the_template_names_the_producer_checked_rules_and_a_block_may():
    """`interval_overlap` and `orphan_reference` are the producer's checks (ruled 2026-11-14): a
    block naming them is accepted, so the template's use of them is not unknown. The control: the
    same block without the exception is unknown."""
    named = {r for c in dc.load_contracts(TEMPLATE).values() for r in c.rules}
    assert dc.PRODUCER_CHECKED <= named
    assert not dc.PRODUCER_CHECKED & set(dc.RULES)
    c = dc.DatasetContract(contract_id="x", types={}, required=(), key=(), scope=None,
                           dependencies=(), rules={r: "m" for r in dc.PRODUCER_CHECKED})
    assert dc.unknown_rules(c) == []
    assert sorted(set(c.rules) - set(dc.RULES)) == sorted(dc.PRODUCER_CHECKED)


def test_load_contract_finds_a_table_in_its_set(tmp_path):
    shutil.copy(TEMPLATE, tmp_path / "mfg_trace.yaml")
    raw = next(d for d in yaml.safe_load_all(TEMPLATE.read_text(encoding="utf-8"))
               if d and d["contract_id"] == "mfg_trace.dim_part")
    c = dc.load_contract("mfg_trace.dim_part", tmp_path)
    assert c.key == tuple(raw["grain"]) and c.scope == raw["scope"]
    assert c.required == tuple(col["name"] for col in raw["columns"] if col.get("required"))
    with pytest.raises(ValueError, match=r"holds no contract 'mfg_trace.absent'.*mfg_trace.dim_part"):
        dc.load_contract("mfg_trace.absent", tmp_path)


def test_a_duplicated_id_is_refused(tmp_path):
    _write(tmp_path, _doc("demo.a"), _doc("demo.a"))
    with pytest.raises(ValueError, match="demo.a.*twice"):
        dc.load_contracts(tmp_path / "demo.yaml")


def test_an_id_outside_the_files_set_is_refused(tmp_path):
    _write(tmp_path, _doc("demo.a"), _doc("other.b"))
    with pytest.raises(ValueError, match="'other.b', which is not 'demo'"):
        dc.load_contracts(tmp_path / "demo.yaml")


def test_a_bare_stem_id_in_a_two_document_file_is_refused(tmp_path):
    _write(tmp_path, _doc("demo.a"), _doc("demo"))
    with pytest.raises(ValueError, match="bare contract_id 'demo'"):
        dc.load_contracts(tmp_path / "demo.yaml")


def test_a_set_of_one_table_may_stand_alone(tmp_path):
    _write(tmp_path, _doc("demo.a"))
    assert list(dc.load_contracts(tmp_path / "demo.yaml")) == ["demo.a"]
    assert dc.load_contract("demo.a", tmp_path).contract_id == "demo.a"


def test_an_empty_stream_is_refused(tmp_path):
    (tmp_path / "demo.yaml").write_text("# only a header\n---\n", encoding="utf-8")
    with pytest.raises(ValueError, match="demo.yaml holds no contract"):
        dc.load_contracts(tmp_path / "demo.yaml")


def test_a_bad_document_among_good_ones_refuses_the_whole_file(tmp_path):
    _write(tmp_path, _doc("demo.a"), _doc("demo.b", grain=["nope"]))
    with pytest.raises(ValueError, match=r"demo.b: .*\['nope'\]"):
        dc.load_contract("demo.a", tmp_path)


def test_scope_none_loads_as_no_scope(tmp_path):
    c = _load(tmp_path, _doc("demo", scope="none"))
    assert c.scope is None and not c.scoped
    assert _load(tmp_path, _doc("demo")).scoped


@pytest.mark.parametrize("how", ["missing", "null"])
def test_no_declared_scope_is_refused(how, tmp_path):
    doc = _doc("demo")
    del doc["scope"]
    if how == "null":
        doc["scope"] = None
    with pytest.raises(ValueError, match="declares no scope"):
        _load(tmp_path, doc)


def test_a_column_named_none_under_scope_none_is_refused(tmp_path):
    doc = _doc("demo", scope="none")
    doc["columns"].append({"name": "none", "type": "string"})
    with pytest.raises(ValueError, match="ambiguous"):
        _load(tmp_path, doc)


def test_the_row_checks_run_on_a_scope_none_contract(tmp_path):
    pl = pytest.importorskip("polars")
    c = _load(tmp_path, _doc("demo", scope="none"))
    with pytest.raises(dc.ContractViolation) as e:
        dc.check_contract_rows(pl.DataFrame({"s": ["a", "a"], "v": ["x", "y"]}), c)
    assert e.value.rule == "duplicate_key"


def _typed(tmp_path, kind):
    doc = _doc("demo", scope="none")
    doc["columns"].append({"name": "t", "type": kind})
    return _load(tmp_path, doc)


def _types():
    pl = pytest.importorskip("polars")
    return {
        "timestamp": ([pl.Datetime("us", "UTC")], [pl.Datetime("us"), pl.Date]),
        "date": ([pl.Date], [pl.Datetime("us", "UTC"), pl.String]),
        "array<string>": ([pl.List(pl.String)], [pl.String, pl.List(pl.Int64)]),
        "boolean": ([pl.Boolean], [pl.Int8]),
        "float": ([pl.Float64], [pl.Int64]),
    }


@pytest.mark.parametrize("kind", ["timestamp", "date", "array<string>", "boolean", "float"])
def test_each_new_type_accepts_its_dtype_and_refuses_others(kind, tmp_path):
    pl = pytest.importorskip("polars")
    c = _typed(tmp_path, kind)
    good, bad = _types()[kind]
    for d in good:
        assert dc.check_contract_schema({"s": pl.String, "t": d}, c, ()) == ["s", "t"]
    for d in bad:
        with pytest.raises(dc.ContractViolation) as e:
            dc.check_contract_schema({"s": pl.String, "t": d}, c, ())
        assert e.value.rule == "wrong_type"


def test_the_type_table_is_the_type_set_and_no_general_array_exists(tmp_path):
    pytest.importorskip("polars")
    assert set(dc._type_checks()) == dc.TYPES
    for kind in ("array<int>", "array"):
        doc = _doc("demo")
        doc["columns"].append({"name": "t", "type": kind})
        with pytest.raises(ValueError, match=f"has type '{kind}'"):
            _load(tmp_path, doc)


def test_a_duplicate_key_over_an_array_grain_is_refused(tmp_path):
    pl = pytest.importorskip("polars")
    doc = _doc("demo", scope="none", grain=["s", "t"])
    doc["columns"][1:] = [{"name": "t", "type": "array<string>", "required": True}]
    c = _load(tmp_path, doc)
    df = pl.DataFrame({"s": ["a", "a"], "t": [["x"], ["x"]]})
    with pytest.raises(dc.ContractViolation) as e:
        dc.check_contract_rows(df, c)
    assert e.value.rule == "duplicate_key"
    dc.check_contract_rows(pl.DataFrame({"s": ["a", "a"], "t": [["x"], ["y"]]}), c)


@pytest.mark.parametrize("rules", [None, {}])
def test_absence_of_a_rule_disables_nothing(rules, tmp_path):
    pl = pytest.importorskip("polars")
    doc = _doc("demo", scope="none", dependencies=[{"by": "s", "determines": ["v"]}])
    if rules is not None:
        doc["rules"] = rules
    c = _load(tmp_path, doc)
    assert c.rules == {}
    with pytest.raises(dc.ContractViolation) as e:
        dc.check_contract_rows(pl.DataFrame({"s": ["a", "a"], "v": ["x", "x"]}), c)
    assert e.value.rule == "duplicate_key"
    both = [{"name": n, "type": "string", "required": True} for n in ("s", "v")]
    c2 = _load(tmp_path, {**doc, "grain": ["s", "v"], "columns": both})
    with pytest.raises(dc.ContractViolation) as e:
        dc.check_contract_rows(pl.DataFrame({"s": ["a", "a"], "v": ["x", "y"]}), c2)
    assert e.value.rule == "not_determined_by"


@pytest.mark.parametrize("rules", [{"duplicate_key": 7}, ["a"], {"duplicate_key": ""}, [], ""])
def test_a_malformed_rules_block_is_refused(rules, tmp_path):
    with pytest.raises(ValueError, match="rules maps a rule id to its message"):
        _load(tmp_path, _doc("demo", rules=rules))


def test_unknown_rules_are_sorted_and_honour_also(tmp_path):
    c = _load(tmp_path, _doc("demo", rules={"zeta": "m", "duplicate_key": "m", "alpha": "m"}))
    assert dc.unknown_rules(c) == ["alpha", "zeta"]
    assert dc.unknown_rules(c, ["alpha"]) == ["zeta"]


def _fin(monkeypatch, tmp_path, doc):
    from agent_fleet.finance_agent import measure_verbs

    _write(tmp_path, doc, name="demo")
    monkeypatch.setenv("DATASET_CONTRACT_DIR", str(tmp_path))
    # no clean seam through a measure row's load path: the join is called directly
    return lambda: measure_verbs._join_contract({"contract": "demo"}, False)


def test_engine_fin_refuses_a_scope_none_contract_at_its_join(monkeypatch, tmp_path):
    join = _fin(monkeypatch, tmp_path, _doc("demo", scope="none"))
    with pytest.raises(ValueError, match="declares scope: none"):
        join()


def test_engine_fin_takes_a_producer_checked_rule_at_its_join(monkeypatch, tmp_path):
    # past the rules check the join reads the row's roles: this minimal row has no `levels`
    join = _fin(monkeypatch, tmp_path, _doc("demo", rules={"interval_overlap": "m"}))
    with pytest.raises(KeyError, match="levels"):
        join()


def test_engine_fin_refuses_a_rule_nobody_raises_at_its_join(monkeypatch, tmp_path):
    join = _fin(monkeypatch, tmp_path, _doc("demo", rules={"key_not_unique": "m"}))
    with pytest.raises(ValueError, match="no reader raises"):
        join()
