"""ELICITATION requires its `disposition` and carries `status` -- the abstain lever survives the row.

cortex's `validateAsk` reads both; a card with neither is drawn as a question even when it was an
abstain (cortex packet 2026-10-08, "elicitation status is dropped by its own row").
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

from iagent_pure import slot_disposition as sd

_MAIN = Path(__file__).resolve().parents[1] / "agent_fleet" / "presentation_agent" / "main.py"


@pytest.fixture(scope="module")
def mod():
    class _Any(types.ModuleType):
        def __getattr__(self, name):  # noqa: D105
            return type(name, (), {"__getattr__": lambda s, n: None})()

    installed = []
    for name in ("baml_client", "baml_client.types", "baml_client.async_client"):
        if name not in sys.modules:
            sys.modules[name] = _Any(name)
            installed.append(name)
    try:
        spec = importlib.util.spec_from_file_location("presentation_probe_levers", _MAIN)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        yield m
    finally:
        for name in installed:
            sys.modules.pop(name, None)


def _disp(action):
    return sd.Disposition(
        action, slot="plan", reason="fuzzy" if action == sd.ASK else "empty",
        options=(sd.Option("p1", "Plan 1"),) if action == sd.ASK else (),
        option_source="resolution" if action == sd.ASK else "none",
        free_text_reason=None if action == sd.ASK else "no_referent",
    )


def _card(action):
    return sd.ask_card(_disp(action), verb_iri="mesh:v", sub_query="q", accepted={})


def _wrap(card):
    return [{"persona": "P", "sub_query": "q", "expert_response": card}]


def _project(mod, card):
    return mod._project_flat_archetype("ELICITATION", _wrap(card), "P")


def test_MIRROR_EQUALS_PRODUCER(mod):
    assert mod._ELICITATION_STATUS_BY_DISPOSITION == sd.STATUS_BY_DISPOSITION


@pytest.mark.parametrize("action", [sd.ASK, sd.ABSTAIN])
def test_BOTH_LEVERS_ARRIVE(mod, action):
    card = _card(action)
    out = _project(mod, card)
    assert out is not None
    assert out["disposition"] == card["disposition"] == action
    assert out["status"] == card["status"] == sd.STATUS_BY_DISPOSITION[action]


@pytest.mark.parametrize("action", [sd.ASK, sd.ABSTAIN])
def test_MISSING_DISPOSITION_IS_REFUSED(mod, action):
    card = _card(action)
    del card["disposition"]
    assert _project(mod, card) is None


@pytest.mark.parametrize("action", [sd.ASK, sd.ABSTAIN])
def test_CONTRADICTING_STATUS_IS_REFUSED(mod, action):
    card = _card(action)
    card["status"] = "slot_abstain" if action == sd.ASK else "slot_elicitation"
    assert _project(mod, card) is None


def test_UNKNOWN_DISPOSITION_IS_REFUSED(mod):
    card = _card(sd.ASK)
    card["disposition"] = "route"
    assert _project(mod, card) is None


def test_IN_AGENT_PRODUCERS_SATISFY_THE_ROW(mod):
    comps = [
        mod._render_refusal_menu({"outcome": "x", "reason": "r"}, ["a"], "s", "P")["components"][0],
        mod._render_abstain_menu({"message": "m"}, ["a"], "P")["components"][0],
    ]
    for c in comps:
        assert c["disposition"] in mod._ELICITATION_STATUS_BY_DISPOSITION
        assert c["status"] == mod._ELICITATION_STATUS_BY_DISPOSITION[c["disposition"]]
        # and the row itself accepts them
        assert mod._project_flat_archetype("ELICITATION", c, "P") is not None
