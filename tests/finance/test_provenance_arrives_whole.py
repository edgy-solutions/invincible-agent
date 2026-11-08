"""data_provenance arrives whole on the card: every fin verb drawn as a MULTI_SERIES, through the projector.

The architect, via Chris, 2026-11-08: the data_provenance seal flips. It "arrives whole: dataset
URN, as-of, ticket id". Before 0.4.82 the projector named five envelope fields for MULTI_SERIES
and `data_provenance` was not one of them, so the engine sent it and no card received it. That is
the drop agent_fleet/presentation_agent/main.py's MULTI_SERIES comment describes three times over.

Two halves, measured separately because they belong to different lanes:

  - THE HOP (Lane 1's, green). Every fin verb bound to MULTI_SERIES answers through its real
    `/measure/<fn>` route, and the real projector function carries `data_provenance` verbatim.
    The control removes it from the tuple and watches it drop.
  - THE CONTENT (fin's, strict xfail). An asset answer's string is the operator's banner and
    " Source: <urn>" (asset_inputs.provenance / dataset_provenance). It names the dataset URN.
    It carries no as-of and no ticket id. When fin's producer adds them, the xfail turns XPASS
    and fails, and this marker is deleted in that PR.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_provenance_arrives_whole.py
"""
from __future__ import annotations

import re

import pytest

from tests.finance.test_the_wire_carries_what_the_engine_declares import _envelope, _fin_bindings
from tests.planning.test_planning_archetypes_are_projected import _fns

ARCH = "MULTI_SERIES"
FIELD = "data_provenance"
URN = "urn:li:dataset:(urn:li:dataPlatform:file,any_asset,TEST)"


@pytest.fixture(autouse=True)
def _member(monkeypatch):
    from agent_fleet.finance_agent import main as fmain
    monkeypatch.setattr(fmain, "can_view_program", lambda program, caller_id, **kw: True)


def _bound() -> list[str]:
    return sorted(fn for fn, arch in _fin_bindings().items() if arch == ARCH)


def _project(ns, env):
    raw = [{"persona": "PROGRAM_FINANCE_ANALYST", "expert_response": env}]
    return ns["_project_planning_archetype"](ARCH, raw, "PROGRAM_FINANCE_ANALYST", None)


def test_the_population_is_inhabited():
    assert len(_bound()) >= 2, f"derived {_bound()} -- the binding derivation is stale"


@pytest.mark.parametrize("fn", _bound())
def test_THE_PROVENANCE_REACHES_THE_CARD_VERBATIM(fn):
    env = _envelope(fn)
    assert isinstance(env.get(FIELD), str) and env[FIELD], f"{fn} sent no {FIELD} (control)"
    got = _project(_fns(), env)
    assert got is not None and got["archetype"] == ARCH
    assert got[FIELD] == env[FIELD]


def test_WITHOUT_THE_TUPLE_ENTRY_IT_DROPS():
    """The control: the same envelope through a projector whose tuple lacks the field."""
    fn = _bound()[0]
    env = _envelope(fn)
    ns = _fns()
    key, carried = ns["_PROJECTED_ARCHETYPES"][ARCH]
    assert FIELD in carried
    ns["_PROJECTED_ARCHETYPES"] = {**ns["_PROJECTED_ARCHETYPES"],
                                   ARCH: (key, tuple(f for f in carried if f != FIELD))}
    got = _project(ns, env)
    assert got is not None and FIELD not in got


def _asset_strings(monkeypatch) -> dict[str, str]:
    from agent_fleet.finance_agent import asset_inputs
    monkeypatch.setenv(asset_inputs.BANNER_ENV, "SYNTHETIC TEST ASSET.")
    return {"provenance": asset_inputs.provenance(URN),
            "dataset_provenance": asset_inputs.dataset_provenance("SYNTHETIC TEST ASSET.", URN)}


def test_AN_ASSET_ANSWER_NAMES_ITS_DATASET_URN(monkeypatch):
    for name, s in _asset_strings(monkeypatch).items():
        assert URN in s, f"{name}: {s!r}"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "fin's producer gap: asset_inputs.provenance and dataset_provenance emit the banner and "
    "' Source: <urn>' only; the ruled as-of and ticket id are not emitted (owner: "
    "invincible-agent/lane/fin)"))
def test_AN_ASSET_ANSWER_CARRIES_ITS_AS_OF_AND_TICKET_ID(monkeypatch):
    for name, s in _asset_strings(monkeypatch).items():
        assert re.search(r"\bas[- ]of\b", s, re.I), f"{name} names no as-of: {s!r}"
        assert re.search(r"\bticket\b", s, re.I), f"{name} names no ticket id: {s!r}"
