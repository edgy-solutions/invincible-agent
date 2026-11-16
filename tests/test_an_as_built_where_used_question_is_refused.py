"""A where-used question asked "as built" or "as maintained" is refused, never answered as designed.

The ontology's comment on ps:Part says a where-used question asked of as_built or as_maintained "is
refused loudly, never answered as an empty table". At the 2026-11-16 rehearsal, "where is part
5530-182 used as built" returned as-designed rows with no word that it had substituted them.

THE CAUSE, MEASURED in engine-o's log. The model filled the slot correctly. It replied with
`"slots_json": {"configuration": "as_built"}`, an object where the contract declares a string. The
parser turned that object into the string `{configuration: as_built}`, which is not JSON, so
/fill_slots returned no slots. The verb then ran on its default, `as_designed`.

The seal drives the real /fill_slots, with the reply stubbed in that measured form, using the
verb's own slot declarations. It then hands the slots it got back to the real producer, where_used.
The CONTROL is the same reply naming as_designed: it must give rows. So a refusal here comes from
the configuration, not from a part that cannot be answered at all.

Run: uv run pytest tests/test_an_as_built_where_used_question_is_refused.py -q
"""
from __future__ import annotations

import asyncio
import json

import pytest

from agent_fleet.ontology_service import where_used as w
from tests.test_where_used_rolls_up_through_every_level import ALICE, DATASET, ask, ident

#: The string the parser produced on 2026-11-16, copied from engine-o's warning line.
MEASURED = "{configuration: as_built}"


def _eo():
    pytest.importorskip("rdflib")
    from agent_fleet.ontology_service import main as eo
    return eo


def _fill(monkeypatch, slots_json: str) -> dict:
    """The real /fill_slots with the where-used verb's own declarations; BAML alone is stubbed."""
    eo = _eo()

    class _Filled:
        confidence = 0.99
        reasoning = "stub"

        def __init__(self, s):
            self.slots_json = s

    async def _fake(**kw):
        return _Filled(slots_json)

    monkeypatch.setattr(eo.b, "FillVerbSlots", _fake)
    req = eo.FillSlotsRequest(query="where is part P used", verb_iri="mesh:whereIsThisPartUsed",
                              declarations=json.dumps(w.slots()), user_email=ALICE)
    return asyncio.run(eo.fill_slots(req)).slots


def _answer(slots: dict) -> dict:
    return ask(ident("P"), ALICE, slots.get("configuration"))


def test_THE_FIXTURE_HOLDS_NO_AS_BUILT_OR_AS_MAINTAINED_DATA():
    """The precondition the refusals depend on, READ from the dataset rather than assumed."""
    held = {c for confs in DATASET.end_items.values() for c in confs}
    assert w.DEFAULT_CONFIGURATION in held
    assert not held & {"as_built", "as_maintained"}, held


def test_THE_MEASURED_REPLY_FILLS_THE_CONFIGURATION(monkeypatch):
    assert _fill(monkeypatch, MEASURED) == {"configuration": "as_built"}


@pytest.mark.parametrize("configuration", ["as_built", "as_maintained"])
@pytest.mark.parametrize("form", ["stringified", "json"])
def test_AS_BUILT_AND_AS_MAINTAINED_ARE_REFUSED_WITH_NO_ROWS(monkeypatch, configuration, form):
    reply = (f"{{configuration: {configuration}}}" if form == "stringified"
             else json.dumps({"configuration": configuration}))
    got = _answer(_fill(monkeypatch, reply))
    assert got["status"] == "refused" and got["reason"] == "configuration_not_available", got
    assert not got.get("where_used") and not got.get("rows"), got


@pytest.mark.parametrize("form", ["stringified", "json"])
def test_CONTROL_AS_DESIGNED_BY_THE_SAME_PATH_GIVES_ROWS(monkeypatch, form):
    reply = "{configuration: as_designed}" if form == "stringified" else '{"configuration": "as_designed"}'
    got = _answer(_fill(monkeypatch, reply))
    assert got["status"] == "ok" and got["rows"], got
    assert all(r["configuration"] == "as_designed" for r in got["where_used"])


@pytest.mark.parametrize("reply", [
    "{configuration: as_built, configuration: as_designed}",   # a key named twice
    "{configuration: [as_built]}",                              # nested
    "{as_built}",                                                # no key
    "configuration: as_built",                                   # no braces
])
def test_A_FORM_THE_READER_CANNOT_BOUND_STAYS_UNREAD(monkeypatch, reply):
    assert _fill(monkeypatch, reply) == {}


def test_A_STRINGIFIED_VALUE_OUTSIDE_THE_ENUM_IS_STILL_REFUSED(monkeypatch):
    """The second form goes through the same acceptance checks as JSON does."""
    assert _fill(monkeypatch, "{configuration: as_imagined}") == {}
