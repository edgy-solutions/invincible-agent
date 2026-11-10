"""Job 17: every route an Engine S `review_request` leaves by carries the MINTED `case_id`.

Engine S no longer builds `case_id` (its image cannot import `iagent_pure`), so the owner mints it
with `acceptance_request.with_minted_ids` before the card reaches a consumer or the render. This
file drives each route with the REAL engine body (which carries NO `case_id`) and asserts on the
outgoing card, then censuses the routes by FORM so a new one fails until it is added.

THE ROUTES (found by AST over `src/`: functions that call `review_request_of`/`with_minted_ids`
or name the keys `review_request` / `subtask_review_request`; `/orchestrate` and the
`/interview/stream` alias are one function, so one pair of routes covers both doors):
  direct    gateway `_stream_direct_outcome`            stamps, then opens, then renders
  ordinary  supervisor `_log_subtask_review_request_asset` stamps in place + materializes;
            gateway `_project_review_request` / `_open_acceptances_from_run` read it back
  not exits `review_request_of` (reader), walk_census `_review_request`/`walk` (reads the RENDERED
            turn, which never carries the block)
The no_match fallback in the supervisor answers from the generalist, never Engine S.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import iagent.gateway as gw  # noqa: E402
from iagent_pure import acceptance_request as ar  # noqa: E402

from ._engine_extra import requires_rdflib  # noqa: E402

_HAZARD = "HAZ-1003"
_REQUESTER = "requester@example.org"
WANT = ar.acceptance_workflow_id(_HAZARD, "medium")

#: (file, function). The census arm requires the search to find EXACTLY these.
STAMPERS = {("src/iagent/gateway.py", "_stream_direct_outcome"),
            ("src/iagent/defs/dynamic_supervisor.py", "_log_subtask_review_request_asset")}
READ_BACK = {("src/iagent/gateway.py", "_project_review_request"),
             ("src/iagent/gateway.py", "_open_acceptances_from_run")}
NOT_EXITS = {("src/iagent_pure/acceptance_request.py", "review_request_of"),
             ("src/iagent_pure/walk_census.py", "_review_request"),
             ("src/iagent_pure/walk_census.py", "walk")}
COVERED = STAMPERS | READ_BACK | NOT_EXITS
_KEYS = {"review_request", "subtask_review_request", "review_request_json"}


def _found(root: Path = _SRC):
    """(file, function) for every function that touches the card, by form; and the callers of
    `with_minted_ids`."""
    found, callers = set(), set()
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root.parent).as_posix()
        for fn in ast.walk(ast.parse(p.read_text("utf-8"))):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            b = fn.body
            doc = b[0].value if b and isinstance(b[0], ast.Expr) and isinstance(
                b[0].value, ast.Constant) else None
            for n in ast.walk(fn):
                if n is doc:
                    continue
                hit = isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in _KEYS
                if isinstance(n, ast.Call):
                    f = n.func
                    nm = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                    hit = hit or nm in ("review_request_of", "with_minted_ids")
                    if nm == "with_minted_ids":
                        callers.add((rel, fn.name))
                if hit:
                    found.add((rel, fn.name))
    return found, callers


# ------------------------------------------------------------------ the census
def test_the_routes_the_search_finds_are_exactly_the_routes_the_seal_covers():
    found, callers = _found()
    assert found == COVERED, (f"new: {sorted(found - COVERED)}; gone: {sorted(COVERED - found)}"
                              " -- add the route to this file and drive it")
    assert callers == STAMPERS, f"with_minted_ids callers moved: {sorted(callers ^ STAMPERS)}"


def test_census_control_a_planted_route_is_found(tmp_path):
    pkg = tmp_path / "src"
    pkg.mkdir()
    (pkg / "x.py").write_text(
        "def leak(resp):\n    return resp['review_request']\n", encoding="utf-8")
    found, _ = _found(pkg)
    assert found == {("src/x.py", "leak")}


# ------------------------------------------------------------------ the engine body
@pytest.fixture
def draft():
    from agent_fleet.safety_agent import matrix, measures
    matrix.reset_cache()
    try:
        out = measures.draft_risk_assessment(hazard_id=_HAZARD)
        assert out.get("review_request"), "FIXTURE VOID: the hazard drafted no card"
        assert "case_id" not in out["review_request"], "the double must send NO case_id"
        yield out
    finally:
        matrix.reset_cache()


class _Client:
    def __init__(self, payload=None):
        self.posts, self.payload = [], payload or {}

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None, **kw):
        self.posts.append({"url": url, "json": json})
        return self

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    @property
    def headers(self):
        return {}


# ------------------------------------------------------------------ route 1: direct
@requires_rdflib
@pytest.mark.asyncio
async def test_direct_route_the_card_leaves_with_the_minted_case_id(monkeypatch, draft):
    from tests.routing import test_the_direct_path_stream_actually_runs as dp
    fake = _Client(payload=dp._PAYLOAD)
    monkeypatch.setattr(gw.httpx, "AsyncClient", fake)
    bundle = dp._bundle()
    bundle["produced_for"]["authz_id"] = _REQUESTER
    async for _ in gw._stream_direct_outcome(
        outcome=dp._outcome(engine_response=draft), bundle=bundle, session_id="s",
        frontend_id="cortex-ui-desktop", user_persona="SAFETY_ENGINEER",
    ):
        pass
    assert draft["review_request"]["case_id"] == WANT  # the card the render reads
    assert bundle["resolved_intent"]["acceptance_dispatched"], "the open did not run"
    sent = [p for p in fake.posts if "/WorkflowRunner/" not in p["url"]]
    assert sent and WANT in json.dumps(sent[-1]["json"], default=str), "Engine F got no minted key"


# ------------------------------------------------------------------ route 2: ordinary
@requires_rdflib
@pytest.mark.asyncio
async def test_ordinary_route_the_card_leaves_with_the_minted_case_id(monkeypatch, draft):
    from iagent.defs import dynamic_supervisor as ds
    from .test_the_ordinary_path_opens_the_acceptance import (
        _Ctx, _as_graphql, _Restate, _bundle, _ROSTER)
    ctx = _Ctx()
    assert ds._log_subtask_review_request_asset(ctx, engine_response=draft, sub_query="q")
    assert draft["review_request"]["case_id"] == WANT  # the card Engine F is handed
    mat = _as_graphql(ctx.events[0])
    assert gw._project_review_request(mat)["case_id"] == WANT  # the card the gateway reads back

    async def _events(run_id):
        return [_ROSTER, mat]

    fake = _Restate()
    monkeypatch.setattr(gw, "_get_run_events", _events)
    monkeypatch.setattr(gw.httpx, "AsyncClient", fake)
    bundle = _bundle()
    assert await gw._open_acceptances_from_run("run-1", bundle) == []
    assert bundle["resolved_intent"]["acceptance_dispatched"], "the open did not run"
    assert len(fake.posts) == 1, fake.posts
