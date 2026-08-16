#!/usr/bin/env python3
"""Run the resolver corpus against a live Engine O and record what it decided.

    python scripts/run_resolver_corpus.py --base-url http://localhost:8000 --repeat 10 \
        --out sandbox.jsonl
    python scripts/run_resolver_corpus.py --base-url http://work-engine-o:8000 --repeat 10 \
        --out work.jsonl
    python scripts/run_resolver_corpus.py --diff sandbox.jsonl work.jsonl

WHY SIX COLUMNS AND NOT ONE. A corpus that records only the chosen class would have
missed the defect it was built for. `ClassifyDomainIntent` emits the class AND the
instance identifier in ONE call, and instance resolution is gated on the latter
(ontology_service/main.py:1638) — so a query can select a perfectly defensible class and
still fail to ground, which is exactly what work saw. Both outputs are recorded, plus
whether the deterministic instance path was reached at all.

THE PRIMARY MEASURE IS `instance_fired`, NOT THE CLASS. `_DATAHUB_TO_IDP` maps a DataHub
DATASET to idp:Table, so for a real table `idp:Table` is the CATALOG's answer and picking
it is not a defect. The defect is the class coming from a model's guess about a kind of
thing rather than the phone book's answer about this thing.

THE ARGMAX COUNTERFACTUAL is recorded free from the `candidates` the response already
returns: what a pure top-score rule WOULD have chosen. It documents rather than asserts
that the one-line interim is unavailable — expect rows where argmax and the LLM disagree
AND `instance_fired` is false, i.e. fixing selection alone would not have grounded them.

Read-only. Every call is a GET-shaped POST to /resolve plus two /find_compatible_verbs
probes; nothing is written to any store.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter, defaultdict

try:
    import requests
    import yaml
except ImportError:  # pragma: no cover
    print("needs `requests` and `pyyaml`", file=sys.stderr)
    raise

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "tests" / "routing" / "resolver_corpus.yaml"
AMBIGUOUS = "AMBIGUOUS"


# ---------------------------------------------------------------------------
# One probe
# ---------------------------------------------------------------------------
def probe(base: str, row: dict, meta: dict, timeout: float) -> dict:
    """Resolve one phrasing and record every signal the response already carries."""
    out: dict = {"id": row["id"], "axis": row.get("axis", ""), "query": row["query"]}
    try:
        r = requests.post(
            f"{base}/resolve",
            json={
                "query": row["query"],
                "domain": meta.get("domain", "DATA_ENGINEERING"),
                "domains": [meta.get("domain", "DATA_ENGINEERING")],
            },
            timeout=timeout,
        )
        r.raise_for_status()
        d = r.json()
    except Exception as exc:  # noqa: BLE001 — a dead probe is data, not a crash
        out["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return out

    prov = d.get("provenance") or {}
    cands = d.get("candidates") or []

    out["resolved_uri"] = d.get("resolved_uri")
    out["confidence"] = d.get("confidence_score")
    # Column 2: the identifier the SAME call emitted. Absent = gate 1639 closed.
    out["instance_identifier"] = prov.get("instance_identifier") or ""
    # Column 4: was the deterministic phone-book path reached at all?
    out["instance_fired"] = bool(prov.get("instance_identifier"))
    out["instance_match"] = prov.get("instance_match") or ""
    out["instance_id"] = prov.get("instance_id") or ""
    out["instance_provider"] = prov.get("instance_provider") or ""
    # The system's own record of the override, when it happened.
    out["llm_guess"] = prov.get("llm_guess") or ""
    out["preemption_path"] = prov.get("preemption_path") or ""
    # Column 3: the full pool, winner and losers.
    out["candidates"] = [
        {"uri": c.get("uri"), "score": c.get("score")} for c in cands
    ]
    # Column 5: what a pure argmax would have picked — AND WHAT THAT WOULD HAVE COST.
    #
    # Recording the disagreement alone invites the wrong conclusion. Measured on sandbox
    # 2026-08-15, the LLM overrode recall on 21% of rows and was BETTER on 5 of 6: argmax
    # would have picked Pipeline (0 verbs) over Dataset (9) on "list the datasets in
    # publog", Column (4) over Table (9) on a literal table path, and would have grounded
    # `p_caeg` — an asset that does not exist — where the LLM correctly abstained to
    # UNKNOWN. Recall systematically over-ranks idp:Column because its definition is full
    # of concrete column-name examples, so identifier-shaped tokens lexically resemble it.
    #
    # So the interesting quantity is not "did they differ" but "would the difference have
    # cost coverage". `argmax_verbs` makes that computable offline: compare it to
    # `compatible_verbs` for the class actually chosen.
    if cands:
        top = max(cands, key=lambda c: c.get("score") or 0.0)
        out["argmax_uri"] = top.get("uri")
        out["argmax_disagrees"] = bool(
            out["argmax_uri"] and out["argmax_uri"] != out["resolved_uri"]
        )
        out["argmax_verbs"] = (
            _verbs(base, out["argmax_uri"], [meta.get("domain", "DATA_ENGINEERING")], timeout)
            if out["argmax_disagrees"] and out["argmax_uri"] else None
        )
    else:
        out["argmax_uri"] = None
        out["argmax_disagrees"] = False
        out["argmax_verbs"] = None

    # Column 6: the fallback discriminant, reproduced deterministically. The supervisor
    # computes this by re-asking UNSCOPED when the scoped walk is empty — no verbs at all
    # is a relevance miss; verbs that entitlements excluded is a scope exclusion, and the
    # two route to different repairs (dynamic_supervisor.py:648-661).
    out["fallback_reason"] = ""
    uri = out.get("resolved_uri")
    if uri and uri != "UNKNOWN":
        scoped = _verbs(base, uri, [meta.get("domain", "DATA_ENGINEERING")], timeout)
        if scoped == 0:
            unscoped = _verbs(base, uri, [], timeout)
            out["fallback_reason"] = (
                "domain_scope_excluded" if unscoped > 0 else "no_compatible_verbs"
            )
        out["compatible_verbs"] = scoped
    elif uri == "UNKNOWN":
        out["fallback_reason"] = "subject_unknown"
    return out


def _verbs(base: str, subject_uri: str, domains: list, timeout: float) -> int:
    try:
        r = requests.post(
            f"{base}/find_compatible_verbs",
            json={"subject_uri": subject_uri, "max_hops": 5, "entitled_domains": domains},
            timeout=timeout,
        )
        r.raise_for_status()
        return len(r.json().get("verbs") or [])
    except Exception:  # noqa: BLE001
        return -1


# ---------------------------------------------------------------------------
# The pool precondition
# ---------------------------------------------------------------------------
def stamp(base: str, meta: dict, timeout: float, note: str = "") -> dict:
    """WHAT DID THIS RUN ACTUALLY MEASURE? A result without that is unattributable.

    Learned the hard way 2026-08-15: a clean 27/27 was produced against a sandbox whose
    Engine O had not been restarted since 2026-08-10 and whose image tag is `:latest`.
    The pool gate passed — all six classes present — so the guard I built caught nothing,
    because the divergence was in the CODE, not the pool. Same failure the gate exists to
    prevent, arriving through the door the gate does not watch.

    `/health` reports `{status, jena_reachable}` and no version, so the service cannot be
    asked what it is. What CAN be captured without new plumbing is a FINGERPRINT of the
    substrate the resolver actually sees: the candidate pool it returns. Two deployments
    with the same fingerprint should behave alike; different fingerprints are the first
    explanation to reach for when their numbers disagree.

    `--stamp` lets the caller record what the fingerprint cannot know (chart version,
    image digest, "work cluster after the 08-15 redeploy"). Free text, recorded verbatim,
    never parsed — its only job is to make a result nameable six weeks from now.
    """
    fp: set = set()
    for q in ("table dataset column pipeline job", "catalog asset", "data"):
        try:
            r = requests.post(
                f"{base}/resolve",
                json={"query": q, "domain": meta.get("domain"),
                      "domains": [meta.get("domain")]},
                timeout=timeout,
            )
            r.raise_for_status()
            fp |= {c.get("uri") for c in (r.json().get("candidates") or [])}
        except Exception:  # noqa: BLE001
            continue
    health = {}
    try:
        health = requests.get(f"{base}/health", timeout=10).json()
    except Exception:  # noqa: BLE001
        pass

    # THIRD AXIS — CATALOG CONTENTS. The pool gate checks which CLASSES exist; this checks
    # whether the THINGS the corpus asks about exist. Every grounding number taken before
    # 2026-08-15 was measured against a catalog with no p_cage in it, so those runs
    # described a system that could not have grounded regardless of phrasing — and neither
    # the pool fingerprint nor the image digest could have revealed it.
    #
    # `instance_id` in provenance is the strong signal: it means a registered
    # mesh:resolveInstance provider actually RESOLVED the token, not merely that the LLM
    # extracted it. Those are different facts and only the first says the catalog has it.
    instances = {}
    for ident in (meta.get("requires_instances") or []):
        try:
            r = requests.post(
                f"{base}/resolve",
                json={"query": ident, "domain": meta.get("domain"),
                      "domains": [meta.get("domain")]},
                timeout=timeout,
            )
            r.raise_for_status()
            prov = r.json().get("provenance") or {}
            instances[ident] = {
                "resolved": bool(prov.get("instance_id")),
                "instance_id": (prov.get("instance_id") or "")[:90],
                "match": prov.get("instance_match") or "",
            }
        except Exception as exc:  # noqa: BLE001
            instances[ident] = {"resolved": False, "error": type(exc).__name__}

    return {
        "_kind": "stamp",
        "base_url": base,
        "note": note,
        "health": health,
        "pool_fingerprint": sorted(u for u in fp if u),
        "pool_size": len(fp),
        "catalog_instances": instances,
        "catalog_resolved": sum(1 for v in instances.values() if v.get("resolved")),
        "catalog_total": len(instances),
    }


def check_pool(base: str, meta: dict, timeout: float) -> tuple[bool, list]:
    """REFUSE TO SCORE A RUN AGAINST THE WRONG CANDIDATE POOL.

    The corpus reasons about classes that were HAND-DELETED from sandbox's Weaviate on
    2026-06-11 and are present at work. Against a pool missing them, every row resolves
    to the surviving class unopposed, the trailing-noun effect cannot appear because the
    noun's target is not a candidate, and the run reports a healthy picker while
    measuring a different system. That number would be confidently wrong, which is worse
    than no number — so this is a hard gate, not a warning.
    """
    required = list(meta.get("requires_pool") or [])
    if not required:
        return True, []
    seen: set = set()
    # A broad query surfaces the pool without assuming any single phrasing reaches it.
    for q in ("table dataset column pipeline job", "catalog asset", "data"):
        try:
            r = requests.post(
                f"{base}/resolve",
                json={"query": q, "domain": meta.get("domain"), "domains": [meta.get("domain")]},
                timeout=timeout,
            )
            r.raise_for_status()
            seen |= {c.get("uri") for c in (r.json().get("candidates") or [])}
        except Exception:  # noqa: BLE001
            continue
    missing = [u for u in required if u not in seen]
    return (not missing), missing


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score(rows: list, corpus_rows: list) -> dict:
    """Rates per axis. AMBIGUOUS never counts as failure — see the corpus header."""
    spec = {r["id"]: r for r in corpus_rows}
    by_axis = defaultdict(lambda: {"n": 0, "fired": 0, "expected_fire": 0,
                                   "fired_when_expected": 0, "ambiguous": 0, "errors": 0})
    for rec in rows:
        if rec.get("_kind") == "stamp":
            continue
        s = spec.get(rec["id"], {})
        a = by_axis[rec.get("axis") or "?"]
        a["n"] += 1
        if rec.get("error"):
            a["errors"] += 1
            continue
        if rec.get("instance_fired"):
            a["fired"] += 1
        exp = s.get("expect_instance")
        if exp is True:
            a["expected_fire"] += 1
            if rec.get("instance_fired"):
                a["fired_when_expected"] += 1
        elif exp == AMBIGUOUS:
            a["ambiguous"] += 1
    return dict(by_axis)


def report(rows: list, corpus_rows: list) -> None:
    axes = score(rows, corpus_rows)
    print("\n=== grounding rate by axis (primary measure) ===")
    for axis, a in sorted(axes.items()):
        rate = (f"{a['fired_when_expected']}/{a['expected_fire']}"
                if a["expected_fire"] else "n/a")
        print(f"  {axis:26s} n={a['n']:4d}  grounded-when-expected={rate:>9s}"
              f"  ambiguous={a['ambiguous']:3d}  errors={a['errors']:3d}")

    # Per-phrasing stability: the nondeterminism question, answered directly.
    print("\n=== per-phrasing stability (repeat runs) ===")
    # AN ERRORED PROBE IS NOT AN UNGROUNDED ONE. Counting a ReadTimeout as "did not
    # ground" manufactures instability out of infrastructure noise. The first sandbox
    # run reported SIX unstable phrasings that were six consecutive timeouts in a single
    # pass — the headline would have read "nondeterminism confirmed" off a transient
    # stall, which is exactly the confidently-wrong number this corpus exists to prevent,
    # produced by the corpus itself. Errors are excluded here and reported separately: a
    # run with errors is a DEGRADED MEASUREMENT, not a measurement of degradation.
    per = defaultdict(list)
    errs = 0
    total = 0
    for r in rows:
        if r.get("_kind") == "stamp":
            continue
        total += 1
        if r.get("error"):
            errs += 1
            continue
        per[r["id"]].append(bool(r.get("instance_fired")))
    unstable = {k: v for k, v in per.items() if len(set(v)) > 1}
    for k, v in sorted(per.items()):
        if len(v) < 2:
            continue
        mark = "  UNSTABLE" if k in unstable else ""
        print(f"  {k:22s} grounded {sum(v)}/{len(v)}{mark}")
    print(f"\n  phrasings with mixed outcomes: {len(unstable)}"
          "   <- >0 means genuine nondeterminism; 0 means every failure is deterministic")
    print(f"  errored probes EXCLUDED from the above: {errs}/{total}"
          + ("   <- DEGRADED RUN: re-run before trusting these numbers"
             if total and errs / total > 0.05 else ""))

    print("\n=== argmax counterfactual ===")
    rows = [r for r in rows if r.get("_kind") != "stamp"]
    dis = [r for r in rows if r.get("argmax_disagrees")]
    both = [r for r in dis if not r.get("instance_fired")]
    # WOULD THE DIFFERENCE HAVE COST ANYTHING? A bare disagreement count reads as "the LLM
    # is unreliable"; the coverage delta is what says whether that is true. On sandbox
    # 2026-08-15 it was not: argmax would have lost coverage on 3 of 6 (Pipeline 0 verbs
    # over Dataset 9; Column 4 over Table 9 on a literal table path) and GROUNDED two rows
    # the resolver correctly abstained on, including an asset that does not exist.
    priced = [r for r in dis if r.get("argmax_verbs") is not None]
    worse = sum(1 for r in priced
                if (r.get("compatible_verbs") or 0) > (r.get("argmax_verbs") or 0))
    tie = sum(1 for r in priced
              if (r.get("compatible_verbs") or 0) == (r.get("argmax_verbs") or 0))
    abstained = sum(1 for r in dis if str(r.get("resolved_uri")) == "UNKNOWN")
    print(f"  argmax would differ on {len(dis)}/{len(rows)} runs")
    if priced:
        print(f"  of the priced ones, argmax LOSES coverage on {worse}, ties on {tie}")
    if abstained:
        print(f"  and would have GROUNDED {abstained} row(s) the resolver abstained on "
              "— a false positive, not a gain")
    print(f"  of those, {len(both)} ALSO failed to ground — argmax alone would not have "
          "fixed them")

    fb = Counter(r.get("fallback_reason") for r in rows if r.get("fallback_reason"))
    if fb:
        print("\n=== fallback_reason ===")
        for k, v in fb.most_common():
            print(f"  {k:24s} {v}")


def diff(a_path: str, b_path: str) -> int:
    """Two clusters, same corpus — does sandbox still resemble work?

    A standing capability rather than a one-off: the runner takes a base URL, so two runs
    and a diff is its natural shape. Divergence here is the fidelity number this project
    has only ever estimated by hand.
    """
    def load(p):
        out = defaultdict(list)
        for line in pathlib.Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("_kind") == "stamp":
                    out.setdefault("_stamp", []).append(r)
                    continue
                out[r["id"]].append(r)
        return out

    A, B = load(a_path), load(b_path)
    ids = sorted(set(A) | set(B))
    print(f"\n=== {a_path}  vs  {b_path} ===")
    diverged = 0
    for i in ids:
        ar, br = A.get(i), B.get(i)
        if not ar or not br:
            print(f"  {i:22s} MISSING from {'A' if not ar else 'B'}")
            diverged += 1
            continue
        a_fire = sum(bool(r.get("instance_fired")) for r in ar) / len(ar)
        b_fire = sum(bool(r.get("instance_fired")) for r in br) / len(br)
        a_cls = Counter(r.get("resolved_uri") for r in ar).most_common(1)[0][0]
        b_cls = Counter(r.get("resolved_uri") for r in br).most_common(1)[0][0]
        if a_cls != b_cls or abs(a_fire - b_fire) > 0.3:
            diverged += 1
            print(f"  {i:22s} class {str(a_cls).split('#')[-1]:12s} -> "
                  f"{str(b_cls).split('#')[-1]:12s}   ground {a_fire:.0%} -> {b_fire:.0%}")
    print(f"\n  {diverged}/{len(ids)} phrasings diverge between the two deployments")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", help="Engine O base url, e.g. http://localhost:8000")
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--repeat", type=int, default=1, help="runs per phrasing")
    ap.add_argument("--out", help="write jsonl here")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--stamp", help="free text naming WHAT this run measured — chart version, image digest, 'work after the 08-15 redeploy'. Recorded verbatim so a result is attributable later.")
    ap.add_argument("--require-pool", action="store_true", default=True)
    ap.add_argument("--no-require-pool", dest="require_pool", action="store_false",
                    help="score anyway against a mismatched pool (you are measuring a "
                         "DIFFERENT system; the number will not mean what it says)")
    ap.add_argument("--diff", nargs=2, metavar=("A.jsonl", "B.jsonl"))
    args = ap.parse_args()

    if args.diff:
        return diff(*args.diff)
    if not args.base_url:
        ap.error("--base-url is required unless --diff")

    doc = yaml.safe_load(pathlib.Path(args.corpus).read_text(encoding="utf-8"))
    meta, corpus_rows = doc.get("meta", {}), doc["rows"]

    if args.require_pool:
        ok, missing = check_pool(args.base_url, meta, args.timeout)
        if not ok:
            print("REFUSING TO RUN — the candidate pool is missing classes this corpus "
                  "reasons about:", file=sys.stderr)
            for m in missing:
                print(f"  {m}", file=sys.stderr)
            print("\nAgainst this pool every row resolves unopposed and the run would "
                  "certify a picker it never exercised. See the corpus header and "
                  "tests/routing/STEP0_IDP_BUILD_SPEC.md:172. Restore the pool through "
                  "the reproducible path, or pass --no-require-pool knowing the number "
                  "describes a different system.", file=sys.stderr)
            return 2

    run_stamp = stamp(args.base_url, meta, args.timeout, args.stamp or "")
    print(f"stamp: pool={run_stamp['pool_size']} classes  "
          f"catalog={run_stamp.get('catalog_resolved')}/{run_stamp.get('catalog_total')} "
          f"instances resolved  health={run_stamp['health']}"
          + (f"\n       note={run_stamp['note']!r}" if run_stamp["note"] else ""))
    if run_stamp.get("catalog_total") and not run_stamp.get("catalog_resolved"):
        print("  CATALOG EMPTY for every probed instance — grounding numbers from this run "
              "describe a system that CANNOT ground, whatever the phrasing. Treat any "
              "grounding rate below as void.", file=sys.stderr)
    if not run_stamp["note"]:
        print("  (no --stamp given: this result will not be attributable to a "
              "deployment later — pass one)", file=sys.stderr)

    results = [run_stamp]
    for i in range(args.repeat):
        for row in corpus_rows:
            rec = probe(args.base_url, row, meta, args.timeout)
            rec["run"] = i
            results.append(rec)
            flag = "." if rec.get("instance_fired") else ("!" if rec.get("error") else "o")
            print(flag, end="", flush=True)
    print()

    if args.out:
        pathlib.Path(args.out).write_text(
            "\n".join(json.dumps(r) for r in results) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.out} ({len(results)} rows)")
    report(results, corpus_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
