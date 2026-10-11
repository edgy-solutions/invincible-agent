"""Directive E′: the SUSTAINMENT read "which parts does <notice> affect" and the provenance stamp on
its answer sources. Sealed on PCN26-182 as it stands on rev 180.

THE FIXTURE IS THE REV-180 GRAPH, READ, NOT IMAGINED. A read-only probe of the sandbox graph on
2026-10-08 found PCN26-182 like this:

- a `SustainmentNotice` carrying its ProvenanceBlock flattened as `provenance_*` keys
  (`obtained_via` user-drop, `standing` supervised, the drop's `ingest_id`);
- two `Component`s `SUBJECT_TO` it, `5530-182` and `5530-183`, whose edges carry no properties;
- an `IngestArtifact` with `dropped_by_authz_id` set to alice, and a `PROMOTION` fact by bob.

`_NOTICE` copies those values key for key. Seeded notices carry no `provenance_*` keys at all;
the seeded arm uses that shape.

WHAT THE ENVELOPE MUST SAY, and what this file reds on:

- `provenance_floor.obtained_via` is `user-drop`. Promotion does not change the rung.
- It is never `unstamped` for a source that has provenance.
- `ingest_ids` is `[]`, because the drop is promoted. The UNPROMOTED arm is the control. It is the
  same notice with no promotion fact, and its id must stay listed. Without that control,
  `ingest_ids == []` could be true for any reason.

THE GATEWAY IS DRIVEN, NOT RESTATED. The engine's sources go through the bff's own
`_sources_event_payload`, which is what emits the SSE `sources` event. So a projection that drops
`promoted_by`, or an emission site that stops passing the promoted set, reds here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agent_fleet.ontology_service import notice_parts as np_mod
from src.iagent import gateway as _gw
from src.iagent.provenance import validate_provenance

_REPO = Path(__file__).resolve().parents[1]

NOTICE = "PCN26-182"
INGEST_ID = "sha256:2a65ca553a868db5ab8110c154d61b15896bbffbba1b51660509a90bf266db00"
DROPPED_BY = "alice@example.com"
PROMOTED_BY = "human:bob@example.com"
PARTS = ["5530-182", "5530-183"]

#: The notice node's properties on rev 180, as the probe returned them.
_NOTICE = {
    "id": NOTICE,
    "type": "PCN",
    "needs_review": True,
    "mfr": "",
    "pub_date": "",
    "revision": "",
    "provenance_obtained_via": "user-drop",
    "provenance_ingest_id": INGEST_ID,
    "provenance_ingest_run": f"user-drop:{INGEST_ID}",
    "provenance_standing": "supervised",
    "provenance_authoritative_source": "unconfirmed-at-intake",
    "provenance_as_of": "unknown",
    "provenance_ingested_at": "2026-10-08T21:41:51Z",
    "provenance_derived_from": "",
}

#: A seeded notice: no `provenance_*` keys at all, as on the 12 seeded notices.
_SEEDED = {"id": "PCN-SEEDED-1", "type": "PCN", "mfr": "ACME"}


def _row(notice=_NOTICE, mpns=PARTS, dropped_by=DROPPED_BY, promoted_by=PROMOTED_BY, total=None):
    """`total` is the notice's whole part count (the statement returns it beside the page);
    default is the page's own length."""
    return {"notice": dict(notice), "mpns": list(mpns), "dropped_by": dropped_by,
            "promoted_by": promoted_by, "total": len(mpns) if total is None else total}


class _Record:
    def __init__(self, d):
        self._d = d

    def data(self):
        return dict(self._d)


class _Driver:
    """A recording double: it records the session's access mode and the statement it ran, and
    answers with the rows it was built with."""

    def __init__(self, rows):
        self.rows = rows
        self.modes: list = []
        self.runs: list = []

    def session(self, **kw):
        self.modes.append(kw.get("default_access_mode"))
        driver = self

        class _S:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def run(self, cypher, params):
                driver.runs.append((cypher, dict(params)))
                return [_Record(r) for r in driver.rows]
        return _S()


def _mat(sources):
    return {"assetKey": {"path": ["subtask_sources"]},
            "metadataEntries": [{"label": "sources_json", "text": json.dumps(sources)}]}


def _answer(**row_kw):
    return np_mod.read_notice_parts(_Driver([_row(**row_kw)]), NOTICE)


# ── the read ─────────────────────────────────────────────────────────────────────────────────

def test_PCN26_182_AFFECTS_ITS_TWO_PARTS_EACH_SOURCE_CARRYING_THE_FOUR_FIELDS():
    ans = _answer()
    assert ans["status"] == "ok" and ans["count"] == 2
    assert [p["mpn"] for p in ans["parts"]] == PARTS
    assert [s["mpn"] for s in ans["sources"]] == PARTS
    for s in ans["sources"]:
        assert s["obtained_via"] == "user-drop"
        assert s["ingest_id"] == INGEST_ID
        assert s["dropped_by"] == DROPPED_BY
        assert s["promoted_by"] == PROMOTED_BY
        # The block is complete as the floor's validator reads it, so the floor cannot read it as
        # unstamped.
        validate_provenance(s["provenance"])
        assert s["provenance"]["ingest_id"] == INGEST_ID
        assert s["provenance"]["standing"] == "supervised"
        # The two top-level copies come FROM the block, so they cannot disagree with it.
        assert s["obtained_via"] == s["provenance"]["obtained_via"]
        assert s["ingest_id"] == s["provenance"]["ingest_id"]
        assert s["uri"] == "http://internal/components/" + s["mpn"]
    assert ans["output_uri"] == np_mod.OUTPUT_URI


def test_THE_READ_IS_ONE_READ_SESSION_RUNNING_THE_STATEMENT_WITH_THE_NOTICE_AS_A_PARAMETER():
    d = _Driver([_row()])
    np_mod.read_notice_parts(d, NOTICE)
    assert d.modes == ["READ"]
    assert d.runs == [(np_mod.NOTICE_PARTS_CYPHER,
                       {"notice_id": NOTICE, "offset": 0, "limit": np_mod.NOTICE_PARTS_PAGE_SIZE})]


def test_THE_STATEMENT_READS_THE_EDGES_AND_FACTS_THE_REV_180_GRAPH_CARRIES():
    """THE STATEMENT TEXT IS SEALED. A recording double proves what was sent, never what the store
    would match. So the names that tie the statement to the rev-180 shape are asserted on the text
    itself: the notice is a parameter, never interpolated, and the statement writes nothing."""
    c = np_mod.NOTICE_PARTS_CYPHER
    assert re.search(r"\(c:SUSTAINMENT:Component\)-\[:SUBJECT_TO\]->\(n\)", c)
    assert re.search(r"\(n:SUSTAINMENT:SustainmentNotice \{id: \$notice_id\}\)", c)
    assert "IngestArtifact {ingest_id: n.provenance_ingest_id}" in c
    assert re.search(r"\(a\)-\[p:PROMOTION\]->\(a\)", c)
    assert "a.dropped_by_authz_id AS dropped_by" in c
    assert "p.promoted_by" in c
    assert not re.search(r"\b(CREATE|MERGE|SET|DELETE|REMOVE)\b", c)
    assert NOTICE not in c


# ── the envelope: the bff's own sources event ────────────────────────────────────────────────

def test_A_PROMOTED_DROP_READS_USER_DROP_AND_IS_NOT_LISTED_UNVERIFIED():
    projected, floor = _gw._sources_event_payload(_mat(_answer()["sources"]))
    assert floor == {"obtained_via": "user-drop", "ingest_ids": [], "unidentified": 0}
    for s in projected:
        assert (s["obtained_via"], s["ingest_id"], s["dropped_by"], s["promoted_by"]) == (
            "user-drop", INGEST_ID, DROPPED_BY, PROMOTED_BY)
        assert s["provenance"]["ingest_id"] == INGEST_ID


def test_CONTROL_THE_SAME_DROP_UNPROMOTED_STAYS_LISTED():
    """It differs from the arm above in ONE thing, the PROMOTION fact. That is what makes the
    `ingest_ids == []` above mean promoted."""
    ans = _answer(promoted_by=None)
    assert all(s["promoted_by"] is None for s in ans["sources"])
    _, floor = _gw._sources_event_payload(_mat(ans["sources"]))
    assert floor == {"obtained_via": "user-drop", "ingest_ids": [INGEST_ID], "unidentified": 0}


def test_A_SOURCE_WITH_PROVENANCE_IS_NEVER_UNSTAMPED_AND_ONE_WITHOUT_IS():
    """The floor reads `unstamped` exactly when a source has no block. A seeded notice has no
    `provenance_*` keys, so its sources carry no block and the floor reads `unstamped`. The rev-180
    drop's sources carry one, and the floor never does."""
    stamped = _answer()["sources"]
    seeded = np_mod.read_notice_parts(_Driver([_row(notice=_SEEDED, dropped_by=None,
                                                    promoted_by=None)]), "PCN-SEEDED-1")["sources"]
    assert seeded and all("provenance" not in s for s in seeded)
    assert all(s["obtained_via"] is None and s["ingest_id"] is None for s in seeded)
    _, f_stamped = _gw._sources_event_payload(_mat(stamped))
    _, f_seeded = _gw._sources_event_payload(_mat(seeded))
    assert f_stamped["obtained_via"] == "user-drop"
    assert f_seeded["obtained_via"] == "unstamped"


def test_A_PROMOTED_BY_WITH_NO_INGEST_ID_PROMOTES_NOTHING():
    """`promoted_ingest_ids` reads the block's id. A `promoted_by` on a source whose block names no
    ingest_id has nothing to promote, and it stays `unidentified`."""
    src = _answer()["sources"][0]
    del src["provenance"]["ingest_id"]
    _, floor = _gw._sources_event_payload(_mat([src]))
    assert floor == {"obtained_via": "user-drop", "ingest_ids": [], "unidentified": 1}


# ── the three answers ───────────────────────────────────────────────────────────────────────

def test_AN_UNKNOWN_NOTICE_IS_REFUSED_AND_A_KNOWN_ONE_WITH_NO_PARTS_IS_REFUSED_AS_NO_AFFECTED_PARTS():
    """Two refusals that must stay two: the graph does not hold the notice, or it holds it and the
    notice names no part. An empty `ok` list would read as "checked, none"."""
    unknown = np_mod.read_notice_parts(_Driver([]), "PCN-NOPE")
    assert (unknown["status"], unknown["reason"]) == ("refused", "unknown_notice")
    empty = np_mod.read_notice_parts(_Driver([_row(mpns=[])]), NOTICE)
    assert (empty["status"], empty["reason"], empty["sources"]) == (
        "refused", "no_affected_parts", [])
    assert empty["reason"] != unknown["reason"]


def test_NO_NOTICE_ID_IS_REFUSED_BEFORE_THE_GRAPH_IS_READ():
    d = _Driver([_row()])
    ans = np_mod.read_notice_parts(d, "")
    assert (ans["status"], ans["reason"]) == ("refused", "notice_required")
    assert d.runs == []


@pytest.mark.parametrize("params,resolved,want", [
    ({"notice_id": NOTICE}, "", NOTICE),
    ({}, "http://internal/sustainment/doc/" + NOTICE, NOTICE),
    ({"notice_id": " "}, "http://internal/sustainment/doc/" + NOTICE, NOTICE),
    ({}, "http://internal/components/5530-182", ""),
    ({}, "", ""),
], ids=["slot", "resolved-notice-iri", "blank-slot-falls-to-iri", "a-part-iri-is-not-a-notice",
        "nothing"])
def test_THE_NOTICE_ID_COMES_FROM_THE_SLOT_OR_THE_RESOLVED_NOTICE_IRI_NEVER_PROSE(params, resolved, want):
    assert np_mod.notice_id_of(params, resolved) == want


# ── the route ───────────────────────────────────────────────────────────────────────────────

def _route(monkeypatch, driver, body):
    from fastapi.testclient import TestClient
    from agent_fleet.ontology_service import main as eo
    monkeypatch.setattr(eo, "_NEO4J_DRIVER", driver)
    return TestClient(eo.app).post("/notice_parts", json=body)


def test_THE_ROUTE_ANSWERS_THE_DISPATCH_BODY_THE_SUPERVISOR_SENDS(monkeypatch):
    d = _Driver([_row()])
    r = _route(monkeypatch, d, {
        "user_query": "which parts does PCN26-182 affect",
        "entitled_domains": ["SUSTAINMENT"],
        "resolved_instance_id": "http://internal/sustainment/doc/" + NOTICE,
        "params": {}, "routed_verb_iri": np_mod.VERB,
    })
    assert r.status_code == 200, r.text
    assert [s["mpn"] for s in r.json()["sources"]] == PARTS
    assert d.runs and d.runs[0][1] == {"notice_id": NOTICE, "offset": 0,
                                       "limit": np_mod.NOTICE_PARTS_PAGE_SIZE}


@pytest.mark.parametrize("domains", [[], ["COST"]], ids=["empty-scope", "other-domain"])
def test_THE_ROUTE_REFUSES_A_CALLER_WITHOUT_SUSTAINMENT_BEFORE_THE_GRAPH_IS_READ(monkeypatch, domains):
    d = _Driver([_row()])
    r = _route(monkeypatch, d, {"entitled_domains": domains, "params": {"notice_id": NOTICE}})
    assert r.status_code == 200 and r.json()["reason"] == "not_entitled"
    assert d.runs == [] and r.json()["sources"] == []


# ── declared: the output class, the gating row, the census row ──────────────────────────────

def test_THE_OUTPUT_CLASS_IS_DECLARED_BY_A_TTL_THE_PRIME_MANIFEST_SHIPS():
    import rdflib
    from rdflib.namespace import OWL, RDF
    manifest = (_REPO / "setup" / "prime_databases.py").read_text(encoding="utf-8")
    shipped = set(re.findall(r'"path":\s*"(ontologies/[^"]+\.ttl)"', manifest))
    assert shipped, "no ontology paths parsed from the prime manifest — instrument failure"
    declared = set()
    for rel in shipped:
        ttl = _REPO / "setup" / rel
        if ttl.exists():
            g = rdflib.Graph().parse(ttl)
            declared |= {str(s) for s in g.subjects(RDF.type, OWL.Class)}
    assert np_mod.OUTPUT_URI in declared
    assert np_mod.INPUT_URI in declared


def test_THE_ROUTE_IS_DECLARED_IN_THE_GATING_MANIFEST_AS_DOMAIN_SCOPED():
    import yaml
    m = yaml.safe_load((_REPO / "docs/architecture/endpoint_gating_manifest.yaml").read_text(
        encoding="utf-8"))
    rows: list = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("path") == "/notice_parts":
                rows.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(m)
    assert len(rows) == 1, rows
    assert (rows[0]["gate"], rows[0]["class"]) == ("domain-scope", "gated")


def test_THE_CENSUS_ASKS_THE_SHEET_QUESTION_AND_EXPECTS_THIS_VERB():
    from iagent_pure import walk_census as wc
    rows = [r for r in wc.load_rows(_REPO / "docs/measurements/walk-census.yaml")
            if r.sheet == "docs/measurements/sustainment-walk-sheet.md"]
    assert len(rows) == 1
    assert rows[0].question == "which parts does PCN26-182 affect"
    assert rows[0].expect_verb == wc._camel_to_snake(np_mod.VERB.split(":", 1)[1])
    assert wc.reconcile(rows, _REPO).problems == []
