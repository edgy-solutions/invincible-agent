"""R-001 at the TEMPLATE: the program_finance board shows every EAC method on one panel.

`test_eac_comparison.py` seals the VERB that makes the ruling keepable. Nothing sealed that the
board actually DISPATCHES it: `policy/canvases/program_finance.yaml` carried
`finEacCalculation` with `method: CPI` as a recorded placeholder, and swapping the comparison
verb in or back out changed no test. These two seals cover the board's side of the join.

The single-method verbs are DERIVED from signatures (a parameter annotated `EACMethod`), never
listed, so a second pinned-method verb added to the engine is refused here without an edit.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import yaml

from agent_fleet.finance_agent import measures
from agent_fleet.finance_agent.main import VERBS
from agent_fleet.finance_agent.measures import EAC_METHODS
from agent_fleet.finance_agent.seed import build_seed

_TEMPLATE = Path(__file__).resolve().parents[2] / "policy" / "canvases" / "program_finance.yaml"
_FN_FOR_VERB = {v["verb"]: v["fn"] for v in VERBS}


def _panels():
    return yaml.safe_load(_TEMPLATE.read_text(encoding="utf-8"))["panels"]


def _pins_one_method(fn_name: str) -> bool:
    params = inspect.signature(getattr(measures, fn_name)).parameters.values()
    return any(p.annotation in ("EACMethod", measures.EACMethod) for p in params)


def test_the_inputs_are_readable():
    """Positive control: the derivation must find the single-method verb that exists, or the
    refusal below passes over an empty set."""
    assert len(_panels()) == 6
    pinned = {fn for fn in _FN_FOR_VERB.values() if _pins_one_method(fn)}
    assert "fin_eac_calculation" in pinned, f"derivation found no single-method verb: {pinned}"
    assert "fin_eac_comparison" not in pinned


def test_no_panel_dispatches_a_verb_that_pins_one_method():
    """Pinning hides the divergence that is the finding (R-001). A panel whose verb takes one
    `EACMethod` is that pin, whatever value its `slots` give."""
    offenders = [
        (i, p["verb"]) for i, p in enumerate(_panels())
        if _pins_one_method(_FN_FOR_VERB[p["verb"]])
    ]
    assert not offenders, f"panel(s) pin one EAC method, against R-001: {offenders}"


def test_one_panel_answers_every_method_on_the_seed():
    """The refusal above is satisfied by a board with no EAC panel at all. This is the half
    that requires the board to still SHOW the estimate: some panel, dispatched with its declared
    slots, returns one row per `EAC_METHODS` member."""
    state = build_seed()
    program_id = state.programs[0].program_id
    answering = []
    for i, p in enumerate(_panels()):
        fn = getattr(measures, _FN_FOR_VERB[p["verb"]])
        try:
            rows = fn(state, program_id=program_id, **(p.get("slots") or {}))
        except TypeError:
            continue
        if isinstance(rows, list) and rows and all(isinstance(r, dict) for r in rows):
            if [r.get("method_label") for r in rows] == list(EAC_METHODS):
                answering.append((i, p["verb"]))
    assert len(answering) == 1, (
        f"expected exactly one panel answering all of {list(EAC_METHODS)}, got {answering}"
    )
