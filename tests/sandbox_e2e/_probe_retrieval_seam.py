"""LIVE PROBE — what does `weaviate_hybrid_search` hand back, and is the vector half alive?

Measured 2026-09-19 against sandbox (engine-o image `91d8d34`, weaviate 1.27.0, client 4.21.0),
answering the fork Lane 1 left open on `find_orphaned_hazards`: *"the search returned one" vs
"the search returned ten and something after it kept one"*.

    THE SEAM RETURNS ONE.  At limit=10 and at limit=50.

**AND THE REASON IS THAT THE VECTOR HALF RETURNS NOTHING, FOR EVERY QUERY, ON THIS COLLECTION.**

    near_vector(query vector)          n=0
    hybrid alpha=1.00 (pure vector)    n=0
    hybrid alpha=0.00 (pure BM25)      n=1
    hybrid AS SHIPPED                  n=1     <- its entire output is its BM25 half

`embed_query` is healthy (768 dims, unit norm), so the `"falling back to BM25"` line — which only
prints when `embed_query` RAISES — never printed. **The degradation has no log line.**

**THE POSITIVE CONTROL IS WHAT NAMED THE CAUSE.** A matcher returning zero reads like a finding,
so this asks the store to find an object BY THAT OBJECT'S OWN STORED VECTOR. An object is its own
nearest neighbour, or there is no index:

    near_vector(safety#Hazard's own stored vector)   n=0
    nearObject{id:<that object>}  ->  ERROR
        "vectorize search vector: nearObject params: vector not found for target: default"

while `_additional{vector}` returns 768 dims for the same object in the same breath. Both are
true: the row carries a vector in the LEGACY unnamed slot, and the named space `default` — the
one the index is configured on and the only one a search can target — holds nothing.

    collection       vectorizer        vectorIndexType   vectorConfig   nearObject(self)
    OntologyClass    None              None              ['default']    ERROR
    Predicate        None              None              ['default']    ERROR
    DocumentChunk    text2vec-ollama   hnsw              None           n=3, self first  <- CONTROL

**Weaviate is healthy and vector search works on this server.** The two broken collections are
the two the router runs on: class recall and verb recall. Both are created by a bare
`collections.create(...)` with no vector configuration, then written with
`batch.add_object(vector=[...])` — `doc_tools/assets/ontology_assets.py:386` (OntologyClass),
`agent_fleet/mesh_registrar/v2_substrate.py:409` and `scripts/seed_sandbox_predicates.py:306`
(Predicate).

**NO INSTRUMENT THAT ASKS "IS THIS ROW VECTORISED?" CAN SEE THIS.** `_additional{vector}` and the
client's `include_vector` both read the legacy slot, the shard reports
`vectorIndexingStatus=READY vectorQueueLength=0` (true — nothing queued, nothing in it), and
24,924 of 26,239 rows do carry a vector. Only asking the server to USE one shows the defect. A
row-count seal over this substrate is GREEN.

THIS IS A PROBE, NOT A SEAL. It needs a live substrate and cannot go red on its own; the seal this
argues for is a retrievability line in the walk census (`nearObject(self)` on one row per
collection), which is a different assertion from the liveness check that passes here today.

Run it inside the engine-o pod, which owns the seam and the embedder:

    kubectl -n sandbox exec -i <engine-o pod> -- python - < tests/sandbox_e2e/_probe_retrieval_seam.py
"""
from __future__ import annotations

import json
import os

import requests

import main  # engine-o's module; flat layout inside the image
import weaviate.classes as wvc
from utils.embed import embed_query
from utils.weaviate_utils import create_weaviate_client

#: The census question `find_orphaned_hazards` OWNS, verbatim from
#: docs/measurements/safety-walk-sheet.md row 2.
QUERY = "what hazards are unattended"
DOMAIN = "SUSTAINMENT"
HAZARD = "http://internal/sustainment/safety#Hazard"

BASE = "http://%s:%s" % (os.environ.get("WEAVIATE_HOST", "iagent-weaviate"),
                         os.environ.get("WEAVIATE_PORT", "8080"))


def _gql(query: str) -> dict:
    return requests.post(BASE + "/v1/graphql", json={"query": query}, timeout=120).json()


def _rows(resp: dict) -> list:
    return (((resp.get("data") or {}).get("Get") or {}).get("OntologyClass") or [])


def _self_verdict(cls: str, uuid: str, k: int = 5) -> str:
    """Is this object findable by its own vector? SELF WITHIN THE TOP-K AT ~0, never `rows[0]`.

    DUPLICATE VECTORS EXIST AND THIS IS NOT THEORETICAL. `IOF_Core` is loaded into two domains;
    measured, the largest group of rows sharing one exact vector is 2 in both routing
    collections. Demonstrated on a scratch pair: `nearObject(a)` returned **b first**, so
    `rows[0] is self` would have reported a correctly repaired row as broken. Tie order is the
    store's to choose.

    The same semantics as `scripts/backfill_vector_space.verify_self`, deliberately — two
    instruments answering one question must answer it the same way.
    """
    r = requests.post(BASE + "/v1/graphql", timeout=120, json={"query":
        '{Get{%s(nearObject:{id:"%s"} limit:%d){_additional{id distance}}}}' % (cls, uuid, k)}).json()
    if r.get("errors"):
        return "REFUSED: " + r["errors"][0].get("message", "")[:90]
    rows = (((r.get("data") or {}).get("Get") or {}).get(cls) or [])
    for row in rows:
        add = row.get("_additional") or {}
        if add.get("id") == uuid:
            ties = sum(1 for x in rows
                       if abs((x.get("_additional") or {}).get("distance") or 0.0) <= 1e-4)
            return "RETRIEVABLE (self in top-%d, distance %s, %d tied at ~0)" % (
                k, add.get("distance"), ties)
    return "NOT RETRIEVABLE (self absent from top-%d of %d rows)" % (k, len(rows))


def seam(label: str, **kw) -> None:
    """The shipped function itself — NOT a reimplementation of it."""
    try:
        got = main._weaviate_hybrid_search_sync(**kw)
    except Exception as exc:
        print("  %-30s RAISED %s: %s" % (label, type(exc).__name__, exc))
        return
    print("  %-30s n=%-3d %s" % (label, len(got), json.dumps(kw)))
    for r in got[:10]:
        print("       %-62s score=%s" % (r.get("uri"), r.get("score")))


def main_probe() -> None:
    main._WEAVIATE_CLIENT = create_weaviate_client()
    coll = main._WEAVIATE_CLIENT.collections.get("OntologyClass")
    filt = wvc.query.Filter.by_property("domain").equal(DOMAIN)
    md = wvc.query.MetadataQuery(distance=True)

    print("=== 1. THE SEAM, as main.py:2329 calls it — with its controls")
    seam("subject limit=10", query=QUERY, domain=DOMAIN, domains=None, limit=10)
    seam("subject limit=50", query=QUERY, domain=DOMAIN, domains=None, limit=50)
    seam("CONTROL 'part'", query="part", domain=DOMAIN, domains=None, limit=10)
    seam("CONTROL 'hazard'", query="hazard", domain=DOMAIN, domains=None, limit=10)
    seam("CONTROL no filter", query=QUERY, domain=None, domains=None, limit=10)

    print()
    print("=== 2. IS THE EMBEDDER AT FAULT? (it is not)")
    vec = embed_query(QUERY)
    print("  dims=%d  norm=%.6f  all_zero=%s"
          % (len(vec), sum(x * x for x in vec) ** 0.5,
             all(float(x) == 0.0 for x in vec)))

    print()
    print("=== 3. THE TWO HALVES, SEPARATELY")
    for label, res in (
        ("near_vector", coll.query.near_vector(
            near_vector=vec, limit=10, filters=filt, return_metadata=md)),
        ("bm25", coll.query.bm25(query=QUERY, limit=10, filters=filt)),
        ("hybrid AS SHIPPED", coll.query.hybrid(
            query=QUERY, vector=vec, limit=10, filters=filt)),
        ("hybrid alpha=1 (vector)", coll.query.hybrid(
            query=QUERY, vector=vec, alpha=1.0, limit=10, filters=filt)),
        ("hybrid alpha=0 (bm25)", coll.query.hybrid(
            query=QUERY, vector=vec, alpha=0.0, limit=10, filters=filt)),
    ):
        print("  %-26s n=%d" % (label, len(res.objects)))

    print()
    print("=== 4. THE POSITIVE CONTROL — find an object by its OWN stored vector")
    own = _rows(_gql('{Get{OntologyClass(where:{path:["uri"],operator:Equal,'
                     'valueText:"%s"} limit:1){uri _additional{id vector}}}}' % HAZARD))
    if not own:
        print("  safety#Hazard ABSENT — instrument failure, not a finding")
        return
    add = own[0]["_additional"]
    stored, oid = add["vector"], add["id"]
    print("  safety#Hazard stored vector: %d dims (the LEGACY slot answers)" % len(stored))
    print("  near_vector(own vector)        n=%d"
          % len(coll.query.near_vector(near_vector=stored, limit=5,
                                       return_metadata=md).objects))
    print("  nearObject(self)              %s" % _self_verdict("OntologyClass", oid))

    print()
    print("=== 5. THE BLAST RADIUS — which collections answer a vector query")
    for cls in ("OntologyClass", "Predicate", "DocumentChunk"):
        sch = requests.get(BASE + "/v1/schema/" + cls, timeout=60).json()
        one = _gql("{Get{%s(limit:1){_additional{id}}}}" % cls)
        got = (((one.get("data") or {}).get("Get") or {}).get(cls) or [])
        verdict = "no objects"
        if got:
            # `got[0]` only PICKS a row to probe — it is not an assertion about ordering.
            verdict = _self_verdict(cls, got[0]["_additional"]["id"])
        print("  %-15s vectorIndexType=%-6r vectorConfig=%-12r %s"
              % (cls, sch.get("vectorIndexType"),
                 list(sch.get("vectorConfig") or {}) or None, verdict))

    print()
    print("=== 6. WHY THIS QUERY — BM25 does not stem, so the plural matches nothing")
    for q in ("hazard", "hazards", "unattended", QUERY):
        rows = _rows(_gql('{Get{OntologyClass(bm25:{query:"%s"} where:{path:["domain"],'
                          'operator:Equal,valueText:"%s"} limit:5){uri}}}' % (q, DOMAIN)))
        print("  bm25 %-32r n=%d  %s"
              % (q, len(rows), ", ".join(x["uri"].rsplit("#", 1)[-1] for x in rows)))

    print()
    print("=== 7. WOULD A WORKING VECTOR HALF FIX THIS ROW? (hand-scored subset of 6)")

    def cos(a, b):
        return (sum(x * y for x, y in zip(a, b))
                / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)))

    scored = []
    for uri in (HAZARD,
                "http://internal/sustainment/safety#Mitigation",
                "http://internal/sustainment/safety#RiskAssessment",
                "http://internal/sustainment/safety#SafetyCriticalItem",
                "http://internal/sustainment/product#Part",
                "http://internal/sustainment/product#PartUsage"):
        r = _rows(_gql('{Get{OntologyClass(where:{path:["uri"],operator:Equal,'
                       'valueText:"%s"} limit:1){_additional{vector}}}}' % uri))
        if r:
            scored.append((cos(vec, r[0]["_additional"]["vector"]), uri))
    for score, uri in sorted(scored, reverse=True):
        print("  cos=%.4f  %s" % (score, uri))
    print("  NOT the pool a fixed search would build — it answers only whether the query")
    print("  vector prefers Hazard to Part, which is what the shipped search never asked.")


if __name__ == "__main__":
    main_probe()
