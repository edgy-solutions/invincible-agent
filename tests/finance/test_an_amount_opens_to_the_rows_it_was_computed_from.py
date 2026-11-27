"""An amount opens to the rows it was computed from, through the REAL routes (phase 1: dataset flow answers).

Every edge and every sink member of a flow answer carries `row_count` and, when the read's receipt has
an as-of, an opaque `drill`. `fin_drill_rows` pages the rows the value names; `POST /drill_rows/download`
serves them as CSV. The population in every seal is the answer's own: each edge and member is read from
the answer, never typed. The oracle is built here: signed sums of the drilled rows, set against the amounts
the answer served.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_an_amount_opens_to_the_rows_it_was_computed_from.py
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
from decimal import Decimal

import pytest
import yaml

pl = pytest.importorskip("polars")

from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.finance_agent import asset_inputs, drill, measures  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from tests.finance.test_a_flow_row_draws_to_its_declared_depth import (  # noqa: E402
    FN_ONCE, b_frame, b_once_frame, once_variant_of_the_wbs_row,
)
from tests.finance.test_a_flow_total_reads_one_period_or_through_it import (  # noqa: E402
    B_DIR, FN_B, PROG_B, SAMPLE_CAL, SAMPLE_ROWS, URN_B, Gate, b_row, contracts_raw, declare, ev_row, frame,
    FN_EV, _yaml,
)
from tests.finance.test_fin_inputs_resolver import (  # noqa: E402,F401
    AS_OF, MeshUnavailable, NotEntitled, _clean_env, frame_of, ticketed, token,
)
from tests.finance.test_variance_decomposition_over_the_ev_fixture import (  # noqa: E402
    ALLOWED, DENIED, PROGRAM, ROW_URN,
)

FN_PLAIN, FN_CV, FN_IPT = "fin_b_flow_wbs", "fin_b_flow_cv", "fin_b_flow_ipt"
STRANGER = "eve@example.com"
LATER = "2026-11-02T00:00:00Z"
SIGN = {"positive": 1, "negative": -1, "zero": 0}


# -- the world: a Gate whose receipt as-of the test can move ------------------------------------

class MovingGate(Gate):
    """`Gate`, with the receipt's `as_of` a thing the test sets (`None`: a receipt with none)."""

    def __init__(self, frames):
        super().__init__(frames)
        self.as_of = AS_OF

    def load(self):
        gate = self

        class Client:
            def __init__(self, **kw):
                self.who = kw["originator_email"]

            def get_dataframe_with_ticket(self, urn):
                gate.asked.append((self.who, urn))
                if urn not in gate.frames or self.who not in gate.granted:
                    raise NotEntitled("refused")
                return ticketed(gate.frames[urn].lazy(), urn, len(gate.asked), as_of=gate.as_of)
        return Client, NotEntitled, MeshUnavailable


def _world(monkeypatch, tmp_path, rows, frames):
    declared = declare(monkeypatch, tmp_path, rows, contracts_raw())
    gate = MovingGate(frames)
    monkeypatch.setattr(engine, "DECLARED", declared)
    for fn, row in declared.items():
        monkeypatch.setitem(engine.VERB_TO_FN, "mesh:" + row.verb, fn)
    monkeypatch.setattr(engine.asset_inputs, "_load_client", gate.load)
    monkeypatch.setattr(engine, "can_view_program",
                        lambda program, caller_id, **kw: program in {PROG_B, PROGRAM} and caller_id in {ALLOWED, DENIED})
    monkeypatch.setattr(engine, "_held_domains", lambda caller: frozenset({"PROGRAM_FINANCE"}))
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")
    gate.declared = declared
    return gate


def _rows():
    return {FN_B: b_row(), FN_PLAIN: _yaml(B_DIR / "measure_verbs" / "fin_b_flow_wbs.yaml"),
            FN_CV: _yaml(B_DIR / "measure_verbs" / "fin_b_flow_cv.yaml"),
            FN_IPT: _yaml(B_DIR / "measure_verbs" / "fin_b_flow_ipt.yaml"),
            FN_EV: ev_row()}


@pytest.fixture
def gate(monkeypatch, tmp_path):
    return _world(monkeypatch, tmp_path, _rows(), {URN_B: b_frame(), ROW_URN: frame_of()})


@pytest.fixture
def client(gate):
    with TestClient(engine.app) as c:
        yield c


def _as(client, who=ALLOWED):
    def post(fn, params, user=who):
        r = client.post(f"/measure/{fn}", json={"params": params, "user_email": user},
                        headers={"Authorization": f"Bearer {token(user)}"})
        return r.status_code, r.json()
    return post


def _answer(client, fn, program=PROG_B, **params):
    status, env = _as(client)(fn, {"program_id": program, **params})
    assert status == 200, env
    return env


def _drills(env):
    """EVERY edge and sink member of the answer, as (label, kind, drill, row_count, signed amount)."""
    out = []
    for e in env["rows"]:
        out.append((e["target"], "edge", e.get("drill"), e["row_count"], SIGN[e["sign"]] * Decimal(e["value_exact"])))
        for m in e.get("members", ()):
            out.append((m["target"], "member", m.get("drill"), m["row_count"], SIGN[m["sign"]] * Decimal(m["value_exact"])))
    return out


def _page(client, value, offset=0, limit=7, user=ALLOWED):
    return _as(client)("fin_drill_rows", {"drill": value, "offset": offset, "limit": limit}, user=user)


def _walk(client, value, limit):
    """Every row under `value`, page after page, and the total the first page said."""
    rows, offset, total = [], 0, None
    while total is None or offset < total:
        status, page = _page(client, value, offset, limit)
        assert status == 200, page
        total = page["total_count"] if total is None else total
        assert page["total_count"] == total, "the total moved between pages"
        assert page["offset"] == offset and page["limit"] == limit
        rows.extend(page["rows"])
        offset += limit
    return rows, total


def _key(row):
    return json.dumps(row, sort_keys=True)


def _signed(rows, row_decl):
    """The signed Decimal sum of the row's value over the drilled rows: a `minus` row is a less b."""
    cols = row_decl.value_columns
    ex = lambda r, c: Decimal(r[f"{c}_exact"])  # noqa: E731
    if row_decl.value_op == "minus":
        return sum((ex(r, cols[0]) - ex(r, cols[1]) for r in rows), Decimal(0))
    return sum((ex(r, cols[0]) for r in rows), Decimal(0))


def _evidence(client, gate, fn, limit, **params):
    env = _answer(client, fn, **params)
    row_decl = gate.declared[fn]
    population = _drills(env)
    assert population and any(k == "member" for _, k, *_ in population), "the control: a sink with members is in the population"
    for target, kind, value, count, amount in population:
        assert isinstance(value, str) and value.startswith("fd1."), (target, kind)
        rows, total = _walk(client, value, limit)
        assert total == count == len(rows), (target, kind, total, count, len(rows))                       # (a)
        assert len({_key(r) for r in rows}) == len(rows), f"a row served twice under {target}"            # (b)
        big, _ = _walk(client, value, 500)
        assert sorted(map(_key, rows)) == sorted(map(_key, big)), f"the pages are not the one read under {target}"
        if row_decl.per_path != "once":
            assert _signed(rows, row_decl) == amount, (target, kind)                                      # (c)
    return env, population


# -- 1. evidence ---------------------------------------------------------------------------------

@pytest.mark.parametrize("params", [{"period": "P10", "basis": "period"}, {"period": "P3", "basis": "cumulative"}])
def test_every_edge_and_member_opens_to_rows_that_sum_to_its_amount_by_period(client, gate, params):
    _evidence(client, gate, FN_B, 7, **params)


def test_every_edge_and_member_opens_to_rows_that_sum_to_its_amount_plain_sum(client, gate):
    _evidence(client, gate, FN_PLAIN, 60)


def test_every_edge_and_member_of_a_minus_row_opens_to_a_less_b(monkeypatch, tmp_path):
    f = b_frame().with_columns((pl.col("acwp") * 2).alias("bcwp"))
    g = _world(monkeypatch, tmp_path, _rows(), {URN_B: f, ROW_URN: frame_of()})
    with TestClient(engine.app) as c:
        env, population = _evidence(c, g, FN_CV, 60)
    gate = g
    assert gate.declared[FN_CV].value_op == "minus"


def test_every_edge_and_member_of_a_sample_flow_row_opens_to_its_rows(client, gate):
    env, population = _evidence(client, gate, FN_EV, 7, program=PROGRAM, period="FY26-06", basis="cumulative")
    assert gate.declared[FN_EV].contract.scope == "program_id"


def test_the_levels_the_edges_name_are_the_levels_the_drill_filters(client, gate):
    """`target[i]` is the value of `levels[i + 1]`: every drilled row of an edge carries exactly the path's values."""
    env = _answer(client, FN_PLAIN)
    levels = gate.declared[FN_PLAIN].levels
    deep = [d for d in _drills(env) if len(d[0]) > 2 and d[1] == "edge" and d[0][-1] != "All other"]  # a sink edge names its members, not a path
    assert deep
    for target, _, value, _, _ in deep:
        rows, _ = _walk(client, value, 500)
        for r in rows:
            assert [str(r[c]) for c in levels[1:len(target)]] == target[1:], target


def test_a_per_path_once_row_counts_dataset_rows_and_pages_them_without_gaps(monkeypatch, tmp_path):
    rows = {**_rows(), FN_ONCE: once_variant_of_the_wbs_row()}
    g = _world(monkeypatch, tmp_path, rows, {URN_B: b_once_frame(b_frame()), ROW_URN: frame_of()})
    with TestClient(engine.app) as c:
        env, population = _evidence(c, g, FN_ONCE, 60)
        root = [d for d in population if d[0] == [env["rows"][0]["target"][0]]]
        (root_edge,) = [e for e in env["rows"] if e["source"] is None]
        assert root_edge["row_count"] == b_frame().height, "dataset rows, not groups"
        assert gate_declared(g, FN_ONCE).per_path == "once"
    assert root


def gate_declared(g, fn):
    return g.declared[fn]


# -- 2. the as-of --------------------------------------------------------------------------------

def test_a_reloaded_dataset_refuses_the_drill_and_serves_no_row(client, gate):
    env = _answer(client, FN_B, period="P10", basis="period")
    value = next(v for _, k, v, *_ in _drills(env) if k == "member")
    status, page = _page(client, value)
    assert status == 200 and page["rows"], "the control: the as-of unchanged serves rows"
    gate.as_of = LATER
    status, body = _page(client, value)
    assert status == 409 and body["detail"]["error"] == "as_of_moved", body
    assert "rows" not in json.dumps(body)
    assert body["detail"]["answer_as_of"] == AS_OF and body["detail"]["data_as_of"] == LATER
    r = client.post("/drill_rows/download", json={"params": {"drill": value}, "user_email": ALLOWED},
                    headers={"Authorization": f"Bearer {token(ALLOWED)}"})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "as_of_moved"


def test_a_receipt_with_no_as_of_serves_no_drill_and_says_why(client, gate, caplog):
    gate.as_of = None
    with caplog.at_level(logging.INFO):
        env = _answer(client, FN_B, period="P10", basis="period")
    assert env["drill_unavailable"] == "as_of_unavailable"
    assert not any("drill" in e or any("drill" in m for m in e.get("members", ())) for e in env["rows"])
    assert all("row_count" in e for e in env["rows"]), "the count does not need an as-of"
    assert "fin.drill_unavailable measure=" + FN_B + " reason=as_of_unavailable" in caplog.text
    gate.as_of = AS_OF
    assert "drill_unavailable" not in _answer(client, FN_B, period="P10", basis="period")


def test_the_answer_declares_the_download_cap(client):
    env = _answer(client, FN_B, period="P10", basis="period")
    assert env["limits"] == {"max_rows": asset_inputs.drill_max_rows()}


# -- 3. the value is checked, not trusted --------------------------------------------------------

def _value_of(client, gate):
    env = _answer(client, FN_B, period="P10", basis="period")
    value = next(v for _, k, v, *_ in _drills(env) if k == "edge" and v)
    return value, drill.decode(value)


def _recode(doc):
    return drill._canonical(doc)


def test_a_value_the_engine_did_not_serve_is_refused_and_reads_nothing(client, gate):
    value, doc = _value_of(client, gate)
    longer = {**doc, "path": ["x"] * len(gate.declared[FN_B].levels)}
    bad = {"garbage": "fd1.not base64!!", "no prefix": value[4:], "extra key": _recode({**doc, "extra": 1}),
           "path too long": _recode(longer),
           "whitespace": "fd1." + __import__("base64").urlsafe_b64encode(
               json.dumps(doc, sort_keys=True).encode()).decode().rstrip("="),
           "a number as-of": _recode({**doc, "as_of": 20261101})}
    before = list(gate.asked)
    for name, v in bad.items():
        status, body = _page(client, v)
        assert (status, body["detail"]["error"]) == (400, "drill_invalid"), name
    assert gate.asked == before, "a refused value reads nothing"


def test_a_value_for_a_changed_measure_is_stale(client, gate):
    value, doc = _value_of(client, gate)
    status, body = _page(client, _recode({**doc, "module_sha256": "0" * 64}))
    assert (status, body["detail"]["error"]) == (409, "drill_stale"), body
    status, body = _page(client, _recode({**doc, "measure": "fin_no_such_row"}))
    assert (status, body["detail"]["error"]) == (409, "drill_stale")
    status, body = _page(client, _recode({**doc, "params": {**doc["params"], "version": "x"}}))
    assert (status, body["detail"]["error"]) == (409, "drill_stale"), "params must be exactly the row's"
    status, page = _page(client, value)
    assert status == 200, "the control: the served value is accepted"


# -- 4. the caller ---------------------------------------------------------------------------------

def test_a_caller_without_the_asset_grant_gets_the_measures_own_403(client, gate):
    value, _ = _value_of(client, gate)
    gate.granted = set()
    want = _as(client)(FN_B, {"program_id": PROG_B, "period": "P10", "basis": "period"})
    got = _page(client, value)
    assert want[0] == got[0] == 403 and got[1] == want[1], (got, want)
    assert got[1]["detail"]["status"] == "access_denied"
    gate.granted = {ALLOWED}
    assert _page(client, value)[0] == 200, "the control: a member with the grant"


def test_a_non_member_gets_what_the_measure_gives_a_non_member(client, gate):
    value, _ = _value_of(client, gate)
    gate.granted.add(STRANGER)
    want = _as(client)(FN_B, {"program_id": PROG_B, "period": "P10", "basis": "period"}, user=STRANGER)
    got = _page(client, value, user=STRANGER)
    assert want[0] == got[0] == 403 and got[1] == want[1], (got, want)
    assert got[1]["detail"]["error"] == "program_not_visible"
    assert _page(client, value)[0] == 200, "the control: a member"


# -- 5. the download -----------------------------------------------------------------------------

def _download(client, value, user=ALLOWED, **params):
    return client.post("/drill_rows/download", json={"params": {"drill": value, **params}, "user_email": user},
                       headers={"Authorization": f"Bearer {token(user)}"})


def test_the_download_is_the_drilled_rows_with_exact_money_and_names_its_file(client, gate):
    env = _answer(client, FN_B, period="P10", basis="period")
    value = next(v for _, k, v, *_ in _drills(env) if k == "member")
    rows, _ = _walk(client, value, 500)
    r = _download(client, value, format="csv")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv") and "utf-8" in r.headers["content-type"]
    assert r.headers["content-disposition"] == f'attachment; filename="{FN_B}-{PROG_B}-rows.csv"'
    table = list(csv.reader(io.StringIO(r.content.decode("utf-8"), newline="")))
    _, page = _page(client, value, 0, 500)
    assert table[0] == [c["name"] for c in page["columns"]]
    money = {c for c in table[0] if f"{c}_exact" in rows[0]}
    assert {"acwp", "bcwp", "bcws"} <= money
    assert len(table) - 1 == len(rows)
    for line, row in zip(table[1:], rows):
        for name, cell in zip(table[0], line):
            if name in money:
                assert cell == row[f"{name}_exact"], "money is its exact string"
            elif row[name] is not None and not isinstance(row[name], (list, float)):
                assert cell == str(row[name]), name


def test_a_cell_a_spreadsheet_would_read_as_a_formula_is_prefixed(monkeypatch, tmp_path):
    f = frame().with_columns(pl.lit("=cmd|' /C calc'!A0").alias("program_name"))
    g = _world(monkeypatch, tmp_path, _rows(), {URN_B: f, ROW_URN: frame_of()})
    with TestClient(engine.app) as c:
        env = _answer(c, FN_B, period="P10", basis="period")
        value = next(v for _, k, v, *_ in _drills(env) if k == "edge")
        r = _download(c, value)
    assert r.status_code == 200, r.text
    table = list(csv.reader(io.StringIO(r.content.decode("utf-8"), newline="")))
    col = table[0].index("program_name")
    assert {line[col] for line in table[1:]} == {"'=cmd|' /C calc'!A0"}
    assert g.asked


def test_a_negative_amount_is_no_formula(gate):
    contract = gate.declared[FN_B].contract
    df = frame().head(1).with_columns(pl.lit(-5.25).alias("acwp"))
    body = drill.csv_bytes(df, contract).decode("utf-8")
    header, line = list(csv.reader(io.StringIO(body, newline="")))
    assert line[header.index("acwp")] == "-5.25"


def test_a_download_over_the_cap_is_refused_naming_both_numbers_and_under_it_is_served(client, gate, monkeypatch):
    env = _answer(client, FN_B, period="P10", basis="period")
    (root,) = [d for d in _drills(env) if d[0] == [env["rows"][0]["target"][0]]]
    count = root[3]
    monkeypatch.setenv("FIN_DRILL_MAX_ROWS", str(count - 1))
    r = _download(client, root[2])
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "download_too_large" and detail["row_count"] == count and detail["max_rows"] == count - 1
    assert str(count) in detail["message"] and str(count - 1) in detail["message"]
    assert _page(client, root[2])[0] == 200, "a page is served whatever the total"
    monkeypatch.setenv("FIN_DRILL_MAX_ROWS", str(count))
    assert _download(client, root[2]).status_code == 200, "the control: the cap at the count"


def test_an_undeclared_format_is_refused(client, gate):
    env = _answer(client, FN_B, period="P10", basis="period")
    value = next(v for _, k, v, *_ in _drills(env))
    r = _download(client, value, format="xlsx")
    assert r.status_code == 400 and r.json()["detail"]["error"] == "format_not_declared"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("FIN_DATASET_URN", ROW_URN)
    monkeypatch.setenv("FIN_DATASET_BANNER", "SYNTHETIC TEST ASSET")
    monkeypatch.setenv("FIN_DATASET_CONTRACT", "ev_fixture")
    monkeypatch.setenv("DATASET_CONTRACT_DIR", str((SAMPLE_ROWS.parents[3] / "contracts")))
    monkeypatch.setenv("FIN_CALENDAR_OVERLAY_DIRS", str(SAMPLE_CAL))
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")
    monkeypatch.setattr(asset_inputs, "_load_client", lambda: None)


def test_boot_holds_the_drill_cap_to_the_read_cap(configured, monkeypatch):
    asset_inputs.check_config()
    monkeypatch.setenv("FIN_ASSET_MAX_ROWS", "500")
    monkeypatch.setenv("FIN_DRILL_MAX_ROWS", "500")
    asset_inputs.check_config()                       # the control: equal is allowed
    for bad in ("501", "0", "-1", "ten"):
        monkeypatch.setenv("FIN_DRILL_MAX_ROWS", bad)
        with pytest.raises(RuntimeError, match="FIN_DRILL_MAX_ROWS"):
            asset_inputs.check_config()


def test_the_drill_cap_defaults_without_refusing_a_lowered_read_cap(monkeypatch):
    monkeypatch.delenv("FIN_DRILL_MAX_ROWS", raising=False)
    monkeypatch.delenv("FIN_ASSET_MAX_ROWS", raising=False)
    assert asset_inputs.drill_max_rows() == 10_000
    monkeypatch.setenv("FIN_ASSET_MAX_ROWS", "300")
    assert asset_inputs.drill_max_rows() == 300


# -- 6. no value is logged -----------------------------------------------------------------------

def test_no_row_path_or_member_value_reaches_a_log(client, gate, monkeypatch, caplog):
    values = {str(v) for col in frame().columns if col not in ("acwp", "bcwp", "bcws", "period")
              for v in frame()[col].unique().to_list()} - {PROG_B}
    with caplog.at_level(logging.DEBUG):
        env, population = _evidence(client, gate, FN_B, 7, period="P10", basis="period")
        value = population[0][2]
        _download(client, value)
        gate.as_of = LATER
        _page(client, value)
        _page(client, "fd1.garbage")
        gate.as_of = AS_OF
    text = caplog.text
    assert "fin.drill_refused" in text, "the control: the refusals did log"
    leaked = sorted(v for v in values if v in text)
    assert not leaked, f"a level value reached a log: {len(leaked)} of them"


# -- 7. the verb is registered the way #576's lookups are ------------------------------------------

def test_the_verb_is_registered_and_its_class_declared():
    verbs = [v for v in engine.VERBS if v["fn"] == drill.DRILL_FN]
    assert [v["verb"] for v in verbs] == ["mesh:finDrillRows"]
    assert verbs[0]["input_uri"] == engine.FIN + "Program"
    assert measures.OUTPUT_URI[drill.DRILL_FN] == engine.FIN + "DrillRowPage"
    calls = [c for c in engine._registration_calls() if c["fn"] == drill.DRILL_FN]
    assert calls and {c["verb"] for c in calls} == {"mesh:finDrillRows"}
    assert [s["name"] for s in calls[0]["slots"]][:1] == ["drill"] or "drill" in {s["name"] for s in calls[0]["slots"]}
    assert engine.VERB_TO_FN["mesh:finDrillRows"] == drill.DRILL_FN
    ttl = (SAMPLE_ROWS.parents[3] / "setup" / "ontologies" / "finance_extension.ttl").read_text(encoding="utf-8")
    block = ttl[ttl.index("fin:DrillRowPage a owl:Class"):].split("\n\n")[0]
    assert "rdfs:subClassOf mesh:Response" in block and "rdfs:comment" in block


def test_the_registration_names_the_measure_route():
    src = (SAMPLE_ROWS.parents[3] / "agent_fleet" / "finance_agent" / "main.py").read_text(encoding="utf-8")
    assert 'endpoint_url=f"{base}/measure/{_call[\'fn\']}"' in src, "every built-in registers at /measure/<fn>"
    assert os.path.exists(SAMPLE_ROWS.parents[3] / "policy" / "measure_verbs" / "fin_drill_rows.yaml")
