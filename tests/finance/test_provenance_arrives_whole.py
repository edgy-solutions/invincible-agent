"""data_provenance arrives whole on the card: every fin verb drawn as a MULTI_SERIES, through the projector.

The architect, via Chris, 2026-11-08: the data_provenance seal flips. It "arrives whole: dataset
URN, as-of, ticket id". Before 0.4.82 the projector named five envelope fields for MULTI_SERIES
and `data_provenance` was not one of them, so the engine sent it and no card received it. That is
the drop agent_fleet/presentation_agent/main.py's MULTI_SERIES comment describes three times over.

Two halves, measured separately because they belong to different lanes:

  - THE HOP (Lane 1's, green). Every fin verb bound to MULTI_SERIES answers through its real
    `/measure/<fn>` route, and the real projector function carries `data_provenance` verbatim.
    The control removes it from the tuple and watches it drop.
  - THE CONTENT (fin's). An asset answer's string is the operator's banner, the ticket clause and
    " Source: <urn>" (asset_inputs.provenance / dataset_provenance), and it names the dataset URN.
    ADR-0065:133 also rules an as-of and a ticket id. The broker's ticket has carried both since
    dag-tools 0.13.0 (#31), and engine-fin pins 0.14.0. engine-fin read through `get_dataframe`,
    which discards the ticket, so until this PR the string said "(ticket: pending)" (ruled
    2026-11-08) and the full rule was a strict xfail. engine-fin now reads through
    `get_dataframe_with_ticket`, and the string carries the receipt's as-of and ticket id. The
    receipt here is the client's own (`ticket_receipt`), built from a ticket as the broker issues
    one. The control is a ticket that stamps neither: its answer still says "(ticket: pending)"
    and claims no as-of. Each half alone is claimed only as far as the receipt says it.

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


TICKET_ID_VALUE = "7f3a9c01-5b2e-4d6a-9e8f-0a1b2c3d4e5f"
AS_OF_VALUE = "2026-11-08T00:00:00Z"
#: A ticket as the broker issues one, credential included; the receipt must carry none of it.
TICKET = {"ticket_id": TICKET_ID_VALUE, "issued_at": "2026-11-12T09:00:00Z", "as_of": AS_OF_VALUE,
          "as_of_source": "snapshot", "access_token": "hunter2-not-a-real-token"}


def _receipt(**over):
    from dag_tools.cortex_data.client import ticket_receipt
    return ticket_receipt(URN, {**TICKET, **over})


def _asset_strings(monkeypatch, receipt) -> dict[str, str]:
    from agent_fleet.finance_agent import asset_inputs
    monkeypatch.setenv(asset_inputs.BANNER_ENV, "SYNTHETIC TEST ASSET.")
    return {"provenance": asset_inputs.provenance(URN, receipt),
            "dataset_provenance": asset_inputs.dataset_provenance("SYNTHETIC TEST ASSET.", URN, receipt)}


def test_AN_ASSET_ANSWER_NAMES_ITS_DATASET_URN(monkeypatch):
    for receipt in (_receipt(), _receipt(ticket_id=None, as_of=None)):
        for name, s in _asset_strings(monkeypatch, receipt).items():
            assert URN in s, f"{name}: {s!r}"
            assert s.endswith(f"Source: {URN}"), f"{name}: the live leg reads the URN as the suffix: {s!r}"


AS_OF = re.compile(r"\bas[- ]of\b", re.I)
TICKET_ID = re.compile(r"\bticket\b[:\s]+(?!pending\b)\w", re.I)


def test_AN_ASSET_ANSWER_CARRIES_ITS_AS_OF_AND_TICKET_ID(monkeypatch):
    """ADR-0065:133, whole: the receipt's own as-of and ticket id, not merely the words."""
    for name, s in _asset_strings(monkeypatch, _receipt()).items():
        assert AS_OF.search(s), f"{name} names no as-of: {s!r}"
        assert TICKET_ID.search(s), f"{name} names no ticket id: {s!r}"
        assert TICKET_ID_VALUE in s and AS_OF_VALUE in s, f"{name} is not this ticket's: {s!r}"
        assert "hunter2" not in s, f"{name} carries the ticket's credential: {s!r}"


def test_THE_CONTROL_A_TICKET_THAT_STAMPS_NEITHER_STAYS_PENDING_AND_CLAIMS_NO_AS_OF(monkeypatch):
    # The ruled text, not asset_inputs.TICKET_PENDING: a seal that read the constant would pass it blank.
    for name, s in _asset_strings(monkeypatch, _receipt(ticket_id=None, as_of=None)).items():
        assert "(ticket: pending)" in s, f"{name}: {s!r}"
        assert not AS_OF.search(s), f"{name} claims an as-of nothing measured: {s!r}"
        assert not TICKET_ID.search(s), f"{name} claims a ticket id nothing minted: {s!r}"


@pytest.mark.parametrize("missing", ["ticket_id", "as_of"])
def test_A_RECEIPT_MISSING_ONE_HALF_CLAIMS_ONLY_THE_OTHER(monkeypatch, missing):
    for name, s in _asset_strings(monkeypatch, _receipt(**{missing: None})).items():
        if missing == "as_of":
            assert not AS_OF.search(s) and TICKET_ID_VALUE in s, f"{name}: {s!r}"
        else:
            assert AS_OF_VALUE in s and "ticket: pending" in s and not TICKET_ID.search(s), f"{name}: {s!r}"


def test_THE_TICKET_ID_PATTERN_TELLS_PENDING_FROM_AN_ID():
    # The control for both arms: a pending ticket is not an id, and an id is.
    assert not TICKET_ID.search("BANNER (ticket: pending) Source: u")
    assert TICKET_ID.search("BANNER (as of 2026-11-08T00:00Z, ticket 7f3a) Source: u")
    assert TICKET_ID.search("ticket: 7f3a") and AS_OF.search("as-of 2026-11-08")

