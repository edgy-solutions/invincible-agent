"""FRACAS results are filtered per caller by program membership (ADR-0056 open question 2,
accepted). The verb is `what_failed_on_this_part`; PN-8801 fails on PLT-ALPHA (FR-6001) and
PLT-BRAVO (FR-6002), mapped to SANDBOX_PROGRAM_ALPHA / _BRAVO by
`policy/overlays/sample/platform_programs.yaml`.

EVERY ARM'S CONTROL DIFFERS IN EXACTLY ONE THING. The empty answer for a non-member is paired
with the same request by a member; the unmapped-platform drop with the same record once mapped;
the 503 with the same request while Topaz answers.
"""
from __future__ import annotations

import ast

import pytest

from agent_fleet.safety_agent import entities, measures
from agent_fleet.utils import program_membership as pm

from . import _program_filter as pf

PART = "PN-8801"


def _ids(out):
    return sorted(f["record_id"] for f in out["failures"])


# -- 1. a member of one program sees that program's record and not the other's ---------------

def test_a_member_of_one_program_sees_only_that_programs_record(monkeypatch):
    pf.install(monkeypatch, caller=pf.BOB, members={pf.BOB: {"SANDBOX_PROGRAM_ALPHA"}})
    out = measures.what_failed_on_this_part(part_number=PART)
    assert _ids(out) == ["FR-6001"], out
    assert out["platforms"] == ["PLT-ALPHA"], "platforms is aggregated AFTER the gate"
    assert out["failure_count"] == 1


# -- 2. no membership: empty, well-formed, NOT a refusal ---------------------------------------

def test_a_caller_with_no_program_membership_gets_the_empty_answer_not_a_refusal(monkeypatch):
    pf.install(monkeypatch, caller=pf.CAROL, members={})
    out = measures.what_failed_on_this_part(part_number=PART)
    assert out["refused"] is False, out
    assert out["failures"] == [] and out["failure_count"] == 0 and out["platforms"] == []
    assert out["systems_of_record_cited"] == []


def test_CONTROL_the_same_request_by_a_member_of_both_gets_both(monkeypatch):
    """Differs from the arm above in membership ONLY: same part, same engine, same fixture."""
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    out = measures.what_failed_on_this_part(part_number=PART)
    assert _ids(out) == ["FR-6001", "FR-6002"], out
    assert out["failure_count"] == 2 and out["platforms"] == ["PLT-ALPHA", "PLT-BRAVO"]


@pytest.mark.parametrize("caller", [None, "svc:supervisor"])
def test_a_caller_with_no_person_is_refused_not_answered_empty(monkeypatch, caller):
    """DECISION: BOTH the service identity and no-resolved-caller refuse (neither carries a
    person). Topaz is not asked."""
    asked = pf.install(monkeypatch, caller=caller, members=pf.ALL_PROGRAMS)
    with pytest.raises(measures.NoPerson):
        measures.what_failed_on_this_part(part_number=PART)
    assert asked == []


def test_no_person_is_a_422_at_the_route_and_the_person_control_differs_only_in_kind(monkeypatch):
    """CONTROL differs in ONE thing: the caller kind (svc vs a person with the same grants)."""
    from fastapi.testclient import TestClient

    from agent_fleet.safety_agent import main

    body = {"query": "", "params": {"part_number": PART}}
    members = {**pf.ALL_PROGRAMS, "svc:supervisor": {"SANDBOX_PROGRAM_ALPHA", "SANDBOX_PROGRAM_BRAVO"}}
    pf.install(monkeypatch, caller="svc:supervisor", members=members)
    with TestClient(main.app) as c:
        r = c.post("/measure/what_failed_on_this_part", json=body)
    assert r.status_code == 422, r.text
    assert r.json() == {"error": "no_person", "fn": "what_failed_on_this_part",
                        "message": "this verb answers for a person; the caller carries none"}
    pf.install(monkeypatch, caller=pf.ALICE, members=members)
    with TestClient(main.app) as c:
        r = c.post("/measure/what_failed_on_this_part", json=body)
    assert r.status_code == 200 and r.json()["failure_count"] == 2, r.text


def test_the_empty_answer_cannot_be_told_from_a_clean_part_by_its_counts(monkeypatch):
    """No quantity oracle: a denied caller's counts equal a clean part's counts."""
    pf.install(monkeypatch, caller=pf.CAROL, members={})
    denied = measures.what_failed_on_this_part(part_number=PART)
    clean = [c.part_number for c in entities.CRITICAL_ITEMS
             if not any(r.part_number == c.part_number for r in entities.FAILURE_RECORDS)]
    assert clean, "fixture assumption: some critical part has no failure"
    ref = measures.what_failed_on_this_part(part_number=clean[0])
    for k in ("failure_count", "platforms", "systems_of_record_cited", "failures"):
        assert denied[k] == ref[k], (k, denied[k], ref[k])


# -- 3. an unmapped platform is denied, even for a member of every mapped program ------------

def test_a_record_whose_platform_has_no_mapping_row_is_never_returned(monkeypatch, tmp_path):
    (tmp_path / "platform_programs.yaml").write_text(
        "platform_programs:\n  PLT-ALPHA: SANDBOX_PROGRAM_ALPHA\n", encoding="utf-8")
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS, overlay_dirs=str(tmp_path))
    out = measures.what_failed_on_this_part(part_number=PART)
    assert _ids(out) == ["FR-6001"], f"PLT-BRAVO has no row and must be dropped: {out}"


def test_CONTROL_the_same_record_with_a_mapping_row_is_returned(monkeypatch, tmp_path):
    """Differs from the arm above in the mapping row ONLY."""
    (tmp_path / "platform_programs.yaml").write_text(
        "platform_programs:\n  PLT-ALPHA: SANDBOX_PROGRAM_ALPHA\n"
        "  PLT-BRAVO: SANDBOX_PROGRAM_BRAVO\n", encoding="utf-8")
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS, overlay_dirs=str(tmp_path))
    assert _ids(measures.what_failed_on_this_part(part_number=PART)) == ["FR-6001", "FR-6002"]


def test_no_overlay_dirs_at_all_denies_every_record(monkeypatch):
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS, overlay_dirs="")
    assert measures.what_failed_on_this_part(part_number=PART)["failures"] == []


def test_every_platform_the_fixture_uses_is_mapped_or_named_unmapped_on_purpose(monkeypatch):
    """DERIVED, not listed: a new record on a new platform with no row reds here until someone
    decides. The only platform allowed to be unmapped is the one the overlay header names."""
    monkeypatch.setenv("PLATFORM_PROGRAM_OVERLAY_DIRS", str(pf.SAMPLE_OVERLAY))
    used = {r.platform for r in entities.FAILURE_RECORDS}
    assert used - set(measures.platform_programs()) <= {"PLT-CHARLIE"}


def test_every_mapped_program_exists_in_program_members_yaml():
    import yaml
    programs = set(yaml.safe_load(
        (pf.REPO / "policy" / "program_members.yaml").read_text("utf-8"))["programs"])
    mapped = set(yaml.safe_load(
        (pf.SAMPLE_OVERLAY / "platform_programs.yaml").read_text("utf-8"))["platform_programs"].values())
    assert mapped and mapped <= programs, mapped - programs


# -- 4. Topaz down is a 503, never an empty result ---------------------------------------------

def test_topaz_down_raises_rather_than_answering_empty(monkeypatch):
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS, topaz_down=True)
    with pytest.raises(measures.ProgramAuthorizationUnavailable):
        measures.what_failed_on_this_part(part_number=PART)


def test_topaz_down_is_a_503_at_the_route_and_the_control_is_a_200(monkeypatch):
    from fastapi.testclient import TestClient

    from agent_fleet.safety_agent import main

    body = {"query": "", "params": {"part_number": PART}}
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS, topaz_down=True)
    with TestClient(main.app) as c:
        r = c.post("/measure/what_failed_on_this_part", json=body)
    assert r.status_code == 503, r.text
    assert r.json()["error"] == "authorization_unavailable"
    assert "failures" not in r.json(), "an outage must never carry an answer"

    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS, topaz_down=False)
    with TestClient(main.app) as c:
        r = c.post("/measure/what_failed_on_this_part", json=body)
    assert r.status_code == 200 and r.json()["failure_count"] == 2, r.text


def test_an_http_error_from_topaz_is_also_an_outage_not_a_deny(monkeypatch):
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS, http_status=500)
    with pytest.raises(measures.ProgramAuthorizationUnavailable):
        measures.what_failed_on_this_part(part_number=PART)


# -- 5. the identity is read from the transport layer, never from a parameter ------------------

def test_a_caller_supplied_identity_param_is_refused_not_trusted(monkeypatch):
    from fastapi.testclient import TestClient

    from agent_fleet.safety_agent import main

    pf.install(monkeypatch, caller=pf.CAROL, members={})
    with TestClient(main.app) as c:
        r = c.post("/measure/what_failed_on_this_part",
                   json={"query": "", "params": {"part_number": PART, "user_email": pf.ALICE}})
    assert r.status_code == 422 and "user_email" in r.json()["unexpected"], r.text


# -- 6. the engine's check asks the SAME question as the gateway's -----------------------------

def test_the_engine_payload_equals_the_gateways_payload():
    """`src/iagent/human_tasks.check_can_view_program` cannot be imported by an engine
    (psycopg2 at module top, no src/ in the image), so its payload is read from its source."""
    src = (pf.REPO / "src" / "iagent" / "human_tasks.py").read_text("utf-8")
    fn = next(n for n in ast.parse(src).body
              if isinstance(n, ast.FunctionDef) and n.name == "check_can_view_program")
    payload = next(a.value for a in ast.walk(fn)
                   if isinstance(a, ast.Assign) and getattr(a.targets[0], "id", "") == "payload")
    names = {"program": "PROG", "caller_id": "WHO"}
    gateway = {k.value: (names[v.id] if isinstance(v, ast.Name) else v.value)
               for k, v in zip(payload.keys, payload.values)}
    assert pm.check_payload("PROG", "WHO") == gateway
    assert "/api/v3/directory/check" in ast.get_source_segment(src, fn)
