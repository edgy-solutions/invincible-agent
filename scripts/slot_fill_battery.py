#!/usr/bin/env python
"""Run a phrasing corpus through the live slot-filler and report accuracy BY OUTCOME CLASS.

THIS FILE CONTAINS NO PHRASINGS. The corpus is authored and fairness-reviewed by a human and
supplied as a JSON file; an agent that wrote both the questions and the system under test
would be grading its own homework. What lives here is the vehicle: the runner, the outcome
classifier, and the reporting.

WHY THE CLASSES ARE NEVER BLENDED INTO ONE PERCENTAGE. The two failure modes are
asymmetric and a single number hides the asymmetry:

  * a MISSED fill is recoverable — the default applies, or the elicitation `ask` catches it,
    and the interpretation strip can disclose what was used;
  * a WRONG fill is the silent-wrong-answer mode returning — the filler confidently supplying
    `initiative` when the speaker said something else, rendering cleanly, with clean
    provenance, and with no surface on which a reader could notice.

They are reported separately, always.

CONFIDENCE IS SLICED BY OUTCOME CLASS, and that slice is the point of collecting it. The
threshold that makes `ask` fire on the model's own uncertainty needs a measured distribution
behind it, not an invented decimal. If confidence separates correct from missed/wrong, the
threshold writes itself. **If it does NOT separate them, that is the more important finding**
— it means confidence is not actionable and the disposition needs a different signal.

CORPUS FORMAT (a JSON list):

    [
      {
        "phrasing":  "where is funding short by initiative",
        "verb":      "mesh:planFundingGap",
        "measure":   "plan_funding_gap",
        "expect":    {"group_by": "initiative"},
        "note":      "optional; why this case is fair"
      }
    ]

`expect: {}` means the phrasing names no parameter and the honest answer is to fill nothing —
these cases are the ones that catch invention, and a corpus without them measures only
eagerness. `expect_refused: ["name"]` asserts the endpoint REFUSED a named slot (the
verb-does-not-take-it and near-miss-vocabulary cases).

USAGE (from a pod with reach to Engine O):

    python slot_fill_battery.py --corpus corpus.json [--url http://iagent-engine-o:8084]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.request

# Outcome classes. Ordered worst-first: a case exhibiting several gets the worst one, because
# a case that both invents a value and misses another is a WRONG fill, not a mixed result.
WRONG = "wrong"
MISSED = "missed"
EXTRA = "extra"
CORRECT = "correct"
ERROR = "error"
_SEVERITY = [ERROR, WRONG, EXTRA, MISSED, CORRECT]


def classify(expected: dict, got: dict) -> tuple[str, list[str]]:
    """Compare a filler's output against what the phrasing supports.

    Returns (worst class, per-slot detail). The classes:

      CORRECT  every expected slot present with the expected value, and nothing else;
      MISSED   an expected slot is absent — recoverable, `ask` catches it;
      WRONG    an expected slot is present with a DIFFERENT value — the silent-wrong-answer
               mode, the one that matters;
      EXTRA    a slot the phrasing does not support was filled. Distinct from WRONG because
               the speaker named nothing for it: this is INVENTION, and on a verb whose
               default differs it produces a confidently wrong scope. Ranked above MISSED and
               below WRONG.

    A value that differs only by container (`"FY26-Q4"` vs `["FY26-Q4"]`) is WRONG, not
    correct-with-a-quibble: the engine iterates the string and answers `422 unknown fiscal
    period(s): F, Y, 2, 6, -, Q, 4`. That equivalence is exactly the one this project has
    paid for three times.
    """
    detail: list[str] = []
    classes: list[str] = []

    for name, want in expected.items():
        if name not in got:
            classes.append(MISSED)
            detail.append(f"MISSED {name} (wanted {want!r})")
        elif got[name] != want:
            classes.append(WRONG)
            detail.append(f"WRONG  {name}={got[name]!r} (wanted {want!r})")

    for name, value in got.items():
        if name not in expected:
            classes.append(EXTRA)
            detail.append(f"EXTRA  {name}={value!r} (the phrasing supports no value for it)")

    if not classes:
        return CORRECT, detail
    return min(classes, key=_SEVERITY.index), detail


def _call(url: str, phrasing: str, verb: str, declarations: str, timeout: float):
    body = json.dumps({"query": phrasing, "verb_iri": verb,
                       "declarations": declarations}).encode()
    req = urllib.request.Request(f"{url}/fill_slots", data=body,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def _dist(values: list[float]) -> str:
    if not values:
        return "n=0"
    vs = sorted(values)
    return (f"n={len(vs)}  min={vs[0]:.2f}  median={statistics.median(vs):.2f}  "
            f"max={vs[-1]:.2f}  mean={statistics.fmean(vs):.2f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--url", default="http://iagent-engine-o:8084")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--json", default="", help="write per-case results here")
    ap.add_argument("--declarations", default="",
                    help="JSON map measure->declarations. Omit to derive from the local "
                         "planning package (only possible where it is importable).")
    args = ap.parse_args()

    doc = json.loads(open(args.corpus, encoding="utf-8").read())
    # A corpus may arrive bare or in an envelope carrying its own grading contract and flag
    # meanings. The envelope is preferred: it makes the author's rulings travel WITH the
    # cases, so a report cannot be read against a different set of rules than it was graded by.
    cases = doc["cases"] if isinstance(doc, dict) else doc
    meta = doc if isinstance(doc, dict) else {}

    if args.declarations:
        decls = json.loads(open(args.declarations, encoding="utf-8").read())
    else:
        from agent_fleet.planning_agent.slots import slots_for
        decls = {c["measure"]: slots_for(c["measure"]) for c in cases}

    by_class: dict[str, list[dict]] = {}
    by_flag: dict[str, list[tuple]] = {}
    conf: dict[str, list[float]] = {}

    for c in cases:
        declarations = json.dumps(decls[c["measure"]])
        try:
            r = _call(args.url, c["phrasing"], c["verb"], declarations, args.timeout)
        except Exception as exc:  # noqa: BLE001
            by_class.setdefault(ERROR, []).append({**c, "detail": [str(exc)[:120]],
                                                   "resolution": {}, "refused": []})
            continue

        got = r.get("slots") or {}
        cls, detail = classify(c.get("expect") or {}, got)

        want_refused = c.get("expect_refused") or []
        if want_refused:
            refused_blob = " ".join(r.get("refused") or [])
            for name in want_refused:
                if name not in refused_blob:
                    cls = WRONG
                    detail.append(f"NOT REFUSED {name} (expected the endpoint to reject it)")

        by_class.setdefault(cls, []).append({
            **c, "got": got, "detail": detail, "confidence": r.get("confidence"),
            "refused": r.get("refused") or [],
            # THE TRI-STATE, recorded per case. Without it H06 and E05 are BOTH `got: {}`
            # and indistinguishable in the run file — one a slot the phrase never named
            # (elicitation, no menu), the other a name that resolved to the wrong class
            # (disambiguation, menu available). An acceptance assertion on WHICH ASK SHAPE
            # is vacuous against a file that cannot tell them apart, and a vacuous
            # acceptance passes.
            "resolution": r.get("resolution") or {},
        })
        for flag in c.get("flags") or []:
            by_flag.setdefault(flag, []).append((cls, c.get("id"), c["phrasing"]))
        if r.get("confidence") is not None:
            conf.setdefault(cls, []).append(float(r["confidence"]))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump([{"id": r.get("id"), "cls": cl, "conf": r.get("confidence"),
                        "expect": r.get("expect"), "got": r.get("got"),
                        "flags": r.get("flags"), "phrasing": r.get("phrasing"),
                        # outcome / instance_id / candidates, per slot — the fields an
                        # acceptance test needs to distinguish an ask WITH a menu from an
                        # ask WITHOUT one. `got: {}` says nothing about which.
                        "resolution": r.get("resolution") or {},
                        "refused": r.get("refused") or []}
                       for cl, rows in by_class.items() for r in rows], fh, indent=1)

    # CORRECT MIXES TWO POPULATIONS and reporting it as one hides the shape. A case that
    # correctly fills a slot and a case that correctly fills NOTHING are both correct, but
    # the second has no value to be confident about — its honest confidence is near zero.
    # Blending them makes the CORRECT distribution bimodal and makes the separation question
    # unanswerable, which is exactly what the first run showed (min=0.00, median=0.97).
    filled_ok = [r["confidence"] for r in by_class.get(CORRECT, [])
                 if r.get("expect") and r.get("confidence") is not None]
    empty_ok = [r["confidence"] for r in by_class.get(CORRECT, [])
                if not r.get("expect") and r.get("confidence") is not None]

    total = sum(len(v) for v in by_class.values())
    print()
    print("SLOT-FILL BATTERY".ljust(70, " "))
    print("=" * 70)
    if meta.get("corpus_version"):
        print(f"  corpus {meta['corpus_version']} by {meta.get('authored_by', '?')}")
        print(f"  against: {meta.get('authored_against', '')[:70]}")
        print("-" * 70)
    for cls in _SEVERITY:
        n = len(by_class.get(cls, []))
        if n:
            print(f"  {cls.upper():8s} {n:4d}  ({n / total:5.1%})")
    print("-" * 70)
    print("  REPORTED SEPARATELY BY DESIGN: a missed fill is recoverable (ask catches it);")
    print("  a wrong or invented fill is the silent-wrong-answer mode. One blended")
    print("  percentage would hide the asymmetry that matters.")

    print()
    print("CONFIDENCE BY OUTCOME CLASS")
    print("=" * 70)
    for cls in _SEVERITY:
        if cls in conf:
            print(f"  {cls.upper():8s} {_dist(conf[cls])}")
    print(f"    of which CORRECT-FILLED  {_dist(filled_ok)}")
    print(f"    of which CORRECT-EMPTY   {_dist(empty_ok)}")
    print("    (a case that correctly fills NOTHING has no value to be confident about;")
    print("     blending the two makes CORRECT bimodal and the question unanswerable)")
    good = filled_ok
    bad = [v for cls in (WRONG, EXTRA, MISSED) for v in conf.get(cls, [])]
    print("-" * 70)
    if good and bad:
        sep = min(good) - max(bad)
        if sep > 0:
            print(f"  SEPARATES: every correct fill scored above every failure "
                  f"(gap {sep:.2f}). A threshold in that gap makes `ask` fire on the "
                  f"model's own uncertainty.")
        else:
            print(f"  DOES NOT SEPARATE: correct fills go as low as {min(good):.2f} while "
                  f"failures reach {max(bad):.2f}. Confidence is NOT actionable as a "
                  f"threshold — the disposition needs a different signal. This is the more "
                  f"important finding of the two.")
    else:
        print("  too few cases in one class to say whether confidence separates them")

    if by_flag:
        print()
        print("BY FLAG — the author's slices, so a platform gap is not read as comprehension")
        print("=" * 70)
        for flag, rows in sorted(by_flag.items()):
            counts: dict[str, int] = {}
            for cl, _, _ in rows:
                counts[cl] = counts.get(cl, 0) + 1
            summary = "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))
            print(f"  {flag:22s} n={len(rows):3d}   {summary}")
            expected = (meta.get("flag_meanings") or {}).get(flag, "")
            if expected:
                print(f"    {expected[:100]}")

    print()
    for cls in (ERROR, WRONG, EXTRA, MISSED):
        for row in by_class.get(cls, []):
            flags = f" {row.get('flags')}" if row.get("flags") else ""
            print(f"  [{cls}] {row.get('id', '')} {row['phrasing']}{flags}")
            for d in row["detail"]:
                print(f"           {d}")
    return 1 if by_class.get(WRONG) or by_class.get(ERROR) else 0


if __name__ == "__main__":
    sys.exit(main())
