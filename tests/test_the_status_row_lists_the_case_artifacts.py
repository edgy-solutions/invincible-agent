"""GET /ingest/{ingest_id}/status gains artifacts[] (ruled 2026-10-16, ruling a): artifact id, kind
and released_at for the case the event opened -- a delegate learns its artifact ids from the row it
already may read.

The list is what the CALLER may open: each artifact passes `artifact_reads.is_entitled`, the gate
GET /artifacts/{id} applies, so an id it could not read is never listed. The key is always present;
`[]` is none, `None` is unknown (the graph could not be read) and the row still answers.

Arms:
  seeded   a delegate sees the artifact it seeded, with kind and released_at.
  hidden   an artifact of the same case it did not seed is absent.
  owner    a person sees the artifacts it owns, not another's.
  none     no case_id -> [] and the graph is not asked.
  unknown  the graph raising -> None, status 200, the rest of the row intact.
  text     the statement matches on the case and scopes the owner edge by the caller.

Run: uv run pytest tests/test_the_status_row_lists_the_case_artifacts.py -v
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import artifact_reads, gateway  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402

_ID = "evt-" + "c" * 64
DELEGATE = "svc:openddil"
OTHER = "svc:other"
PERSON = "alice@example.com"
_MAP = json.dumps({DELEGATE: ["operator.atlantia@example.com"], OTHER: []})


@pytest.fixture(autouse=True)
def _delegates(monkeypatch):
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF", _MAP)


def _art(id, kind="maintenance-action-record", released_at=1760000000000, *, seeded_by=None,
         owner=False):
    return {"id": id, "kind": kind, "released_at": released_at, "is_owner": owner,
            "seeded_by": seeded_by}


class _Session:
    def __init__(self, d):
        self.d = d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, cypher, **params):
        self.d.calls.append((cypher, params))
        if self.d.boom:
            raise RuntimeError("neo4j unreachable")
        return list(self.d.records)


class _Driver:
    def __init__(self, records=(), boom=False):
        self.records, self.boom, self.calls = list(records), boom, []

    def session(self):
        return _Session(self)


def _row(**over):
    base = {"id": _ID, "status": "case_opened", "kind": "event", "sha256": "c" * 64,
            "submitted_by": DELEGATE, "on_behalf_of": DELEGATE, "created_at": 1, "updated_at": 2,
            "case_id": "E-1", "duplicate_of": None, "detail": None, "origin_suggestion": None,
            "failure": None, "attempt": 1, "notice_id": None}
    base.update(over)
    return base


@pytest.fixture
def status(monkeypatch):
    def _make(caller, records=(), *, row=None, boom=False):
        monkeypatch.setattr(ist, "get_status_for", lambda ingest_id, caller_id: row or _row())
        driver = _Driver(records, boom=boom)
        monkeypatch.setattr(gateway, "neo4j_driver", driver)
        user = type("U", (), {"authz_id": caller, "id": caller, "sub": caller, "email": caller,
                              "persona": None, "entitled_domains": [], "is_authenticated": True})()
        gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
        r = TestClient(gateway.app).get(f"/ingest/{_ID}/status")
        return r, driver
    yield _make
    gateway.app.dependency_overrides.clear()


def test_a_delegate_sees_the_artifact_it_seeded_with_kind_and_released_at(status):
    r, _ = status(DELEGATE, [_art("A-1", released_at=1760000000123, seeded_by=DELEGATE)])
    assert r.status_code == 200, r.text
    assert r.json()["artifacts"] == [{"artifact_id": "A-1", "kind": "maintenance-action-record",
                                      "released_at": 1760000000123}]


def test_an_artifact_of_the_same_case_it_did_not_seed_is_absent(status):
    r, _ = status(DELEGATE, [_art("A-1", seeded_by=DELEGATE), _art("A-2", seeded_by=OTHER),
                             _art("A-3", seeded_by=None)])
    assert [a["artifact_id"] for a in r.json()["artifacts"]] == ["A-1"]


def test_a_person_sees_what_it_owns_and_not_a_delegates_seeding(status):
    r, _ = status(PERSON, [_art("A-1", owner=True), _art("A-2", seeded_by=PERSON),
                           _art("A-3", seeded_by=DELEGATE)],
                  row=_row(submitted_by=PERSON, on_behalf_of=PERSON))
    assert [a["artifact_id"] for a in r.json()["artifacts"]] == ["A-1"]


def test_an_unreleased_artifact_lists_with_a_null_released_at(status):
    r, _ = status(DELEGATE, [_art("A-1", released_at=None, seeded_by=DELEGATE)])
    assert r.json()["artifacts"] == [{"artifact_id": "A-1", "kind": "maintenance-action-record",
                                      "released_at": None}]


def test_no_case_id_is_an_empty_list_and_the_graph_is_not_asked(status):
    r, driver = status(DELEGATE, [_art("A-1", seeded_by=DELEGATE)], row=_row(case_id=None))
    assert r.status_code == 200
    assert r.json()["artifacts"] == []
    assert driver.calls == []


def test_a_case_with_no_artifact_is_an_empty_list(status):
    r, _ = status(DELEGATE, [])
    assert r.json()["artifacts"] == []


def test_the_graph_raising_is_unknown_not_none_and_the_row_still_answers(status):
    r, driver = status(DELEGATE, boom=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["artifacts"] is None
    assert body["stage"] == "case_opened" and body["case_id"] == "E-1"
    assert len(driver.calls) == 1


def test_the_statement_matches_on_the_case_and_scopes_the_owner_edge_by_the_caller(status):
    _, driver = status(DELEGATE, [_art("A-1", seeded_by=DELEGATE)])
    (cypher, params), = driver.calls
    assert cypher == artifact_reads.CASE_ARTIFACTS_CYPHER
    assert "MATCH (a:AnswerArtifact {case_id: $case_id})" in cypher
    assert "owner:Actor {actor_id: $user_id}" in cypher
    assert params == {"case_id": "E-1", "user_id": DELEGATE}
