#!/usr/bin/env python3
"""Relocate stored vectors from the LEGACY slot into the NAMED space the index searches.

╔══════════════════════════════════════════════════════════════════════════════════════════╗
║  ⚠  AFTER THIS SCRIPT SUCCEEDS, EVERY REPAIRED ROW READS AS HAVING NO VECTOR.            ║
║                                                                                          ║
║      REST  /v1/objects?include=vector   `vector`  -> None        `vectors.default` -> 768 ║
║      GraphQL  _additional{vector}       []                                               ║
║                                                                                          ║
║  THAT IS THE REPAIR WORKING, NOT DATA LOSS. The two slots are different keys on the      ║
║  wire. Every instrument this fleet has used to ask "is this row vectorised?" reads the   ║
║  LEGACY key, so it will show rows going from "has a vector" to "has no vector" at the    ║
║  exact moment they become searchable.                                                    ║
║                                                                                          ║
║  DO NOT REVERT ON THAT SIGNAL. Verify with nearObject(self) — this script verifies the   ║
║  FIRST relocated row before it writes a second, re-verifies every --verify-every rows,   ║
║  and STOPS on the first regression.                                                      ║
╚══════════════════════════════════════════════════════════════════════════════════════════╝

## What is wrong, and why this is a relocation rather than a rebuild

Measured 2026-09-19. A bare `collections.create(name, properties)` on weaviate-client 4.21.0
emits a NAMED vector space `default`; a positional `insert(vector=[...])` writes the LEGACY
unnamed slot. The named space — the only target a search can name — stays empty, so the store
answers `"vector not found for target: default"` on a row whose vector reads back as 768 dims.
`OntologyClass` and `Predicate` were both in that state, which made every routing decision in
the fleet silently BM25-only.

**The vectors themselves are fine.** Readable, right dimension, right embedder. Nothing is
re-embedded, no LLM is called, doc-tools is not involved and nothing is deleted — each row's own
vector is read and written back under the name. Measured lossless against a deliberately
un-normalised probe: norms identical, max|delta| = 0.000e+00, self-distance 0.0 after.

## SCOPE: NAMED ROWS ONLY — blank nodes are skipped, not relocated

Ruled by the architect 2026-09-19 and confirmed against doc-tools' source: blank nodes do not
belong in the retrieval index, so nothing relocates them. They are 96.2% of `OntologyClass`
(25,255 of 26,239), they are there because the Weaviate writer has no `!isBlank` filter while
its Neo4j sibling has two, and DELETING the existing ones is a separate act that is NOT in this
script and not ordered. This script only declines to repair them.

Expected dry run on `OntologyClass`, and any difference is a finding rather than a nuisance:

    blank-skipped    25,255      not index rows — doc-tools' ingest filter, not a backfill
    no-vector            16      NAMED and vectorless: a RE-EMBED, which this cannot do
    would-relocate      968      the actual work
                     ------
                     26,239      the five outcomes partition the walk; they must sum to it

## THIS SCRIPT DOES NOT RUN ITSELF

`--apply` is required and refuses without `--i-have-read-the-warning`. Default is a dry run.
Chris authorizes and runs it, in daylight. The ruled order is:

    1. canary   --classes OntologyClass --canary safety --apply --i-have-read-the-warning
    2. verify   "what hazards are unattended" stops abstaining
    3. the rest --classes OntologyClass,Predicate --apply --i-have-read-the-warning

## RUNNING IT — from inside a pod, not through a port-forward

Port-forwards die across every roll and a dead forward looks exactly like an empty answer. Pipe
the script into a pod that already has the connection and the deps:

    kubectl -n sandbox exec -i <engine-o pod> -- python - --classes OntologyClass \\
        < scripts/backfill_vector_space.py

**STDIN IS THE SCRIPT**, so the row set cannot be piped and `--uris-file` cannot name a path that
only exists in your checkout. Use `--canary safety` (the set is IN this file, so it travels with
it) or `--uris a,b,c`. `--uris-file` remains for runs from a checkout with a route to the store.

It reads `WEAVIATE_HOST`/`WEAVIATE_PORT` from the pod's own env, so it needs no configuration.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

try:
    import requests
except ImportError:  # pragma: no cover
    print("ERROR: pip install requests", file=sys.stderr)
    sys.exit(1)

# ── THE SPACE NAME IS READ FROM THE STORE, NOT IMPORTED, AND THAT IS DELIBERATE ───────────
#
# The obvious thing is to import `weaviate_utils.VECTOR_SPACE` so there is one declaration. It
# is wrong HERE, and trying to run it is what showed why: this script must run against a cluster
# whose images PREDATE the fix — that is its entire purpose — so importing the new constant
# makes a repair tool depend on the repair having already shipped. Piped into a pod on the
# current image it died on exactly that.
#
# Reading the collection's own `vectorConfig` is not a compromise, it is STRONGER: a constant is
# a local belief about the store, and this is the store's answer.
DEFAULT_SPACE = "default"

#: The collections the router reads. Named rather than discovered: a backfill that swept every
#: collection would also rewrite `DocumentChunk`, which is on the LEGACY schema and works — and
#: relocating its vectors would break the one collection that is currently fine.
ROUTING_CLASSES = ("OntologyClass", "Predicate")

#: Named row sets, IN THIS FILE so they travel with it into a pod.
#:
#: `safety` is the architect's ruled canary and it is the right one because its pass condition is
#: not "the script did not crash": *"what hazards are unattended"* currently builds a pool of one
#: (`product#Part`) and abstains, and the query vector already ranks `safety#Hazard` 0.659 over
#: `product#Part` 0.520 — so that question is the one that visibly changes. Six rows also means a
#: mistake costs six rows, every one re-derivable from the ontology.
CANARY_SETS = {
    "safety": (
        "http://internal/sustainment/safety#AcceptanceAuthority",
        "http://internal/sustainment/safety#Hazard",
        "http://internal/sustainment/safety#Mitigation",
        "http://internal/sustainment/safety#RiskAssessment",
        "http://internal/sustainment/safety#SafetyCriticalItem",
        "http://internal/sustainment/safety#WriteUp",
    ),
}

# ── BLANK NODES ARE NOT RELOCATED, AND THE PREDICATE LIVES HERE ──────────────────────────
#
# RULED by the architect 2026-09-19, conditional on doc-tools confirming the read — and the read
# is confirmed (`doc-tools` `lane/7f` @ aa36e41, by me): blank nodes do not belong in the
# retrieval index, so this script relocates NAMED rows only.
#
# WHY THEY ARE IN THERE AT ALL, because "96% of the index is anonymous nodes" reads like a
# design decision and is not one. doc-tools has TWO writers off the same rdflib graph. The Neo4j
# leg excludes blank nodes twice — `FILTER(!isBlank(?uri))` in its SPARQL and an
# `isinstance(..., rdflib.term.BNode)` in Python — and a test seals it. The Weaviate leg, which
# is the writer that fills THIS index, carries neither, and nothing seals it. A 2026-06-15 fix
# reached one writer; the file's own comment counts two. It is a leak, not a design.
#
# THE SHAPE, AND THERE ARE TWO OF THEM. rdflib renders a blank node as `BNode.__str__` — `N`
# followed by a 32-char hex id — and doc-tools documents exactly that form, `N[a-f0-9]{32}`.
# **The live index carries a SECOND spelling their documented form does not match**: lowercase
# `n`, the same 32 hex, and a literal `b246` suffix. Measured over the 1,299 vectorless blank
# rows I had listed: 1,296 are the rdflib form and 3 are the second. Two parsers, one index.
#
# WHY THAT MATTERS RATHER THAN BEING TRIVIA: had this script keyed on doc-tools' documented
# regex, those rows would have been classified NAMED and either relocated or reported to
# doc-tools as re-embed work. The count that decides the whole dry run turns on the predicate,
# so the predicate is stated here, in the script, and both known spellings are named.
#
# AND THE THIRD BUCKET EXISTS BECAUSE MY SPELLING CENSUS IS A SAMPLE. I enumerated spellings
# over the 1,299 VECTORLESS blanks, not over all 25,255 — the other 23,956 were never listed
# row by row. A third spelling in that unexamined majority is entirely possible. So anything
# that looks blank under the loose form and matches NEITHER known spelling is `ambiguous`: it
# is not written, it is printed, and it makes the run exit non-zero. An undecided row must not
# have its fate chosen by whichever regex the tool happened to be written with, and a clean
# exit must not be available while one exists.
#
# These match a URI STRING read back out of the store. The INGEST filter that stops new ones
# arriving is doc-tools' and must key on `isinstance(..., rdflib.term.BNode)`, not on any string
# shape — a string predicate is only correct for tools like this one, reading rows back.
BLANK_URI = re.compile(r"^[Nn][0-9a-f]{20,}$")

#: Collections whose rows carry NO `uri` property, so the blank check above cannot fire on them
#: — with the reason it is correct that it does not.
#:
#: MEASURED, not assumed: a `Predicate` row has `input_uri`/`output_uri` and no `uri`, so
#: `blankness()` reads "" and answers "named" for every one of them. That is the right outcome
#: — a Predicate row is a VERB REGISTRATION, not an RDF class node, and a blank node cannot
#: occur there — but it is right for an accidental reason, and a filter that returns the correct
#: answer because it is reading a field that does not exist is one collection away from being a
#: guard that silently passes everything. So the run REPORTS which collections the blank check
#: was live on, and refuses a clean exit if a collection not named here turns out to carry no
#: uris at all.
URILESS_CLASSES = ("Predicate",)

#: The spellings actually observed in this index, each with the evidence for calling it blank.
BLANK_SPELLINGS = {
    #: rdflib `BNode.__str__`; doc-tools documents this one. 1,296 of 1,299 listed.
    "rdflib": re.compile(r"^N[0-9a-f]{32}$"),
    #: Lowercase, `b246`-suffixed; doc-tools' documented form does NOT match it. 3 of 1,299.
    "b246": re.compile(r"^n[0-9a-f]{32}b246$"),
}


def blankness(uri):
    """One of "named", "blank", "ambiguous" — the whole population, partitioned.

    Every row lands in exactly one bucket and none is dropped on the floor. "ambiguous" is a
    blank-LOOKING uri in neither known spelling, and it FAILS the run rather than being absorbed
    into either answer.
    """
    uri = uri or ""
    if any(rx.match(uri) for rx in BLANK_SPELLINGS.values()):
        return "blank"
    return "ambiguous" if BLANK_URI.match(uri) else "named"


#: How near "at distance ~0" is. Cosine on an identical vector is exactly 0.0 in every
#: measurement so far; the tolerance exists for float32 round-trips, not for near-misses.
SELF_DISTANCE_TOLERANCE = 1e-4


def _base_url():
    """The store's HTTP base, tolerating the THREE shapes the fleet's env actually uses.

    MEASURED ON A REAL POD, because the first version built
    `http://iagent-weaviate.sandbox.svc.cluster.local:8080:8080/...` and died on an InvalidURL.
    engine-o carries BOTH conventions at once:

        WEAVIATE_HTTP_HOST = iagent-weaviate.sandbox.svc.cluster.local:8080   <- host AND port
        WEAVIATE_HOST      = iagent-weaviate                                  <- host only
        WEAVIATE_PORT      = 8080
    """
    explicit = os.getenv("WEAVIATE_URL")
    if explicit:
        return explicit.rstrip("/")
    host = os.getenv("WEAVIATE_HTTP_HOST") or os.getenv("WEAVIATE_HOST") or "localhost"
    host = host.split("://", 1)[-1].rstrip("/")
    if ":" in host:                      # already host:port — appending would make host:port:port
        return "http://" + host
    port = os.getenv("WEAVIATE_HTTP_PORT") or os.getenv("WEAVIATE_PORT") or "8080"
    return "http://%s:%s" % (host, port)


BASE = _base_url()


def _get(path, **params):
    r = requests.get(BASE + path, params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def page(cls, after=None, limit=100):
    params = {"class": cls, "include": "vector", "limit": limit}
    if after:
        params["after"] = after
    return (_get("/v1/objects", **params).get("objects") or [])


def space_of(cls):
    """The name of the vector space THIS collection actually indexes, read from its schema.

    Refuses anything but exactly one named space. Zero means the collection is on the legacy
    single-vector schema — where a positional write is CORRECT and relocating would break it,
    which is the state `DocumentChunk` is in. More than one means a decision nobody has made.
    """
    sch = _get("/v1/schema/" + cls)
    names = sorted((sch.get("vectorConfig") or {}))
    if len(names) != 1:
        raise SystemExit(
            "REFUSING %s: its schema declares %d named vector space(s) %r. Zero means the "
            "LEGACY single-vector schema, where the current write is correct and relocating "
            "would break it; more than one is a choice nobody has made. Neither is this "
            "script's job." % (cls, len(names), names))
    if names[0] != DEFAULT_SPACE:
        print("   note: %s indexes %r, not %r — using the schema's answer"
              % (cls, names[0], DEFAULT_SPACE))
    return names[0]


def slots(obj, space):
    """(legacy_vector, named_vector) for one object, as the wire reports them."""
    return obj.get("vector"), (obj.get("vectors") or {}).get(space)


def verify_self(cls, uuid, k=5):
    """Is this row findable by its own vector? Returns (ok, detail).

    **SELF WITHIN THE TOP-K AT DISTANCE ~0, NOT `rows[0] is self`.** Duplicate vectors exist —
    `IOF_Core` is loaded into two domains — so several rows can sit at distance 0.0 and the
    store is free to order ties however it likes. An assertion that self ranks FIRST would fail
    on a correctly repaired row for a reason that has nothing to do with the repair.

    MEASURED, so `k` is not a guess: the largest group of rows sharing one exact vector is **2**
    in both routing collections (OntologyClass 26,239 rows -> 24,922 distinct vectors, 4 rows in
    2 pairs; Predicate 135 -> 126 distinct, 18 rows in 9 pairs). k=5 is 2.5x the worst case.

    AND IT CANNOT FALSE-FAIL IF THAT EVER GROWS. If self is absent but the whole page is ties at
    ~0, the top-k is saturated and k was too small — it retries once, wider, before reporting a
    regression. Widening on saturation costs one query and removes the only way this check can
    be wrong in the safe direction.
    """
    def _query(kk):
        q = ('{Get{%s(nearObject:{id:"%s"} limit:%d){_additional{id distance}}}}'
             % (cls, uuid, kk))
        r = requests.post(BASE + "/v1/graphql", json={"query": q}, timeout=120).json()
        if r.get("errors"):
            return None, r["errors"][0].get("message", "")[:200]
        return (((r.get("data") or {}).get("Get") or {}).get(cls) or []), ""

    for attempt_k in (k, k * 20):
        rows, err = _query(attempt_k)
        if rows is None:
            # A SERVER ERROR IS A FAILURE, NOT A MISS. "vector not found for target" is the
            # unrepaired state saying so in words.
            return False, "server refused: " + err
        if not rows:
            return False, "nearObject returned nothing at k=%d" % attempt_k
        for row in rows:
            add = row.get("_additional") or {}
            if add.get("id") == uuid:
                dist = add.get("distance")
                if dist is not None and abs(dist) > SELF_DISTANCE_TOLERANCE:
                    return False, "self found but at distance %s (expected ~0)" % dist
                ties = sum(1 for r2 in rows
                           if abs(((r2.get("_additional") or {}).get("distance") or 0.0))
                           <= SELF_DISTANCE_TOLERANCE)
                return True, "self in top-%d at distance %s (%d row(s) tied at ~0)" % (
                    attempt_k, dist, ties)
        # Self absent. Only worth widening if the page is saturated with ties.
        saturated = all(
            abs(((r2.get("_additional") or {}).get("distance") or 1.0))
            <= SELF_DISTANCE_TOLERANCE for r2 in rows)
        if not (saturated and len(rows) >= attempt_k):
            return False, ("self NOT in top-%d and the page is not saturated with ties — the "
                           "row is not findable by its own vector" % attempt_k)
        print("      (top-%d was all ties at ~0 and self was not among them — widening)"
              % attempt_k)
    return False, "self not found even at k=%d among tied rows" % (k * 20)


def relocate(cls, obj, space, apply_it):
    """Write this row's OWN vector into the named space. Properties travel with it.

    `PUT /v1/objects` REPLACES the whole object, so the properties must be sent back or every
    field is blanked. That is the single most dangerous thing about this operation and it is why
    the properties are read in the same request as the vector rather than re-derived.
    """
    uuid = obj["id"]

    # ── THE BLANK CHECK IS FIRST, AND THE ORDER IS THE POINT ─────────────────────────────
    # Checked before `already-named` and before `no-vector` so the outcome counts PARTITION the
    # collection: every row is blank, ambiguous, named-and-relocatable, named-and-already-done,
    # or named-and-vectorless, and the five sum to the walk. Put this check later and the 1,299
    # vectorless blank nodes would land in `no-vector` and be reported to doc-tools as re-embed
    # work — which is the wrong ask for a row that should not be in the index at all.
    kind = blankness((obj.get("properties") or {}).get("uri") or "")
    if kind == "blank":
        return "blank-skipped"
    if kind == "ambiguous":
        return "blank-AMBIGUOUS-skipped"

    legacy, named = slots(obj, space)
    if named:
        return "already-named"
    if not legacy:
        # A row with NO vector at all. The backfill cannot repair it — there is nothing to
        # relocate — and it needs a RE-EMBED. Reported, never silently counted as done.
        return "no-vector"
    if not apply_it:
        return "would-relocate"
    body = {"class": cls, "id": uuid,
            "properties": obj.get("properties") or {},
            "vectors": {space: legacy}}
    r = requests.put(BASE + "/v1/objects/%s/%s" % (cls, uuid), json=body, timeout=120)
    r.raise_for_status()
    return "relocated"


def _selected_uris(args):
    if args.canary:
        return set(CANARY_SETS[args.canary]), "--canary " + args.canary
    if args.uris:
        return {u.strip() for u in args.uris.split(",") if u.strip()}, "--uris"
    if args.uris_file:
        with open(args.uris_file, encoding="utf-8") as fh:
            return ({ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")},
                    args.uris_file)
    return None, ""


def run_class(cls, args):
    print("=" * 78)
    print("%s  (%s)" % (cls, "APPLY" if args.apply else "DRY RUN — nothing is written"))
    print("=" * 78)

    space = space_of(cls)
    print("   indexed vector space, read from the schema: %r" % space)

    wanted, how = _selected_uris(args)
    if wanted is not None:
        print("   restricted to %d uri(s) from %s" % (len(wanted), how))

    counts = {}
    novector_uris = []
    ambiguous_uris = []
    with_uri = 0
    seen = 0
    after = None
    verified_once = False
    since_verify = 0
    t0 = time.time()
    rc = 0

    def _report(tag):
        print("   %s walked %d  %s  (%.1fs)"
              % (tag, seen, json.dumps(counts, sort_keys=True), time.time() - t0))

    def _verify(uuid, why):
        ok, detail = verify_self(cls, uuid, k=args.verify_k)
        print("   VERIFY (%s) %s: %s — %s"
              % (why, uuid, "RETRIEVABLE" if ok else "NOT RETRIEVABLE", detail))
        return ok

    try:
        while True:
            objs = page(cls, after=after, limit=args.page_size)
            if not objs:
                break
            after = objs[-1]["id"]
            for obj in objs:
                uri = (obj.get("properties") or {}).get("uri") or ""
                if wanted is not None and uri not in wanted:
                    continue
                if seen < args.offset:
                    seen += 1
                    continue
                if args.limit and (seen - args.offset) >= args.limit:
                    continue

                outcome = relocate(cls, obj, space, args.apply)
                counts[outcome] = counts.get(outcome, 0) + 1
                if uri:
                    with_uri += 1
                if outcome == "no-vector":
                    novector_uris.append(uri or obj["id"])
                elif outcome == "blank-AMBIGUOUS-skipped":
                    ambiguous_uris.append(uri or obj["id"])
                seen += 1

                if outcome == "relocated":
                    since_verify += 1
                    # ── THE FIRST ONE IS VERIFIED BEFORE A SECOND IS WRITTEN ──────────
                    # The banner promises this. Verifying only at the end would mean a wrong
                    # write shape rewrote the whole collection before anything noticed — and
                    # the rows would read as vectorless the entire time, which is exactly the
                    # signal the banner tells people NOT to panic about. The promise has to
                    # be true or the banner is asking for trust it has not earned.
                    if not verified_once:
                        verified_once = True
                        since_verify = 0
                        if not _verify(obj["id"], "first relocated row"):
                            _report("STOPPED after")
                            print("   STOPPING BEFORE THE NEXT WRITE. One row was rewritten "
                                  "and is not searchable: the write shape is wrong, not the "
                                  "plan. Nothing else has been touched.", file=sys.stderr)
                            return 1
                    elif args.verify_every and since_verify >= args.verify_every:
                        since_verify = 0
                        if not _verify(obj["id"], "every %d" % args.verify_every):
                            _report("STOPPED after")
                            print("   STOPPING: a later row regressed. Earlier rows verified, "
                                  "so this is not the write shape — check the store's health "
                                  "before continuing.", file=sys.stderr)
                            return 1

                if args.progress_every and seen % args.progress_every == 0:
                    _report("...")

            if args.limit and (seen - args.offset) >= args.limit and wanted is None:
                break
    except requests.HTTPError as exc:
        # COUNTS ON THE WAY OUT. An HTTP error mid-walk used to surface as a bare traceback,
        # which leaves the operator not knowing how many rows were already rewritten — and that
        # is the single fact they need to decide whether to resume or investigate.
        _report("FAILED after")
        print("   HTTP error: %s" % exc, file=sys.stderr)
        body = getattr(getattr(exc, "response", None), "text", "")
        if body:
            print("   body: %s" % body[:500], file=sys.stderr)
        print("   Re-running is safe: relocated rows are skipped as `already-named`.",
              file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        _report("INTERRUPTED after")
        print("   Re-running is safe: relocated rows are skipped as `already-named`.",
              file=sys.stderr)
        return 1

    _report("done:")

    # ── SAY WHETHER THE BLANK CHECK WAS LIVE, RATHER THAN LEAVING IT TO BE ASSUMED ───────
    if seen and not with_uri:
        if cls in URILESS_CLASSES:
            print("   the blank-node check was INERT here: %s rows carry no `uri` property, "
                  "which is expected and correct — a %s row is a verb registration, not an RDF "
                  "class node." % (cls, cls))
        else:
            rc = 2
            print("   %s rows carry NO `uri` property, so the blank-node check could not fire "
                  "on ANY row of this collection and every row was treated as named by "
                  "default. That may be right, but nothing here established it. This run is "
                  "NOT clean." % cls, file=sys.stderr)
    elif seen:
        print("   the blank-node check was live on %d of %d rows (those carrying a `uri`)"
              % (with_uri, seen))

    if ambiguous_uris:
        # ── AN UNDECIDED ROW FAILS THE RUN. IT IS NOT SKIPPED QUIETLY ────────────────────
        # These matched the loose blank spelling and NOT rdflib's documented one. Nothing was
        # written for them either way — but a run that leaves them unexplained must not exit 0,
        # because the next person reads a clean exit as "the partition was clean".
        rc = 2
        print("   %d row(s) are UNDECIDED: blank under the loose spelling, named under "
              "rdflib's. Nothing was written for them. This run is NOT clean — the two "
              "spellings disagree and someone must say which is right before an --apply "
              "means anything." % len(ambiguous_uris), file=sys.stderr)
        for u in sorted(ambiguous_uris)[:20]:
            print("      %s" % u, file=sys.stderr)
        if len(ambiguous_uris) > 20:
            print("      ... and %d more" % (len(ambiguous_uris) - 20), file=sys.stderr)

    if novector_uris:
        # ── THE ONE CASE THIS SCRIPT CANNOT REPAIR, NAMED RATHER THAN COUNTED ────────────
        print("   %d NAMED row(s) carry NO VECTOR AT ALL. A relocation cannot repair them — "
              "there is nothing to relocate — they need a RE-EMBED and that is doc-tools' work. "
              "Blank nodes are NOT in this count: they are skipped above, so this number is the "
              "re-embed ask and not a population that also needs filtering."
              % len(novector_uris))
        if args.list_no_vector:
            with open(args.list_no_vector, "w", encoding="utf-8") as fh:
                fh.write("# %s rows with no vector in either slot, %s\n"
                         % (cls, time.strftime("%Y-%m-%d")))
                for u in sorted(novector_uris):
                    fh.write(u + "\n")
            print("   wrote %d uri(s) to %s" % (len(novector_uris), args.list_no_vector))
        else:
            for u in sorted(novector_uris)[:10]:
                print("      %s" % u)
            if len(novector_uris) > 10:
                print("      ... and %d more (use --list-no-vector FILE for all)"
                      % (len(novector_uris) - 10))

    if args.apply and not verified_once:
        print("   nothing was relocated, so there is nothing to verify")
    return rc


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--classes", default=",".join(ROUTING_CLASSES),
                   help="comma-separated; default the two routing collections")
    p.add_argument("--offset", type=int, default=0, help="skip this many rows first")
    p.add_argument("--limit", type=int, default=0, help="stop after this many (0 = all)")
    p.add_argument("--canary", choices=sorted(CANARY_SETS),
                   help="a named row set defined IN this file, so it travels into a pod")
    p.add_argument("--uris", help="comma-separated uris; works when stdin is the script")
    p.add_argument("--uris-file", help="uris from a file — only for runs from a checkout")
    p.add_argument("--page-size", type=int, default=100)
    p.add_argument("--progress-every", type=int, default=2000,
                   help="print running counts every N rows (0 = off)")
    p.add_argument("--verify-every", type=int, default=500,
                   help="re-verify a relocated row every N relocations (0 = first only)")
    p.add_argument("--verify-k", type=int, default=5,
                   help="top-k for the self-retrieval check; the largest measured duplicate "
                        "group is 2, and it widens itself on a saturated page")
    p.add_argument("--list-no-vector", metavar="FILE",
                   help="write the uris that carry no vector at all (re-embed work) here")
    p.add_argument("--apply", action="store_true",
                   help="actually write. Without it this is a dry run.")
    p.add_argument("--i-have-read-the-warning", action="store_true",
                   help="required with --apply; see the banner at the top of this file")
    args = p.parse_args(argv)

    chosen = [f for f in (args.canary, args.uris, args.uris_file) if f]
    if len(chosen) > 1:
        print("REFUSING: give at most one of --canary / --uris / --uris-file.", file=sys.stderr)
        return 2

    if args.apply and not args.i_have_read_the_warning:
        print(__doc__.split("## What is wrong")[0], file=sys.stderr)
        print("REFUSING: --apply requires --i-have-read-the-warning. After this runs, every "
              "repaired row reads as having NO vector on every instrument this fleet has been "
              "using. That is the repair working. Read the banner above, then pass the flag.",
              file=sys.stderr)
        return 2

    unknown = [c for c in args.classes.split(",") if c not in ROUTING_CLASSES]
    if unknown:
        # DocumentChunk is on the legacy schema and WORKS. Relocating its vectors would break
        # the one collection that is currently fine, so this refuses by default rather than
        # trusting whoever typed the flag at 2am.
        print("REFUSING: %r is not a routing collection. This script relocates vectors and "
              "`DocumentChunk` is on the legacy schema where that is CORRECT — moving them "
              "would break the only collection that works. Known: %r"
              % (unknown, list(ROUTING_CLASSES)), file=sys.stderr)
        return 2

    print("weaviate at %s | space read per collection | %s"
          % (BASE, "APPLYING" if args.apply else "DRY RUN"))
    rc = 0
    for cls in args.classes.split(","):
        rc |= run_class(cls, args)
    if not args.apply:
        print()
        print("DRY RUN — nothing was written. Re-run with --apply "
              "--i-have-read-the-warning to perform the relocation.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
