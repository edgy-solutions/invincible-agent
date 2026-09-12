"""engine-lg's runtime deps are the ENGINE's, not the repo's — so its seals say which half ran.

`langgraph` is declared in `agent_fleet/graph_host/pyproject.toml` and NOT in the repo root's
`[project.dependencies]`. That is deliberate and matches `rdflib`/`ontology_service`: the
repo-wide dependency seal (`tests/test_every_import_is_a_declared_dependency.py`) EXCLUDES
`agent_fleet/` precisely because each engine declares its own.

**The root venv having langgraph is an accident of how it was synced, not a guarantee.** It
lives in the `agent-fleet` EXTRA, so a bare `uv sync` produces a venv without it — which is the
`uvicorn` worked example from that seal: it survived on the base image's contents and broke
where nobody ran it. A peer lane hit exactly this and got a RuntimeError rather than a skip.

── WHY A SKIP HERE IS NOT ALLOWED TO HIDE THE COVERAGE CLAIM ───────────────────────────────
Gating the whole registration-coverage file on langgraph would take the seal DARK in every
environment that lacks it — including CI — and a seal that skips silently verifies nothing.

So the file is split by what each half actually needs:

    ALWAYS RUNS   every ratified row produces a correct registration PAYLOAD. Pure: the SDK
                  and yaml, no graph import, no compile. This is the coverage claim and it
                  must not depend on an engine's optional extra.
    SKIPS, NAMED  the host BOOTS, compiles each graph and POSTs the payloads. Needs the
                  engine's deps, and the skip reason names the command that supplies them.

A skip that says "not importable" tells the reader nothing they can act on. This one says how
to make it run.
"""

from __future__ import annotations

import importlib.util

import pytest

_HAVE_LANGGRAPH = importlib.util.find_spec("langgraph") is not None

#: The command, not just the diagnosis. `langgraph` lives in the repo's `agent-fleet` extra and
#: in graph_host's own pyproject, so either of these supplies it.
_SUPPLY = (
    "run `uv sync --extra agent-fleet` in this worktree, or use engine-lg's own environment "
    "(`cd agent_fleet/graph_host && uv sync`)"
)

needs_langgraph = pytest.mark.skipif(
    not _HAVE_LANGGRAPH,
    reason=(
        "engine-lg's graphs import langgraph, which is the ENGINE's declared dependency and "
        f"not the repo root's — {_SUPPLY}. A SKIP HERE IS NOT A PASS: the registration PAYLOAD "
        "assertions in this directory still ran and still cover every ratified row; what is "
        "unverified without langgraph is that the host boots, compiles them and POSTs."
    ),
)
