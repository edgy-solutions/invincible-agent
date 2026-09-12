"""The engine-extra split for safety seals — what still runs when `rdflib` is absent.

ADOPTED FROM `invincible-agent-22`'s shape, and this is the THIRD instance of one class in a day:
`rdflib` for ontology_service, `langgraph` for graph_host, now `rdflib` for safety_agent. Three
makes it doctrine rather than an incident, and the architect has ruled it into the playbook.

── THE SPLIT ───────────────────────────────────────────────────────────────────────────────
    ALWAYS RUNS    the claim that does not need the import — the file's CONTENT, read as text,
                   and anything answerable from YAML or the AST. **A coverage claim must not
                   depend on an engine's optional extra.**
    SKIPS, NAMED   the half that PARSES — resolution through `matrix.py`, which imports rdflib
                   inside `_load()`. The reason names the COMMAND and states what remains
                   verified.

── WHY NOT JUST GATE THE FILE ──────────────────────────────────────────────────────────────
Because **a seal that skips verifies nothing**, and gating the whole module takes the coverage
claim dark wherever the dependency is legitimately absent — CI included. `rdflib` lives in the
`agent-fleet` EXTRA by design: the root-dependency seal deliberately excludes `agent_fleet/` and
each engine declares its own. So this is not a missing declaration to fix; it is a seal that must
survive the dependency being correctly absent.

And "not importable" is a diagnosis nobody can act on. A skip whose reason names neither the
command nor what is still covered is indistinguishable from a seal that was never written.
"""
from __future__ import annotations

import pytest

#: Names the command AND what survives, so a reader of a skipped line knows the size of the hole.
_REASON = (
    "rdflib is in the `agent-fleet` EXTRA, not root deps — run `uv sync --extra agent-fleet`. "
    "SKIPPED HERE: resolution through matrix.py (a cell -> risk level -> audience). "
    "STILL VERIFIED without it: that safety_risk_matrix.ttl DECLARES all twenty MIL-STD-882E "
    "Table III cells with the standard's values, read as text; that every declared kind, audience "
    "and output class is present; and every assertion over YAML or the AST."
)

def _rdflib_present() -> bool:
    try:
        import rdflib  # noqa: F401
    except Exception:  # noqa: BLE001 — any import failure means the parsing half cannot run
        return False
    return True


requires_rdflib = pytest.mark.skipif(not _rdflib_present(), reason=_REASON)
