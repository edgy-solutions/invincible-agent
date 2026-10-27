"""The supervisor's /classify_predicate budget is a named interim, measured, not a literal.

Roll 207 (2026-10-24, sandbox revision 215): the docs walk and Q9 failed on `infra_error`. Engine O's
ClassifyPredicate answered with the expected verb in 33-55 s, but the supervisor had already given
up at a literal `timeout=30`. Architect ruling 2026-10-24: raise it to 60 s, as an interim on the same
terms as RESOLVE_SUBJECT_TIMEOUT_S.

These checks read the source text and never import the module (it pulls in Dagster).
"""
from __future__ import annotations

import ast
from pathlib import Path

_SUPERVISOR = Path(__file__).resolve().parents[2] / "src" / "iagent" / "defs" / "dynamic_supervisor.py"

#: The slowest ClassifyPredicate call, in seconds: Engine O log, walks 05:19-05:52Z on 2026-10-24.
MEASURED_P100_S = 55.196


def _tree() -> ast.Module:
    return ast.parse(_SUPERVISOR.read_text(encoding="utf-8"))


def _module_constant(name: str):
    for n in _tree().body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return ast.literal_eval(n.value)
    raise AssertionError(f"{name} is not a module-level constant in dynamic_supervisor.py")


def _classify_posts() -> list[ast.Call]:
    return [
        n for n in ast.walk(_tree())
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "post"
        and n.args and "/classify_predicate" in ast.unparse(n.args[0])
    ]


def test_the_classify_budget_covers_the_measured_p100():
    assert _module_constant("CLASSIFY_PREDICATE_TIMEOUT_S") >= MEASURED_P100_S


def test_the_classify_post_uses_the_named_budget():
    posts = _classify_posts()
    assert len(posts) == 1, f"expected one /classify_predicate POST, found {len(posts)}"
    kw = {k.arg: k.value for k in posts[0].keywords}
    assert isinstance(kw.get("timeout"), ast.Name), ast.unparse(kw.get("timeout")) if kw.get("timeout") else None
    assert kw["timeout"].id == "CLASSIFY_PREDICATE_TIMEOUT_S"
