"""`/enumerate_instances` withholds what `/notice_parts` and `/resolve_instance` withhold (ruled
2026-10-10, (d): "enumerateInstances gets the same gate"). FILTER ONLY, on the wire lane/74 built
(sealed in tests/routing/test_enumerate_instances_hears_the_caller.py, not here).

WHAT IS SEALED. After the fan-out, the members of the first provider that answers `members` pass
through `_filter_sustainment_candidates` -- the function `/resolve_instance` runs, no second rule:
  * a stranger loses the drop-derived notice and the component linked only to it; the seeded notice
    and a non-sustainment IRI stay; `count` equals what was returned;
  * the dropper, and a person holding OWNER on a promoted notice, lose nothing (the controls);
  * a non-person (no email, or a service id) is treated as a stranger even holding OWNER;
  * WITHHELD IS UNKNOWN: a provider whose every member is withheld has answered `empty`, so the
    next provider is asked, and with none the answer is the one an `empty` provider gives;
  * the provider's `count` does not reveal how many were withheld;
  * a lookup failure is the 503 `/resolve_instance` answers for the same failure;
  * the filter is the SAME function (AST).
RESIDUAL: `too_many` carries a count and no members and is not filtered.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from neo4j.exceptions import ServiceUnavailable

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

pytest.importorskip("rdflib", reason="the agent-fleet extra carries rdflib")

NB = "http://internal/sustainment/doc/"
CB = "http://internal/components/"
TABLE = {"SUSTAINMENT": frozenset({"SUSTAINMENT"})}
OWNER = "SUSTAINMENT"
DROPPER = "dropper@example.com"
STRANGER = "consumer@example.com"
DROP_N, SEED_N = NB + "PCN-D1", NB + "PCN-S1"
COMP = CB + "5530-1"
OTHER_IRI = "http://elsewhere/PROG-1"
MAIN = _ROOT / "agent_fleet" / "ontology_service" / "main.py"


def _m(iri):
    return {"instance_id": iri, "label": iri.rsplit("/", 1)[-1]}


ALL4 = [_m(DROP_N), _m(COMP), _m(SEED_N), _m(OTHER_IRI)]


def _drop_row(nid, *, promoted=False):
    return {
        "notice": {"id": nid, "type": "PCN", "provenance_obtained_via": "user-drop",
                   "provenance_ingest_id": "sha256:" + nid},
        "mpns": [], "dropped_by": DROPPER, "has_artifact": True,
        "origin_owner_domain": OWNER if promoted else None, "origin_program": None,
        "origin_resolved_by": "steward" if promoted else None,
        "promoted": promoted, "promoted_by": "human:bob" if promoted else None,
    }


def _seeded_row(nid):
    return {"notice": {"id": nid, "type": "PCN", "mfr": "ACME"}, "mpns": [], "dropped_by": None,
            "has_artifact": False, "promoted": False, "promoted_by": None}


class _Rec:
    def __init__(self, d):
        self._d = d

    def data(self):
        return dict(self._d)


class _Driver:
    """Rows by notice id; an id absent has NO Neo4j row."""

    def __init__(self, rows, raises=False):
        self.rows, self.raises = rows, raises

    def session(self, **kw):
        drv = self

        class _S:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def run(self, cypher, params=None, **kw2):
                if drv.raises:
                    raise ServiceUnavailable("neo4j down")
                # Neo4j refuses a statement run without one of its $parameters; so does this double.
                missing = set(re.findall(r"\$(\w+)", cypher)) - set(params or {})
                assert not missing, f"statement run without ${sorted(missing)}"
                nid = params["notice_id"]
                return [_Rec(drv.rows[nid])] if nid in drv.rows else []
        return _S()


class _Jena:
    """The component -> notice link lookup."""

    def __init__(self, links):
        self.links = links

    async def __call__(self, query, domain="MAINTENANCE", **kw):
        if "subjectToNotice" in query:
            return [{"c": c, "n": n} for c, ns in self.links.items() if f"<{c}>" in query
                    for n in ns]
        return []


class _ResolveJena:
    """What `/resolve_instance` reads: the notice row, and no component links."""

    async def __call__(self, query, domain="MAINTENANCE", **kw):
        if "subjectToNotice" in query:
            return []
        return [{"s": DROP_N, "type": "http://internal/sustainment/pcn#ProductChangeNotice"}]


def _rows(promoted=False):
    return {"PCN-D1": _drop_row("PCN-D1", promoted=promoted), "PCN-S1": _seeded_row("PCN-S1")}


@pytest.fixture()
def eo(monkeypatch):
    from agent_fleet.ontology_service import main as mod
    monkeypatch.setattr(mod, "_load_domain_consumption_for_notice_parts", lambda: TABLE)
    monkeypatch.setattr(mod, "_notice_parts_can_view_program", lambda program, caller: True)
    monkeypatch.setattr(mod, "execute_sparql", _Jena({COMP: [DROP_N]}))
    monkeypatch.setattr(mod, "_NEO4J_DRIVER", _Driver(_rows()))
    return mod


@pytest.fixture()
def ask(eo, monkeypatch):
    """ask(answers, ...) -> response. `answers`: provider name -> the body that provider returns."""
    from fastapi.testclient import TestClient

    def _go(answers, *, user_email="", domains=(), driver=None):
        if driver is not None:
            monkeypatch.setattr(eo, "_NEO4J_DRIVER", driver)

        class _Client:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json=None, **kw):
                return SimpleNamespace(status_code=200, json=lambda: dict(answers[url]))

        monkeypatch.setattr(eo.httpx, "AsyncClient", _Client)
        rows = [{"provider": n, "endpoint_url": n} for n in answers]
        monkeypatch.setattr(eo, "_discover_enumerate_providers",
                            lambda *a, **k: eo.MeshResult.answered(rows))
        return TestClient(eo.app).post("/enumerate_instances", json={
            "class_uri": "http://x#C", "user_email": user_email,
            "entitled_domains": list(domains)})
    return _go


def _members(members, count=None):
    return {"outcome": "members", "members": members,
            "count": len(members) if count is None else count}


EMPTY = {"outcome": "empty", "members": [], "count": 0}


def _ids(resp):
    assert resp.status_code == 200, resp.text
    return [m["instance_id"] for m in resp.json()["members"]]


# -- the four-member list ----------------------------------------------------------------------

def test_STRANGER_loses_the_notice_and_its_component_and_count_matches(ask):
    r = ask({"p1": _members(ALL4)}, user_email=STRANGER)
    assert _ids(r) == [SEED_N, OTHER_IRI]
    assert r.json()["count"] == 2


def test_DROPPER_sees_all_four(ask):
    r = ask({"p1": _members(ALL4)}, user_email=DROPPER)
    assert _ids(r) == [DROP_N, COMP, SEED_N, OTHER_IRI]
    assert r.json()["count"] == 4


def test_ENTITLED_person_sees_all_four_once_the_notice_is_promoted(ask):
    # differs from STRANGER in exactly the grant (OWNER in entitled_domains) and the promotion
    r = ask({"p1": _members(ALL4)}, user_email=STRANGER, domains=[OWNER],
            driver=_Driver(_rows(promoted=True)))
    assert _ids(r) == [DROP_N, COMP, SEED_N, OTHER_IRI]
    still = ask({"p1": _members(ALL4)}, user_email=STRANGER, domains=[OWNER],
                driver=_Driver(_rows()))  # granted but not promoted
    assert _ids(still) == [SEED_N, OTHER_IRI]
    ungranted = ask({"p1": _members(ALL4)}, user_email=STRANGER, domains=[],
                    driver=_Driver(_rows(promoted=True)))  # promoted but not granted
    assert _ids(ungranted) == [SEED_N, OTHER_IRI]


@pytest.mark.parametrize("who", ["", "svc:x"])
def test_NON_PERSON_holding_OWNER_is_withheld(ask, who):
    """Was: answered seeded content only. Now (2026-10-16, gov #39 closed): REFUSED 422
    `no_person` -- a non-person gets nothing, a fortiori not the promoted member its OWNER
    grant would have unlocked. Shape sealed in test_enumerate_instances_refuses_a_caller_who_is_not_a_person.py."""
    r = ask({"p1": _members(ALL4)}, user_email=who, domains=[OWNER],
            driver=_Driver(_rows(promoted=True)))
    assert r.status_code == 422, r.text
    assert r.json()["error"] == "no_person"
    assert "members" not in r.json()


# -- withheld is unknown -----------------------------------------------------------------------

def test_ALL_WITHHELD_falls_to_the_NEXT_PROVIDER(ask):
    answers = {"p1": _members([_m(DROP_N)]), "p2": _members([_m(OTHER_IRI)])}
    stranger = ask(answers, user_email=STRANGER)
    dropper = ask(answers, user_email=DROPPER)
    assert _ids(stranger) == [OTHER_IRI] and stranger.json()["provider"] == "p2"
    assert _ids(dropper) == [DROP_N] and dropper.json()["provider"] == "p1"


def test_ALL_WITHHELD_with_no_second_provider_answers_as_an_empty_provider_does(ask):
    withheld = ask({"p1": _members([_m(DROP_N)])}, user_email=STRANGER)
    empty = ask({"p1": EMPTY}, user_email=STRANGER)
    assert withheld.status_code == 200
    assert withheld.json() == empty.json() == {"outcome": "empty", "members": [], "count": 0}
    # control: the dropper's answer is not simply always empty
    assert ask({"p1": _members([_m(DROP_N)])}, user_email=DROPPER).json()["outcome"] == "members"


def test_COUNT_DOES_NOT_LEAK_the_withheld(ask):
    four = [_m(DROP_N), _m(SEED_N), _m(OTHER_IRI), _m("http://elsewhere/PROG-2")]
    stranger = ask({"p1": _members(four, count=10)}, user_email=STRANGER)
    dropper = ask({"p1": _members(four, count=10)}, user_email=DROPPER)
    assert len(_ids(stranger)) == 3 and stranger.json()["count"] == 9
    assert len(_ids(dropper)) == 4 and dropper.json()["count"] == 10


# -- a lookup failure --------------------------------------------------------------------------

def test_LOOKUP_FAILURE_is_the_503_resolve_instance_answers(eo, ask, monkeypatch):
    from fastapi.testclient import TestClient
    bad = _Driver({}, raises=True)
    got = ask({"p1": _members(ALL4)}, user_email=STRANGER, driver=bad)
    monkeypatch.setattr(eo, "execute_sparql", _ResolveJena())
    ref = TestClient(eo.app).post("/resolve_instance", json={
        "identifier": "PCN-D1", "user_email": STRANGER, "entitled_domains": []})
    assert ref.status_code == 503, "the reference failure must be the route's own 503"
    assert got.status_code == 503 and "members" not in got.json()
    assert got.json() == ref.json()


# -- one filter --------------------------------------------------------------------------------

def test_SHARED_FILTER_enumerate_calls_the_one_function_and_nothing_else_tests_the_prefixes():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    called = {c.func.id for c in ast.walk(fns["enumerate_instances"])
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    # directly, or through the one helper whose only job is to call it (and map its raise to 503)
    assert "_filter_sustainment_candidates" in called or (
        "_gate_enumerated_members" in called and "_filter_sustainment_candidates" in {
            c.func.id for c in ast.walk(fns["_gate_enumerated_members"])
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)})
    prefixes = {"_NOTICE_IRI_PREFIX", "_COMPONENT_IRI_PREFIX"}
    users = {name for name, fn in fns.items()
             if prefixes & {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}}
    assert users == {"_filter_sustainment_candidates"}, users
