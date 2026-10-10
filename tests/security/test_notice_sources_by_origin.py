"""Entitlement at READ on the sources of `mesh:whichPartsDoesThisNoticeAffect` (architect ruling).

The ruling: entitlement is enforced at read of promoted content and on the sources of mesh read
verbs, not on IngestArtifact rows. After promotion every drop has an origin and the read check is
ONE rule, `can_consume(caller domains, origin) AND program_member`; before promotion, and while the
origin is unresolved (awaiting_origin, including a steward REJECTING a suggestion), the drop is
visible to its dropper alone.

THE REAL ROUTE IS DRIVEN (`notice_parts_route` through TestClient), against a fake graph that
answers by the notice id it is asked about and records the statement it was sent: a row-only double
would pass whatever the cypher said, so the statement text is asserted to ask for the origin.

A WITHHELD notice answers byte-for-byte as an UNKNOWN one (status and body), so neither the status
code nor the body is an existence oracle.
"""
from __future__ import annotations

import json

import pytest
import yaml
from fastapi.testclient import TestClient

from agent_fleet.ontology_service import main as eo
from agent_fleet.ontology_service import notice_parts as np_mod
from agent_fleet.utils import origin_entitlement as oe

NOTICE = "PCN-T1"
UNKNOWN = "PCN-NOPE"
DROPPER = "dropper-1"
CALLER = "alice-1"

_TABLE_YAML = """
domain_consumption:
  SUSTAINMENT:
    granted_by: t
    reason: t
    allowed_origins: [SUSTAINMENT]
  FINANCE:
    granted_by: t
    reason: t
    allowed_origins: [FINANCE]
"""

_NODE = {"id": NOTICE, "type": "PCN", "provenance_obtained_via": "user-drop",
         "provenance_ingest_id": "sha256:aa", "provenance_standing": "supervised"}
_SEEDED = {"id": NOTICE, "type": "PCN", "mfr": "ACME"}


def _row(*, node=None, has_artifact=True, promoted=True, owner="SUSTAINMENT", program=None,
         resolved_by="steward", dropped_by=DROPPER, mpns=("5530-1", "5530-2")):
    return {
        "notice": dict(node if node is not None else _NODE),
        "mpns": list(mpns),
        "dropped_by": dropped_by,
        "has_artifact": has_artifact,
        "origin_owner_domain": owner,
        "origin_program": program,
        "origin_resolved_by": resolved_by,
        "promoted": promoted,
        "promoted_by": "human:bob" if promoted else None,
    }


class _Rec:
    def __init__(self, d):
        self._d = d

    def data(self):
        return dict(self._d)


class _Graph:
    """Answers one row for the id it holds and nothing for any other; records every statement."""

    def __init__(self, row=None):
        self.row = row
        self.runs: list = []

    def session(self, **kw):
        g = self

        class _S:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def run(self, cypher, params=None, **kw2):
                params = dict(params or {}, **kw2)
                g.runs.append((cypher, params))
                if g.row is not None and params.get("notice_id") == NOTICE:
                    return [_Rec(g.row)]
                return []
        return _S()


class _Program:
    def __init__(self, answer=True, raises=False):
        self.answer, self.raises, self.calls = answer, raises, []

    def __call__(self, program, caller_id):
        self.calls.append((program, caller_id))
        if self.raises:
            raise RuntimeError("topaz down")
        return self.answer


@pytest.fixture
def post(monkeypatch, tmp_path):
    f = tmp_path / "domain_consumption.yaml"
    f.write_text(_TABLE_YAML, encoding="utf-8")
    monkeypatch.setenv("DOMAIN_CONSUMPTION_FILE", str(f))

    def _post(row, *, user=CALLER, domains=("SUSTAINMENT",), notice=NOTICE, program=None):
        g = _Graph(row)
        monkeypatch.setattr(eo, "_NEO4J_DRIVER", g)
        prog = program if program is not None else _Program()
        monkeypatch.setattr(eo, "_notice_parts_can_view_program", prog, raising=False)
        body = {"entitled_domains": list(domains), "params": {"notice_id": notice}}
        if user is not None:
            body["user_email"] = user
        r = TestClient(eo.app).post("/notice_parts", json=body)
        return r, g, prog
    return _post


def _unknown_equivalent(post_):
    r, _, _ = post_(None, notice=UNKNOWN)
    return r.status_code, json.loads(r.text.replace(UNKNOWN, NOTICE))


def _same_as_unknown(post_, r):
    assert (r.status_code, r.json()) == _unknown_equivalent(post_)
    assert r.json()["reason"] == "unknown_notice" and r.json()["sources"] == []


def test_the_statement_asks_for_the_origin_and_the_promotion():
    r = np_mod.NOTICE_PARTS_CYPHER
    for frag in ("a IS NOT NULL AS has_artifact", "a.origin_owner_domain AS origin_owner_domain",
                 "a.origin_program AS origin_program", "a.origin_resolved_by AS origin_resolved_by",
                 "count(p) > 0 AS promoted", "head(collect(p.promoted_by)) AS promoted_by"):
        assert frag in r


# 1
def test_arm1_steward_origin_the_callers_domains_cannot_consume_is_withheld_as_unknown(post):
    r, g, prog = post(_row(owner="FINANCE", resolved_by="steward"))
    assert g.runs and "origin_owner_domain" in g.runs[0][0]
    _same_as_unknown(post, r)
    assert prog.calls == []


# 2
def test_arm2_consuming_caller_steward_origin_no_program_is_visible_without_asking(post):
    r, g, prog = post(_row(owner="SUSTAINMENT", program=None))
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert [s["mpn"] for s in r.json()["sources"]] == ["5530-1", "5530-2"]
    assert prog.calls == []


# 3
def test_arm3_origin_with_a_program_needs_membership(post):
    row = _row(owner="SUSTAINMENT", program="PROG-A")
    r, _, prog = post(row, program=_Program(False))
    _same_as_unknown(post, r)
    assert prog.calls == [("PROG-A", CALLER)]
    r, _, prog = post(row, program=_Program(True))
    assert r.json()["status"] == "ok" and len(r.json()["sources"]) == 2
    assert prog.calls == [("PROG-A", CALLER)]


# 4
def test_arm4_not_promoted_consuming_non_dropper_is_withheld(post):
    r, _, _ = post(_row(promoted=False, owner="SUSTAINMENT"))
    _same_as_unknown(post, r)


# 5
def test_arm5_not_promoted_the_dropper_sees_it(post):
    r, _, _ = post(_row(promoted=False, owner=None, resolved_by=None), user=DROPPER)
    assert r.json()["status"] == "ok" and len(r.json()["sources"]) == 2


# 6
@pytest.mark.parametrize("promoted", [True, False])
@pytest.mark.parametrize("kw", [
    dict(owner=None, resolved_by=None),
    dict(owner="SUSTAINMENT", resolved_by="unresolved"),
    dict(owner="SUSTAINMENT", resolved_by=""),
], ids=["no-origin", "unresolved", "blank-rung"])
def test_arm6_awaiting_origin_is_dropper_only(post, promoted, kw):
    r, _, _ = post(_row(promoted=promoted, **kw))
    _same_as_unknown(post, r)
    r, _, _ = post(_row(promoted=promoted, **kw), user=DROPPER)
    assert r.json()["status"] == "ok" and len(r.json()["sources"]) == 2


# 7
def test_arm7_drop_derived_with_no_artifact_node_fails_closed(post):
    r, _, _ = post(_row(has_artifact=False, owner=None, resolved_by=None, dropped_by=None))
    _same_as_unknown(post, r)


# 8
def test_arm8_a_seeded_notice_is_unchanged(post):
    seeded = _row(node=_SEEDED, has_artifact=False, promoted=False, owner=None,
                  resolved_by=None, dropped_by=None)
    r, _, prog = post(seeded)
    assert r.json()["status"] == "ok" and len(r.json()["sources"]) == 2
    assert prog.calls == []
    r, _, _ = post(seeded, user=None)
    assert r.json()["status"] == "ok"


# 9
def test_arm9_topaz_down_is_503_for_an_admitted_caller_and_unknown_for_a_refused_one(post):
    r, _, prog = post(_row(owner="SUSTAINMENT", program="PROG-A"), program=_Program(raises=True))
    assert r.status_code == 503
    assert prog.calls == [("PROG-A", CALLER)]
    r, _, prog = post(_row(owner="FINANCE", program="PROG-A"), program=_Program(raises=True))
    _same_as_unknown(post, r)
    assert prog.calls == []


# 10
@pytest.mark.parametrize("dropped_by", [DROPPER, ""], ids=["named-dropper", "blank-dropper"])
@pytest.mark.parametrize("user", [None, ""], ids=["absent", "empty"])
def test_arm10_an_absent_caller_id_never_matches_the_dropper(post, dropped_by, user):
    r, _, _ = post(_row(promoted=False, owner=None, resolved_by=None, dropped_by=dropped_by),
                   user=user)
    _same_as_unknown(post, r)


# 11
def test_arm11_a_visible_source_carries_the_origin_and_its_rung(post):
    r, _, _ = post(_row(owner="SUSTAINMENT", program=None, resolved_by="steward"))
    assert r.json()["sources"]
    for s in r.json()["sources"]:
        assert s["origin"] == {"owner_domain": "SUSTAINMENT", "program": None,
                               "resolved_by": "steward"}


def test_the_shared_decider_is_one_class_object_and_a_programless_origin_needs_no_membership():
    from src.iagent import origin
    assert origin.DropperNotProgramMember is oe.DropperNotProgramMember
    assert origin.origin_visible is oe.origin_visible
    t = oe.load_domain_consumption(yaml.safe_load(_TABLE_YAML))
    assert oe.origin_visible(viewer_domains=["SUSTAINMENT"], is_program_member=False,
                             origin=oe.Origin(owner_domain="SUSTAINMENT"), table=t)
    assert not oe.origin_visible(viewer_domains=["SUSTAINMENT"], is_program_member=False,
                                 origin=oe.Origin(owner_domain="SUSTAINMENT", program="P"),
                                 table=t)
