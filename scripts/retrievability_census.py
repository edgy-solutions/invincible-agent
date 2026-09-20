#!/usr/bin/env python3
"""READ-ONLY census: does EVERY row in a routing collection pass nearObject(self)?

Why this exists beside `backfill_vector_space.py`, which already knows how to check one row:
that script's built-in verification runs on the rows a run actually REPAIRED, so in a dry run
it verifies nothing, and after a successful apply it verifies the FIRST repaired row. Neither
answers the question an order asks before deciding not to backfill —

    is `retrievable` equal to `total`, for every row, right now?

A slot-state count is a strong proxy and is NOT that claim: it reads what is stored, while
`nearObject(self)` reads what the INDEX can reach. Those came apart once already (a row whose
`vector` read back 768 dims and whose search answered "vector not found for target: default"),
which is the whole reason the named-space fix exists. So this asks the consuming operation.

WHAT IT WRITES: nothing. GETs, plus GraphQL reads. Safe to run during anything.

NEGATIVE CONTROL, ALWAYS, NOT ON REQUEST. `n/n retrievable` is a uniform extreme, and a checker
that cannot answer False produces one on a broken store as readily as a healthy one. So every
run also asks nearObject on a uuid that does not exist and REFUSES TO REPORT if that came back
retrievable. A green here is only worth the control that ran beside it.

RUN IT FROM INSIDE A POD, not through a port-forward -- a dead forward looks exactly like an
empty collection, and forwards die across every roll:

    kubectl -n sandbox exec -i <engine-o pod> -- python - --classes Predicate \\
        < scripts/retrievability_census.py

    ... python - --classes Predicate --since 2026-09-19T20:13:55Z   # flag rows newer than a baseline

Env is read from the pod: WEAVIATE_URL, else WEAVIATE_HTTP_HOST/WEAVIATE_HOST (+ _PORT). The
indexed space name is read from each collection's own schema, never imported -- the same reason
the backfill reads it: this must run against images that predate the fix.
"""

from __future__ import annotations

import argparse
import calendar
import os
import sys
import time

try:
    import requests
except ImportError:  # pragma: no cover
    print("ERROR: pip install requests", file=sys.stderr)
    sys.exit(1)


def _base_url():
    """The store's HTTP base, tolerating the three env shapes the fleet actually uses.

    Kept identical in behaviour to backfill_vector_space._base_url: engine-o carries both
    conventions at once, and a host value that already contains a port must not get another
    appended (that built `...:8080:8080` and died on an InvalidURL).
    """
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
BOGUS_UUID = "00000000-dead-4000-8000-000000000000"


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
    """The name of the vector space THIS collection indexes, per its own schema.

    Zero named spaces means the LEGACY single-vector schema, where nearObject still works and
    the named-space question does not apply; it is reported rather than treated as a failure.
    """
    sch = _get("/v1/schema/" + cls)
    names = sorted((sch.get("vectorConfig") or {}))
    if len(names) == 1:
        return names[0]
    return None if not names else ",".join(names)


TOP_K = 5
NEAR_ZERO = 1e-4


def retrievable(cls, uuid):
    """Self within top-k at distance ~0 -- the RULED shape, and deliberately not `rows[0]`.

    The obvious test is "self is the single nearest neighbour". It is wrong, and measuring it is
    what showed why: five `Predicate` rows failed it while sitting correctly in the named space.
    Each has a TWIN -- a sibling row whose `search_text` embeds to within ~1.8e-07 -- and the
    tie is broken toward the twin, so self lands at rank 2 and a `limit:1` check calls a healthy,
    searchable row unreachable. `mesh:assessImpact Dataset->ImpactSet` vs `Column->ImpactSet` is
    the worked example.

    So the question is "can the index reach this row", not "does it rank first among duplicates".
    Returns (ok, note) -- note is non-empty when self was reachable but NOT rank 0, because a
    duplicate-vector pair is worth reporting even though it is not a retrievability failure.
    """
    q = ('{Get{%s(nearObject:{id:"%s"} limit:%d){_additional{id distance}}}}'
         % (cls, uuid, TOP_K))
    r = requests.post(BASE + "/v1/graphql", json={"query": q}, timeout=120).json()
    if r.get("errors"):
        return False, r["errors"][0].get("message", "")[:160]
    rows = (((r.get("data") or {}).get("Get") or {}).get(cls) or [])
    for rank, row in enumerate(rows):
        add = row.get("_additional") or {}
        if add.get("id") != uuid:
            continue
        dist = add.get("distance")
        if dist is not None and abs(dist) > NEAR_ZERO:
            return False, "self found at rank %d but distance %.3g exceeds ~0" % (rank, dist)
        if rank == 0:
            return True, ""
        twin = ((rows[0].get("_additional") or {}).get("id"), (rows[0].get("_additional") or {}).get("distance"))
        return True, "reachable at rank %d; duplicate-vector twin %s at distance %.3g" % (
            rank, twin[0], twin[1] if twin[1] is not None else float("nan"))
    if not rows:
        return False, "nearObject returned no rows at all"
    return False, "self absent from top-%d (nearest was %s)" % (
        TOP_K, (rows[0].get("_additional") or {}).get("id"))


def label(obj):
    """A human identifier for a row, from whatever the collection actually carries.

    `Predicate` has NO `uri` property -- a first version of this probe assumed one and printed
    every row blank, which turns a finding into an unreadable list of uuids. OntologyClass does
    carry `uri`. So the label is derived from the properties that exist, and falls back to the
    uuid rather than to an empty string.
    """
    p = obj.get("properties") or {}
    if p.get("uri"):
        return str(p["uri"])
    verb = p.get("verb_iri") or p.get("verb_local")
    if verb:
        bits = [str(verb)]
        src = str(p.get("input_uri") or "").rsplit("#", 1)[-1]
        dst = str(p.get("output_uri") or "").rsplit("#", 1)[-1]
        if src or dst:
            bits.append("%s->%s" % (src or "?", dst or "?"))
        if p.get("frontend_id"):
            bits.append(str(p["frontend_id"]))
        return " ".join(bits)
    return obj.get("id", "?")


def slot_state(obj, space):
    legacy = obj.get("vector")
    named = (obj.get("vectors") or {}).get(space) if space else None
    if named:
        return "named"
    if legacy:
        return "legacy"
    return "no-vector"


def _cutoff_ms(text):
    """ISO8601 Z -> unix ms. Weaviate reports creationTimeUnix in milliseconds."""
    if not text:
        return None
    if text.isdigit():
        return int(text)
    return int(calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ"))) * 1000


def run_class(cls, cutoff_ms):
    print("=" * 78)
    print("%s  RETRIEVABILITY CENSUS (read-only)" % cls)
    print("=" * 78)
    space = space_of(cls)
    print("   indexed vector space, read from the schema: %r" % space)

    # The control runs FIRST. If the checker cannot say False, no per-row green means anything.
    ctrl_ok, ctrl_why = retrievable(cls, BOGUS_UUID)
    print("   NEGATIVE CONTROL nearObject(%s) -> %s%s"
          % (BOGUS_UUID, "RETRIEVABLE" if ctrl_ok else "not retrievable",
             ("  (%s)" % ctrl_why) if ctrl_why else ""))
    if ctrl_ok:
        print("   REFUSING TO REPORT: the checker called a nonexistent uuid retrievable, so it "
              "cannot distinguish the states this census exists to distinguish.", file=sys.stderr)
        return 1, None

    total = 0
    ok_count = 0
    notes = []
    failures = []
    newer = []
    stamped = 0
    states = {}
    after = None
    t0 = time.time()

    while True:
        objs = page(cls, after=after)
        if not objs:
            break
        after = objs[-1]["id"]
        for obj in objs:
            total += 1
            uuid = obj["id"]
            uri = label(obj)
            st = slot_state(obj, space)
            states[st] = states.get(st, 0) + 1
            ok, why = retrievable(cls, uuid)
            if ok:
                ok_count += 1
                if why:
                    notes.append((uri, uuid, why))
            else:
                failures.append((uri, uuid, st, why))
            created = obj.get("creationTimeUnix")
            if created is not None:
                stamped += 1
                if cutoff_ms is not None and int(created) > cutoff_ms:
                    newer.append((uri, uuid, int(created), st, ok))

    print("   total rows          : %d" % total)
    print("   retrievable         : %d" % ok_count)
    # ALL THREE buckets are printed, zeros included, and they are asserted to sum to the total.
    # A dict of counts silently omits the bucket that is empty, so "no vectorless rows" would be
    # read off an ABSENT line -- a plausible negative rather than a measured one. The third
    # bucket has a known writer (a properties-only batch replace clears the vector), so its being
    # zero is a claim someone will rely on.
    print("   slot states         : named=%d, legacy=%d, no-vector=%d"
          % (states.get("named", 0), states.get("legacy", 0), states.get("no-vector", 0)))
    partition = states.get("named", 0) + states.get("legacy", 0) + states.get("no-vector", 0)
    print("   partition sums to   : %d of %d  %s"
          % (partition, total,
             "(every row is in exactly one bucket)" if partition == total
             else "*** MISMATCH — a row escaped the partition ***"))
    if states.get("no-vector", 0):
        print("   NOTE: %d row(s) have NO VECTOR IN EITHER SLOT. A relocation backfill cannot "
              "repair these — there is nothing to relocate; they need a RE-EMBED."
              % states["no-vector"])
    print("   VERDICT             : %s"
          % ("retrievable == total" if ok_count == total and total
             else "RETRIEVABLE != TOTAL — %d row(s) unreachable" % (total - ok_count)))

    if failures:
        # The breakdown is COMPUTED, not read off the list below: a truncated listing is a
        # sample, and reading "how many named rows fail" off one gave 4 where the answer was 5.
        by_slot = {}
        for _uri, _uuid, st, _why in failures:
            by_slot[st] = by_slot.get(st, 0) + 1
        print("   failures by slot state: %s"
              % ", ".join("%s=%d" % kv for kv in sorted(by_slot.items())))
        named_failing = by_slot.get("named", 0)
        if named_failing:
            print("   NOTE: %d row(s) are in the NAMED space and STILL fail nearObject(self). A "
                  "slot-state count would call these healthy; they are not, and a relocation "
                  "backfill cannot fix them -- there is nothing to relocate." % named_failing)
        print("   rows that FAIL nearObject(self), ALL of them:")
        for uri, uuid, st, why in failures:
            print("     %-52s %s slot=%-7s %s" % (uri[:52], uuid, st, why[:70]))

    if notes:
        print("   reachable, but NOT rank 0 — duplicate-vector pairs (%d). Not a retrievability "
              "failure; recorded because two rows embedding to ~0 apart is a routing hazard of "
              "its own:" % len(notes))
        for uri, uuid, why in notes:
            print("     %-52s %s %s" % (uri[:52], uuid, why))

    # Absence of timestamps must not read as "no new rows".
    print("   rows carrying creationTimeUnix: %d of %d" % (stamped, total))
    if cutoff_ms is None:
        print("   (no --since given, so no row was classified as new)")
    elif stamped < total:
        print("   WARNING: %d row(s) carry NO creation timestamp, so 'newer than the baseline' "
              "is UNDECIDABLE for them — not empty." % (total - stamped))
    if cutoff_ms is not None:
        print("   rows newer than the cutoff: %d" % len(newer))
        for uri, uuid, created, st, ok in sorted(newer, key=lambda r: r[2]):
            print("     %-58s %s  created=%s  slot=%s  retrievable=%s"
                  % (uri[:58], uuid,
                     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(created / 1000.0)),
                     st, ok))

    print("   (%.1fs)" % (time.time() - t0))
    return (0 if ok_count == total and total else 1), total


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--classes", default="Predicate",
                   help="comma-separated collections (default: Predicate)")
    p.add_argument("--since", default=None,
                   help="ISO8601 Z or unix ms; rows created after it are listed")
    args = p.parse_args(argv)

    print("store: %s" % BASE)
    cutoff = _cutoff_ms(args.since)
    if cutoff is not None:
        print("cutoff: %s (%d ms)"
              % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(cutoff / 1000.0)), cutoff))

    rc = 0
    for cls in [c.strip() for c in args.classes.split(",") if c.strip()]:
        code, _ = run_class(cls, cutoff)
        rc = rc or code
    return rc


if __name__ == "__main__":
    sys.exit(main())
