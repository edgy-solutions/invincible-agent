"""Engine W identity census: does the per-chunk gate decide the same for every identity on both
retrieval paths of ``KNOWLEDGE_SEARCH_VIA_MESH``?

Written 2026-10-06 for Lane 1 to run after roll #20, which ships the flag (default off).

TWO HALVES.

RUN -- inside the Engine W container, ONCE PER FLAG VALUE. The flag is read at import, so each run
is its own process and no roll is needed between them. Pipe this file on stdin to the image's
interpreter, from the image's WORKDIR (``/app``, where ``service.py`` lives). The container exec
runs no shell, so the flag goes through ``env``::

    env KNOWLEDGE_SEARCH_VIA_MESH=false /app/.venv/bin/python - run --label off \
        --identity <email> [--identity <email> ...]   > off.json
    env KNOWLEDGE_SEARCH_VIA_MESH=true  /app/.venv/bin/python - run --label on \
        --identity <email> [--identity <email> ...]   > on.json

stdout carries the JSON and nothing else; the module's own prints go to stderr. A run REFUSES TO
START if the imported module's flag is not the one its label claims (the env did not reach the
import), or if agentic auth is off (every identity would keep everything: a census of nothing).
Pass the SAME identities and queries to both runs; the diff refuses two different censuses.

DIFF -- anywhere, stdlib only::

    python scripts/probes/engine_w_identity_census.py diff off.json on.json

WHAT IS COMPARED. Both paths search by ``near_vector``, but the mesh reader builds its own rows, so
a source may be RETRIEVED by one path only -- that is retrieval, not the gate, and is REPORTED, not
failed. The claim is the GATE's: for every (identity, query) and every source retrieved by BOTH
paths, kept on one iff kept on the other. Every one of these is a red:

* a shared source the two paths decide differently;
* a source kept AND dropped within one run (the gate was not a function of the source);
* a run whose own replication of the search-then-gate disagrees with ``retrieve_gated_chunks``
  (the census would be a claim about this script, not the live function);
* a real identity whose search failed or was refused on either path;
* POPULATION: no shared cell at all, or no real identity keeping any shared source -- parity on a
  gate that keeps nothing is parity on a shut door;
* the DENY CONTROL (an identity with no grants) keeping anything, on either path;
* the EMPTY CALLER doing anything but the one ruled difference (2026-10-04, difference 1): ON, the
  SDK's ``Initiator`` refuses before any search; OFF, the search runs and the gate keeps nothing.

Exit 0 when nothing is red, 1 otherwise, 2 on a usage error.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

#: The sandbox e2e's three knowledge queries (tests/sandbox_e2e/test_engine_w_knowledge.py), with
#: the domain each names. Override with ``--query DOMAIN=text``.
DEFAULT_QUERIES = [
    ("MAINTENANCE", "what are the common failure modes of an aircraft auxiliary fuel pump?"),
    ("MAINTENANCE", "what is the inspection schedule for the C-130 APU?"),
    ("MANUFACTURING", "what is the standard cure cycle for an epoxy carbon fiber laminate?"),
]

#: An identity no grant names: the gate must keep nothing for it on either path.
DENY_CONTROL = "census-deny-control@invalid.example"


# ── RUN (in the container) ─────────────────────────────────────────────────────────────────

def _source(obj) -> Optional[str]:
    """The source the gate decides on -- the same keys, in the same order, as
    ``service._gate_hits``. The run's cross-check compares POSITIONS, so it cannot see these labels
    drift; tests/test_engine_w_identity_census.py reads the keys out of service.py instead."""
    sid = (obj.properties.get("source_url") or obj.properties.get("uri")
           or obj.properties.get("doc_id"))
    return None if sid == "Unknown Document" else sid


def _cell(service, client, collection: str, identity: str, kind: str, domain: str,
          query: str) -> Dict[str, Any]:
    label = domain.upper().replace(" ", "_").replace("-", "_")   # as query_knowledge derives it
    cell: Dict[str, Any] = {"identity": identity, "kind": kind, "domain": domain, "query": query,
                            "refused": None, "hits": [], "agrees_with_live": None,
                            "live_refused": None}
    try:
        if service.KNOWLEDGE_SEARCH_VIA_MESH:
            hits = service._search_via_mesh(client, collection, label, query, None, identity)
        else:
            hits = service._search_direct(client, collection, label, query, None)
        kept, dropped = service._gate_hits(hits, identity)
    except Exception as exc:  # noqa: BLE001 -- the refusal IS the datum
        cell["refused"] = f"{type(exc).__name__}: {exc}"
        return cell
    kept_at = {i for i, _ in kept}
    cell["hits"] = [{"pos": i, "source": _source(o), "kept": i in kept_at}
                    for i, o in enumerate(hits)]
    try:
        live_kept, live_dropped, live_retrieved = service.retrieve_gated_chunks(
            client, collection_name=collection, domain_label=label, semantic_query=query,
            metadata_filters=None, caller_email=identity)
    except Exception as exc:  # noqa: BLE001 -- the live function refused what the replication ran
        cell["live_refused"] = f"{type(exc).__name__}: {exc}"
        cell["agrees_with_live"] = False
        return cell
    cell["agrees_with_live"] = (
        [i for i, _ in live_kept] == sorted(kept_at) and live_dropped == dropped
        and live_retrieved == len(hits))
    return cell


def run(label: str, identities: List[str], queries: List[Tuple[str, str]]) -> Dict[str, Any]:
    with contextlib.redirect_stdout(sys.stderr):      # the module prints at import and per search
        import service  # type: ignore[import-not-found] -- the container's /app/service.py
        flag = bool(service.KNOWLEDGE_SEARCH_VIA_MESH)
        if flag != (label == "on"):
            raise SystemExit(f"label {label!r} but the imported module's flag is {flag}: "
                             "set KNOWLEDGE_SEARCH_VIA_MESH in THIS process's environment")
        if not service.ENABLE_AGENTIC_AUTH:
            raise SystemExit("agentic auth is off: every identity keeps every chunk, and the "
                             "census would measure nothing")
        client = service.get_weaviate_client()
        collection = os.getenv("WEAVIATE_DOC_COLLECTION", "DocumentChunks")
        who = [(i, "real") for i in identities] + [(DENY_CONTROL, "deny"), ("", "empty")]
        cells = []
        for identity, kind in who:
            for domain, query in queries:
                print(f"[census] {label} {kind} {identity!r} {domain}: {query[:50]}")
                cells.append(_cell(service, client, collection, identity, kind, domain, query))
    return {"census": "engine-w-identity", "label": label, "flag": flag,
            "collection": collection, "cells": cells}


# ── DIFF (anywhere) ────────────────────────────────────────────────────────────────────────

def _decisions(cell) -> Dict[Optional[str], set]:
    out: Dict[Optional[str], set] = {}
    for h in cell["hits"]:
        out.setdefault(h["source"], set()).add(h["kept"])
    return out


def diff(off: Dict[str, Any], on: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """``(reds, notes)``. Pure: both arguments are the JSON a run wrote."""
    reds: List[str] = []
    notes: List[str] = []
    for doc, label, flag in ((off, "off", False), (on, "on", True)):
        if (doc.get("census"), doc.get("label"), doc.get("flag")) != (
                "engine-w-identity", label, flag):
            reds.append(f"the {label} file is not an Engine W census run with the flag {label}: "
                        f"{(doc.get('census'), doc.get('label'), doc.get('flag'))}")
    if reds:
        return reds, notes

    def key(c):
        return (c["identity"], c["kind"], c["domain"], c["query"])
    a = {key(c): c for c in off["cells"]}
    b = {key(c): c for c in on["cells"]}
    if set(a) != set(b) or off.get("collection") != on.get("collection"):
        reds.append(f"two different censuses: cells only off {sorted(set(a) - set(b))}, only on "
                    f"{sorted(set(b) - set(a))}, collections {off.get('collection')!r} / "
                    f"{on.get('collection')!r}")
        return reds, notes

    shared_cells = kept_shared = 0
    for k in sorted(a):
        identity, kind, domain, query = k
        where = f"{kind} {identity!r} {domain} {query[:40]!r}"
        x, y = a[k], b[k]
        for side, c in (("off", x), ("on", y)):
            if c["agrees_with_live"] is False:
                reds.append(f"{where}: the {side} run's replication disagrees with "
                            f"retrieve_gated_chunks (live refused: {c.get('live_refused')!r})")
            split = sorted(str(s) for s, d in _decisions(c).items() if len(d) > 1)
            if split:
                reds.append(f"{where}: on {side}, sources both kept and dropped: {split}")
        if kind == "empty":
            if x["refused"] or any(h["kept"] for h in x["hits"]):
                reds.append(f"{where}: OFF should search and keep nothing; got refused="
                            f"{x['refused']!r}, kept={[h['source'] for h in x['hits'] if h['kept']]}")
            if not y["refused"]:
                reds.append(f"{where}: ON should be refused by the SDK's Initiator before any "
                            f"search; it searched and returned {len(y['hits'])} hit(s)")
            continue
        if x["refused"] or y["refused"]:
            reds.append(f"{where}: the search did not run: off={x['refused']!r} on={y['refused']!r}")
            continue
        if kind == "deny":
            leaked = [(s, h["source"]) for s, c in (("off", x), ("on", y))
                      for h in c["hits"] if h["kept"]]
            if leaked:
                reds.append(f"{where}: the deny control kept {leaked}")
        dx, dy = _decisions(x), _decisions(y)
        only = sorted(str(s) for s in set(dx) ^ set(dy))
        if only:
            notes.append(f"{where}: retrieved by one path only (retrieval, not the gate): {only}")
        for s in set(dx) & set(dy):
            shared_cells += 1
            if dx[s] != dy[s]:
                reds.append(f"{where}: source {s!r} kept={sorted(dx[s])} off, "
                            f"kept={sorted(dy[s])} on")
            elif kind == "real" and dx[s] == {True}:
                kept_shared += 1
    if not shared_cells:
        reds.append("POPULATION: no source was retrieved by both paths for any identity; the "
                    "census compared nothing")
    elif not kept_shared:
        reds.append("POPULATION: no real identity kept any shared source; parity on a gate that "
                    "keeps nothing is parity on a shut door -- census an identity with a grant")
    notes.append(f"{shared_cells} shared (identity, query, source) decisions, {kept_shared} "
                 "kept by a real identity on both paths")
    return reds, notes


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="engine_w_identity_census", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="in the Engine W container: one flag value's census, JSON out")
    r.add_argument("--label", choices=("off", "on"), required=True)
    r.add_argument("--identity", action="append", required=True,
                   help="an end user's entitlement key (email); repeat for several")
    r.add_argument("--query", action="append", default=None, metavar="DOMAIN=text")
    d = sub.add_parser("diff", help="compare an off run with an on run")
    d.add_argument("off")
    d.add_argument("on")
    args = ap.parse_args(argv)

    if args.cmd == "run":
        if any(not i.strip() or i == DENY_CONTROL for i in args.identity):
            ap.error("--identity: a blank identity and the deny control are added by the census "
                     "itself, as controls")
        queries = DEFAULT_QUERIES
        if args.query:
            if any("=" not in q for q in args.query):
                ap.error("--query is DOMAIN=text")
            queries = [tuple(q.split("=", 1)) for q in args.query]
        json.dump(run(args.label, args.identity, queries), sys.stdout, indent=1)
        sys.stdout.write("\n")
        return 0

    with open(args.off, encoding="utf-8") as f:
        off = json.load(f)
    with open(args.on, encoding="utf-8") as f:
        on = json.load(f)
    reds, notes = diff(off, on)
    for n in notes:
        print(f"note  {n}")
    for red in reds:
        print(f"RED   {red}")
    print("GREEN: the gate decides alike on both paths" if not reds else f"{len(reds)} red(s)")
    return 1 if reds else 0


if __name__ == "__main__":
    sys.exit(main())
