"""The subtask result carries its disposition: route | ask | abstain | fallback | infra_error.

`route_status` says whether a verb MATCHED; an ask card is a matched route that never
dispatched, so a scorer reading `route_status` alone cannot tell an ask from an answer.
`disposition` is the second key that can.

Run: uv run pytest tests/routing/test_the_subtask_result_carries_its_disposition.py -q
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.iagent.defs import dynamic_supervisor as ds  # noqa: E402
from iagent_pure.slot_disposition import Disposition  # noqa: E402

_SRC = _REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py"


# -- 1. census by AST ---------------------------------------------------------------------

def _returns_of(fn: ast.AST):
    """Every `return` of `fn`, skipping nested function definitions."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Return):
            yield node
        stack.extend(ast.iter_child_nodes(node))


def _sites_without_disposition(source: str, fn_name: str):
    tree = ast.parse(source)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == fn_name
    )
    rets = list(_returns_of(fn))
    bad = []
    for r in rets:
        keys = (
            {k.value for k in r.value.keys if isinstance(k, ast.Constant)}
            if isinstance(r.value, ast.Dict) else set()
        )
        if "disposition" not in keys:
            bad.append(r.lineno)
    return len(rets), bad


def test_the_checker_reports_a_site_that_lacks_the_key():
    src = (
        "def f(x):\n"
        "    if x:\n"
        "        return {'route_status': 'a', 'disposition': 'route'}\n"
        "    def inner():\n"
        "        return 1\n"
        "    return {'route_status': 'b'}\n"
    )
    n, bad = _sites_without_disposition(src, "f")
    assert (n, bad) == (2, [6])


def test_every_return_of_execute_subtask_carries_a_disposition():
    n, bad = _sites_without_disposition(_SRC.read_text(encoding="utf-8"), "execute_subtask")
    assert n >= 9, f"census walked only {n} returns"
    assert not bad, f"{n} returns walked; no `disposition` key at lines {bad}"


# -- doubles ------------------------------------------------------------------------------

class _Log:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _Ctx:
    run_id = "run-1"
    log = _Log()

    def get_mapping_key(self):
        return "task_0"

    def log_event(self, ev):
        pass

    def add_output_metadata(self, md):
        pass


class _Cfg:
    user_query = "how many on lot 4"
    user_persona = "PORTFOLIO_LEAD"
    user_email = ""
    user_id = "u"
    trace_id = "t"
    session_id = "s"
    thread_id = "th"
    entitled_domains = ["MAINTENANCE"]
    entity_refs = None
    pre_resolved = None
    predicate_fallback_score_threshold = 0.5
    spoken_slot = ""
    spoken_answer = ""
    bound_slots = None

    def __init__(self, slots=None):
        self.slots = slots


_TASK = {"sub_query": "how many on lot 4"}
_LOT = {"name": "lot", "type": "integer", "required": True, "kind": "spoken-mandatory"}


def _pred(score=0.9):
    return {
        "verb_iri": "mesh:aVerb", "score": score, "owner_persona": "ANALYST",
        "endpoint": "http://engine.invalid/measure/x", "domains": ["MAINTENANCE"],
        "slots": json.dumps([_LOT]),
    }


class _Resp:
    status_code = 200
    text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return {"components": [{"rows": []}], "status": "ok"}


@pytest.fixture
def drive(monkeypatch):
    def _run(*, slots=None, score=0.9):
        monkeypatch.setattr(
            ds, "_classify_route",
            lambda *a, **k: (ds._ROUTING_MATCHED, _pred(score), {"subject_uri": "mesh:Lot"}),
        )
        monkeypatch.setattr(ds, "_log_subtask_route_assets", lambda *a, **k: None)
        monkeypatch.setattr(ds, "_make_enumerator", lambda *a, **k: (lambda *x, **y: None))
        monkeypatch.setattr(ds, "_raise_if_identity_failed", lambda *a, **k: None)
        monkeypatch.setattr(
            ds, "_fill_slots_from_query",
            lambda *a, **k: SimpleNamespace(slots={}, resolution={}, fill_slots=""),
        )
        monkeypatch.setattr(
            ds, "_call_engine_a_fallback",
            lambda *a, **k: {"route_status": "no_match", "expert_response": {}},
        )
        monkeypatch.setattr(ds.requests, "post", lambda *a, **k: _Resp())
        return ds.execute_subtask.compute_fn.decorated_fn(_Ctx(), _Cfg(slots), dict(_TASK))
    return _run


# -- 2-5. behaviour -----------------------------------------------------------------------

def test_an_ask_is_matched_and_its_disposition_is_ask(drive):
    out = drive(slots=None)
    assert out["route_status"] == "matched"
    assert out["disposition"] == "ask"


def test_a_supplied_slot_routes(drive):
    out = drive(slots={"lot": "4"})
    assert out["disposition"] == "route"


def test_a_low_confidence_match_falls_back(drive):
    out = drive(score=0.1)
    assert out["disposition"] == "fallback"


def test_execute_subtask_decides_through_the_module_level_name(drive, monkeypatch):
    monkeypatch.setattr(
        ds, "decide_subtask_disposition",
        lambda *a, **k: Disposition(action="abstain", reason="forced"),
    )
    out = drive(slots={"lot": "4"})
    assert out["disposition"] == "abstain"
