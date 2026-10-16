"""`/resolve_instance` withholds what `/notice_parts` withholds (architect Q7, 2026-10-10).

"Trace first, then rule. ... If yes, visible_by_origin gates it in a follow-up PR, same helper, no
new rule." The trace said yes: doc-tools' user-drop parser writes the notice into Jena
`SUSTAINMENT_INSTANCES` at extraction, before any promotion, and engine-o's resolver returned it
(and the components linked to it) to any caller.

WHAT IS SEALED. The route runs the SAME verdict `read_notice_parts` runs (`notice_visible`):
  * an unpromoted drop notice: the dropper sees it; a consumer with the right domain does not; no
    identity does not. The promoted twin is the control for each (it differs in one thing);
  * a withheld candidate is ABSENT, so the body equals the body of a Jena that never held the row;
  * a component linked only to withheld notices is withheld; one linked to ANY visible notice, or
    to none, is visible; a candidate that is not sustainment content is untouched;
  * a lookup failure (Neo4j or the link query) answers 503, never an unfiltered list;
  * (the wire -- the caller's identity and grant reaching the fan-out -- is sealed in
    tests/routing/test_resolve_instance_hears_the_caller.py, not here).

Q8 PRECONDITION (architect, 2026-10-10: "no provenance and no seed stamp -> withheld"; the flag is
`notice_parts.SEED_PROVENANCE_STAMPED`, sealed in test_q8_flips_on_one_precondition.py). Two arms
here are TODAY'S behaviour and FLIP when doc-tools stamps seed provenance:
`test_a_seeded_notice_is_visible_to_a_caller_with_no_identity` and
`test_a_notice_iri_with_no_neo4j_row_is_visible_to_a_caller_with_no_identity`. When the stamp lands,
`source_visibility`'s no-`provenance_ingest_id` branch and `visible_notice_ids`'s no-row branch flip
together, and these two arms are inverted with them.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from neo4j.exceptions import ServiceUnavailable

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

pytest.importorskip("rdflib", reason="the agent-fleet extra carries rdflib")

NB = "http://internal/sustainment/doc/"
CB = "http://internal/components/"
COMPONENT_CLASS = "http://internal/sustainment/pcn#Component"
NOTICE_CLASS = "http://internal/sustainment/pcn#ProductChangeNotice"
TABLE = {"SUSTAINMENT": frozenset({"SUSTAINMENT"})}
DROPPER = "dropper@example.com"
OTHER = "consumer@example.com"


def _drop_row(nid, *, promoted=False):
    return {
        "notice": {"id": nid, "type": "PCN", "provenance_obtained_via": "user-drop",
                   "provenance_ingest_id": "sha256:" + nid},
        "mpns": [], "dropped_by": DROPPER, "has_artifact": True,
        "origin_owner_domain": "SUSTAINMENT" if promoted else None,
        "origin_program": None,
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
    """Rows by notice id; an id absent from `rows` has NO Neo4j row. Records every session and run."""

    def __init__(self, rows, raises=False):
        self.rows, self.raises = rows, raises
        self.sessions, self.runs = 0, []

    def session(self, **kw):
        drv = self
        drv.sessions += 1

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
                drv.runs.append(nid)
                return [_Rec(drv.rows[nid])] if nid in drv.rows else []
        return _S()


class _Jena:
    """`instances`: the SUSTAINMENT_INSTANCES rows; `links`: component IRI -> notice IRIs."""

    def __init__(self, instances, links=None, link_raises=False):
        self.instances, self.links, self.link_raises = list(instances), links or {}, link_raises
        self.queries = []

    async def __call__(self, query, domain="MAINTENANCE", **kw):
        self.queries.append(query)
        if "subjectToNotice" in query:
            if self.link_raises:
                from agent_fleet.ontology_service import main as _m
                raise _m.SubstrateUnavailable("jena down")
            return [{"c": c, "n": n} for c, ns in self.links.items() if f"<{c}>" in query
                    for n in ns]
        return list(self.instances)


def _notice(nid):
    return {"s": NB + nid, "type": NOTICE_CLASS}


def _comp(mpn):
    return {"s": CB + mpn, "type": COMPONENT_CLASS}


@pytest.fixture()
def eo(monkeypatch):
    from agent_fleet.ontology_service import main as mod
    monkeypatch.setattr(mod, "_load_domain_consumption_for_notice_parts", lambda: TABLE)
    monkeypatch.setattr(mod, "_notice_parts_can_view_program", lambda program, caller: True)
    return mod


@pytest.fixture()
def call(eo, monkeypatch):
    from fastapi.testclient import TestClient

    def _go(identifier, *, jena, driver, user_email="", domains=("SUSTAINMENT",)):
        monkeypatch.setattr(eo, "execute_sparql", jena)
        monkeypatch.setattr(eo, "_NEO4J_DRIVER", driver)
        return TestClient(eo.app).post("/resolve_instance", json={
            "identifier": identifier, "user_email": user_email,
            "entitled_domains": list(domains)})
    return _go


def _ids(resp):
    assert resp.status_code == 200, resp.text
    return [c["instance_id"] for c in resp.json()["candidates"]]


# -- an unpromoted drop notice ---------------------------------------------------------------

def test_the_dropper_sees_an_unpromoted_drop_notice(call):
    r = call("PCN-D1", jena=_Jena([_notice("PCN-D1")]),
             driver=_Driver({"PCN-D1": _drop_row("PCN-D1")}), user_email=DROPPER)
    assert _ids(r) == [NB + "PCN-D1"]


def test_a_consumer_with_the_right_domain_does_not_see_it_but_sees_its_promoted_twin(call):
    jena = _Jena([_notice("PCN-D1")])
    withheld = call("PCN-D1", jena=jena, driver=_Driver({"PCN-D1": _drop_row("PCN-D1")}),
                    user_email=OTHER)
    control = call("PCN-D1", jena=jena,
                   driver=_Driver({"PCN-D1": _drop_row("PCN-D1", promoted=True)}),
                   user_email=OTHER)
    assert _ids(withheld) == []
    assert _ids(control) == [NB + "PCN-D1"]


def test_no_identity_does_not_see_it_but_the_dropper_does(call):
    jena = _Jena([_notice("PCN-D1")])
    drv = _Driver({"PCN-D1": _drop_row("PCN-D1")})
    assert _ids(call("PCN-D1", jena=jena, driver=drv, user_email="")) == []
    assert _ids(call("PCN-D1", jena=jena, driver=drv, user_email=DROPPER)) == [NB + "PCN-D1"]


def test_a_withheld_notice_answers_exactly_as_a_jena_that_never_held_it(call):
    held = call("PCN-D1", jena=_Jena([_notice("PCN-D1")]),
                driver=_Driver({"PCN-D1": _drop_row("PCN-D1")}), user_email=OTHER)
    never = call("PCN-D1", jena=_Jena([]), driver=_Driver({}), user_email=OTHER)
    visible = call("PCN-D1", jena=_Jena([_notice("PCN-D1")]),
                   driver=_Driver({"PCN-D1": _drop_row("PCN-D1")}), user_email=DROPPER)
    assert held.status_code == never.status_code == 200
    assert held.json() == never.json() == {"candidates": []}
    # the control: the body is not simply always empty
    assert visible.json() != held.json() and set(visible.json()) == set(held.json())


def test_a_withheld_component_answers_exactly_as_a_jena_that_never_held_it(call):
    held = call("5530-1", jena=_Jena([_comp("5530-1")], {CB + "5530-1": [NB + "PCN-D1"]}),
                driver=_Driver({"PCN-D1": _drop_row("PCN-D1")}), user_email=OTHER)
    never = call("5530-1", jena=_Jena([]), driver=_Driver({}), user_email=OTHER)
    assert held.json() == never.json() == {"candidates": []}


# -- Q8 precondition: these two arms flip when doc-tools stamps seed provenance ---------------

def test_a_seeded_notice_is_visible_to_a_caller_with_no_identity(call):
    """Q8 PRECONDITION: flips (to withheld) when `notice_parts.SEED_PROVENANCE_STAMPED` becomes True."""
    seeded = call("PCN-S1", jena=_Jena([_notice("PCN-S1")]),
                  driver=_Driver({"PCN-S1": _seeded_row("PCN-S1")}))
    control = call("PCN-S1", jena=_Jena([_notice("PCN-S1")]),
                   driver=_Driver({"PCN-S1": _drop_row("PCN-S1")}))
    assert _ids(seeded) == [NB + "PCN-S1"]
    assert _ids(control) == []


def test_a_notice_iri_with_no_neo4j_row_is_visible_to_a_caller_with_no_identity(call):
    """Q8 PRECONDITION: flips (to withheld) when `notice_parts.SEED_PROVENANCE_STAMPED` becomes True."""
    drv = _Driver({})
    norow = call("PCN-N1", jena=_Jena([_notice("PCN-N1")]), driver=drv)
    control = call("PCN-N1", jena=_Jena([_notice("PCN-N1")]),
                   driver=_Driver({"PCN-N1": _drop_row("PCN-N1")}))
    assert _ids(norow) == [NB + "PCN-N1"]
    assert drv.runs == ["PCN-N1"]  # it WAS looked up; the absence of a row is what decided
    assert _ids(control) == []


# -- components --------------------------------------------------------------------------------

def test_a_component_linked_only_to_a_withheld_drop_notice_is_withheld(call):
    jena = _Jena([_comp("5530-1")], {CB + "5530-1": [NB + "PCN-D1"]})
    withheld = call("5530-1", jena=jena, driver=_Driver({"PCN-D1": _drop_row("PCN-D1")}),
                    user_email=OTHER)
    control = call("5530-1", jena=jena,
                   driver=_Driver({"PCN-D1": _drop_row("PCN-D1", promoted=True)}),
                   user_email=OTHER)
    assert _ids(withheld) == []
    assert _ids(control) == [CB + "5530-1"]


def test_a_component_linked_to_a_withheld_notice_and_a_seeded_one_is_visible(call):
    links = {CB + "5530-1": [NB + "PCN-D1", NB + "PCN-S1"]}
    rows = {"PCN-D1": _drop_row("PCN-D1"), "PCN-S1": _seeded_row("PCN-S1")}
    both = call("5530-1", jena=_Jena([_comp("5530-1")], links), driver=_Driver(rows),
                user_email=OTHER)
    only_withheld = call("5530-1", jena=_Jena([_comp("5530-1")], {CB + "5530-1": [NB + "PCN-D1"]}),
                         driver=_Driver(rows), user_email=OTHER)
    assert _ids(both) == [CB + "5530-1"]
    assert _ids(only_withheld) == []


def test_a_component_with_no_linked_notice_is_visible_and_neo4j_is_not_asked(call):
    drv = _Driver({"PCN-D1": _drop_row("PCN-D1")})
    jena = _Jena([_comp("5530-1")], {})
    r = call("5530-1", jena=jena, driver=drv)
    assert _ids(r) == [CB + "5530-1"]
    assert drv.sessions == 0 and drv.runs == []
    # control: the same component WITH a withheld link is gone and Neo4j was asked
    r2 = call("5530-1", jena=_Jena([_comp("5530-1")], {CB + "5530-1": [NB + "PCN-D1"]}),
              driver=drv)
    assert _ids(r2) == [] and drv.runs == ["PCN-D1"]


def test_a_candidate_that_is_not_sustainment_content_is_untouched(call):
    other = {"s": "http://elsewhere/PROG-1", "type": "http://elsewhere/Program"}
    drv = _Driver({}, raises=True)  # asking Neo4j at all would 503
    jena = _Jena([other])
    r = call("PROG-1", jena=jena, driver=drv)
    assert _ids(r) == ["http://elsewhere/PROG-1"]
    assert drv.sessions == 0 and not any("subjectToNotice" in q for q in jena.queries)


def test_a_component_iri_that_could_break_the_link_query_is_withheld(call):
    bad = CB + '5530"x'
    jena = _Jena([{"s": bad, "type": COMPONENT_CLASS}])
    r = call('5530"x', jena=jena, driver=_Driver({}))
    assert _ids(r) == []
    assert not any("subjectToNotice" in q for q in jena.queries)
    ok = call("5530x", jena=_Jena([_comp("5530x")]), driver=_Driver({}))  # the control
    assert _ids(ok) == [CB + "5530x"]


def test_one_read_session_covers_every_notice_the_candidates_reach(call):
    links = {CB + "5530-1": [NB + "PCN-D1", NB + "PCN-D2"]}
    drv = _Driver({"PCN-D1": _drop_row("PCN-D1"), "PCN-D2": _drop_row("PCN-D2")})
    r = call("5530-1", jena=_Jena([_comp("5530-1")], links), driver=drv, user_email=OTHER)
    assert _ids(r) == []
    assert drv.sessions == 1 and sorted(drv.runs) == ["PCN-D1", "PCN-D2"]


# -- a lookup failure is a 503, never an unfiltered list ---------------------------------------
# The doubles raise the stores' real outage classes (neo4j's ServiceUnavailable, main's
# SubstrateUnavailable) because the route's catch is narrowed to `_VISIBILITY_OUTAGE`.

def test_a_neo4j_failure_answers_503(call):
    jena = _Jena([_notice("PCN-D1")])
    bad = call("PCN-D1", jena=jena, driver=_Driver({}, raises=True), user_email=DROPPER)
    ok = call("PCN-D1", jena=jena, driver=_Driver({"PCN-D1": _drop_row("PCN-D1")}),
              user_email=DROPPER)
    assert bad.status_code == 503 and "candidates" not in bad.json()
    assert ok.status_code == 200


def test_a_link_query_failure_answers_503(call):
    links = {CB + "5530-1": [NB + "PCN-D1"]}
    bad = call("5530-1", jena=_Jena([_comp("5530-1")], links, link_raises=True),
               driver=_Driver({}))
    ok = call("5530-1", jena=_Jena([_comp("5530-1")], links), driver=_Driver({}))
    assert bad.status_code == 503
    assert ok.status_code == 200


def test_a_disconnected_graph_answers_503_only_when_a_notice_is_involved(call):
    notice = call("PCN-D1", jena=_Jena([_notice("PCN-D1")]), driver=None)
    other = call("PROG-1", jena=_Jena([{"s": "http://elsewhere/PROG-1", "type": "t"}]),
                 driver=None)
    assert notice.status_code == 503
    assert other.status_code == 200
