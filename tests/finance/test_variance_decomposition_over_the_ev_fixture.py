"""The flow-decomposition measure proved on the EV fixture, through the REAL engine route.

A TEST overlay (tests/finance/overlays/variance_decomposition/, never policy/) declares one
dataset-kind row over the fixture's own columns. The route is real; the mesh client is replaced at
`asset_inputs._load_client` by a double holding a gate per caller; the frame is a real parquet
built from the seed the way `test_the_variance_live_test_can_go_red` builds it. The expected edges
are computed HERE, with polars, from the same frame, and not through the module. Nothing says a
cluster behaves this way.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_variance_decomposition_over_the_ev_fixture.py
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

pl = pytest.importorskip("polars")

from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.finance_agent import asset_inputs, seed  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from tests.finance.test_fin_inputs_resolver import (  # noqa: E402,F401
    MeshUnavailable, NotEntitled, _clean_env, frame_of, token,
)

OVERLAY = Path(__file__).parent / "overlays" / "variance_decomposition"
FN = "fin_flow_acwp"
ROW_URN = "urn:li:dataset:(urn:li:dataPlatform:s3,ev_fixture,PROD)"
PROGRAM = seed.PROGRAM_ID
ALLOWED, DENIED = "alice@example.com", "mallory@example.com"
THRESHOLD = Decimal("0.15")


class Gate:
    """The client double: a subject not in `granted` is refused, and only the row's URN exists."""

    def __init__(self, frame):
        self.frame = frame
        self.granted = {ALLOWED}
        self.asked: list[tuple[str, str]] = []

    def load(self):
        gate = self

        class Client:
            def __init__(self, **kw):
                self.who = kw["originator_email"]

            def get_dataframe(self, urn):
                gate.asked.append((self.who, urn))
                if urn != ROW_URN or self.who not in gate.granted:
                    raise NotEntitled("refused")
                return gate.frame
        return Client, NotEntitled, MeshUnavailable


@pytest.fixture
def flow_rows(monkeypatch):
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(OVERLAY))
    rows = engine._load_declared()
    monkeypatch.setattr(engine, "DECLARED", rows)
    monkeypatch.setitem(engine.VERB_TO_FN, "mesh:" + rows[FN].verb, FN)
    return rows


@pytest.fixture
def members(monkeypatch):
    held = {ALLOWED, DENIED}
    monkeypatch.setattr(engine, "can_view_program",
                        lambda program, caller_id, **kw: program == PROGRAM and caller_id in held)
    monkeypatch.setattr(engine, "_held_domains", lambda caller: frozenset({"PROGRAM_FINANCE"}))


@pytest.fixture
def gate(tmp_path, flow_rows, members, monkeypatch):
    path = tmp_path / "ev.parquet"
    frame_of().write_parquet(path)
    g = Gate(pl.scan_parquet(path))
    monkeypatch.setattr(engine.asset_inputs, "_load_client", g.load)
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")   # FIN_DATASET_URN stays UNSET
    return g


@pytest.fixture
def post(gate):
    who = {"allowed": ALLOWED, "denied": DENIED}
    with TestClient(engine.app) as c:
        def call(role="allowed", params=None, fn=FN):
            r = c.post(f"/measure/{fn}", json={"params": params or {"program_id": PROGRAM},
                                               "user_email": who[role]},
                       headers={"Authorization": f"Bearer {token(who[role])}"})
            return r.status_code, r.json()
        call.client = c
        yield call


# ── the oracle: polars sums and the stated rule, NOT the module ───────────────────────────────

def expected_edges(frame, threshold=THRESHOLD):
    f = frame.filter(pl.col("program_id") == PROGRAM)

    def split(parent, kids):
        total = sum((abs(v) for v in kids.values()), Decimal(0))
        small = [k for k, v in kids.items() if v != 0 and abs(v) / total < threshold]
        out, kept = [], []
        for k, v in kids.items():
            if len(small) > 1 and k in small:
                continue
            out.append((parent + [k], v))
            kept.append(k)
        if len(small) > 1:
            out.append((parent + ["All other"], sum((kids[k] for k in small), Decimal(0))))
        return out, kept

    cas = {r[0]: Decimal(str(r[1])) for r in f.group_by("control_account").agg(pl.col("acwp").sum()).iter_rows()}
    level1, kept = split([PROGRAM], cas)
    edges = [(None, [PROGRAM], sum(cas.values(), Decimal(0)))]          # the root edge
    edges += [([PROGRAM], t, v) for t, v in level1]
    for ca in kept:
        wps = {r[0]: Decimal(str(r[1])) for r in f.filter(pl.col("control_account") == ca)
               .group_by("work_package").agg(pl.col("acwp").sum()).iter_rows()}
        level2, _ = split([PROGRAM, ca], wps)
        edges += [([PROGRAM, ca], t, v) for t, v in level2]
    table = [(s, t, abs(v), "positive" if v > 0 else "negative" if v < 0 else "zero", len(t) - 1) for s, t, v in edges]
    return sorted(table, key=lambda e: (e[4], e[0] or [], -e[2], e[1]))


def served(rows):
    return [(e["source"], e["target"], Decimal(e["value_exact"]), e["sign"], e["level"]) for e in rows]


SIGN = {"positive": 1, "negative": -1, "zero": 0}


def conserved(rows, root_value):
    value_of = {tuple(e["target"]): SIGN[e["sign"]] * Decimal(e["value_exact"]) for e in rows}
    assert value_of[(PROGRAM,)] == root_value                       # the root edge carries the total
    for node in {tuple(e["source"]) for e in rows if e["source"] is not None}:
        kids = sum((SIGN[e["sign"]] * Decimal(e["value_exact"]) for e in rows if e["source"] == list(node)),
                   Decimal(0))
        assert kids == value_of[node], node


# ── green ─────────────────────────────────────────────────────────────────────────────────────

def test_the_edges_equal_an_independent_computation_from_the_same_frame(post):
    status, env = post()
    assert status == 200, env
    want = expected_edges(frame_of())
    assert served(env["rows"]) == want
    kinds = {t[-1] for _s, t, *_ in want}
    assert "All other" in kinds                                  # the collapse fired, at level 1
    assert {"WP-3101", "WP-3102"} <= kinds                       # and the lone child kept its name
    assert not {"WP-1101", "WP-4101", "WP-5101"} & kinds         # collapsed accounts' children are gone


def test_the_flow_conserves_at_every_node_of_the_served_table(post):
    _status, env = post()
    total = frame_of().filter(pl.col("program_id") == PROGRAM)["acwp"].sum()
    conserved(env["rows"], Decimal(str(total)))


def test_the_envelope_names_the_shape_the_source_and_the_method(post, gate, flow_rows):
    _status, env = post()
    assert env["render"]["shape"] == "FLOW_DECOMPOSITION"
    assert env["data_source"] == {"kind": "asset", "urn": ROW_URN}
    assert env["data_provenance"].startswith("SYNTHETIC") and ROW_URN in env["data_provenance"]
    assert env["measure"] == FN and env["output_uri"].endswith("DeclaredMeasureSeries")
    assert env["artifact_id"].startswith(f"fin:{FN}:")
    assert env["method"]["version"] == "1.3.0" and env["method"]["module_sha256"] == flow_rows[FN].module_sha256
    assert env["verdict"] and "net" in env["verdict"] and "All other" in env["verdict"]
    assert "series" not in env and "reference" not in env
    assert all(isinstance(e["value"], float) and e["value_exact"] for e in env["rows"])
    assert gate.asked == [(ALLOWED, ROW_URN)]                     # read as the caller


def test_the_row_urn_is_read_and_the_environments_is_never_consulted(post, gate, monkeypatch):
    monkeypatch.setenv("FIN_DATASET_URN", "urn:li:dataset:(urn:li:dataPlatform:s3,other,PROD)")
    status, env = post()
    assert status == 200 and gate.asked == [(ALLOWED, ROW_URN)]
    assert env["data_source"]["urn"] == ROW_URN


def test_a_program_the_asset_does_not_hold_is_a_422_not_a_seed_answer(post, monkeypatch):
    monkeypatch.setattr(engine, "can_view_program", lambda *a, **k: True)
    status, body = post(params={"program_id": "NP-NOBODY"})
    assert status == 422 and "not_in_model" in body["detail"]


# ── refusals ──────────────────────────────────────────────────────────────────────────────────

def test_a_denied_caller_is_a_403_access_denied_with_no_figure(post):
    status, body = post("denied")
    assert status == 403 and body["detail"]["status"] == "access_denied"
    assert body["detail"]["denied_assets"] == [ROW_URN]
    assert "rows" not in body and "rows" not in body["detail"]


def test_a_null_level_value_is_a_502_naming_the_rule(post, gate):
    gate.frame = gate.frame.with_columns(
        pl.when(pl.col("work_package") == "WP-1101").then(None).otherwise(pl.col("control_account"))
        .alias("control_account")).lazy()
    status, body = post()
    assert status == 502 and body["detail"]["error"] == "asset_contract_violation"
    assert body["detail"]["rule"] == "null_value" and "control_account" in body["detail"]["message"]


def test_a_missing_value_column_is_a_502_naming_the_rule(post, gate):
    gate.frame = gate.frame.drop("acwp")
    status, body = post()
    assert status == 502 and body["detail"]["rule"] == "missing_column"
    assert "acwp" in body["detail"]["message"]


def test_a_non_numeric_value_column_is_a_502_naming_the_rule(post, gate):
    gate.frame = gate.frame.with_columns(pl.col("acwp").cast(pl.String))
    status, body = post()
    assert status == 502 and body["detail"]["rule"] == "wrong_type"


def test_a_non_finite_value_is_a_502_naming_the_rule(post, gate):
    gate.frame = gate.frame.with_columns(
        pl.when(pl.col("work_package") == "WP-1101").then(float("inf")).otherwise(pl.col("acwp")).alias("acwp"))
    status, body = post()
    assert status == 502 and body["detail"]["rule"] == "non_finite"


def test_a_level_value_that_is_the_sink_label_is_a_502_naming_no_value(post, gate):
    # 4.1 is renamed to the sink's label; 1.1 and 5.1 still collapse, so the two would share a path
    gate.frame = gate.frame.with_columns(
        pl.when(pl.col("control_account").cast(pl.String) == "4.1").then(pl.lit("All other"))
        .otherwise(pl.col("control_account").cast(pl.String)).alias("control_account")).lazy()
    status, body = post()
    assert status == 502 and body["detail"]["rule"] == "refused_by_module"
    assert "4.1" not in str(body) and "rows" not in body


def test_the_row_cap_is_a_422_asset_too_large(post, monkeypatch):
    monkeypatch.setenv("FIN_ASSET_MAX_ROWS", "3")
    status, body = post()
    assert status == 422 and body["detail"]["error"] == "asset_too_large"


def test_a_mesh_outage_is_a_503(post, gate, monkeypatch):
    def down():
        class Client:
            def __init__(self, **kw):
                pass

            def get_dataframe(self, urn):
                raise MeshUnavailable("down")
        return Client, NotEntitled, MeshUnavailable
    monkeypatch.setattr(engine.asset_inputs, "_load_client", down)
    status, body = post()
    assert status == 503 and body["detail"]["error"] == "asset_unavailable"


def test_the_window_param_is_refused_for_this_kind(post):
    status, body = post(params={"program_id": PROGRAM, "window": ["FY26-01"]})
    assert status == 400 and "window" in body["detail"]


def test_a_null_program_is_refused_and_carries_no_figure(post):
    status, body = post(params={"program_id": None})
    assert status == 422 or status == 403  # visibility is checked first on a missing program
    assert "rows" not in body


# ── exports and registration ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("flag", [None, ROW_URN])
def test_an_export_naming_a_dataset_measure_is_refused_with_the_existing_code(flow_rows, flag, monkeypatch):
    if flag:
        monkeypatch.setenv("FIN_DATASET_URN", flag)
    with pytest.raises(engine.HTTPException) as e:
        engine._refuse_asset_exports([FN])
    assert e.value.status_code == 409 and e.value.detail["error"] == "asset_export_unsupported"
    assert e.value.detail["measures"] == [FN]


def test_a_built_in_only_export_is_unaffected(flow_rows):
    engine._refuse_asset_exports(["fin_performance_indices"])


def test_a_package_naming_it_is_a_409_before_anything_is_measured(post, gate, monkeypatch):
    body = {"user_email": ALLOWED, "recipient_scope": f"program_office.{PROGRAM}",
            "canvas": {"template_id": "program_finance", "template_hash": "h",
                       "panels": [{"panel": 0, "verb": "mesh:finFlowActualCost",
                                   "params": {"program_id": PROGRAM}}]}}
    r = post.client.post("/package_export", json=body, headers={"Authorization": f"Bearer {token(ALLOWED)}"})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "asset_export_unsupported" and gate.asked == []


def test_the_verb_registers_like_a_state_row(flow_rows):
    calls = [c for c in engine._registration_calls("http://engine.test") if c["endpoint_url"].endswith(FN)]
    assert len(calls) == 1
    (c,) = calls
    assert c["verb"] == "mesh:" + flow_rows[FN].verb and c["output_uri"].endswith("DeclaredMeasureSeries")
    assert [s["name"] for s in c["slots"]] == ["program_id"] and c["domains"] == ["PROGRAM_FINANCE"]


def test_the_envelope_serves_the_label_and_the_sink_is_marked_by_node_kind(post):
    status, env = post()
    assert status == 200, env
    assert env["render"]["other_label"] == "All other"
    for e in env["rows"]:
        assert (e["node_kind"] == "other") == (e["target"][-1] == env["render"]["other_label"]), e
    others = [e for e in env["rows"] if e["node_kind"] == "other"]
    assert len(others) == 1 and others[0]["level"] == 1          # accounts 4.1, 1.1, 5.1 collapse
    assert others[0]["source"] == [PROGRAM]
    assert f"{len(others)} 'All other' sink(s)" in env["verdict"]
