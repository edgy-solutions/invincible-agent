"""Every Dagster trigger asset must POST a body its engine will accept.

WHY THIS EXISTS. Three of the six assets in ``agent_routers.py`` posted no body at all, and
each failed differently against a required field:

  * ``trigger_langgraph_support``  -> 422, ``SupportRequest.thread_id`` has no default
  * ``trigger_swarms_scraper``     -> 422, ``ScrapeRequest`` requires task_description AND dataset_id
  * ``trigger_restate_analyst``    -> 502 reading "Restate proxy call failed", because the proxy's
                                      ``await request.json()`` raised inside a bare ``except``

ADR-0046's Context filed the first one only. The class was three. The three assets that DID work
carried hand-written ``# Dummy payload`` comments, so the set read as if somebody had decided which
engines needed a body — when the three without were simply the three nobody ran. That misreading is
what this guard exists to prevent recurring.

NO IMPORTS OF EITHER SIDE. The engines are separate uv projects with their own locks; importing
``agent_fleet.swarms_scraper.main`` here would drag swarms, langgraph and restate into this suite.
Both sides are read as SOURCE via ``ast``, the same move the SDK's consumer-contract test makes
against dag-tools.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_ROUTERS = _REPO / "src" / "iagent" / "defs" / "agent_routers.py"

# asset name -> (engine main.py, the request model that types its endpoint)
#
# `/analyze` is the odd one: it takes a raw Starlette ``Request``, not ``AnalyzeRequest``, so
# FastAPI never validates it. AnalyzeRequest is the documented mirror ("Proxy request model —
# mirrors AgentTask") and Restate's AnalystService reads those fields off the payload, so it is
# the right contract to pin even though the framework will not enforce it.
_CONTRACTS = {
    "trigger_restate_analyst": ("restate_analyst", "AnalyzeRequest"),
    "trigger_langgraph_support": ("langgraph_support", "SupportRequest"),
    "trigger_swarms_scraper": ("swarms_scraper", "ScrapeRequest"),
}


def _trigger_posts() -> dict[str, ast.Call]:
    """Map every ``trigger_*`` asset to the ``requests.post`` call it makes."""
    tree = ast.parse(_ROUTERS.read_text(encoding="utf-8"))
    found: dict[str, ast.Call] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("trigger_"):
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "post"
                and isinstance(sub.func.value, ast.Name)
                and sub.func.value.id == "requests"
            ):
                found[node.name] = sub
    return found


def _json_keys(call: ast.Call) -> set[str] | None:
    """The literal keys of the call's ``json=`` dict, or None if it has no ``json=``."""
    for kw in call.keywords:
        if kw.arg == "json":
            if not isinstance(kw.value, ast.Dict):
                pytest.skip(f"json= is not a dict literal; cannot read keys statically")
            return {k.value for k in kw.value.keys if isinstance(k, ast.Constant)}
    return None


def _required_fields(engine: str, model: str) -> set[str]:
    """Fields on ``model`` that are annotated with NO default — the ones a caller must send."""
    src = (_REPO / "agent_fleet" / engine / "main.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ClassDef) and node.name == model:
            return {
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign)
                and stmt.value is None
                and isinstance(stmt.target, ast.Name)
            }
    raise AssertionError(f"{model} not found in agent_fleet/{engine}/main.py")


def test_every_trigger_asset_posts_a_body():
    """THE CLASS GUARD. A bodyless POST is the defect; it does not matter which engine."""
    posts = _trigger_posts()
    assert posts, "no trigger_* assets found — did agent_routers.py move?"
    bodyless = sorted(name for name, call in posts.items() if _json_keys(call) is None)
    assert not bodyless, (
        "these Dagster assets POST no body and will 4xx/5xx before reaching their engine: "
        + ", ".join(bodyless)
    )


@pytest.mark.parametrize("asset", sorted(_CONTRACTS))
def test_trigger_body_covers_every_required_field(asset: str):
    """THE FIELD GUARD. A body is not enough — it has to carry the fields with no defaults."""
    engine, model = _CONTRACTS[asset]
    sent = _json_keys(_trigger_posts()[asset])
    assert sent is not None, f"{asset} posts no body"
    missing = _required_fields(engine, model) - sent
    assert not missing, (
        f"{asset} omits {sorted(missing)}, which {model} "
        f"(agent_fleet/{engine}/main.py) requires with no default"
    )
