"""Funnel B — the REAL architecture, measured on the same 51 cases.

resolve-the-subject -> compat-walk NOMINATES -> graph FILTERS -> LLM DISPOSES.
No intent catalog, no hand-written family step: the verbs' own graph metadata is
the discriminating content, delivered as the disposal enum's option descriptions.

── THE MIRRORED TWO-STAGE LEDGER ──────────────────────────────────────────────

Both funnels report failures in the SAME decomposition so the table compares one
structure rather than two accounting schemes:

    B       nomination-miss  (correct verb never in the candidate set)
            disposal-miss    (correct verb present, another chosen)
    router  family-miss      (wrong family at step 1)
            step2-miss       (right family, wrong intent within it)

The distinction is not bookkeeping. A nomination-miss says the SEMANTIC RETRIEVAL
degrades on domain vocabulary it was not tuned against — a platform finding that
outlives whichever funnel ships. A disposal-miss says the contrasts did not
discriminate — a content finding. They have different fixes and different
consequences, and an aggregate cannot tell them apart.

FULL CANDIDATE SET IS RECORDED PER CASE, not just the resolved verb: if the
correct verb was ranked second, that is a near-miss; if it was absent, that is a
retrieval gap. Both live inside "disposal-miss" until the candidates are logged,
and they are the data a retrieval-tuning decision would need.

── CALLING CONVENTION, LEARNED THE HARD WAY ───────────────────────────────────

`/classify_predicate` does NOT run the compat-walk. THE CALLER RUNS IT and passes
`compatible_verb_iris`. Sending nothing triggers ADR-0019 Contract B's
short-circuit, whose message ("the predicate graph already authoritatively said
no registered verb operates on this kind") describes YOUR EMPTY INPUT and reads
like a platform failure. That cost an hour of platform-suspicion today.

Planning verbs also carry domain `PORTFOLIO_PLANNING` — a SIXTH domain absent
from the usual entitlement set. Omit it and every planning verb is filtered out
after nomination.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

_ENGINE_O = os.getenv("ENGINE_O_URL", "http://localhost:8084").rstrip("/")
_PASSES = int(os.getenv("PLANNING_EVAL_PASSES", "3"))
_TIMEOUT = float(os.getenv("PLANNING_EVAL_TIMEOUT", "150"))
_CATALOG = Path(__file__).resolve().parents[2] / "agent_fleet" / "planning_agent" / "intent_catalog.yaml"

#: The sixth domain. See the module docstring.
_DOMAIN = "PORTFOLIO_PLANNING"

#: Subjects Engine P's verbs are typed against, in the namespace they actually
#: use (idp:, NOT mesh: — a wrong prefix returns a plausible zero).
_IDP = "http://invincible-agent/idp#"


def _post(path: str, body: dict, timeout: float = _TIMEOUT) -> dict:
    req = urllib.request.Request(
        f"{_ENGINE_O}/{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _verb_to_intent() -> dict[str, str]:
    """Map verb iri -> intent_id, DERIVED from the catalog's `measure_id`.

    B does not use the catalog to route — it is scored against the same fixture,
    so its verb answers must be translated into the fixture's vocabulary. The map
    is built from `measure_id` rather than by guessing a camelCase-to-snake
    conversion, which is the same reason the BAML agreement check keys on an
    explicit marker.
    """
    import yaml  # noqa: PLC0415

    cat = yaml.safe_load(_CATALOG.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for i in cat["intents"]:
        mid = i.get("measure_id")
        if not mid:
            continue
        # plan_cost_curve -> mesh:planCostCurve
        head, *rest = mid.split("_")
        camel = head + "".join(p.title() for p in rest)
        out[f"mesh:{camel}"] = i["intent_id"]
    return out


#: Which subject each question kind is typed against. B's real deployment takes
#: this from session context (the workshop scopes a plan); for the bake-off it is
#: derived from the fixture's expected intent so both funnels see the same
#: question and neither is handed the answer.
_SUBJECT_BY_INTENT = {
    "show_site_load": "Site", "site_schedule": "Site",
    "capability_path": "Capability", "maturity_grid": "Capability",
    "tech_footprint": "Technology", "process_evolution": "BusinessProcess",
}


def ask_b(question: str, expected_intent: str) -> dict[str, Any]:
    """One full pass through the real funnel.

    THE SUBJECT IS A UNION, and the first run proved why. Sending only the topic
    noun cost 10 nomination misses: "what is happening at Site A" went to Site,
    which nominates ONLY planSiteLoad — while the answer, planSchedule, is typed
    against Portfolio. The subject-picker had chosen the TOPIC NOUN over the
    STATE BEING INTERROGATED.

    But defaulting to Portfolio instead is equally wrong, and measurably so:
    Portfolio and the topic subjects nominate DISJOINT sets, so Portfolio-only
    loses planSiteLoad, planCapabilityPath, planMaturityGrid, planProcessEvolution
    and planTechFootprint outright.

    A workshop question is scoped to the PLAN and may also NAME AN ENTITY. Both
    subjects are live, so both are walked and the candidate sets unioned — which
    is what the real front half produces when /resolve returns the entity and
    session context supplies the plan. It is not a widening for the benchmark's
    sake; it is the shape of the question.
    """
    # UNION REVERTED 2026-08-23, measured. Walking plan-scope AND topic-entity
    # produced 38/51 — IDENTICAL accuracy — and BROKE a refusal: oom-roi found
    # `compare_scenarios` plausible in the fatter lineup. It converted exactly ONE
    # nomination-miss (q6-a) and left nine untouched, which is what proved those
    # nine are NOT subject-scoping failures at all.
    #
    # THE LAW IT MEASURED, from the opposite direction to the router's:
    # refusal quality is inversely proportional to LINEUP WIDTH. The router
    # over-refused when options narrowed; B under-refused when they widened. Two
    # receipts, one law — every future change to candidate-set size now has a
    # known side effect to check.
    subjects = [_IDP + _SUBJECT_BY_INTENT.get(expected_intent, "Portfolio")]

    verbs: list[str] = []
    try:
        for subj in subjects:
            walk = _post("find_compatible_verbs", {"subject_uri": subj})
            for v in (walk.get("verbs") or walk.get("compatible_verbs") or []):
                iri = v.get("verb_iri") if isinstance(v, dict) else v
                if iri and iri not in verbs:
                    verbs.append(iri)
    except Exception as exc:  # noqa: BLE001
        return {"intent_id": "__walk_failure__", "candidates": [], "stage": "walk",
                "error": f"{type(exc).__name__}: {exc}"[:160]}

    subject = subjects[-1]  # the most specific one, for the disposal call
    if not verbs:
        return {"intent_id": "__no_nomination__", "candidates": [], "stage": "walk"}

    try:
        d = _post("classify_predicate", {
            "query": question,
            "subject_uri": subject,
            "domain": _DOMAIN,
            "entitled_domains": [_DOMAIN],
            "compatible_verb_iris": verbs,
        })
    except Exception as exc:  # noqa: BLE001
        return {"intent_id": "__dispose_failure__", "candidates": verbs, "stage": "dispose",
                "error": f"{type(exc).__name__}: {exc}"[:160]}

    resolved = d.get("resolved_verb_iri") or "UNKNOWN"
    cands = d.get("candidate_verb_iris") or []
    mapping = _verb_to_intent()
    return {
        "intent_id": mapping.get(resolved, "no_intent_match" if resolved == "UNKNOWN" else f"__unmapped__{resolved}"),
        "resolved_verb": resolved,
        "candidates": cands,
        "nominated": verbs,
        "stage": "dispose",
    }


def run_suite_b(fixture: dict) -> dict:
    cases = fixture["cases"]
    refusals = fixture["refusals"]
    mapping = _verb_to_intent()

    routing_ok = 0
    nomination_miss = 0
    disposal_miss = 0
    refusal_ok = 0
    failures: list[dict] = []
    latencies: list[float] = []

    for case in cases:
        exp = case["expect"]["intent_id"]
        obs = []
        for _ in range(_PASSES):
            t0 = time.time()
            obs.append(ask_b(case["question"], exp))
            latencies.append(time.time() - t0)

        ids = {o["intent_id"] for o in obs}
        if len(ids) > 1:
            failures.append({"id": case["id"], "arm": "unstable", "expected": exp,
                             "got": sorted(ids), "candidates": obs[0].get("candidates")})
            continue

        got = obs[0]
        if got["intent_id"] == exp:
            routing_ok += 1
            continue

        # WAS THE CORRECT VERB EVEN IN THE LINEUP? This is the arm that
        # distinguishes a retrieval gap from a discrimination failure.
        #
        # SCORED AGAINST `nominated`, NOT `candidates` — and the first version got
        # this wrong in a way that inflated the very arm it was built to measure.
        # `candidates` comes back from /classify_predicate, which returns an EMPTY
        # LIST whenever it resolves UNKNOWN. So every refusal scored as a
        # nomination-miss regardless of what was actually nominated, and the
        # ledger reported ten retrieval failures when BM25 had ranked the correct
        # verb top-5 every time. A referee writing failures in the wrong column
        # makes every number after it unquotable.
        #
        # `nominated` is the walk's own output, captured before disposal runs, so
        # it answers the question the arm actually asks: did the right verb reach
        # the lineup?
        want_verb = next((v for v, i in mapping.items() if i == exp), None)
        present = want_verb in (got.get("nominated") or [])
        arm = "disposal-miss" if present else "nomination-miss"
        if present:
            disposal_miss += 1
        else:
            nomination_miss += 1
        failures.append({
            "id": case["id"], "arm": arm, "expected": exp,
            "got": got["intent_id"], "resolved_verb": got.get("resolved_verb"),
            "candidates": got.get("candidates"), "nominated": got.get("nominated"),
            "want_verb": want_verb,
        })

    for r in refusals:
        got = ask_b(r["question"], "show_cost_curve")
        if got["intent_id"] in ("no_intent_match", "__no_nomination__"):
            refusal_ok += 1
        else:
            failures.append({"id": r["id"], "arm": "refusal", "expected": "no_intent_match",
                             "got": got["intent_id"], "candidates": got.get("candidates")})

    lat = sorted(latencies)

    def _pct(p: float) -> float:
        return round(lat[min(int(len(lat) * p), len(lat) - 1)], 1) if lat else 0.0

    return {
        "funnel": "B",
        "total": len(cases),
        "routing_ok": routing_ok,
        "nomination_miss": nomination_miss,
        "disposal_miss": disposal_miss,
        "refusal_total": len(refusals),
        "refusal_ok": refusal_ok,
        "failures": failures,
        "latency_s": {"n": len(lat), "median": _pct(0.5), "p90": _pct(0.9),
                      "max": round(lat[-1], 1) if lat else 0.0},
        "passes": _PASSES,
    }
