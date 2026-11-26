"""The lineage engine walks from the resolved asset, filtered by platform.

Seals the start-of-walk decision (`lineage_start`) on both resolution paths
(supervisor-supplied and legacy raw resolver JSON) and the wiring of
`run_trace_lineage` in the analyst's main.py. Names are made up.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_ANALYST = _REPO / "agent_fleet" / "restate_analyst" / "main.py"
_START = _REPO / "agent_fleet" / "restate_analyst" / "lineage_start.py"

_spec = importlib.util.spec_from_file_location("lineage_start_under_test", _START)
ls = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ls
_spec.loader.exec_module(ls)

_URN = "urn:li:dashboard:(tool_a,dash-1)"
_SCOPE_A = {"platforms": ["platform_a"], "platform_mentioned": True, "unrecognized": []}
_SCOPE_NONE = {"platforms": [], "platform_mentioned": False, "unrecognized": []}
_SCOPE_TYPO = {"platforms": [], "platform_mentioned": True, "unrecognized": ["platfrm"]}


def _load_supplied_resolution():
    tree = ast.parse(_ANALYST.read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_supplied_resolution"]
    nodes += [n for n in tree.body if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "SUPERVISOR_RESOLUTION_OUTCOMES" for t in n.targets)]
    assert len(nodes) == 2
    ns: dict = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<analyst>", "exec"), ns)
    return ns["_supplied_resolution"]


def test_supervisor_path_walks_from_the_supplied_urn():
    request = {"resolved_subject_uri": "class:Dashboard", "resolved_instance_id": _URN,
               "resolved_instance_label": "Made Up Dashboard"}
    ctx = _load_supplied_resolution()(request)
    inst, label = ls.supplied_instance(ctx, request.get("resolved_instance_label") or "")
    assert (inst, label) == (_URN, "Made Up Dashboard")
    assert ls.start_of(inst) == "urn"
    body = ls.walk_body(inst, _SCOPE_A, ["d1"], "a@example.test")
    assert body["subject_urn"] == _URN and body["platforms"] == ["platform_a"]
    assert body["entitled_domains"] == ["d1"] and body["caller_email"] == "a@example.test"


def test_legacy_path_walks_from_the_provenance_urn():
    raw = {"resolved_uri": "class:Dashboard",
           "provenance": {"instance_id": _URN, "instance_label": "X"}}
    inst, label = ls.supplied_instance(raw)
    assert (inst, label) == (_URN, "X")
    assert ls.start_of(inst) == "urn"
    body = ls.walk_body(inst, _SCOPE_A, [], "")
    assert body["subject_urn"] == _URN and body["platforms"] == ["platform_a"]


def test_top_level_wins_and_threaded_label_wins():
    ctx = {"instance_id": " urn:top ", "provenance": {"instance_id": "urn:prov", "instance_label": "P"}}
    assert ls.supplied_instance(ctx, "T") == ("urn:top", "T")
    assert ls.supplied_instance(ctx) == ("urn:top", "P")


@pytest.mark.parametrize("ctx", [{}, {"provenance": "x"}, {"provenance": None}, {"provenance": []}])
def test_empty_and_malformed_provenance_do_not_crash(ctx):
    assert ls.supplied_instance(ctx) == ("", "")
    assert ls.start_of("") == "none"


def test_non_urn_is_a_name():
    assert ls.start_of("some asset") == "name"


def test_unrecognised_platform_is_no_walk_and_no_platform_is_full_walk():
    assert ls.walk_body(_URN, _SCOPE_TYPO, [], "") is None
    body = ls.walk_body(_URN, _SCOPE_NONE, [], "")
    assert body is not None and body["platforms"] == []


# -- wiring census ---------------------------------------------------------------------

def _fn(tree):
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_trace_lineage")


def _called(fn, name):
    return [n for n in ast.walk(fn) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == name]


def _census(source: str) -> list[str]:
    """Return the list of wiring defects in `run_trace_lineage` of `source`."""
    bad = []
    fn = _fn(ast.parse(source))
    for name in ("supplied_instance", "start_of", "walk_body"):
        if not _called(fn, name):
            bad.append(f"{name} not called")
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get"
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "semantic_ctx"
                and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "instance_id"):
            bad.append("semantic_ctx.get('instance_id') remains")
    bound = {t.id for a in ast.walk(fn) if isinstance(a, ast.Assign)
             and isinstance(a.value, ast.Call) and isinstance(a.value.func, ast.Name)
             and a.value.func.id == "walk_body" for t in a.targets if isinstance(t, ast.Name)}
    posts = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "post"
             and n.args and "lineage_by_platform" in ast.unparse(n.args[0])]
    if not posts:
        bad.append("no /lineage_by_platform POST")
    for p in posts:
        kw = next((k.value for k in p.keywords if k.arg == "json"), None)
        if not (isinstance(kw, ast.Name) and kw.id in bound):
            bad.append("POST json= is not the walk_body result")
    return bad


def test_wiring_run_trace_lineage_uses_the_start_functions():
    assert _census(_ANALYST.read_text(encoding="utf-8")) == []


_INLINE = '''
async def run_trace_lineage():
    raw_instance, label_hint = supplied_instance(semantic_ctx, "")
    start_of(raw_instance)
    body = walk_body("u", {}, [], "")
    _requests.post(f"{wrapper_url}/lineage_by_platform",
                   json={"subject_urn": "u", "platforms": []}, timeout=1)
'''


def test_control_the_census_fails_on_an_inline_body():
    assert _census(_INLINE) == ["POST json= is not the walk_body result"]
