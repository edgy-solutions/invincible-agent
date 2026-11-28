"""The waterfall reaches the card: a walk envelope, through the projector, as cortex's Waterfall reads it.

The architect, via Chris, 2026-11-26: "Cortex reports #553 doesn't add the mapping that carries a
WATERFALL component's fields to the frontend. Add it as a follow-up PR." #553 admitted the
archetype and declared `mesh:Waterfall`. Without a `_PROJECTED_ARCHETYPES` row the projector has no
entry for it, `_project_planning_archetype` returns None, and the answer degrades to
KNOWLEDGE_DOCUMENT.

No engine declares the WATERFALL shape yet (fin's COMPUTED_SHAPES entry is what will). The
envelope here is therefore the REAL engine route's answer for a minus row over the EV fixture
(tests/finance/test_the_walk_has_a_start_and_an_end.py), which sends `rows` and `walk`, the two
fields cortex's contract requires. The projector is the real function, loaded without the agent's
imports.

  - The row exists, and a walk envelope projects as WATERFALL with `rows` verbatim and `walk` whole.
  - The passthrough is cortex-ui's `WATERFALL_ENVELOPE_FIELDS`, in its order. It is pinned here
    with its source, because CI cannot read the sibling repo.
  - A missing walk is not invented: the card gets no `walk` key and draws its `walk_missing`
    refusal.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_the_waterfall_reaches_the_card.py
"""
from __future__ import annotations

import pytest

pytest.importorskip("polars")

from tests.planning.test_planning_archetypes_are_projected import _fns  # noqa: E402
from tests.finance.test_the_walk_has_a_start_and_an_end import (  # noqa: E402,F401
    FN_CV, FN_SAMPLE, epost, ev_world,
)

ARCH = "WATERFALL"

#: cortex-ui src/archetypes/waterfall/contract.ts `WATERFALL_ENVELOPE_FIELDS`, read at cortex-ui
#: master e65409b on 2026-11-26. The contract's `rows` (required, an array) is the payload key.
CORTEX_WATERFALL_ENVELOPE_FIELDS = ("walk", "value_label", "render", "verdict", "data_provenance")


def _project(env):
    ns = _fns()
    raw = [{"persona": "PROGRAM_FINANCE_ANALYST", "expert_response": env}]
    return ns, ns["_project_planning_archetype"](ARCH, raw, "PROGRAM_FINANCE_ANALYST", None)


def _walk_env(epost):
    status, env = epost(FN_CV)
    assert status == 200, env
    assert set(env["walk"]) == {"start", "end"}            # control: the engine did send a walk
    assert isinstance(env["rows"], list) and env["rows"]   # control: and rows to draw
    return env


def test_THE_ROW_IS_CORTEXS_ENVELOPE():
    ns = _fns()
    assert ARCH in ns["_PROJECTED_ARCHETYPES"], "no WATERFALL row: the card degrades to KNOWLEDGE_DOCUMENT"
    payload_key, carried = ns["_PROJECTED_ARCHETYPES"][ARCH]
    assert payload_key == "rows"
    assert tuple(carried) == CORTEX_WATERFALL_ENVELOPE_FIELDS


def test_A_WALK_ENVELOPE_PROJECTS_AS_THE_WATERFALL_CARD(epost):
    env = _walk_env(epost)
    _ns, got = _project(env)
    assert got is not None, "the projector has no WATERFALL row: the card draws nothing"
    assert got["archetype"] == ARCH
    assert got["rows"] == env["rows"]                       # verbatim
    assert got["walk"] == env["walk"]                       # whole, not picked or rebuilt
    for k in CORTEX_WATERFALL_ENVELOPE_FIELDS:
        if k in env:
            assert got[k] == env[k], k


def test_A_MISSING_WALK_IS_NOT_INVENTED(epost):
    status, column = epost(FN_SAMPLE)
    assert status == 200 and "walk" not in column, column   # control: this envelope has no walk
    _ns, got = _project(column)
    assert got is not None and "walk" not in got            # cortex draws walk_missing, not a made-up walk
