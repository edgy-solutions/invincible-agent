#!/usr/bin/env python3
"""READ-ONLY: does the VECTOR arm change the ranking at all, row for row?

THE QUESTION, and why it is not the retrievability census's question. The census asks whether
`nearObject(self)` can reach a row. This asks the next verb over: given that the index CAN reach
89 of `Predicate`'s 133 rows, does adding the vector to the query change WHICH rows come back, or
in WHAT ORDER? Those are different claims, and the first does not imply the second — a store can
hold reachable vectors that contribute nothing to any ranking a caller ever sees.

Lane eo measured `mode='hybrid'` over a collection where NOTHING was reachable (`OntologyClass`),
where bm25 and hybrid were necessarily identical. `Predicate` is the discriminating population
because it is MIXED: 89 reachable, 44 not. If the two arms are identical HERE, the vector leg
contributes nothing even where the index can reach the rows — eo's own words for a larger finding
than theirs.

FIDELITY TO THE PRODUCTION CALL. The two arms mirror `mesh_vectors.WeaviateVectors._search`
exactly: same client, same `limit`, `filters=None` (which is what `_domain_filter` returns for
`domains=()`), and NO `alpha` — so hybrid's fusion weight is whatever the client's default is,
which is what the fleet actually runs. The query text for a row is its own `search_text`, the
property the writer embedded; a query invented by me would measure my phrasing, not the store.

THREE ARMS, NOT TWO, AND THE THIRD IS THE CONTROL THAT MAKES A NULL READABLE.
    bm25        query text only                  — the vector cannot matter
    hybrid      query text + query vector        — the production call
    near_vector query vector only                — the vector is the ONLY input

"hybrid == bm25" is only a finding about the VECTOR if the vector can be shown to carry ranking
information at all. The `near_vector` arm is that showing: if it returns an order DIFFERENT from
bm25, then the vector is informative and hybrid's ignoring it is a property of the fusion, not of
an empty embedding. If `near_vector` matches bm25 too, the honest report is weaker — the arms
cannot be distinguished on this population and the experiment says so instead of claiming a cause.

FOUR MORE CONTROLS, none on request:
  * the query vector's DIMENSION is asserted non-zero and printed. A silently failed embed makes
    hybrid degrade to bm25 inside the client, which would produce a perfect null for a reason
    that has nothing to do with retrieval.
  * the embedding's SERVED model identity is printed, not the constant — the same discipline
    `utils.embed` exists to enforce.
  * a nonsense query runs through all three arms, so a run where everything returns the same rows
    regardless of input is visible as an instrument failure rather than read as a result.
  * reachability is re-derived HERE by `nearObject(self)` per row, with the census's negative
    control on a uuid that does not exist. The population is not taken from a prior file: a
    measurement that inherits its own population cannot notice the population moved.

WRITES NOTHING. Queries only. Run it from INSIDE a pod that carries `utils/` and can reach both
Weaviate and the embedding endpoint -- a dead port-forward is indistinguishable from an empty
collection, and the forwards die across every roll:

    kubectl -n sandbox exec -i <engine-o pod> -- python - < scripts/bm25_vs_hybrid_arm.py
    ... python - --collection Predicate --limit 10 --max-rows 5      # a fast smoke of the wiring
"""

from __future__ import annotations

import argparse
import sys

DEAD_UUID = "00000000-dead-4000-8000-000000000000"


def _fail(msg: str) -> None:
    print("ERROR: %s" % msg, file=sys.stderr)
    sys.exit(2)


try:
    from utils.embed import QUERY_PREFIX, embed_query, observe_query_embedding
    from utils.weaviate_utils import create_weaviate_client
except Exception as exc:  # pragma: no cover - the pod either has these or this cannot run
    _fail(
        "this must run inside a pod carrying /app/utils (engine-o does): %s. Running it on a "
        "workstation would measure a port-forward and a different embedder." % exc
    )

try:
    from weaviate.classes.query import MetadataQuery
except Exception as exc:  # pragma: no cover
    _fail("weaviate v4 client required: %s" % exc)


def _ordered(resp) -> list[str]:
    """The ranking as a list of uuids, in the order the store returned them."""
    return [str(o.uuid) for o in (getattr(resp, "objects", None) or [])]


def _has_vector(obj) -> bool:
    """Whether the v4 client handed back ANY vector for this row.

    DELIBERATELY NOT A SLOT STATE. The first version of this reported named/legacy/no-vector and
    said the 44 unreachable rows were `named=44` -- flatly contradicting the retrievability census,
    which reads the REST object and finds all 44 in `legacy`. The cause is the client: v4 surfaces
    whatever vector exists under the key `default`, which is ALSO this collection's named space, so
    the two states are indistinguishable through this path. The census's REST read is the authority
    on slot state and this script does not offer a second, weaker answer to that question -- a
    figure that disagrees with a measured one is a contradiction waiting to be cited, not a
    corroboration. Kept only as a presence bit, which this path CAN answer.
    """
    vectors = getattr(obj, "vector", None) or {}
    return bool(vectors)


def _space_name(client, collection: str) -> str:
    """The indexed space is READ from the schema, never imported from the writer's constant."""
    cfg = client.collections.get(collection).config.get()
    named = getattr(cfg, "vector_config", None) or getattr(cfg, "vectorizer_config", None)
    if isinstance(named, dict) and named:
        return sorted(named.keys())[0]
    return "default"


def _arm(fn, **kw):
    """Run one arm, tolerating the target_vector requirement WITHOUT hiding which form ran.

    A named-vector collection may refuse a vector query that does not name its target. Retrying
    with the target is correct, but a retry that is not REPORTED turns two different queries into
    one indistinguishable result line, so the form that answered is returned beside the rows.

    `_space` is POPPED BEFORE the first call, not inside the retry. Leaving it in made the plain
    call raise `TypeError: unexpected keyword argument '_space'` on every arm — which this function
    would have reported as the store refusing, turning all 133 rows into "unreachable" and the
    compared population into the empty set. A null result from an empty population reads exactly
    like a null result from a measured one.
    """
    space = kw.pop("_space", None)
    try:
        return fn(**kw), "plain"
    except Exception as exc_plain:
        if space is None:
            return exc_plain, "failed"
        try:
            return fn(target_vector=space, **kw), "target_vector"
        except Exception:
            return exc_plain, "both-failed"


def _domain_filter(domains: list[str]):
    """`mesh_vectors._domain_filter`'s Predicate branch, rebuilt rather than imported.

    ADR-0009's agnostic OR (`domains contains_any [entitled]` OR `length == 0`) is load-bearing:
    a fifth of the routing table carries no domains, and dropping that half of the OR would
    measure a pool the router never sees. Imported would be better than rebuilt, but `mesh_vectors`
    takes its filter factory by injection and the pod's copy is a module, not a wiring -- so this
    mirrors the branch and names the file it mirrors, which is the checkable form.
    """
    from weaviate.classes.query import Filter

    scoped = [d.upper() for d in domains if d]
    if not scoped:
        return None
    return Filter.any_of([
        Filter.by_property("domains").contains_any(scoped),
        Filter.by_property("domains", length=True).equal(0),
    ])


def _one_question(coll, space, text: str, domains: list[str], limit: int) -> int:
    """ONE user phrase down all three arms, scoped — does the WINNER change?

    WHY THIS EXISTS BESIDE THE ROW-FOR-ROW PASS, and why the row-for-row pass cannot answer it.
    Querying a row with its OWN `search_text` is the easiest case there is: the row is a near-exact
    lexical and vector match for itself, so it wins both arms and the top-1 never moves. That
    measures "does the vector reorder the tail", which is a real question but NOT the router's.
    The router is handed a user PHRASE and acts on the winner. `finance-variance-drivers` went
    PASS -> FAIL by returning the verb `finVarianceAnalysis` where the sheet expects
    `fin_variance_drivers` -- a top-1 change on a phrase. Only this arm can speak to that.
    """
    from weaviate.classes.query import MetadataQuery as MQ

    filt = _domain_filter(domains)
    vec = embed_query(text)
    r_bm, _ = _arm(coll.query.bm25, query=text, limit=limit, filters=filt,
                   return_metadata=MQ(score=True), _space=space)
    r_hy, _ = _arm(coll.query.hybrid, query=text, vector=vec, limit=limit, filters=filt,
                   return_metadata=MQ(score=True), _space=space)
    r_nv, _ = _arm(coll.query.near_vector, near_vector=vec, limit=limit, filters=filt,
                   return_metadata=MQ(distance=True), _space=space)

    print("=" * 78)
    print("QUESTION: %s" % text)
    print("   domains scope: %s   filter: %s" % (domains or "(none)", "ADR-0009 OR branch" if filt else "None"))
    winners = {}
    for name, r in (("bm25", r_bm), ("hybrid", r_hy), ("near_vector", r_nv)):
        if isinstance(r, Exception):
            print("   %-11s REFUSED: %s" % (name, r))
            continue
        objs = getattr(r, "objects", None) or []
        print("   %-11s top %d:" % (name, min(limit, len(objs))))
        for i, o in enumerate(objs[:5]):
            p = o.properties or {}
            print("       %d. %-34s %-22s %s" % (
                i, str(p.get("verb_local") or p.get("verb_iri"))[:34],
                str(p.get("archetype"))[:22], str(o.uuid)[:8]))
        winners[name] = (objs[0].properties or {}).get("verb_local") if objs else None
    print("   WINNERS: bm25=%r hybrid=%r near_vector=%r" % (
        winners.get("bm25"), winners.get("hybrid"), winners.get("near_vector")))
    same = winners.get("bm25") == winners.get("hybrid")
    print("   the vector arm %s the winner on this phrase." % ("does NOT change" if same else "CHANGES"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", default="Predicate")
    ap.add_argument("--limit", type=int, default=10, help="mirrors nominate()'s default")
    ap.add_argument("--max-rows", type=int, default=0, help="0 = every reachable row")
    ap.add_argument("--question", default=None, help="one user phrase; skips the row-for-row pass")
    ap.add_argument("--domains", default="", help="comma-separated entitlement scope for --question")
    args = ap.parse_args()

    if args.question:
        client = create_weaviate_client()
        try:
            coll = client.collections.get(args.collection)
            return _one_question(coll, _space_name(client, args.collection), args.question,
                                 [d for d in args.domains.split(",") if d], args.limit)
        finally:
            client.close()

    client = create_weaviate_client()
    coll = client.collections.get(args.collection)
    space = _space_name(client, args.collection)

    print("=" * 78)
    print("%s  BM25 vs HYBRID vs NEAR_VECTOR, row for row (read-only)" % args.collection)
    print("=" * 78)
    print("   indexed vector space, read from the schema: %r" % space)
    print("   query prefix on the wire: %r" % QUERY_PREFIX)

    # ── the embedder's own identity, observed rather than declared ──
    obs = observe_query_embedding("iagent bm25-vs-hybrid arm probe")
    dim = obs.dimension
    print("   embedding: requested=%r served=%r dim=%d" % (obs.requested, obs.served, dim))
    if not dim:
        _fail("the embedder returned no vector; hybrid would degrade to bm25 INSIDE the client "
              "and every row would compare equal for a reason unrelated to retrieval")

    # ── the population, re-derived here, with the census's negative control ──
    dead, _form = _arm(coll.query.near_object, near_object=DEAD_UUID, limit=1, _space=space)
    if not isinstance(dead, Exception) and _ordered(dead):
        _fail("NEGATIVE CONTROL FAILED: nearObject on a uuid that does not exist returned rows. "
              "A checker that cannot answer False is not evidence of anything.")
    print("   NEGATIVE CONTROL nearObject(%s) -> not retrievable" % DEAD_UUID)

    rows = []
    for obj in coll.iterator(include_vector=True,
                             return_properties=["search_text", "verb_iri", "verb_local"]):
        rows.append(obj)
    print("   total rows: %d" % len(rows))

    reachable, unreachable = [], []
    for obj in rows:
        resp, _f = _arm(coll.query.near_object, near_object=str(obj.uuid), limit=1, _space=space)
        (unreachable if isinstance(resp, Exception) or not _ordered(resp) else reachable).append(obj)
    print("   reachable by nearObject(self): %d     unreachable: %d" % (len(reachable), len(unreachable)))
    print("   rows carrying ANY vector (presence only; the census owns slot state): %d of %d"
          % (sum(1 for o in rows if _has_vector(o)), len(rows)))

    target = reachable[: args.max_rows] if args.max_rows else reachable
    print("   rows compared: %d (limit=%d per arm)" % (len(target), args.limit))
    print()

    same_all = 0
    hy_vs_bm = 0
    tops = {k: 0 for k in ("top1 same", "top3 same", "same SET, different order",
                           "bm25 ranks self first", "hybrid ranks self first",
                           "near_vector ranks self first")}
    nv_vs_bm = 0
    differing = []
    forms = set()

    for obj in target:
        props = obj.properties or {}
        text = (props.get("search_text") or props.get("verb_local") or props.get("verb_iri") or "").strip()
        if not text:
            differing.append((str(obj.uuid), "NO QUERY TEXT", [], [], []))
            continue
        vec = embed_query(text)

        r_bm, f1 = _arm(coll.query.bm25, query=text, limit=args.limit,
                        return_metadata=MetadataQuery(score=True), _space=space)
        r_hy, f2 = _arm(coll.query.hybrid, query=text, vector=vec, limit=args.limit,
                        return_metadata=MetadataQuery(score=True), _space=space)
        r_nv, f3 = _arm(coll.query.near_vector, near_vector=vec, limit=args.limit,
                        return_metadata=MetadataQuery(distance=True), _space=space)
        forms.update((f1, f2, f3))

        bm, hy, nv = (_ordered(r) if not isinstance(r, Exception) else ["<refused>"]
                      for r in (r_bm, r_hy, r_nv))
        if hy != bm:
            hy_vs_bm += 1
        if nv != bm:
            nv_vs_bm += 1
        if hy == bm == nv:
            same_all += 1
        if hy != bm:
            differing.append((str(obj.uuid), text[:48], bm, hy, nv))

        # ── WHERE in the ranking the arms disagree, which is the part a ROUTER can feel ──
        # "the order changed" and "the answer changed" are different claims. A router that takes
        # the top candidate is unaffected by churn at rank 3, so a count of differing ORDERS
        # over-states the consequence unless the top of the list is counted separately.
        me = str(obj.uuid)
        if bm[:1] == hy[:1]:
            tops["top1 same"] += 1
        if bm[:3] == hy[:3]:
            tops["top3 same"] += 1
        if bm[:1] == [me]:
            tops["bm25 ranks self first"] += 1
        if hy[:1] == [me]:
            tops["hybrid ranks self first"] += 1
        if nv[:1] == [me]:
            tops["near_vector ranks self first"] += 1
        if set(bm) == set(hy):
            tops["same SET, different order"] += 1

    print("-" * 78)
    print("RESULT over %d reachable rows, limit=%d" % (len(target), args.limit))
    print("   hybrid ranking DIFFERS from bm25 : %d of %d" % (hy_vs_bm, len(target)))
    print("   near_vector DIFFERS from bm25    : %d of %d   <- the control: can the vector rank?"
          % (nv_vs_bm, len(target)))
    print("   all three arms identical         : %d of %d" % (same_all, len(target)))
    print("   query forms that answered        : %s" % sorted(forms))
    print()
    print("   WHERE the two arms disagree (the part a router can feel):")
    for k in ("top1 same", "top3 same", "same SET, different order",
              "bm25 ranks self first", "hybrid ranks self first", "near_vector ranks self first"):
        print("      %-30s : %d of %d" % (k, tops[k], len(target)))
    print()
    if hy_vs_bm == 0 and nv_vs_bm == 0:
        print("   READING: the arms CANNOT BE DISTINGUISHED on this population. This is NOT")
        print("   evidence that the vector is ignored -- a vector that ranks identically to bm25")
        print("   is indistinguishable from one that is dropped. Report it as undecided.")
    elif hy_vs_bm == 0:
        print("   READING: the vector RANKS (near_vector differs from bm25 on %d rows) and hybrid")
        print("   still returns bm25's exact order. The vector leg contributes nothing to the")
        print("   ranking a caller sees, on rows the index CAN reach." % ())
    else:
        print("   READING: hybrid diverges from bm25 on %d rows -- the vector arm DOES change the"
              % hy_vs_bm)
        print("   ranking. eo's null on OntologyClass does not generalise to Predicate.")

    if differing:
        print()
        print("   rows where hybrid != bm25 (uuid, query, then the two orders' first 4):")
        for uuid, text, bm, hy, _nv in differing[:40]:
            print("     %s  %s" % (uuid, text))
            print("        bm25  : %s" % ", ".join(x[:8] for x in bm[:4]))
            print("        hybrid: %s" % ", ".join(x[:8] for x in hy[:4]))

    # ── the nonsense-query control, LAST, so a reader sees it beside the result ──
    junk = "zzzqqq xyzzy plugh frobnitz"
    jv = embed_query(junk)
    j_bm, _ = _arm(coll.query.bm25, query=junk, limit=args.limit, _space=space)
    j_hy, _ = _arm(coll.query.hybrid, query=junk, vector=jv, limit=args.limit, _space=space)
    j_nv, _ = _arm(coll.query.near_vector, near_vector=jv, limit=args.limit, _space=space)
    print()
    print("   INSTRUMENT CONTROL, nonsense query %r:" % junk)
    for name, r in (("bm25", j_bm), ("hybrid", j_hy), ("near_vector", j_nv)):
        got = _ordered(r) if not isinstance(r, Exception) else ["<refused>"]
        print("     %-11s -> %d rows%s" % (name, len(got), "" if got else "  (empty, as bm25 should be)"))
    print("   If a real query and this one return the SAME rows, the run measured nothing.")

    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
