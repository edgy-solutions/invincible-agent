"""Item 3's seals — a program-finance canvas, packaged.

THE RULE THESE EXIST FOR: seeding and packageExport read the SAME thing. The template is the
package definition; the per-panel (verb, params) a seed dispatches and the per-panel
(verb, params) a package computes come out of ONE function, `canvas_template.panel_dispatch`.

Every arm has a positive control beside the refusal it asserts. The duckdb-dependent arms use
`pytest.importorskip("duckdb")` like cost's tests: a SKIPPED arm is not a green, and the run
that reports this file's result must be the `--with duckdb==1.5.2` one.
"""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import typing

import pytest
from fastapi import HTTPException

ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.finance_agent import export as fin_export  # noqa: E402
from agent_fleet.finance_agent import state_codec  # noqa: E402
from agent_fleet.finance_agent.seed import build_seed  # noqa: E402
from iagent.canvas_template import (  # noqa: E402
    Package, load_template, panel_dispatch, recipient_scope_for, template_ref,
)

SCOPE = "program_office.NP-MERIDIAN"
BINDINGS = {"program": "NP-MERIDIAN"}
SHA64 = "sha256:" + "a" * 64


def _template():
    return load_template("program_finance")


def _dispatches():
    t = _template()
    return [panel_dispatch(t, i, BINDINGS) for i in range(len(t.panels))]


# ── gateway doubles ──────────────────────────────────────────────────────────
class _User:
    id = "a400f096-d252-49cc-9336-5f47a5b9e4cd"
    authz_id = "alice@example.com"
    email = "alice@example.com"


class _Stranger(_User):
    authz_id = "mallory@example.com"


class _Req:
    headers = {"authorization": "Bearer t"}


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


GOOD_ENGINE_BODY = {
    "artifact_filename": f"fin-package-{SCOPE}.html", "artifact_sha256": SHA64,
    "artifact_bytes": 10, "algorithm_sha": "0" * 40,
}


@pytest.fixture()
def posts(monkeypatch):
    """Record every POST the gateway makes; answer with a valid engine body."""
    import iagent.gateway as gw

    calls: list[dict] = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append({"url": url, "json": json, "headers": headers})
            return _Resp(200, dict(GOOD_ENGINE_BODY))

    monkeypatch.setattr(gw.httpx, "AsyncClient", _Client)
    return calls


def _export(body_kwargs, user=None):
    import iagent.gateway as gw

    body = gw.ExportPackageRequest(**body_kwargs)
    try:
        return 200, asyncio.run(gw.export_package(body, _Req(), user or _User()))
    except HTTPException as exc:
        return exc.status_code, exc.detail


GOOD = {"template_id": "program_finance", "bindings": BINDINGS}


# ── ONE FUNCTION ─────────────────────────────────────────────────────────────
def test_the_seed_and_the_export_derive_one_set_of_params(posts):
    from iagent.gateway import _pre_resolved_from_seed_panel

    status, _ = _export(GOOD)
    assert status == 200
    assert len(posts) == 1
    panels = posts[0]["json"]["canvas"]["panels"]
    dispatches = _dispatches()
    assert len(panels) == len(dispatches) == 6
    for i, (verb, _subject, params) in enumerate(dispatches):
        seed_params = _pre_resolved_from_seed_panel(
            {"template_id": "program_finance", "panel": i, "bindings": BINDINGS})[1]
        assert params == seed_params, f"panel {i}: panel_dispatch and the seed differ"
        assert panels[i]["params"] == params, f"panel {i}: the POSTed canvas differs"
        assert panels[i]["verb"] == verb


def test_one_function_CONTROL_the_comparison_can_see_a_dropped_static_slot():
    """The comparison above must be able to fail: a panel with static slots, params minus one."""
    verb, _s, params = _dispatches()[3]
    assert len(params) > 1, "panel 3 declares static slots, so a drop is observable"
    dropped = dict(params)
    dropped.pop(next(k for k in dropped if k != "program_id"))
    assert dropped != params


# ── DERIVED RECIPIENT ────────────────────────────────────────────────────────
def test_the_recipient_is_derived_from_the_template_and_the_binding():
    assert recipient_scope_for(_template(), BINDINGS) == SCOPE


def test_the_recipient_refuses_without_a_package_or_a_binding():
    with pytest.raises(ValueError):
        recipient_scope_for(load_template("portfolio"), BINDINGS)
    with pytest.raises(ValueError):
        recipient_scope_for(_template(), {})


def test_AUDIENCES_equals_the_package_literal_args():
    literal = typing.get_args(Package.model_fields["audience"].annotation)
    assert tuple(fin_export.AUDIENCES) == tuple(literal)


def test_RECIPIENT_SCOPES_is_derived_not_listed():
    derived = {
        f"{a}.{p.program_id}": p.program_id
        for p in build_seed().programs for a in fin_export.AUDIENCES
    }
    assert fin_export.RECIPIENT_SCOPES == derived
    assert SCOPE in derived  # control: the derivation is non-empty and holds the notional scope


# ── GATEWAY GATES ────────────────────────────────────────────────────────────
def test_gate_1_answers_with_a_template_is_422_before_any_post(posts):
    status, _ = _export({**GOOD, "answers": [{"artifact_id": "x"}]})
    assert status == 422 and posts == []


def test_gate_2_unknown_template_is_400_before_any_post(posts):
    status, _ = _export({"template_id": "no_such_template", "bindings": BINDINGS})
    assert status == 400 and posts == []


def test_gate_3_a_template_without_a_package_is_422_before_any_post(posts):
    status, _ = _export({"template_id": "portfolio", "bindings": {}})
    assert status == 422 and posts == []


def test_gate_4_binding_gates_fire_before_any_post(posts):
    status, _ = _export({"template_id": "program_finance",
                         "bindings": {**BINDINGS, "no_such_slot": "x"}})
    assert status == 422 and posts == []
    status, _ = _export({"template_id": "program_finance", "bindings": {}})
    assert status == 409 and posts == []


def test_gate_5_a_disagreeing_scope_is_409_naming_the_derived_one(posts):
    status, detail = _export({**GOOD, "recipient_scope": "program_office.NP-OTHER"})
    assert status == 409 and posts == []
    assert detail == {"reason": "recipient_scope_disagrees_with_canvas_audience",
                      "derived": SCOPE}


def test_gate_6_a_non_reader_is_403_before_any_post(posts):
    status, _ = _export(GOOD, user=_Stranger())
    assert status == 403 and posts == []


def test_gates_7_and_8_CONTROL_a_valid_request_posts_once_and_is_shaped(posts):
    status, out = _export({**GOOD, "recipient_scope": SCOPE})
    assert status == 200
    assert len(posts) == 1 and posts[0]["url"].endswith("/package_export")
    assert posts[0]["json"]["recipient_scope"] == SCOPE
    canvas = posts[0]["json"]["canvas"]
    assert canvas["template_id"] == "program_finance"
    assert canvas["template_hash"] == template_ref(_template())
    assert out["status"] == "exists" and out["artifact_sha256"] == SHA64
    assert out["artifact_uri"] == f"/export/package/artifact/fin-package-{SCOPE}.html"


def test_both_export_routes_shape_through_the_ONE_helper():
    """"exists" is decided in one place, so the cost path and the finance-template path cannot
    drift into reporting it under different rules. Callers are DERIVED from the AST, not named
    by what they happen to be called today, and the rule's own text is counted, so a route that
    grows a private copy reds here even while still calling the helper somewhere."""
    import ast

    src = (ROOT / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
    callers = {
        fn.name for fn in ast.walk(ast.parse(src))
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_shape_export_package_response" for n in ast.walk(fn))
    }
    assert callers == {"export_package", "_export_package_from_template"}, sorted(callers)
    assert src.count("engine returned no verifiable artifact hash") == 1
    assert src.count("_SHA256_LOCATOR_RE.match(sha)") == 1


def test_the_cost_path_without_a_template_id_still_demands_a_recipient(posts):
    status, detail = _export({})
    assert status == 409 and detail["reason"] == "recipient_required" and posts == []


# ── ENGINE REFUSALS ──────────────────────────────────────────────────────────
@pytest.fixture()
def engine(monkeypatch):
    from fastapi.testclient import TestClient

    from agent_fleet.finance_agent import main as fmain

    built: list[dict] = []

    class _Builder:
        @staticmethod
        def build(**kw):
            built.append(kw)
            return {"manifest": {"panels": kw["panels"], "as_of": "2026-01-01",
                                 "recipient_scope": kw["recipient_scope"],
                                 "algorithm_sha": kw["sha"],
                                 "template_id": kw["template_id"],
                                 "template_hash": kw["template_hash"]},
                    "html_sha256": SHA64, "html_bytes": 1, "duckdb_sha256": SHA64}

    monkeypatch.setattr(fmain, "_repo_root", lambda: ROOT)
    monkeypatch.setitem(sys.modules, "build_fin_package", _Builder)
    monkeypatch.setattr("build_cost_package.algorithm_sha", lambda: "0" * 40)
    with TestClient(fmain.app) as client:
        yield client, built


def _canvas(mutate=None):
    panels = [{"panel": i, "verb": v, "params": dict(p)}
              for i, (v, _s, p) in enumerate(_dispatches())]
    if mutate:
        mutate(panels)
    return {"template_id": "program_finance", "template_hash": "h", "panels": panels}


def test_engine_refuses_an_unknown_scope_403(engine):
    client, built = engine
    r = client.post("/package_export", json={"recipient_scope": "program_office.NOPE",
                                              "canvas": _canvas()})
    assert r.status_code == 403 and built == []


def test_engine_refuses_an_empty_canvas_422(engine):
    client, built = engine
    r = client.post("/package_export", json={"recipient_scope": SCOPE,
                                              "canvas": {**_canvas(), "panels": []}})
    assert r.status_code == 422 and built == []


def test_engine_refuses_an_unknown_verb_422(engine):
    client, built = engine
    c = _canvas(lambda ps: ps[0].update(verb="mesh:finNoSuchVerb"))
    r = client.post("/package_export", json={"recipient_scope": SCOPE, "canvas": c})
    assert r.status_code == 422 and built == []


def test_engine_refuses_a_foreign_program_403_and_drops_nothing(engine):
    client, built = engine
    c = _canvas(lambda ps: ps[2]["params"].update(program_id="NP-OTHER"))
    r = client.post("/package_export", json={"recipient_scope": SCOPE, "canvas": c})
    assert r.status_code == 403 and built == []


def test_engine_CONTROL_a_valid_canvas_passes_every_refusal_and_reaches_the_builder(engine):
    client, built = engine
    r = client.post("/package_export", json={"recipient_scope": SCOPE, "canvas": _canvas()})
    assert r.status_code == 200, r.text
    assert len(built) == 1 and len(built[0]["panels"]) == 6


@pytest.mark.parametrize("raised, fragment", [
    (ImportError("No module named 'duckdb'", name="duckdb"), "dependency duckdb is not installed"),
    (SystemExit("pyodide runtime not found under .pyodide-cache"), "builder refused: pyodide"),
])
def test_engine_names_a_builder_that_cannot_run_503(engine, monkeypatch, raised, fragment):
    """An image without duckdb, or without the pinned runtime, answers a NAMED 503 -- not the
    bare 500 an escaped ImportError / SystemExit would give. The CONTROL is
    test_engine_CONTROL_a_valid_canvas_passes_every_refusal_and_reaches_the_builder, which runs
    the same fixture with a builder that succeeds."""
    client, built = engine

    def _raise(**kw):
        built.append(kw)
        raise raised

    monkeypatch.setattr(sys.modules["build_fin_package"], "build", staticmethod(_raise))
    r = client.post("/package_export", json={"recipient_scope": SCOPE, "canvas": _canvas()})
    assert len(built) == 1, "the builder was never reached -- this arm refused somewhere earlier"
    assert r.status_code == 503, r.text
    assert fragment in r.json()["detail"], r.json()["detail"]


def test_each_panels_artifact_id_is_the_one_measure_serves(engine):
    client, built = engine
    r = client.post("/package_export", json={"recipient_scope": SCOPE, "canvas": _canvas()})
    assert r.status_code == 200, r.text
    from agent_fleet.finance_agent import main as fmain

    assert len(built[0]["panels"]) == 6
    for p in built[0]["panels"]:
        m = client.post(f"/measure/{p['fn']}", json={"params": p["params"]})
        assert m.status_code == 200, f"{p['fn']}: {m.text[:200]}"
        assert m.json()["artifact_id"] == p["artifact_id"], p["fn"]
    assert fmain.VERB_TO_FN[built[0]["panels"][0]["verb"]] == built[0]["panels"][0]["fn"]


# ── DISJOINT FILENAME SETS ───────────────────────────────────────────────────
def test_cost_and_finance_filename_sets_are_disjoint_and_nonempty():
    from agent_fleet.cost_agent import seed as cost_seed

    cost = {n for s in cost_seed.RECIPIENT_SCOPES for n in cost_seed.artifact_filenames(s)}
    fin = {n for s in fin_export.RECIPIENT_SCOPES for n in fin_export.artifact_filenames(s)}
    assert cost and fin
    assert cost.isdisjoint(fin)
    # control: each side claims its own and refuses the other's
    f = next(iter(fin))
    c = next(iter(cost))
    assert fin_export.scope_of_artifact(f) == SCOPE and cost_seed.scope_of_artifact(f) is None
    assert cost_seed.scope_of_artifact(c) is not None and fin_export.scope_of_artifact(c) is None


# ── PAGE LOGIC IN CPYTHON ────────────────────────────────────────────────────
def _served_panels():
    from agent_fleet.finance_agent import main as fmain

    out = []
    for i, (verb, _s, params) in enumerate(_dispatches()):
        fn = fmain.VERB_TO_FN[verb]
        env = fmain._measure_envelope(fn, dict(params))
        out.append({"panel": i, "verb": verb, "fn": fn, "params": dict(params),
                    "artifact_id": env["artifact_id"], "rows": env["rows"]})
    return out


_FLAT_RUNNER = """
import json, sys
sys.path.insert(0, sys.argv[1])
import page
assert page.__file__.startswith(sys.argv[1]), page.__file__
payload = json.loads(sys.stdin.read())
print(json.dumps(page.verify(payload["state"], payload["panels"]), default=str))
"""


def _verify_flat(tmp_path, state_dict, panels):
    import build_fin_package as b

    flat = tmp_path / "flat"
    for rel, text in b._embedded_sources().items():
        dest = flat / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-c", _FLAT_RUNNER, str(flat)],
        input=json.dumps({"state": state_dict, "panels": panels}, default=str),
        capture_output=True, text=True, cwd=str(tmp_path), timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    return json.loads(proc.stdout)


def _narrowed_dict():
    return state_codec.state_to_dict(state_codec.narrow(build_seed(), "NP-MERIDIAN"))


def test_page_verify_reproduces_all_six_panels_from_the_flat_sources(tmp_path):
    results = _verify_flat(tmp_path, _narrowed_dict(), json.loads(json.dumps(_served_panels(), default=str)))
    assert len(results) == 6
    assert all(r["reproduced"] for r in results), results


def test_page_verify_reports_exactly_the_perturbed_panel(tmp_path):
    panels = json.loads(json.dumps(_served_panels(), default=str))
    rows = panels[2]["rows"]
    # perturb the first numeric leaf of panel 2's served rows
    def bump(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    o[k] = v + 12345
                    return True
                if bump(v):
                    return True
        elif isinstance(o, list):
            for v in o:
                if bump(v):
                    return True
        return False
    assert bump(rows), "panel 2 holds a numeric value to perturb"
    results = _verify_flat(tmp_path, _narrowed_dict(), panels)
    assert [r["panel"] for r in results if not r["reproduced"]] == [2]


def test_a_narrowed_state_round_trips_to_identical_rows_for_all_six_panels():
    from agent_fleet.finance_agent import measures
    from agent_fleet.finance_agent import main as fmain

    narrowed = state_codec.narrow(build_seed(), "NP-MERIDIAN")
    rebuilt = state_codec.state_from_dict(json.loads(json.dumps(
        state_codec.state_to_dict(narrowed), default=str)))
    for verb, _s, params in _dispatches():
        fn = fmain.VERB_TO_FN[verb]
        a = getattr(measures, fn)(fmain.STATE, **params)
        b = getattr(measures, fn)(rebuilt, **params)
        assert fin_export._canonical(a) == fin_export._canonical(b), fn


def test_state_codec_refuses_an_unmapped_field_type_by_name():
    with pytest.raises(ValueError, match="programs"):
        state_codec._collection_item_type(int, "programs")
    with pytest.raises(ValueError, match="obs"):
        state_codec._collection_item_type(list[int], "obs")
    # control: a real `list[<dataclass>]` annotation maps
    hints = typing.get_type_hints(state_codec.FinanceState)
    assert dataclasses.is_dataclass(state_codec._collection_item_type(hints["programs"], "programs"))


def test_the_duckdb_ddl_refuses_an_unmapped_type_by_name():
    import build_fin_package as b

    with pytest.raises(ValueError, match="weird"):
        b._sql_type(complex, "_Odd", "weird")
    assert b._sql_type(str, "_Odd", "ok") == "VARCHAR"  # control


# ── REAL BUILD ───────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def real_build(tmp_path_factory):
    pytest.importorskip("duckdb", reason="duckdb is not installed in this venv: the program-finance canvas package export is NOT verified (root agent-fleet extra declares it; uv sync --extra agent-fleet)")
    from fastapi.testclient import TestClient

    from agent_fleet.finance_agent import main as fmain

    if not (ROOT / ".pyodide-cache").is_dir():
        pytest.skip("no .pyodide-cache in this checkout; the real build cannot run")

    dist = tmp_path_factory.mktemp("fin_dist")
    manifests: list[dict] = []
    real_audit = fin_export.audit_line

    def spy(manifest, **kw):
        manifests.append(manifest)
        return real_audit(manifest, **kw)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fmain, "_dist_dir", lambda root: dist)
        mp.setattr(fin_export, "audit_line", spy)
        canvas = {
            "template_id": "program_finance", "template_hash": template_ref(_template()),
            "panels": [{"panel": i, "verb": v, "params": dict(p)}
                       for i, (v, _s, p) in enumerate(_dispatches())],
        }
        with TestClient(fmain.app) as client:
            r = client.post("/package_export", json={"recipient_scope": SCOPE, "canvas": canvas})
    assert r.status_code == 200, r.text[:400]
    html_name, duckdb_name = fin_export.artifact_filenames(SCOPE)
    return {"resp": r.json(), "manifest": manifests[0], "html": dist / html_name,
            "duckdb": dist / duckdb_name, "template_hash": template_ref(_template())}


def test_the_real_build_html_parses_has_no_cdn_and_names_six_panels(real_build):
    from build_cost_package import check_javascript

    html_bytes = real_build["html"].read_bytes()
    html = html_bytes.decode("utf-8")
    assert check_javascript(html) == []
    assert "cdn.jsdelivr.net" not in html
    assert len(real_build["manifest"]["panels"]) == 6
    assert real_build["manifest"]["template_hash"] == real_build["template_hash"] != "testhash"
    m = re.search(r'<script id="package-data" type="application/json">(.*?)</script>', html, re.S)
    assert m and len(json.loads(m.group(1))["panels"]) == 6
    resp = real_build["resp"]
    assert resp["artifact_sha256"] == "sha256:" + hashlib.sha256(html_bytes).hexdigest()
    print("REAL_BUILD_HTML_SHA256", resp["artifact_sha256"])
    print("REAL_BUILD_DUCKDB_SHA256", resp["duckdb_sha256"])


def test_the_real_build_duckdb_hash_is_in_the_manifest_and_the_tables_agree(real_build):
    pytest.importorskip("duckdb", reason="duckdb is not installed in this venv: the program-finance canvas package export is NOT verified (root agent-fleet extra declares it; uv sync --extra agent-fleet)")
    import build_fin_package as b

    path = real_build["duckdb"]
    assert real_build["manifest"]["duckdb_sha256"] == (
        "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest())
    panels = _served_panels()
    assert b.tables_agree(_narrowed_dict(), panels, path) == []


def test_the_build_refuses_when_the_duckdb_disagrees_with_the_state(tmp_path):
    """CONTROL for the arm above: `tables_agree` can say no."""
    pytest.importorskip("duckdb", reason="duckdb is not installed in this venv: the program-finance canvas package export is NOT verified (root agent-fleet extra declares it; uv sync --extra agent-fleet)")
    import build_fin_package as b

    path = tmp_path / "x.duckdb"
    panels = _served_panels()
    state_dict = _narrowed_dict()
    b.build_duckdb(path, state_dict, panels)
    assert b.tables_agree(state_dict, panels, path) == []
    tampered = json.loads(json.dumps(state_dict, default=str))
    coll = next(k for k, v in tampered.items() if isinstance(v, list) and v)
    tampered[coll].pop()
    assert b.tables_agree(tampered, panels, path) != []


def test_the_html_half_alone_parses_without_duckdb():
    """Runs with or without duckdb: the page the builder produces passes the JS check."""
    import build_fin_package as b
    from build_cost_package import check_javascript

    if not (ROOT / ".pyodide-cache").is_dir():
        pytest.skip("no .pyodide-cache in this checkout")
    html = b.build_html(SCOPE, "NP-MERIDIAN", ROOT / ".pyodide-cache", _narrowed_dict(),
                        _served_panels(),
                        template_id="program_finance", as_of="2026-01-01", sha="0" * 40)
    assert check_javascript(html) == []
    assert "cdn.jsdelivr.net" not in html
