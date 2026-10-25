"""ADR-0047 §5.1, instance 1: `GET /cases/{case_id}/action`, sealed against the section's wording.

The architect, 2026-10-19 (Q6): "The action-route read is an instance of §5.1 (the record derives
from the event the delegate seeded). ... Gov seals both against §5.1's wording." The clauses this
file binds to, read from §5.1 and its 2026-10-08 amendment:

  W1  "a `svc:` principal may not be one of them" / "Every other `svc:` recipient is still
      refused." A service is a recipient ONLY as a declared delegate. An undeclared service is
      refused however else it might qualify: as the case's dropper, by domain cells, or as a
      task holder.
  W2  "only as that artifact's seeding delegate (`seeded_by`)." Being a declared delegate admits
      nothing by itself. The case-level `seeded_by` decides, and the delegate never reaches the
      person gate (`_load_viewable_case`).
  W3  "answers everyone else exactly as it answers an absent id." Asserted inside every refusal
      arm: the body is the one a delegate gets for a case that does not exist, and no refusal
      reads the artifact store.

Each W1 arm has a control that differs only in being a person, so the arm can only be red for
the reason it names. The harness is Lane 1's
(`tests/test_a_case_action_record_names_who_chose_approved_released.py`); its 13 arms are not
repeated here.

Run: uv run pytest tests/test_the_action_route_reads_as_adr_0047_5_1_words_it.py -q
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from src.iagent import gateway, human_tasks  # noqa: E402
from tests.test_a_case_action_record_names_who_chose_approved_released import (  # noqa: E402,F401
    DELEGATE, OTHER_DELEGATE, _CASE, _delegates, _record, _row, client_for,
)
from tests.test_cases_route import _FakeRestate, _user  # noqa: E402

#: A service identity that is NOT a key of DELEGATE_ON_BEHALF_OF.
UNDECLARED = "svc:undeclared"
PERSON = "dana@example.com"


def _spec(dropper: str) -> dict:
    return {"trigger": {"domain_type": "SAFETY", "dropped_by": {"authz_id": dropper}}}


def _undelegated_case() -> dict:
    """A case opened by a caller that is not a declared delegate: `/ingest/events` stamps
    `seeded_by` only for a declared delegate, so it has none."""
    return dict(_CASE, seeded_by=None)


@pytest.fixture
def tasks(monkeypatch):
    """`holds_task_on_case`, keyed on what the gate must pass it: True only for a (case, holder)
    pair in the set."""
    held: set[tuple[str, str]] = set()
    monkeypatch.setattr(human_tasks, "holds_task_on_case",
                        lambda case_id, who: (case_id, who) in held)
    return held


def _absent_case_body(client_for) -> dict:
    c = client_for(_user(DELEGATE), _FakeRestate(case=None), {})
    resp = c.get("/cases/c-nope/action")
    assert resp.status_code == 403, resp.text
    return resp.json()


def _refused_like_absent(client_for, resp) -> None:
    assert resp.status_code == 403, resp.text
    assert resp.json() == _absent_case_body(client_for)


# -- W1: an undeclared service is never a recipient --------------------------------------------

@pytest.mark.parametrize("who, expect_admitted", [(UNDECLARED, False), (PERSON, True)])
def test_W1_the_cases_dropper_reads_it_only_if_a_person(client_for, tasks, who, expect_admitted):
    """The person gate admits a case's dropper (`can_view_case` (a)). An undeclared service that
    drops as itself is that dropper; Q16 calls that the misuse."""
    c = client_for(_user(who), _FakeRestate(case=_undelegated_case(), spec1=_spec(who)),
                   {"c-1": [_row(_record(), seeded_by=None)]})
    resp = c.get("/cases/c-1/action")
    if expect_admitted:
        assert resp.status_code == 200, resp.text
    else:
        assert gateway.neo4j_driver.runs == [], "the artifact store was read for a refusal"
        _refused_like_absent(client_for, resp)


@pytest.mark.parametrize("who, expect_admitted", [(UNDECLARED, False), (PERSON, True)])
def test_W1_a_holder_of_every_label_reads_it_only_if_a_person(client_for, tasks, who,
                                                               expect_admitted):
    c = client_for(_user(who, domains=["SAFETY"]),
                   _FakeRestate(case=_undelegated_case(), spec1=_spec("alice")),
                   {"c-1": [_row(_record(), seeded_by=None)]})
    resp = c.get("/cases/c-1/action")
    if expect_admitted:
        assert resp.status_code == 200, resp.text
    else:
        assert gateway.neo4j_driver.runs == [], "the artifact store was read for a refusal"
        _refused_like_absent(client_for, resp)


@pytest.mark.parametrize("who, expect_admitted", [(UNDECLARED, False), (PERSON, True)])
def test_W1_a_task_holder_reads_it_only_if_a_person(client_for, tasks, who, expect_admitted):
    """Q13's words for the same shape: "a service holding a review task counts for nothing"."""
    tasks.add(("c-1", who))
    c = client_for(_user(who), _FakeRestate(case=_undelegated_case(), spec1=_spec("alice")),
                   {"c-1": [_row(_record(), seeded_by=None)]})
    resp = c.get("/cases/c-1/action")
    if expect_admitted:
        assert resp.status_code == 200, resp.text
    else:
        assert gateway.neo4j_driver.runs == [], "the artifact store was read for a refusal"
        _refused_like_absent(client_for, resp)


# -- W2: a declared delegate is admitted on its seeding, and on nothing else -------------------

@pytest.mark.parametrize("case_seeder, expect_admitted", [(OTHER_DELEGATE, False),
                                                          (DELEGATE, True)])
def test_W2_the_cases_seeder_decides_not_the_records(client_for, tasks, case_seeder,
                                                     expect_admitted):
    """The record names THIS delegate, so only the case-level `seeded_by` can refuse."""
    case = dict(_CASE, seeded_by=case_seeder)
    c = client_for(_user(DELEGATE), _FakeRestate(case=case, spec1=_spec("alice")),
                   {"c-1": [_row(_record(), seeded_by=DELEGATE)]})
    resp = c.get("/cases/c-1/action")
    if expect_admitted:
        assert resp.status_code == 200, resp.text
    else:
        assert gateway.neo4j_driver.runs == [], "the artifact store was read for a refusal"
        _refused_like_absent(client_for, resp)


def test_W2_a_delegate_that_qualifies_as_a_person_is_still_refused(client_for, tasks,
                                                                   monkeypatch):
    """A declared delegate that is the dropper, holds every label and holds a task, on a case
    another delegate seeded, is refused, and the person gate is never asked."""
    asked: list[str] = []

    async def _spy(case_id, current_user):
        asked.append(case_id)
        raise AssertionError("a delegate reached the person gate")

    monkeypatch.setattr(gateway, "_load_viewable_case", _spy)
    tasks.add(("c-1", DELEGATE))
    case = dict(_CASE, seeded_by=OTHER_DELEGATE)
    c = client_for(_user(DELEGATE, domains=["SAFETY"]),
                   _FakeRestate(case=case, spec1=_spec(DELEGATE)),
                   {"c-1": [_row(_record(), seeded_by=DELEGATE)]})
    resp = c.get("/cases/c-1/action")
    assert asked == []
    assert gateway.neo4j_driver.runs == [], "the artifact store was read for a refusal"
    _refused_like_absent(client_for, resp)
