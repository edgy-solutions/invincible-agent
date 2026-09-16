"""LIVE PROBE — how many rows declare themselves domain-agnostic, per Weaviate collection.

THE CENSUS LINE for ADR-0009's OR-filter: *"OR of `domains contains_any [entitled]` and
`domains == []` to keep domain-agnostic predicates visible to scoped callers."* That branch is
either load-bearing or dead, and only the substrate can say which. Measured 2026-09-14 against
sandbox:

    Predicate       129 rows,  27 with len(domains) == 0     -> 21% ARE domain-agnostic
    OntologyClass 21078 rows,   0 domain-agnostic            -> 8 distinct domains, all non-empty

**SO THE PREDICATE BRANCH IS LOAD-BEARING AND THE CLASS BRANCH WOULD BE DEAD.** Removing the
first would drop a fifth of the routing table out of every scoped search. Adding the second
would be a guard that cannot fire — and worse, see below.

**THE CLASS SIDE CANNOT EXPRESS THE BRANCH AT ALL ON THIS SCHEMA**, which is why the two call
sites differ. It is a schema divergence, not a code choice:

    Predicate     invertedIndexConfig.indexPropertyLength = True   -> len(domains)==0 filters
    OntologyClass invertedIndexConfig.indexPropertyLength = unset  -> len(domain)==0 RAISES

and `_weaviate_hybrid_search_sync` wraps its query in `except Exception: return []`, so a
length filter added there would not error loudly — **it would empty the class candidate pool in
silence.** Routing down, service green. That combination is why this probe exists rather than a
patch.

THIS IS A PROBE, NOT A SEAL, AND THE DIFFERENCE IS NOT A DETAIL. It is run on demand — it needs a
port-forward and a live substrate, which CI does not have — so **it cannot go red on its own.** A
collected seal risks being triaged as flakiness at the failure line; this one risks never firing at
all, which is the other failure and the one that reads as safety.

**Its trigger has an OWNER and an OCCASION, which is the only mitigation here that is not a claim:**
`doc-tools-7f` asked for it to be re-run after the next prime, for their own reason — whether a
re-ingest rewrites existing rows decides whether their 2026-09-12 derived-labels fix is live. **A
trigger somebody else is waiting on is the only kind that reliably fires.** If that stops being
true, this file is a report with a date on it, not a check.

What it asserts when it IS run: if a domain-agnostic OntologyClass row ever appears, the class side
needs a rule it currently cannot express, and someone has to be told.

Run (read-only, aggregate counts only — no object contents leave the cluster):

    kubectl port-forward -n sandbox svc/iagent-weaviate 18080:8080 &
    py tests/sandbox_e2e/_probe_domain_agnostic_rows.py
"""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:18080"

#: Measured 2026-09-14. The PREDICATE figure is expected to move — verbs get registered — so it is
#: reported, not asserted. The CLASS figure is asserted: zero is the premise the missing branch
#: rests on, and the day it stops being zero the rule has a hole.
EXPECTED_AGNOSTIC_CLASSES = 0


def _gql(query: str) -> dict:
    req = urllib.request.Request(
        f"{BASE}/v1/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _count(cls: str, where: str | None = None) -> int | str:
    clause = f"(where:{where})" if where else ""
    out = _gql("{ Aggregate { %s%s { meta { count } } } }" % (cls, clause))
    if out.get("errors"):
        return f"ERROR: {out['errors'][0].get('message', '?')[:120]}"
    return out["data"]["Aggregate"][cls][0]["meta"]["count"]


def _domain_values(cls: str, prop: str) -> list[tuple[int, str]]:
    out = _gql(
        '{ Aggregate { %s(groupBy:["%s"]) { meta { count } groupedBy { value } } } }' % (cls, prop)
    )
    if out.get("errors"):
        return []
    rows = out["data"]["Aggregate"][cls]
    return sorted(((r["meta"]["count"], r["groupedBy"]["value"]) for r in rows), reverse=True)


def main() -> int:
    predicates = _count("Predicate")
    agnostic_predicates = _count("Predicate", '{path:["len(domains)"],operator:Equal,valueInt:0}')
    classes = _count("OntologyClass")
    class_domains = _domain_values("OntologyClass", "domain")

    # The class side has no length index, so "agnostic" is derived by subtraction: every row that
    # carries one of the declared domain values, against the total. A groupBy cannot report rows
    # with no value to group by, which is exactly why the subtraction is the measurement.
    grouped = sum(n for n, _ in class_domains)
    agnostic_classes = classes - grouped if isinstance(classes, int) else "UNKNOWN"

    print(f"Predicate      total            : {predicates}")
    print(f"Predicate      len(domains) == 0: {agnostic_predicates}   <- ADR-0009's branch, load-bearing")
    print(f"OntologyClass  total            : {classes}")
    print(f"OntologyClass  grouped by domain: {grouped} across {len(class_domains)} values")
    print(f"OntologyClass  domain-agnostic  : {agnostic_classes}")
    for n, v in class_domains:
        print(f"                  {n:>7}  {v!r}")

    if agnostic_classes != EXPECTED_AGNOSTIC_CLASSES:
        print()
        print(f"RED: {agnostic_classes} OntologyClass row(s) carry no domain, expected "
              f"{EXPECTED_AGNOSTIC_CLASSES}.")
        print("     The class search has NO domain-agnostic branch and cannot be given one on this")
        print("     schema (indexPropertyLength is unset on OntologyClass, so a length filter")
        print("     raises, and the call site returns [] on any exception — silently).")
        print("     Those rows are invisible to every domain-scoped caller. Either the schema gains")
        print("     property-length indexing (immutable post-creation: recreate + re-ingest), or")
        print("     the writer must stop producing domain-less classes.")
        return 1

    print()
    print(f"GREEN: no domain-agnostic OntologyClass rows, so the missing branch has no subject.")
    print(f"       {agnostic_predicates} of {predicates} predicates ARE agnostic — that branch stays.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
