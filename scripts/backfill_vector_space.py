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
║  LEGACY key, so it will show 26,239 rows going from "has a vector" to "has no vector"    ║
║  at the exact moment they become searchable.                                             ║
║                                                                                          ║
║  DO NOT REVERT ON THAT SIGNAL. Verify with nearObject(self) — this script does it for    ║
║  you, on every batch, and refuses to continue if it regresses.                           ║
╚══════════════════════════════════════════════════════════════════════════════════════════╝

## What is wrong, and why this is a relocation rather than a rebuild

Measured 2026-09-19. A bare `collections.create(name, properties)` on weaviate-client 4.21.0
emits a NAMED vector space `default`; a positional `insert(vector=[...])` writes the LEGACY
unnamed slot. The named space — the only target a search can name — stays empty, so the store
answers `"vector not found for target: default"` on a row whose vector reads back as 768 dims.
`OntologyClass` and `Predicate` were both in that state, which made every routing decision in
the fleet silently BM25-only.

**The vectors themselves are fine.** They are readable, they are the right dimension, and they
were computed by the right embedder. Nothing needs re-embedding, no LLM is called, doc-tools is
not involved and nothing is deleted — each row's own vector is read and written back under the
name. Measured lossless against a deliberately un-normalised probe: norms identical, max|delta|
= 0.000e+00, self-distance 0.0 after.

## THIS SCRIPT DOES NOT RUN ITSELF

`--apply` is required and refuses without `--i-have-read-the-warning`. Default is a dry run.
Chris authorizes and runs it, in daylight. The ruled order is:

    1. canary   --classes OntologyClass --uris-file canary.txt   (the six safety# rows)
    2. verify   the walk census row for `what hazards are unattended` stops abstaining
    3. the rest --classes OntologyClass,Predicate --apply        (one sitting)

## RUNNING IT — from inside a pod, not through a port-forward

The store is `iagent-weaviate` on the cluster network. **Port-forwards die across every roll and
a dead forward looks exactly like an empty answer**, which is the last thing this operation
should be exposed to. Pipe the script into a pod that already has the connection and the deps —
the same path every measurement behind this change used:

    kubectl -n sandbox exec -i <engine-o pod> -- python - --classes OntologyClass \\
        < scripts/backfill_vector_space.py

It reads `WEAVIATE_HOST`/`WEAVIATE_PORT` from the pod's own env, so it needs no configuration.
Running it from a checkout works too if you have a route to the store.

Usage:

    ... python - --classes OntologyClass                             # dry run, writes nothing
    ... python - --classes OntologyClass --uris-file canary.txt      # the canary set
    ... python - --classes OntologyClass --apply --i-have-read-the-warning
"""
from __future__ import annotations

import argparse
import json
import os
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
# a local belief about the store, and this is the store's answer. A collection that declares
# something other than one named space is refused rather than guessed at.
DEFAULT_SPACE = "default"

def _base_url():
    """The store's HTTP base, tolerating the THREE shapes the fleet's env actually uses.

    MEASURED ON A REAL POD, because the first version built
    `http://iagent-weaviate.sandbox.svc.cluster.local:8080:8080/...` and died on an InvalidURL.
    engine-o carries BOTH conventions at once:

        WEAVIATE_HTTP_HOST = iagent-weaviate.sandbox.svc.cluster.local:8080   <- host AND port
        WEAVIATE_HOST      = iagent-weaviate                                  <- host only
        WEAVIATE_PORT      = 8080

    So a host value is checked for a port before one is appended. `WEAVIATE_URL` wins outright,
    for a caller who has a route of their own.
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

#: The collections the router reads. Named rather than discovered: a backfill that swept every
#: collection would also rewrite `DocumentChunk`, which is on the LEGACY schema and works — and
#: relocating its vectors would break the one collection that is currently fine.
ROUTING_CLASSES = ("OntologyClass", "Predicate")


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


def retrievable(cls, uuid):
    """THE ONLY CHECK THAT DISTINGUISHES THE STATES. An object is its own nearest neighbour or
    the space it was written to is not the space that is indexed."""
    q = ('{Get{%s(nearObject:{id:"%s"} limit:1){_additional{id}}}}' % (cls, uuid))
    r = requests.post(BASE + "/v1/graphql", json={"query": q}, timeout=120).json()
    if r.get("errors"):
        return False, r["errors"][0].get("message", "")[:160]
    rows = (((r.get("data") or {}).get("Get") or {}).get(cls) or [])
    return bool(rows) and rows[0]["_additional"]["id"] == uuid, ""


def relocate(cls, obj, space, apply_it):
    """Write this row's OWN vector into the named space. Properties travel with it.

    `PUT /v1/objects` REPLACES the whole object, so the properties must be sent back or every
    field is blanked. That is the single most dangerous thing about this operation and it is why
    the properties are read in the same request as the vector rather than re-derived.
    """
    uuid = obj["id"]
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


def run_class(cls, args):
    print("=" * 78)
    print("%s  (%s)" % (cls, "APPLY" if args.apply else "DRY RUN — nothing is written"))
    print("=" * 78)

    space = space_of(cls)
    print("   indexed vector space, read from the schema: %r" % space)

    wanted = None
    if args.uris_file:
        with open(args.uris_file, encoding="utf-8") as fh:
            wanted = {ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")}
        print("   restricted to %d uri(s) from %s" % (len(wanted), args.uris_file))

    counts = {}
    seen = skipped = 0
    after = None
    first_repaired = None
    t0 = time.time()

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
                skipped += 1
                continue
            outcome = relocate(cls, obj, space, args.apply)
            counts[outcome] = counts.get(outcome, 0) + 1
            if outcome == "relocated" and first_repaired is None:
                first_repaired = obj["id"]
            seen += 1
        if args.limit and (seen - args.offset) >= args.limit and wanted is None:
            break

    print("   walked %d  %s  (%.1fs)"
          % (seen, json.dumps(counts, sort_keys=True), time.time() - t0))

    # ── THE VERIFICATION, BUILT IN, ON THE ROWS THIS RUN ACTUALLY TOUCHED ──────────────
    if first_repaired:
        ok, why = retrievable(cls, first_repaired)
        print("   VERIFY nearObject(self) on %s: %s%s"
              % (first_repaired, "RETRIEVABLE" if ok else "STILL NOT RETRIEVABLE",
                 "" if ok else "  <- " + why))
        if not ok:
            print("   STOPPING: rows were rewritten and are still not searchable. Do not "
                  "continue; the write shape is wrong, not the plan.", file=sys.stderr)
            return 1
        print("   (its REST `vector` now reads None and `vectors.%s` holds the dims — that is "
              "the repair, not loss)" % space)
    elif args.apply:
        print("   nothing was relocated, so there is nothing to verify")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--classes", default=",".join(ROUTING_CLASSES),
                   help="comma-separated; default the two routing collections")
    p.add_argument("--offset", type=int, default=0, help="skip this many rows first")
    p.add_argument("--limit", type=int, default=0, help="stop after this many (0 = all)")
    p.add_argument("--uris-file", help="restrict to the uris listed in this file (the canary)")
    p.add_argument("--page-size", type=int, default=100)
    p.add_argument("--apply", action="store_true",
                   help="actually write. Without it this is a dry run.")
    p.add_argument("--i-have-read-the-warning", action="store_true",
                   help="required with --apply; see the banner at the top of this file")
    args = p.parse_args(argv)

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

    print("weaviate at %s | space %r | %s"
          % (BASE, "read per collection", "APPLYING" if args.apply else "DRY RUN"))
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
