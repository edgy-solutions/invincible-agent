#!/usr/bin/env python3
"""READ-ONLY. Would a WORKING vector search put mesh:explain's subject in the pool?

74's method (their packet section 5), applied to the docs walk's own questions. Every call here is
a read: Weaviate GETs plus embedding calls. Nothing is written, no collection is touched.

    kubectl -n sandbox exec -i <engine-o pod> -- python - "how do I add an engine" "…" \\
        < scripts/explain_cosine_probe.py

THE CAVEAT IS 74'S AND IT IS NOT A DISCLAIMER, IT IS THE SCOPE OF THE ANSWER. This is a
HAND-SCORED ranking over STORED vectors. It is NOT the pool a fixed search would build: no
tokenizer, no BM25 half, no domain filter, no top-k truncation, no tie-breaking. It answers
exactly one question — does the query vector PREFER explain's subject to the alternatives — which
is the question the shipped search never got to ask because the vectors were in the wrong slot.
A good number here does NOT mean routing will work; a bad one DOES mean it cannot.

WHY IT CAN BE ASKED AT ALL: the stored vectors are READABLE even though nothing indexes them.
OntologyClass rows carry their vector in the LEGACY unnamed slot, which is why the search finds
nothing while the data is perfectly good. This probe reads whichever slot holds the vector.

IDENTIFIERS ARE DERIVED, NOT TYPED. An earlier draft of this probe lived in a scratchpad outside
the tree and named `main.embed_query` and `main.get_weaviate_client` in the docs agent — neither
exists. The canonical embedder is agent_fleet/utils/embed.embed_query; the subject is read off
mesh:explain's own Predicate row rather than hardcoded, and cross-checked against the constant
below. The questions are PASSED IN, derived from docs/measurements/walk-census.yaml by the caller,
so this file cannot drift from the sheet the census parses.
"""

from __future__ import annotations

import math
import os
import sys

import requests

# Cross-check only. The subject is READ from the live Predicate row; if the store disagrees with
# this constant the probe SAYS SO rather than silently preferring either one.
EXPECTED_SUBJECT = "http://invincible-agent/mesh#DocPage"
EXPLAIN_VERBS = ("mesh:explain", "http://invincible-agent/mesh#explain")


def _embed_query():
    """The fleet's own embedder. Flat layout first, package layout second.

    The agent images do `COPY ${AGENT_DIR}/ /app/`, so `agent_fleet/utils/` lands at `/app/utils/`.
    mem0_utils.py:385-387 uses exactly this pair of spellings, in this order.
    """
    try:
        from utils.embed import embed_query  # type: ignore
        return embed_query, "utils.embed"
    except ImportError:
        from agent_fleet.utils.embed import embed_query  # type: ignore
        return embed_query, "agent_fleet.utils.embed"


def _base_url():
    explicit = os.getenv("WEAVIATE_URL")
    if explicit:
        return explicit.rstrip("/")
    host = os.getenv("WEAVIATE_HTTP_HOST") or os.getenv("WEAVIATE_HOST") or "localhost"
    host = host.split("://", 1)[-1].rstrip("/")
    if ":" in host:
        return "http://" + host
    port = os.getenv("WEAVIATE_HTTP_PORT") or os.getenv("WEAVIATE_PORT") or "8080"
    return "http://%s:%s" % (host, port)


BASE = _base_url()


def _page(cls, after=None, limit=200):
    params = {"class": cls, "include": "vector", "limit": limit}
    if after:
        params["after"] = after
    r = requests.get(BASE + "/v1/objects", params=params, timeout=120)
    r.raise_for_status()
    return r.json().get("objects") or []


def _vector_of(obj):
    """Whichever slot holds it. Named first, then the legacy unnamed slot."""
    named = obj.get("vectors") or {}
    for v in named.values():
        if v:
            return v, "named"
    if obj.get("vector"):
        return obj["vector"], "legacy"
    return None, "none"


def cosine(a, b):
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return 0.0 if na == 0 or nb == 0 else num / (na * nb)


def subject_from_store():
    after = None
    found = {}
    while True:
        objs = _page("Predicate", after=after)
        if not objs:
            break
        after = objs[-1]["id"]
        for o in objs:
            p = o.get("properties") or {}
            if str(p.get("verb_iri")) in EXPLAIN_VERBS:
                found[str(p.get("verb_iri"))] = str(p.get("input_uri") or "")
    return found


def main():
    questions = [a for a in sys.argv[1:] if a.strip()]
    if not questions:
        print("REFUSING: no questions passed. They must be derived from walk-census.yaml by the "
              "caller, not invented here.", file=sys.stderr)
        return 2

    embed_query, embed_module = _embed_query()
    print("store          : %s" % BASE)
    print("embedder       : %s" % embed_module)

    subjects = subject_from_store()
    print("explain rows in store: %s" % (subjects or "NONE"))
    distinct = set(subjects.values())
    if not distinct:
        print("REFUSING: no mesh:explain Predicate row, so there is no subject to score against.",
              file=sys.stderr)
        return 1
    if len(distinct) > 1:
        print("REFUSING: the explain rows disagree about input_uri: %s" % sorted(distinct),
              file=sys.stderr)
        return 1
    subject = distinct.pop()
    print("subject (read) : %s" % subject)
    if subject != EXPECTED_SUBJECT:
        print("NOTE: the store's subject differs from this file's cross-check constant %r. The "
              "STORE wins and is used; the constant is stale." % EXPECTED_SUBJECT)

    rows, slots = [], {}
    after = None
    while True:
        objs = _page("OntologyClass", after=after)
        if not objs:
            break
        after = objs[-1]["id"]
        for o in objs:
            vec, slot = _vector_of(o)
            slots[slot] = slots.get(slot, 0) + 1
            if not vec:
                continue
            p = o.get("properties") or {}
            rows.append({"uri": str(p.get("uri") or ""), "label": str(p.get("label") or ""),
                         "domain": str(p.get("domain") or ""), "vec": vec})

    print("OntologyClass slots  : %s" % ", ".join("%s=%d" % kv for kv in sorted(slots.items())))
    print("rows with a readable vector: %d" % len(rows))
    if not rows:
        print("REFUSING: no readable vectors, so a cosine cannot be taken.", file=sys.stderr)
        return 1

    present = [r for r in rows if r["uri"] == subject]
    print("subject present WITH A VECTOR: %s" % bool(present))
    if not present:
        print("  -> the subject has no readable vector. A ranking that cannot contain it is not "
              "evidence about recall; it is evidence the subject needs a RE-EMBED.")

    for q in questions:
        qv = embed_query(q)
        print("\n==== %r  (query dim=%d) ====" % (q, len(qv)))
        for scope, subset in (("DOCS domain", [r for r in rows if r["domain"] == "DOCS"]),
                              ("ALL domains", rows)):
            if not subset:
                print("  [%-11s] EMPTY SUBSET — nothing to rank, and that is a finding, not a zero"
                      % scope)
                continue
            scored = sorted(((cosine(qv, r["vec"]), r) for r in subset), key=lambda t: -t[0])
            print("  [%-11s] n=%d   top 5:" % (scope, len(subset)))
            for i, (s, r) in enumerate(scored[:5], 1):
                mark = "   <== SUBJECT" if r["uri"] == subject else ""
                print("      %d. %.4f  %-52s %s%s" % (i, s, r["uri"][-52:], r["label"][:20], mark))
            rank = next((i for i, (s, r) in enumerate(scored, 1) if r["uri"] == subject), None)
            print("      -> subject rank %s of %d%s"
                  % (rank if rank else "ABSENT", len(subset),
                     ("  cosine=%.4f" % next(s for s, r in scored if r["uri"] == subject))
                     if rank else ""))

    print("\nCAVEAT (74's, unchanged): hand-scored over STORED vectors. Not the pool a fixed")
    print("search would build — no BM25 half, no domain filter, no top-k, no tie-breaking. It")
    print("answers only whether the query vector PREFERS the subject. A good number here does not")
    print("mean routing works; a bad one means it cannot.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
