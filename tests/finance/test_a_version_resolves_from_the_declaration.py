"""A spoken version or period label resolves from the DECLARATION, never from the data.

RED ON MASTER UNTIL engine-fin's members land (fin's item 4). Written first, as fin's target,
by the ruling: "Version and period are not searched in the data. They resolve against the
declared version list and the declared calendar." These tests FAIL (not skip, not xfail) today:
`/resolve_instance` walks only `_RESOLVABLE` classes' `_members_of`, so a declared version
(`contract.versions`) or period label (`calendar.labels`) is not a candidate for anyone.

Every label is read FROM the loaded fixture objects, never typed. The membership check is
replaced at the name `main` uses (`engine.can_view_program`) as in
test_fin_enumeration_honours_program_members.py.

Tests 2, 3, the "outside" half of 5, the guards and the positive control are GREEN on master.
2 and 3 are green for the wrong reason (nothing resolves at all); they are the scope half and
the control of 1. 6 proves the harness reaches the real provider, so the reds are real misses.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from agent_fleet.finance_agent import asset_inputs  # noqa: E402
from agent_fleet.finance_agent import fiscal_calendar  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.utils import dataset_contracts  # noqa: E402

B_DIR = REPO / "tests" / "fixtures" / "fin_program_b"
CONTRACT = dataset_contracts.load_contracts(B_DIR / "contracts" / "program_b_versions.yaml")[
    "program_b_versions"]
CALENDAR = fiscal_calendar.load_calendars([B_DIR / "fin_calendar"])[CONTRACT.calendar]
VERSIONS = tuple(CONTRACT.versions)
PERIODS = tuple(CALENDAR.labels)

PROGRAM = "NP-MERIDIAN"
MEMBER = "alice@example.com"
NON_MEMBER = "carol@example.com"


@pytest.fixture(autouse=True)
def declared(monkeypatch):
    monkeypatch.setenv("DATASET_CONTRACT_DIR", str(B_DIR / "contracts"))
    monkeypatch.setenv("FIN_CALENDAR_OVERLAY_DIRS", str(B_DIR / "fin_calendar"))

    def can_view(program, caller_id, **kw):
        return (program, caller_id) == (PROGRAM, MEMBER)

    monkeypatch.setattr(engine, "can_view_program", can_view)


@pytest.fixture
def client():
    with TestClient(engine.app) as c:
        yield c


def _resolve(client, identifier, user_email, class_uri=None):
    body = {"identifier": identifier, "user_email": user_email}
    if class_uri is not None:
        body["class_uri"] = class_uri
    r = client.post("/resolve_instance", json=body)
    assert r.status_code == 200, r.text
    return r.json()["candidates"]


def _equal(cands, label):
    return [c for c in cands if label in (c["instance_id"], c["label"])
            and c["score"] >= engine._RESOLVE_FLOOR]


def _undeclared(declared_labels):
    label = declared_labels[0] + "-UNDECLARED"
    assert label not in declared_labels
    return label


def test_guard_the_declared_lists_are_not_empty():
    assert len(VERSIONS) > 0 and len(PERIODS) > 0


@pytest.mark.parametrize("version", VERSIONS)
def test_1_a_declared_version_resolves_for_a_member(client, version):
    cands = _resolve(client, version, MEMBER)
    assert _equal(cands, version), f"no candidate equal to declared version {version!r}: {cands}"


@pytest.mark.parametrize("version", VERSIONS)
def test_2_a_declared_version_does_not_resolve_for_a_non_member(client, version):
    """The scope half of 1. Green on master for the wrong reason: nothing resolves at all."""
    assert _equal(_resolve(client, version, NON_MEMBER), version) == []


def test_3_a_version_outside_the_list_does_not_resolve(client):
    """1's control. Green on master."""
    label = _undeclared(VERSIONS)
    assert _equal(_resolve(client, label, MEMBER), label) == []


def test_4_nothing_is_searched_in_the_data(client, monkeypatch):
    calls: list[str] = []

    def trap(name):
        def reader(*a, **kw):
            calls.append(name)
            raise AssertionError(f"asset_inputs.{name} called: the declaration is not the data")
        return reader

    for name in ("read_rows", "read_dataset_rows", "read_dataset_series", "require_grant",
                 "state_from_rows", "_load_client"):
        monkeypatch.setattr(asset_inputs, name, trap(name))
    cands = _resolve(client, VERSIONS[0], MEMBER)
    assert calls == [], f"the data was read: {calls}"
    assert _equal(cands, VERSIONS[0]), f"no candidate equal to declared version {VERSIONS[0]!r}: {cands}"
    # SKIPPED sub-case: an undeclared value in the double's data. Every reader needs the
    # catalogued asset and its client; there is no seam to return rows without it.


@pytest.mark.parametrize("period", PERIODS)
def test_5_a_declared_period_resolves_for_a_member(client, period):
    cands = _resolve(client, period, MEMBER)
    assert _equal(cands, period), f"no candidate equal to declared period {period!r}: {cands}"


def test_5_a_period_outside_the_calendar_does_not_resolve(client):
    label = _undeclared(PERIODS)
    assert _equal(_resolve(client, label, MEMBER), label) == []


def test_6_positive_control_a_seed_member_still_resolves(client):
    name = engine.STATE.programs[0].name
    cands = _resolve(client, name, MEMBER)
    assert PROGRAM in {c["instance_id"] for c in cands}, "harness does not reach the provider"
