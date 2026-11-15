"""A `personal_data` column is withheld from every read unless the reading engine releases it.

Ruled 2026-11-14 (ADR-0070 ruling 4): the contract records the FACT; the shared reader never selects
the column by default and refuses a row that names it unreleased. No engine passes a release yet.
"""
import ast
from pathlib import Path

import polars as pl
import pytest
import yaml

from agent_fleet.utils import dataset_contracts as dc

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "tests" / "fixtures" / "dag_tools_mfg_trace" / "mfg_trace.yaml"
RESULT = "mfg_trace.test_result"
DTYPES = {"string": pl.String, "numeric": pl.Float64, "integer": pl.Int64, "float": pl.Float64,
          "boolean": pl.Boolean, "date": pl.Date, "timestamp": pl.Datetime(time_zone="UTC"),
          "array<string>": pl.List(pl.String)}


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


def _result():
    return dc.load_contracts(TEMPLATE)[RESULT]


def _schema(contract, **over):
    s = {c: DTYPES[k] for c, k in contract.types.items()}
    s.update(over)
    return s


def test_the_template_marks_operator_ref_personal():
    """The one personal column of the mfg_trace template is test_result.operator_ref."""
    got = dc.load_contracts(TEMPLATE)
    assert got[RESULT].personal == {"operator_ref"}
    assert all(c.personal == frozenset() for cid, c in got.items() if cid != RESULT)


def test_a_read_withholds_a_personal_column_by_default():
    c = _result()
    got = dc.check_contract_schema(_schema(c), c, ())
    assert got == [col for col in c.types if col != "operator_ref"]
    # control: the reading engine's release brings it back
    assert "operator_ref" in dc.check_contract_schema(_schema(c), c, (), released={"operator_ref"})


def test_a_row_naming_an_unreleased_personal_column_is_refused():
    c = _result()
    with pytest.raises(dc.ContractViolation) as exc:
        dc.check_contract_schema(_schema(c), c, ("operator_ref",))
    assert exc.value.rule == "personal_data"
    assert "operator_ref" in str(exc.value)
    got = dc.check_contract_schema(_schema(c), c, ("operator_ref",), released={"operator_ref"})
    assert "operator_ref" in got


def test_an_asset_without_the_personal_column_is_not_missing_a_column():
    """The broker may project the column away for an unentitled caller: not required, so not missing."""
    c = _result()
    schema = _schema(c)
    del schema["operator_ref"]
    assert "operator_ref" not in dc.check_contract_schema(schema, c, ())


def test_a_withheld_column_is_still_type_checked():
    """A dtype is schema metadata, not a value: withholding the column does not skip its type."""
    c = _result()
    with pytest.raises(dc.ContractViolation) as exc:
        dc.check_contract_schema(_schema(c, operator_ref=pl.Int64), c, ())
    assert exc.value.rule == "wrong_type"


def test_a_release_names_only_personal_columns():
    c = _result()
    with pytest.raises(ValueError, match="not personal_data columns"):
        dc.check_contract_schema(_schema(c), c, (), released={"result_id"})


def _personal_doc(case):
    cols = [{"name": "s", "type": "string", "required": True},
            {"name": "v", "type": "string"},
            {"name": "p", "type": "string", "personal_data": True}]
    doc = _doc("demo", columns=cols)
    if case == "required":
        cols[2]["required"] = True
    elif case == "grain":
        doc["grain"] = ["s", "p"]
    elif case == "scope":
        doc["scope"] = "p"
        doc["grain"] = ["p"]
    elif case == "by":
        doc["dependencies"] = [{"by": "p", "determines": ["v"]}]
    elif case == "determines":
        doc["dependencies"] = [{"by": "s", "determines": ["p"]}]
    return doc


@pytest.mark.parametrize("case", ["required", "grain", "scope", "by", "determines"])
def test_a_personal_column_is_refused_where_every_read_needs_it(tmp_path, case):
    # `p` is not required in the grain, scope and `by` cases: the personal refusal is the one a
    # reader sees, ahead of "must be required", whose remedy would be the wrong one
    with pytest.raises(ValueError, match=r"personal_data column\(s\) \['p'\]"):
        _load(tmp_path, _personal_doc(case))


def test_personal_data_is_true_or_false(tmp_path):
    doc = _personal_doc("none")
    doc["columns"][2]["personal_data"] = "yes"
    with pytest.raises(ValueError, match="true or false"):
        _load(tmp_path, doc)


def test_a_personal_column_that_nothing_requires_loads(tmp_path):
    c = _load(tmp_path, _personal_doc("none"))
    assert c.personal == {"p"}
    assert dc.withheld(c) == ["p"]
    assert dc.withheld(c, {"p"}) == []


def test_a_contract_without_personal_columns_withholds_nothing(tmp_path):
    c = _load(tmp_path, _doc("demo"))
    assert c.personal == frozenset()
    assert dc.withheld(c) == []
    assert dc.check_contract_schema({"s": pl.String, "v": pl.String}, c, ()) == ["s", "v"]


def _fin(monkeypatch, tmp_path, doc, ds):
    from agent_fleet.finance_agent import measure_verbs

    _write(tmp_path, doc, name="demo")
    monkeypatch.setenv("DATASET_CONTRACT_DIR", str(tmp_path))
    # no clean seam through a measure row's load path: the join is called directly
    return lambda: measure_verbs._join_contract({"contract": "demo", **ds}, False)


def _fin_doc():
    cols = [{"name": "s", "type": "string", "required": True},
            {"name": "v", "type": "string"},
            {"name": "n", "type": "numeric"},
            {"name": "p", "type": "string", "personal_data": True}]
    return _doc("demo", columns=cols)


def test_engine_fin_refuses_a_row_naming_a_personal_column(monkeypatch, tmp_path):
    """Engine-fin releases no personal data (ruled 2026-11-14): its join refuses a row naming one."""
    for ds in ({"levels": ["s", "p"], "value_columns": ["n"]},
               {"levels": ["s", "v"], "value_columns": ["p"]}):
        with pytest.raises(ValueError, match="releases no personal data"):
            _fin(monkeypatch, tmp_path, _fin_doc(), ds)()
    # control: the same row without the personal column does not raise the personal message
    ok = {"levels": ["s", "v"], "value_columns": ["n"]}
    try:
        _fin(monkeypatch, tmp_path, _fin_doc(), ok)()
    except ValueError as exc:
        assert "personal data" not in str(exc)


def test_the_read_path_never_selects_a_personal_column(tmp_path):
    """`read_dataset_rows` collects a frame without the personal column the asset carries."""
    from agent_fleet.finance_agent import asset_inputs

    c = _load(tmp_path, _fin_doc())
    lf = pl.LazyFrame({"s": ["P"], "v": ["a"], "n": [1.5], "p": ["secret"]})
    selected = []

    class Spy:
        def collect_schema(self):
            return lf.collect_schema()

        def filter(self, *a):
            return self

        def select(self, cols):
            selected.append(list(cols))
            return lf.select(cols)

    rows = asset_inputs.read_dataset_rows(lambda urn: Spy(), "urn", ("s", "v"), ("n",), "plus", "sum", "P", c)
    assert rows
    assert selected == [["s", "v", "n"]]


def _flagged(source):
    """For each `check_contract_schema` call in `source`: does it pass a release?"""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if name == "check_contract_schema":
                out.append(len(node.args) > 3 or any(isinstance(a, ast.Starred) for a in node.args)
                           or any(k.arg in ("released", None) for k in node.keywords))
    return out


def test_no_engine_releases_personal_data():
    """Census: no engine calls `check_contract_schema` with a release (ruled 2026-11-14)."""
    calls = []
    for path in sorted((ROOT / "agent_fleet").rglob("*.py")):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        calls += [(path, f) for f in _flagged(path.read_text(encoding="utf-8"))]
    assert len(calls) >= 2, "the census reached no call: asset_inputs has two"
    assert [str(p) for p, f in calls if f] == []
    # positive control: the visitor flags every form a release could take, and not a plain call
    src = ("check_contract_schema(s, c, n, released={'x'})\nm.check_contract_schema(s, c, n, r)\n"
           "check_contract_schema(*a)\ncheck_contract_schema(s, c, n, **kw)\ncheck_contract_schema(s, c, n)\n")
    assert _flagged(src) == [True, True, True, True, False]


def test_personal_data_is_a_registered_rule():
    assert "personal_data" in dc.RULES
