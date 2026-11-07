"""The flow table reaches the card: #255's envelope, through the projector, as cortex reads it.

Chris, 2026-11-05: "Projector row accepted as proposed; Lane 1 adds it in 0.4.80." The row was
`"FLOW_DECOMPOSITION": ("rows", ("value_label", "render", "verdict"))`. Without it the projector
has no entry for the archetype, and cortex's card at 93d76e8 draws nothing.

The envelope here is the REAL engine route's answer over the EV fixture (the fixtures of
tests/finance/test_variance_decomposition_over_the_ev_fixture.py). The projector is the real
function, loaded without the agent's imports. So the join is measured, not restated:

  - `rows` arrive verbatim, root edge first.
  - `render` arrives whole: `unit` and `other_label` live only inside it.
  - `value_label` and `verdict` arrive as the engine sent them.
  - Every key the tuple names is one the engine sends, so no passthrough waits on a field that
    never comes.
  - `data_provenance` does not travel, as proposed. Cortex asked Chris on 11-06 whether it should;
    that ruling would change this arm and the tuple together.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_the_flow_table_reaches_the_card.py
"""
from __future__ import annotations

import pytest

pytest.importorskip("polars")

from tests.finance.test_variance_decomposition_over_the_ev_fixture import (  # noqa: E402,F401
    _clean_env, flow_rows, gate, members, post,
)
from tests.planning.test_planning_archetypes_are_projected import _fns  # noqa: E402

ARCH = "FLOW_DECOMPOSITION"


def _project(env):
    ns = _fns()
    raw = [{"persona": "PROGRAM_FINANCE_ANALYST", "expert_response": env}]
    return ns, ns["_project_planning_archetype"](ARCH, raw, "PROGRAM_FINANCE_ANALYST", None)


def _served(post):
    status, env = post()
    assert status == 200, env
    assert env["render"]["shape"] == ARCH          # the engine declares the shape this row serves
    return env


def test_THE_SERVED_FLOW_TABLE_PROJECTS_AS_THE_CARD_READS_IT(post):
    env = _served(post)
    _ns, got = _project(env)
    assert got is not None, "the projector has no FLOW_DECOMPOSITION row: the card draws nothing"
    assert got["archetype"] == ARCH
    assert got["rows"] == env["rows"] and got["rows"][0]["source"] is None   # verbatim, root first
    assert got["render"] == env["render"]                                    # whole, not picked
    assert "other_label" in got["render"]
    assert got["value_label"] == env["value_label"] and got["verdict"] == env["verdict"]


def test_EVERY_FIELD_THE_ROW_CARRIES_IS_ONE_THE_ENGINE_SENDS(post):
    env = _served(post)
    ns, _got = _project(env)
    payload_key, carried = ns["_PROJECTED_ARCHETYPES"][ARCH]
    assert payload_key == "rows"
    assert [k for k in (payload_key, *carried) if k not in env] == []


def test_THE_SYNTHETIC_BANNER_DOES_NOT_TRAVEL_AS_PROPOSED(post):
    env = _served(post)
    assert env["data_provenance"].startswith("SYNTHETIC")      # control: the engine does send it
    _ns, got = _project(env)
    assert got is not None and "data_provenance" not in got
