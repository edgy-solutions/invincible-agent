"""Run an elicitation corpus END TO END and report BY TRIGGER SHAPE AND BY PATH.

THIS FILE CONTAINS NO PHRASINGS. The corpus is authored separately, the same rule the
slot battery follows — a runner that carries its own cases is a runner that can be tuned
until it passes.

WHAT THIS MEASURES, AND HOW IT DIFFERS FROM THE SLOT BATTERY. That one asserts on
`/fill_slots` output: did the filler read the phrasing. This one runs the whole turn —

    phrase -> /fill_slots -> accept_slots -> decide_disposition
           -> ask_card -> [the corpus's scripted answer] -> resolve_ask
           -> BIND: accept_slots(merged) -> POST the verb, assert it ANSWERS
           -> RESPEAK: re-issue the phrase with the answer, assert what it now FILLS

— because the thing under test is the disposition, and a disposition that produces a
beautiful card nobody can answer has not been measured by asserting on the card.

REPORTED BY SHAPE AND BY PATH, NEVER BLENDED. A missed ask (the system stayed silent when
it could not proceed) and a spurious ask (it interrupted when it knew) are different
failures with different fixes, and one percentage hides which one moved. BIND and RESPEAK
are different mechanisms and are counted apart for the same reason.

Usage:
    python scripts/elicitation_battery.py --corpus docs/measurements/elicitation_corpus_v1.json \\
        [--engine-o http://localhost:8084] [--engine-p http://localhost:8095] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests

sys.path.insert(0, "src")

from iagent_pure.slot_acceptance import accept_slots                      # noqa: E402
from iagent_pure.slot_disposition import (                                # noqa: E402
    BIND,
    RESPEAK,
    PickRefused,
    ask_card,
    decide_disposition,
    resolve_ask,
)

IDP = "http://invincible-agent/idp#"


def _fill(engine_o: str, query: str, verb_iri: str, declarations: list[dict], timeout: float) -> dict:
    r = requests.post(
        f"{engine_o}/fill_slots",
        json={"query": query, "verb_iri": verb_iri, "declarations": json.dumps(declarations)},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json() or {}


def _enumerator(engine_p: str, timeout: float):
    """`class_uri -> {outcome, members, count}` against the LIVE provider.

    Deliberately live rather than stubbed: the bound is a server-side env var, so a stub
    would measure the bound this runner believes in rather than the one deployed — and the
    two currently differ (deployed 8, ruled 10). The run must meet what is deployed.
    """
    def _e(class_uri: str) -> dict:
        r = requests.post(f"{engine_p}/enumerate_instances",
                          json={"class_uri": class_uri}, timeout=timeout)
        r.raise_for_status()
        return r.json() or {}
    return _e


def _measure(engine_p: str, fn: str, params: dict, timeout: float) -> tuple[int, Any]:
    r = requests.post(f"{engine_p}/measure/{fn}",
                      json={"state_ref": "baseline", "params": params}, timeout=timeout)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text[:200]


def run_case(case: dict, *, decls: list[dict], engine_o: str, engine_p: str, timeout: float) -> dict:
    """One case, end to end. Returns a record; never raises on a case's own failure."""
    out: dict[str, Any] = {"id": case["id"], "family": case.get("family", ""),
                           "phrasing": case["phrasing"]}
    filled = _fill(engine_o, case["phrasing"], case["verb"], decls, timeout)
    accepted = accept_slots(filled.get("slots") or {}, decls)
    disp = decide_disposition(
        accepted=accepted.params, declared=decls,
        resolution=filled.get("resolution") or {},
        enumerate_class=_enumerator(engine_p, timeout),
    )
    out["disposition"] = disp.action
    out["slot"] = disp.slot or ""
    out["reason"] = disp.reason
    out["option_source"] = disp.option_source
    out["free_text_reason"] = disp.free_text_reason
    out["options"] = [o.value for o in disp.options]
    out["filled"] = accepted.params
    out["message"] = ""

    if disp.action != "ask" or "answer" not in case:
        return out

    card = ask_card(disp, verb_iri=case["verb"], sub_query=case["phrasing"],
                    accepted=accepted.params)
    out["message"] = card["message"]
    try:
        rr = resolve_ask(card, case["answer"])
    except PickRefused as exc:
        out["path"] = "refused"
        out["refusal"] = str(exc)
        return out

    out["path"] = rr.action
    if rr.action == BIND:
        # THE PICK MUST SURVIVE THE DECLARATION GUARD IT WILL ACTUALLY MEET. `config.slots`
        # outranks the filler, so these are the params that reach the verb.
        acc2 = accept_slots(rr.slots, decls)
        out["bound_slots"] = acc2.params
        out["bound_refusals"] = [str(r) for r in acc2.refusals]
        status, body = _measure(engine_p, case["measure"], acc2.params, timeout)
        out["verb_status"] = status
        out["verb_answers"] = status == 200
        out["verb_rows"] = len(body) if isinstance(body, list) else None
    elif rr.action == RESPEAK:
        # The answer re-enters as WORDS. Everything downstream is the ordinary path.
        out["reissued_query"] = rr.query
        re_filled = _fill(engine_o, rr.query, case["verb"], decls, timeout)
        re_accepted = accept_slots(re_filled.get("slots") or {}, decls)
        out["reissued_fills"] = re_accepted.params
        res = (re_filled.get("resolution") or {}).get(disp.slot or "") or {}
        out["reissued_outcome"] = res.get("outcome", "")
    return out


def grade(case: dict, rec: dict) -> tuple[str, list[str]]:
    """PASS/FAIL plus the specific mismatches. Disposition first, answer second."""
    why: list[str] = []
    exp = case.get("expect") or {}
    if exp.get("disposition") and rec.get("disposition") != exp["disposition"]:
        why.append(f"disposition {rec.get('disposition')!r} != {exp['disposition']!r}")
    if exp.get("slot") and rec.get("slot") != exp["slot"]:
        why.append(f"slot {rec.get('slot')!r} != {exp['slot']!r}")
    if exp.get("option_source") and rec.get("option_source") != exp["option_source"]:
        why.append(f"option_source {rec.get('option_source')!r} != {exp['option_source']!r}")
    if exp.get("free_text_reason") and rec.get("free_text_reason") != exp["free_text_reason"]:
        why.append(f"free_text_reason {rec.get('free_text_reason')!r} != {exp['free_text_reason']!r}")
    for v in exp.get("options_contain") or []:
        if v not in (rec.get("options") or []):
            why.append(f"option {v!r} not offered")

    ea = case.get("expect_after_answer") or {}
    if ea:
        if ea.get("path") and rec.get("path") != ea["path"]:
            why.append(f"path {rec.get('path')!r} != {ea['path']!r}")
        if "slots" in ea and rec.get("bound_slots") != ea["slots"]:
            why.append(f"bound_slots {rec.get('bound_slots')!r} != {ea['slots']!r}")
        if ea.get("verb_answers") and not rec.get("verb_answers"):
            why.append(f"verb did not answer (status {rec.get('verb_status')})")
        if "reissued_fills" in ea and rec.get("reissued_fills") != ea["reissued_fills"]:
            why.append(f"reissued_fills {rec.get('reissued_fills')!r} != {ea['reissued_fills']!r}")
        if ea.get("reissued_outcome") and rec.get("reissued_outcome") != ea["reissued_outcome"]:
            why.append(f"reissued_outcome {rec.get('reissued_outcome')!r} != {ea['reissued_outcome']!r}")
    return ("PASS" if not why else "FAIL"), why


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--engine-o", default="http://localhost:8084")
    ap.add_argument("--engine-p", default="http://localhost:8095")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    doc = json.loads(open(args.corpus, encoding="utf-8").read())
    cases = doc["cases"]

    from agent_fleet.planning_agent.slots import slots_for

    records, grades = [], {}
    for c in cases:
        decls = slots_for(c["measure"])
        try:
            rec = run_case(c, decls=decls, engine_o=args.engine_o,
                           engine_p=args.engine_p, timeout=args.timeout)
        except Exception as exc:  # noqa: BLE001 — a transport failure is a RESULT, not a crash
            rec = {"id": c["id"], "family": c.get("family", ""), "error": f"{type(exc).__name__}: {exc}"}
        verdict, why = ("ERROR", [rec["error"]]) if "error" in rec else grade(c, rec)
        rec["verdict"], rec["why"] = verdict, why
        records.append(rec)
        grades[c["id"]] = verdict

    # ── report ───────────────────────────────────────────────────────────────────────
    print("\nELICITATION BATTERY — end to end")
    print("=" * 78)
    for r in records:
        mark = {"PASS": "  ok  ", "FAIL": " FAIL ", "ERROR": " ERR  "}[r["verdict"]]
        print(f"{mark}{r['id']:5s} {r.get('family',''):18s} "
              f"{r.get('disposition','-'):8s} {r.get('path','-'):8s} {r.get('slot','')}")
        for w in r["why"]:
            print(f"        -> {w}")

    print("\nBY TRIGGER SHAPE — never blended, because a missed ask and a spurious ask")
    print("are different failures with different fixes")
    print("=" * 78)
    fams: dict[str, list[str]] = {}
    for c in cases:
        fams.setdefault(c.get("family", "?"), []).append(grades[c["id"]])
    for fam, vs in sorted(fams.items()):
        ok = sum(1 for v in vs if v == "PASS")
        print(f"  {fam:20s} {ok}/{len(vs)}")

    print("\nBY PATH — BIND and RESPEAK are different mechanisms")
    print("=" * 78)
    paths: dict[str, list[str]] = {}
    for r in records:
        paths.setdefault(r.get("path") or "(no answer scripted)", []).append(r["verdict"])
    for path, vs in sorted(paths.items()):
        ok = sum(1 for v in vs if v == "PASS")
        print(f"  {path:22s} {ok}/{len(vs)}")

    total = len(records)
    passed = sum(1 for r in records if r["verdict"] == "PASS")
    print("\n" + "=" * 78)
    print(f"  {passed}/{total} pass")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
