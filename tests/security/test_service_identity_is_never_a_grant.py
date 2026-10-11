"""A service identity is never a grant (lane/74 packet items 1-2).

`/resolve_instance` takes `user_email` / `entitled_domains` from the BODY. Entitlement belongs to a
PERSON: when the caller is not one (no identity, or a `svc:` identity), `notice_visible` treats
`viewer_domains` as EMPTY, program membership as FALSE, and the dropper match cannot hold. A
non-person therefore sees seeded content only. The rule lives ONCE, in
`origin_entitlement.is_person`, and is applied in `notice_parts.notice_visible`, the verdict both
`read_notice_parts` and the `/resolve_instance` filter call.

Each arm runs on both callers. The CONTROL differs in exactly the caller (a person who is not the
dropper, same domains, same promoted notice).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

pytest.importorskip("rdflib", reason="the agent-fleet extra carries rdflib")

from agent_fleet.ontology_service import notice_parts as np_mod  # noqa: E402
from agent_fleet.utils import origin_entitlement as oe  # noqa: E402

NB = "http://internal/sustainment/doc/"
NOTICE_CLASS = "http://internal/sustainment/pcn#ProductChangeNotice"
OWNER = "SUSTAINMENT"
TABLE = {OWNER: frozenset({OWNER})}
DROPPER = "dropper@example.com"
STEWARD = "steward@example.com"
SVC = "svc:engine-a"


def _drop_row(nid, *, dropper=DROPPER):
    """A PROMOTED drop-derived notice whose origin owner_domain is exactly OWNER."""
    return {
        "notice": {"id": nid, "type": "PCN", "provenance_obtained_via": "user-drop",
                   "provenance_ingest_id": "sha256:" + nid},
        "mpns": ["5530-1"], "total": 1, "dropped_by": dropper, "has_artifact": True,
        "origin_owner_domain": OWNER, "origin_program": None, "origin_resolved_by": "steward",
        "promoted": True, "promoted_by": "human:bob",
    }


def _seeded_row(nid):
    return {"notice": {"id": nid, "type": "PCN", "mfr": "ACME"}, "mpns": ["5530-1"], "total": 1,
            "dropped_by": None, "has_artifact": False, "promoted": False, "promoted_by": None}


class _Rec:
    def __init__(self, d):
        self._d = d

    def data(self):
        return dict(self._d)


class _Driver:
    def __init__(self, rows):
        self.rows = rows

    def session(self, **kw):
        drv = self

        class _S:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def run(self, cypher, params=None, **kw2):
                missing = set(re.findall(r"\$(\w+)", cypher)) - set(params or {})
                assert not missing, f"statement run without ${sorted(missing)}"
                nid = params["notice_id"]
                return [_Rec(drv.rows[nid])] if nid in drv.rows else []
        return _S()


class _Jena:
    def __init__(self, instances):
        self.instances = list(instances)

    async def __call__(self, query, domain="MAINTENANCE", **kw):
        return list(self.instances)


def _read_visible(nid, row, caller, domains=(OWNER,)):
    """Whether read_notice_parts answers the notice (True) or as an unknown one (False)."""
    out = np_mod.read_notice_parts(
        _Driver({nid: row}), nid, caller_id=caller, viewer_domains=domains, table=TABLE,
        can_view_program=lambda program, who: True)
    if out.get("status") == "ok":
        return True
    assert out.get("reason") == "unknown_notice", out
    return False


@pytest.fixture()
def route(monkeypatch):
    from fastapi.testclient import TestClient
    from agent_fleet.ontology_service import main as mod
    monkeypatch.setattr(mod, "_load_domain_consumption_for_notice_parts", lambda: TABLE)
    monkeypatch.setattr(mod, "_notice_parts_can_view_program", lambda program, caller: True)

    def _go(nid, row, user_email, domains=(OWNER,)):
        monkeypatch.setattr(mod, "execute_sparql",
                            _Jena([{"s": NB + nid, "type": NOTICE_CLASS}]))
        monkeypatch.setattr(mod, "_NEO4J_DRIVER", _Driver({nid: row}))
        body = {"identifier": nid, "entitled_domains": list(domains)}
        if user_email is not None:
            body["user_email"] = user_email
        r = TestClient(mod.app).post("/resolve_instance", json=body)
        assert r.status_code == 200, r.text
        return [c["instance_id"] for c in r.json()["candidates"]]
    return _go


# -- the promoted drop notice, by caller --------------------------------------------------------

def test_corpus_shape_no_user_email_is_withheld_on_both_callers(route):
    row = _drop_row("PCN-D1")
    assert _read_visible("PCN-D1", row, "") is False
    assert route("PCN-D1", row, None) == []


def test_a_service_identity_is_withheld_on_both_callers(route):
    row = _drop_row("PCN-D1")
    assert _read_visible("PCN-D1", row, SVC) is False
    assert route("PCN-D1", row, SVC) == []


def test_control_a_person_who_is_not_the_dropper_sees_it_on_both_callers(route):
    row = _drop_row("PCN-D1")
    assert _read_visible("PCN-D1", row, STEWARD) is True
    assert route("PCN-D1", row, STEWARD) == [NB + "PCN-D1"]


def test_a_service_that_is_the_dropper_has_no_dropper_exemption(route):
    row = _drop_row("PCN-D1", dropper="svc:x")
    assert _read_visible("PCN-D1", row, "svc:x") is False
    assert route("PCN-D1", row, "svc:x") == []
    # control: a PERSON who is the dropper keeps the exemption
    person = _drop_row("PCN-D1", dropper=DROPPER)
    assert _read_visible("PCN-D1", person, DROPPER, domains=()) is True
    assert route("PCN-D1", person, DROPPER, domains=()) == [NB + "PCN-D1"]


# -- seeded content is unchanged ----------------------------------------------------------------

def test_a_seeded_notice_is_visible_to_the_corpus_shape_and_to_a_service(route):
    row = _seeded_row("PCN-S1")
    for caller in ("", SVC):
        assert _read_visible("PCN-S1", row, caller) is True
    assert route("PCN-S1", row, None) == [NB + "PCN-S1"]
    assert route("PCN-S1", row, SVC) == [NB + "PCN-S1"]


# -- the predicate --------------------------------------------------------------------------------

@pytest.mark.parametrize("caller", ["", "  ", None, "svc:a", " svc:a"])
def test_is_person_is_false_for_no_caller_and_for_a_service(caller):
    assert oe.is_person(caller) is False


def test_is_person_is_true_for_a_person():
    assert oe.is_person("alice@example.com") is True
