"""SEAL 3 — two seeds of the same template under the same identity produce identical PANEL SETS.

ADR-0050 acceptance 3. Scope stated precisely, because the loose version is unpassable: identical
**(verb, declared slots, slot role, ordinal)** per panel. NOT identical artifact ids — those are
minted per run (`uuid4`) — and NOT identical rendered content, which is state-dependent by design
(ADR-0042).

**THIS SEAL MUST BE SHOWN TO FAIL AGAINST TODAY'S PHRASE-BASED SEED.** A seal that has never been
shown to bite on the thing it was written to catch is decorative, and this is the one seal
phrase-based seeding cannot pass. Recording that failure is what makes §2 a measurement rather
than a claim.

── WHY THE FAILURE IS PROVABLE WITHOUT A CLUSTER, AND WHY THAT IS NOT A DODGE ─────────────────
The live arm below drives the real endpoint and is the recorded run. But the structural half is
decidable from the source and is stronger than a single observation, because one live pass could
come back stable by luck and would then read as a passing seal.

Today's seeder (`gateway.py` PORTFOLIO_CANVAS_QUESTIONS) declares five PHRASES and a `measure`
label used for nothing but ordering. It does not declare a verb. The verb for each panel is
whatever the classifier returns for that phrase ON THAT RUN, and the seeder's own comment records
the verb MOVING — *"subject resolution SHIFTS when the ontology or verb set changes — 'where are
we over budget' moved Portfolio 0.86 -> Site 0.75 across a single prime."*

So today's seed has no panel set until after it runs, and the seal's subject is not merely
unstable — it is **not expressible**. That is the finding §2 is built on.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_GATEWAY = _ROOT / "src" / "iagent" / "gateway.py"
_TEMPLATE = _ROOT / "policy" / "canvases" / "portfolio.yaml"


def panel_set(panels: list[dict]) -> list[tuple]:
    """THE COMPARISON, and its scope is the seal's scope.

    `(ordinal, verb, role, canonicalised slots)`. Artifact ids and rendered content are
    deliberately excluded — including them would make the seal unpassable for reasons that are
    correct behaviour, and a seal nobody can pass gets deleted rather than fixed.
    """
    return [
        (i,
         p.get("verb"),
         p.get("role"),
         tuple(sorted((k, str(v)) for k, v in (p.get("slots") or {}).items())))
        for i, p in enumerate(panels)
    ]


# ── THE STRUCTURAL ARM — runs everywhere, and it is the recorded failure ────────────────────
def test_todays_phrase_seed_cannot_express_a_panel_set():
    """SEAL 3 AGAINST TODAY'S SEED: it fails, and it fails STRUCTURALLY.

    Asserted against the seeder's source rather than a run, so the result cannot be a lucky
    pass. If this test ever fails, today's seeder has started declaring verbs — at which point
    the phrase-based path has become the template path and this file should be retired.
    """
    src = _GATEWAY.read_text(encoding="utf-8")

    # The list literal, not the name's first mention — `: list[dict]` carries a `]` of its own,
    # which a naive split on "]" eats. Read from the assignment to the line that closes it.
    m = re.search(r"^PORTFOLIO_CANVAS_QUESTIONS[^=]*=\s*\[\n(.*?)^\]", src, re.S | re.M)
    if m is None:
        # The symbol is GONE, which is a different fact from the symbol having changed shape.
        # The gateway half of slice 1 replaces `seedPortfolioCanvas` with `seedCanvas`, so this
        # is the expected end state — but it must be read as "the phrase seeder was retired",
        # never as "the seal passed".
        pytest.skip(
            "PORTFOLIO_CANVAS_QUESTIONS is gone from gateway.py — the phrase-based seeder has "
            "been retired (the gateway half of slice 1). Seal 3's failure against it is a "
            "historical record now; re-read the recorded run rather than this test.")
    block = m.group(1)

    questions = re.findall(r'"question":\s*"([^"]+)"', block)
    assert len(questions) == 5, f"expected today's five seeded questions, found {len(questions)}"

    # The seeder declares PHRASES. No entry names a verb, so no (verb, slots) tuple exists until
    # the classifier has run — which is the whole of seal 3's failure.
    verbs = re.findall(r'"verb":\s*"(mesh:[A-Za-z]+)"', block)
    assert not verbs, (
        "today's seeder now declares verbs — seal 3's premise has changed and §2's measurement "
        f"needs re-taking. Found: {verbs}")

    # And the seeder's own comment records the instability, so this is not a theoretical worry.
    assert "subject resolution SHIFTS" in src, (
        "the seeder no longer records that subject resolution moves across a prime — verify "
        "whether that was fixed or merely deleted before trusting this seal's rationale")


def test_the_ratified_template_can_express_a_panel_set():
    """The other half of the measurement: the same five panels, now decidable without running.

    Seal 3 passing for the template while failing for the phrase seed is what makes §2 a
    comparison rather than an assertion.
    """
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(_TEMPLATE.read_text(encoding="utf-8"))
    first = panel_set(doc["panels"])
    second = panel_set(yaml.safe_load(_TEMPLATE.read_text(encoding="utf-8"))["panels"])

    assert first == second, "the template's panel set is not stable across two reads"
    assert len(first) == 5, f"expected five panels, got {len(first)}"
    assert all(v and v.startswith("mesh:") for _, v, _, _ in first), (
        "a panel does not name a verb — the template has regressed toward a phrase")
    assert first[0][2] == "anchor", "position 0 must be the anchor; ORDER IS THE DECLARATION"


def test_the_comparison_can_actually_fail():
    """BREAK-ON-PURPOSE for the comparison itself.

    `panel_set` deliberately ignores artifact ids. A comparison that ignored too much would pass
    on two genuinely different boards, which is the decorative-seal shape one level down.
    """
    a = [{"verb": "mesh:planSchedule", "role": "anchor", "slots": {"group_by": "initiative"}}]
    assert panel_set(a) == panel_set([dict(a[0], artifact_id="different-uuid")]), (
        "the comparison is sensitive to artifact ids — it will fail for the wrong reason")
    assert panel_set(a) != panel_set(
        [{"verb": "mesh:planSchedule", "role": "anchor", "slots": {"group_by": "capability"}}]), (
        "the comparison ignores declared slots — it cannot see the difference it exists to see")
    assert panel_set(a) != panel_set([{"verb": "mesh:planCostCurve", "role": "anchor"}]), (
        "the comparison ignores the verb — it is not comparing panel sets at all")


# ── THE LIVE ARM — the recorded run, opt-in ─────────────────────────────────────────────────
#
# NOT RUN AS PART OF THE SUITE, and the reason is a measurement hazard rather than convenience:
#
#   * Seeding is SEQUENTIAL BY RULING (b) — ~25 minutes per seed, so this arm is ~50 minutes.
#   * `max_concurrent_runs: 2` plus a reaper gap DEADLOCKED this queue twice in one day. Two
#     full seeds fired alongside other work is how the substrate dies with nobody awake.
#   * A PRIME CHANGES SUBJECT RESOLUTION. Running this during or just after a prime yields the
#     expected failure FOR AN UNATTRIBUTABLE REASON, and a recorded failure that cannot be
#     attributed is a coincidence wearing a result's clothes.
#
# Set CANVAS_SEED_LIVE=1 and CORTEX_BFF_URL to record the run. Run it on a QUIET substrate.
@pytest.mark.skipif(os.environ.get("CANVAS_SEED_LIVE") != "1",
                    reason="live seed arm: set CANVAS_SEED_LIVE=1 on a quiet substrate (~50 min)")
def test_two_live_seeds_of_todays_canvas_produce_the_same_panel_set():
    """The recorded run. EXPECTED TO FAIL — that failure is the deliverable.

    Recovers each panel's verb from its artifact's routing record, because today's seed returns
    only artifact ids and the verb is not knowable any other way.
    """
    import httpx

    base = os.environ.get("CORTEX_BFF_URL")
    assert base, "CORTEX_BFF_URL must be set for the live arm"
    token = os.environ.get("CANVAS_SEED_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    # ── PRE-FLIGHT: THE INSTRUMENT MUST BE ABLE TO WORK BEFORE IT IS ALLOWED TO JUDGE ────────
    #
    # Found 2026-09-08 against the live bff, BEFORE spending the window: there is NO
    # `/artifacts/{id}` route. Its whole surface is /seed/portfolio_canvas, /canvas/seed,
    # /canvas/lineage_edges, /me/canvases, /interview/stream. Verb recovery by artifact fetch
    # 404s — so the arm as first written would have burned ~25 minutes on the first seed and
    # then errored with nothing recorded.
    #
    # And the near-miss that matters more: had recovery returned None per panel instead of
    # 404ing, BOTH runs would have produced identical all-None panel sets and SEAL 3 WOULD HAVE
    # PASSED. A broken instrument turning a seal green is strictly worse than one turning it
    # red. Hence VOID: a run that cannot recover verbs is neither pass nor fail.
    #
    # `AnswerArtifact` exists as a Neo4j label, which is the likely headless recovery path. It
    # is NOT wired here yet — writing a recovery path I have not proven would reintroduce the
    # same defect one layer down.
    def _void(reason: str):
        pytest.fail(f"SEAL 3 VOID — the instrument could not produce a reading, so this run is "
                    f"neither a pass nor a failure and must not be recorded as either: {reason}")

    probe = httpx.get(f"{base.rstrip('/')}/openapi.json", headers=headers, timeout=30)
    if probe.status_code != 200:
        _void(f"cannot read the bff's route table (HTTP {probe.status_code})")
    routes = set(probe.json().get("paths", {}))
    if "/seed/portfolio_canvas" not in routes:
        _void("the phrase seeder is gone from this deployment — seal 3's subject does not exist "
              "here; re-read the recorded structural result instead")
    if not any(p.startswith("/artifacts") for p in routes):
        _void("no /artifacts route on this bff, so per-panel verbs cannot be recovered. Wire a "
              "proven recovery path (AnswerArtifact in Neo4j is the candidate) before running "
              "this arm — do NOT let unrecovered verbs compare equal")

    def seed(session: str) -> list[dict]:
        r = httpx.post(f"{base.rstrip('/')}/seed/portfolio_canvas",
                       json={"session_id": session, "frontend_id": "cortex-ui-desktop"},
                       headers=headers, timeout=3600)
        r.raise_for_status()
        ids = r.json()["artifact_ids"]
        if len(ids) != 5:
            _void(f"the seed returned {len(ids)} artifact ids, not five")
        panels = []
        for i, aid in enumerate(ids):
            if aid is None:
                # A seeded question that FAILED. Real information, aligned to slot index by the
                # seeder on purpose, and a legitimate part of a panel set.
                panels.append({"verb": None, "role": None, "slots": {}, "unseeded": True})
                continue
            a = httpx.get(f"{base.rstrip('/')}/artifacts/{aid}", headers=headers, timeout=60)

            # ── READ FAILURES ARE VOID, NEVER DIFFERENCES ───────────────────────────────────
            # `GET /artifacts/{id}` is gated and scoped to the caller by the PRODUCED_FOR edge,
            # and its author states two shape facts this arm must respect (2026-09-09):
            #
            #   * an unreachable graph answers 503, NOT 404 — "we could not look" is not "there
            #     is no such thing". Treating 503 as absence would record a difference that
            #     never happened.
            #   * `verb_iri` is null when unrecorded and never a placeholder; the recorded
            #     non-answer "UNKNOWN" is normalised to null at the source rather than
            #     forwarded, because two artifacts both saying "UNKNOWN" would compare EQUAL on
            #     a value meaning "no idea".
            #
            # So: anything that is not a clean 200 ends the run as VOID. An authorisation
            # failure especially — two runs that both read nothing would agree perfectly.
            if a.status_code == 503:
                _void(f"artifact {aid} (ordinal {i}): the graph was unreachable (503). We could "
                      f"not LOOK; that is not a difference and must not be recorded as one")
            if a.status_code in (401, 403):
                _void(f"artifact {aid} (ordinal {i}): not readable under this identity "
                      f"({a.status_code}). Two runs that both read nothing agree perfectly")
            if a.status_code == 404:
                _void(f"artifact {aid} (ordinal {i}): the seed returned this id and the store "
                      f"does not have it. That is an anomaly in the seed/read path, not a "
                      f"finding about panel-set stability")
            if a.status_code != 200:
                _void(f"artifact {aid} (ordinal {i}): unexpected status {a.status_code}")
            panels.append({"verb": (a.json().get("routing") or {}).get("verb_iri"),
                           "role": None, "slots": {}, "unseeded": False})

        # ── A NULL VERB IS AN UNREAD PANEL, NOT AN EQUAL ONE ────────────────────────────────
        # Scoped to panels that DID seed: a null there means the verb was never recorded, so the
        # seal would be comparing "no idea" against "no idea" and scoring it as agreement. The
        # all-null case is the catastrophic version (every panel silently equal); the partial
        # case is the quiet one, and it is the reason this checks ANY rather than ALL.
        #
        # If nulls turn out to be normal rather than exceptional, that is a finding about the
        # RECORDING path to fix at its source — the way "UNKNOWN" was — and not a reason to
        # relax this into scoring unknowns as matches.
        unread = [i for i, p in enumerate(panels) if not p["unseeded"] and p["verb"] is None]
        if unread:
            _void(f"panels {unread} seeded but recorded no verb_iri. A null is UNREAD, not "
                  f"equal — comparing two of them scores agreement about nothing")
        return panels

    first, second = seed("seal3-run-a"), seed("seal3-run-b")
    assert panel_set(first) == panel_set(second), (
        "SEAL 3 FAILED against today's phrase-based seed — which is the expected and recorded "
        f"result.\n  run A: {panel_set(first)}\n  run B: {panel_set(second)}")
