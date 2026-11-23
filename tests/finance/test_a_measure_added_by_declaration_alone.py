"""A measure added by declaration alone: one sample row, no engine code, proved end to end.

The architect's order (2026-11-22): "add one new measure to the sample overlay end to end, with
tests, touching no engine code". The row is policy/overlays/sample/measure_verbs/
fin_flow_cost_variance.yaml. The route is the real one; the mesh client is replaced at
`asset_inputs._load_client` by a double holding a gate per caller; the frame is a real parquet built
from the seed. The expected edges are computed HERE, with polars, and not through the module.
The census proves the claim: no `*.py` under `agent_fleet/` or `src/` names the measure or its verb.
Nothing here ran on a cluster.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_a_measure_added_by_declaration_alone.py
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

pl = pytest.importorskip("polars", reason="the oracle sums the frame with polars")

from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.finance_agent import asset_inputs, measures, seed  # noqa: E402,F401
from agent_fleet.finance_agent import main as engine  # noqa: E402
from tests.finance.test_fin_inputs_resolver import (  # noqa: E402,F401
    AS_OF, MeshUnavailable, NotEntitled, _clean_env, frame_of, ticketed, token,
)

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "policy" / "overlays" / "sample" / "measure_verbs"
FN = "fin_flow_cost_variance"
VERB = "finFlowCostVariance"
ROW = SAMPLE / f"{FN}.yaml"
ROW_URN = "urn:li:dataset:(urn:li:dataPlatform:s3,ev_fixture,PROD)"
PROGRAM = seed.PROGRAM_ID
ALLOWED, DENIED = "alice@example.com", "mallory@example.com"
THRESHOLD = Decimal("0.05")
OTHERS = ["fin_eac_trend", "fin_ev_cumulative", "fin_flow_acwp", "fin_flow_eac_variance", "fin_tcpi",
          "fin_vac_cpi"]


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

            def get_dataframe_with_ticket(self, urn):
                gate.asked.append((self.who, urn))
                if urn != ROW_URN or self.who not in gate.granted:
                    raise NotEntitled("refused")
                return ticketed(gate.frame, urn, len(gate.asked))
        return Client, NotEntitled, MeshUnavailable


@pytest.fixture
def flow_rows(monkeypatch, tmp_path):
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    (overlay / ROW.name).write_bytes(ROW.read_bytes())          # the shipped row, loaded ALONE
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(overlay))
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
        yield call


# -- the oracle: polars sums and the stated rule, NOT the module ---------------------------------

def expected_edges(frame, threshold=THRESHOLD):
    f = frame.filter(pl.col("program_id") == PROGRAM).with_columns((pl.col("bcwp") - pl.col("acwp")).alias("cv"))

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

    cas = {r[0]: Decimal(str(r[1])) for r in f.group_by("control_account").agg(pl.col("cv").sum()).iter_rows()}
    level1, kept = split([PROGRAM], cas)
    edges = [(None, [PROGRAM], sum(cas.values(), Decimal(0)))]          # the root edge
    edges += [([PROGRAM], t, v) for t, v in level1]
    for ca in kept:
        wps = {r[0]: Decimal(str(r[1])) for r in f.filter(pl.col("control_account") == ca)
               .group_by("work_package").agg(pl.col("cv").sum()).iter_rows()}
        level2, _ = split([PROGRAM, ca], wps)
        edges += [([PROGRAM, ca], t, v) for t, v in level2]
    table = [(s, t, abs(v), "positive" if v > 0 else "negative" if v < 0 else "zero", len(t) - 1) for s, t, v in edges]
    return sorted(table, key=lambda e: (e[4], e[0] or [], -e[2], e[1]))


def served(rows):
    return [(e["source"], e["target"], Decimal(e["value_exact"]), e["sign"], e["level"]) for e in rows]


# -- the census ----------------------------------------------------------------------------------

NAMES = (FN, VERB)
SKIP_DIRS = {".venv", "__pycache__", "node_modules", ".git"}


def scan(root: Path, pattern: str = "*.py") -> dict[str, set[str]]:
    """Every file under `root` matching `pattern` that holds either name, with the names it holds."""
    hits: dict[str, set[str]] = {}
    for path in sorted(root.rglob(pattern)):
        if SKIP_DIRS & set(path.relative_to(root).parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found = {n for n in NAMES if n in text}
        if found:
            hits[path.relative_to(REPO).as_posix()] = found
    return hits


# -- seals ---------------------------------------------------------------------------------------

def test_it_loads_from_the_shipped_sample_directory_beside_every_other_sample_row(monkeypatch):
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(SAMPLE))        # no overlay but the sample
    rows = engine._load_declared()
    assert sorted(rows) == sorted(OTHERS + [FN])
    row = rows[FN]
    assert row.verb == VERB
    assert row.kind == "dataset" and row.archetype == "FLOW_DECOMPOSITION"
    assert row.module == "agent_fleet.finance_agent.measure_modules.variance_decomposition"
    assert (row.function, row.version) == ("flow_edges", "1.3.0")
    assert row.dataset_urn == ROW_URN
    assert (row.levels, row.value_op, row.value_columns) == (
        ("program_id", "control_account", "work_package"), "minus", ("bcwp", "acwp"))


def test_the_real_route_serves_the_edges_an_independent_computation_gives(post, gate):
    status, env = post()
    assert status == 200, env
    want = expected_edges(frame_of())
    assert served(env["rows"]) == want
    assert not [e for e in env["rows"] if e["node_kind"] == "other"]       # nothing collapses at 0.05
    zeros = [e for e in env["rows"] if e["sign"] == "zero"]
    assert {e["target"][-1] for e in zeros} == {
        "2.1", "4.1", "WP-1101", "WP-2101", "WP-2102", "WP-3102", "WP-4101", "WP-5102"}
    assert all(Decimal(e["value_exact"]) == 0 for e in zeros)
    assert {e["sign"] for e in env["rows"]} == {"positive", "negative", "zero"}
    (root,) = [e for e in env["rows"] if e["source"] is None]
    assert root["sign"] == "negative" and Decimal(root["value_exact"]) == Decimal(1130000)
    assert gate.asked == [(ALLOWED, ROW_URN)]                              # read as the caller


def test_the_flow_root_equals_the_built_in_cost_variance_in_magnitude_and_sign(post):
    _status, env = post()
    (root,) = [e for e in env["rows"] if e["source"] is None]
    flow = (-1 if root["sign"] == "negative" else 1) * Decimal(root["value_exact"])
    (tree,) = measures.fin_variance_analysis(seed.build_seed(), program_id=PROGRAM, variance_kind="cost")
    built_in = Decimal(str(tree["variance_exact"]))
    assert built_in == Decimal(-1130000), built_in
    assert flow == built_in


def test_a_denied_caller_is_a_403_access_denied_and_nothing_is_computed(post, gate, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("computed for a refused caller")
    monkeypatch.setattr(engine.measure_verbs, "run_dataset", boom)
    status, body = post("denied")
    assert status == 403 and body["detail"]["status"] == "access_denied"
    assert body["detail"]["denied_assets"] == [ROW_URN]
    assert "rows" not in body and "rows" not in body["detail"]
    assert gate.asked == [(DENIED, ROW_URN)]


def test_the_engine_names_it_nowhere():
    assert (REPO / "agent_fleet").is_dir() and (REPO / "src").is_dir()
    assert {**scan(REPO / "agent_fleet"), **scan(REPO / "src")} == {}


def test_the_census_scan_finds_both_names_where_they_are_declared():
    """Positive control: the SAME function, pointed at the sample directory, fires on both names."""
    hits = scan(SAMPLE, "*.yaml")
    assert set().union(*hits.values()) == set(NAMES)
    assert any(path.endswith(ROW.name) for path in hits)


def test_it_registers_as_a_mesh_verb_beside_the_built_ins(monkeypatch):
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(SAMPLE))
    rows = engine._load_declared()
    monkeypatch.setattr(engine, "DECLARED", rows)
    monkeypatch.setitem(engine.VERB_TO_FN, "mesh:" + VERB, FN)
    calls = [c for c in engine._registration_calls() if c["verb"] == "mesh:" + VERB]
    assert len(calls) == 1
    (c,) = calls
    assert c["fn"] == FN and c["output_uri"].endswith("DeclaredMeasureSeries")
    assert [s["name"] for s in c["slots"]] == ["program_id"] and c["domains"] == ["PROGRAM_FINANCE"]


def test_a_fresh_import_routes_and_registers_it_with_no_help_from_a_test():
    """The seals above load the row after import, so they set `VERB_TO_FN` themselves. This one
    imports engine-fin in a fresh interpreter with only the sample overlay set, and reads what
    the engine built: the import-time path (main.py's `VERB_TO_FN.update` over `DECLARED`)."""
    import os
    import subprocess
    import sys
    probe = ("import sys; sys.path.insert(0, '.')\n"
             "from agent_fleet.finance_agent import main as m\n"
             f"v = 'mesh:{VERB}'\n"
             "print('PROBE', m.VERB_TO_FN.get(v), [c['fn'] for c in m._registration_calls() if c['verb'] == v])\n")
    env = {**os.environ, "MEASURE_VERB_OVERLAY_DIRS": str(SAMPLE)}
    out = subprocess.run([sys.executable, "-I", "-c", probe], cwd=REPO, env=env, capture_output=True,
                         text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    (line,) = [ln for ln in out.stdout.splitlines() if ln.startswith("PROBE ")]
    assert line == f"PROBE {FN} ['{FN}']"
