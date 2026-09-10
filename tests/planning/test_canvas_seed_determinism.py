"""SEAL 3 — two seeds of the same template under the same identity produce identical PANEL SETS.

ADR-0050 acceptance 3. Scope stated precisely, because the loose version is unpassable: identical
**(verb, declared slots, slot role, ordinal)** per panel. NOT identical artifact ids — those are
minted per run (`uuid4`) — and NOT identical rendered content, which is state-dependent by design
(ADR-0042).

**THE ORIGINAL SCOPING SAID THIS SEAL "CANNOT BE PASSED" BY PHRASE SEEDING. IT WAS PASSED, THREE
TIMES OVER, ON 2026-09-09** — and the correction is more useful than the seal was. Two seeds
against UNCHANGED state agree, because on a quiet substrate the classifier is deterministic. The
event the seeder's comment actually names is an ONTOLOGY CHANGE, and seeding twice in one window
never exercises it. A green there meant only *"the substrate did not move between the two runs"*.

So there are now two live arms and they are not interchangeable:

  * `test_two_live_seeds_...`   — same-window. **Kept, and it is NOT the seal**: it is the
    control that showed the classifier is deterministic when nothing changes. Its green is
    evidence about the substrate, never about phrase seeding.
  * `test_the_panel_set_survives_a_prime` — seed → PRIME → seed, ADR-0050 acceptance 3 as
    amended. The only version that can bite.

Recording the falsification here rather than quietly rewriting the claim, because a docstring
that still asserted "cannot pass" would be the stale-comment-that-matches-the-symptom shape this
repo has already paid for.

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
#   * Seeding is SEQUENTIAL BY RULING (b). MEASURED 2026-09-09: 5.5–6.6 minutes per seed (398s
#     for one; 659s for two), so this arm is ~11 minutes — NOT the ~25-per-seed the ruling's
#     comment estimated, which is roughly 4x pessimistic. The qualitative half of RULING (b) is
#     untouched: sequential-not-parallel is unaffected by how long each ask takes.
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
        body = r.json()
        ids = body["artifact_ids"]
        if len(ids) != 5:
            _void(f"the seed returned {len(ids)} artifact ids, not five")

        # ── AN ALL-FAILED SEED MEASURES NOTHING — VOID, NOT AGREEMENT ───────────────────────
        #
        # THIS GUARD EXISTS BECAUSE ITS ABSENCE PRODUCED A FALSE GREEN, 2026-09-09. Every one of
        # the five questions failed with HTTP 403 in ~0.1s; the route still answered 200 with
        # five null artifact_ids. Both runs therefore produced five `unseeded` panels, compared
        # EQUAL, and SEAL 3 REPORTED PASS on a board where nothing seeded at all. The tell was
        # the clock — 2.48s for what RULING (b) says is ~50 minutes — not any assertion here.
        #
        # The hole was the exemption directly below: a null on a panel the SEEDER reported as
        # failed is real information and still compares, which is true and was the right call —
        # a question that failed in run A and succeeded in run B is a genuine difference. It is
        # only true while SOMETHING succeeded. Comparing two total failures is comparing two
        # empty sets and scoring it as agreement.
        #
        # `seeded` and `total` were in the response the whole time and the arm read neither.
        seeded = body.get("seeded")
        detail = "; ".join(
            f"slot {x.get('slot')}: {x.get('status')} {x.get('detail') or ''}".strip()
            for x in (body.get("results") or [])
            if x.get("status") != "ok"
        )
        if not any(i is not None for i in ids):
            _void(f"NOTHING SEEDED — all five questions failed, so this run has no panel set to "
                  f"compare. Two such runs agree perfectly and mean nothing "
                  f"(seeded={seeded}/{body.get('total')}). Causes: {detail or 'unreported'}")
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
            doc = a.json()
            # `verb_iri` is TOP-LEVEL on this route, not nested under `routing`. The first
            # version of this arm read `routing.verb_iri` and would have returned None for
            # every panel — voiding a full seed for an instrument reason, after spending it.
            # Verified against a real artifact before this run rather than assumed.
            #
            # An ABSENT key is a shape change and must void; a PRESENT null is the route's
            # honest "unrecorded", which the unread guard below already handles. Those are
            # different facts and collapsing them would hide a contract change behind a
            # data-quality message.
            if "verb_iri" not in doc:
                _void(f"artifact {aid} (ordinal {i}) has no `verb_iri` field at all — the "
                      f"route's response shape changed; this arm is reading the wrong "
                      f"contract, not observing a missing verb. Keys: {sorted(doc)}")
            panels.append({"verb": doc.get("verb_iri"),
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


# ── SEAL 3, RE-SCOPED: seed -> PRIME -> seed (ADR-0050 acceptance 3, amended 2026-09-09) ─────
#
# THE ORIGINAL SCOPING WAS FALSIFIED BY ITS OWN PASS. Two seeds against UNCHANGED state agreed
# three times over, because on a quiet substrate the classifier is deterministic. The event the
# seeder's comment actually names is an ONTOLOGY CHANGE — *"subject resolution SHIFTS when the
# ontology or verb set changes … moved Portfolio 0.86 -> Site 0.75 ACROSS A SINGLE PRIME."*
#
# So the comparison that can bite spans a prime. This arm supplies the second half: the baseline
# was seeded BEFORE, and one seed runs AFTER.
#
# THE BASELINE IS PINNED BY ARTIFACT ID, NOT RE-DERIVED. Two `seal3-run-a-*` sets exist in the
# graph from different attempts, and "the most recent run A" would silently re-point the baseline
# the next time anyone seeds. These five ids ARE the recorded pre-prime observation from
# 2026-09-09 (commit 08ddf94); reading them back is reading the record, not re-measuring it.
_PRE_PRIME_BASELINE = [
    "urn:li:answerArtifact:seal3-run-a-seed0-f55f0994",   # mesh:planSchedule
    "urn:li:answerArtifact:seal3-run-a-seed1-c03024c5",   # mesh:planCostCurve
    "urn:li:answerArtifact:seal3-run-a-seed2-3ebea304",   # mesh:planSiteLoad
    "urn:li:answerArtifact:seal3-run-a-seed3-be62f7af",   # mesh:planFundingGap
    "urn:li:answerArtifact:seal3-run-a-seed4-5d4b8787",   # mesh:planMaturityGrid
]

# What the record says those five resolved to, so a baseline that reads back DIFFERENTLY is
# caught rather than quietly adopted. A prime is `wipe: false` and must not alter a stored
# artifact; if it does, that is a much larger finding than seal 3 and this arm must not paper
# over it by comparing against whatever the graph now says.
_PRE_PRIME_VERBS = [
    "mesh:planSchedule", "mesh:planCostCurve", "mesh:planSiteLoad",
    "mesh:planFundingGap", "mesh:planMaturityGrid",
]


@pytest.mark.skipif(os.environ.get("CANVAS_SEED_PRIME_B") != "1",
                    reason="run B of the across-a-prime arm: set CANVAS_SEED_PRIME_B=1 AFTER a "
                           "prime AND after the reregister hook has finished (two different "
                           "completions; only the second means the substrate has settled)")
def test_the_panel_set_survives_a_prime():
    """SEAL 3, the version that can bite. One seed, compared to the pinned pre-prime record.

    A DIFFERENCE HERE IS THE FINDING, and it is what the original scoping was reaching for: the
    same five phrases resolving to different verbs because the ontology moved underneath them.

    A MATCH IS ALSO A REAL RESULT and must not be overclaimed. It would mean these five phrases
    are robust to THIS prime — not that phrase seeding is stable, and not the quiet-substrate
    green that the unamended seal produced. Note the asymmetry deliberately: the shift the
    seeder recorded was for *"where are we over budget"*, which is NOT one of the five phrases
    seeded today (slot 1 asks *"what does spend look like per period"*). So a match is quite
    possible and says less than it appears to.
    """
    import httpx

    base = os.environ.get("CORTEX_BFF_URL")
    assert base, "CORTEX_BFF_URL must be set"
    token = os.environ.get("CANVAS_SEED_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    def _void(reason: str):
        pytest.fail(f"SEAL 3 (across a prime) VOID — no reading was produced, so this is neither "
                    f"a pass nor a failure and must not be recorded as either: {reason}")

    def _verb_of(aid: str, where: str) -> str:
        r = httpx.get(f"{base.rstrip('/')}/artifacts/{aid}", headers=headers, timeout=60)
        if r.status_code == 503:
            _void(f"{where} {aid}: graph unreachable (503) — we could not look")
        if r.status_code in (401, 403):
            _void(f"{where} {aid}: not readable under this identity ({r.status_code})")
        if r.status_code == 404:
            _void(f"{where} {aid}: not found. If this is the BASELINE, the prime altered stored "
                  f"artifacts under `wipe: false` — a far larger finding than seal 3, and this "
                  f"arm must not paper over it")
        if r.status_code != 200:
            _void(f"{where} {aid}: unexpected status {r.status_code}")
        doc = r.json()
        if "verb_iri" not in doc:
            _void(f"{where} {aid}: no `verb_iri` field — the route's shape changed; this arm is "
                  f"reading the wrong contract. Keys: {sorted(doc)}")
        return doc.get("verb_iri")

    def _slots_of(aid: str) -> tuple:
        """The SLOTS half of acceptance 3's scope, read from the graph's `resolved_intent`.

        SCOPE GAP CLOSED 2026-09-09. Acceptance 3 scopes the comparison as
        **(verb, declared slots, slot role, ordinal)**, and this arm compared verb and ordinal
        only — every panel was built with `"slots": {}`, so a slot-level divergence across the
        prime would have passed unseen. A seal that quietly checks a subset of its own stated
        scope is the decorative shape one layer in.

        Read from Neo4j rather than the route because the route does not expose
        `accepted_slots`; the graph does, on `resolved_intent`. Verified against the pinned
        baseline: the five recorded slot sets match `portfolio.yaml`'s declarations exactly,
        including slot 3's `group_by: org`.

        Returns () when the graph is unreachable rather than voiding — the slots half is an
        ADDITION to a comparison whose verb half already works, and losing the graph should
        narrow the seal with a warning rather than void a spent seed.
        """
        try:
            import json as _json
            from neo4j import GraphDatabase
            uri = os.environ.get("NEO4J_URI")
            pw = os.environ.get("NEO4J_PASSWORD")
            if not (uri and pw):
                return ()
            drv = GraphDatabase.driver(uri, auth=(os.environ.get("NEO4J_USER", "neo4j"), pw))
            try:
                with drv.session() as s:
                    rec = s.run("MATCH (a:AnswerArtifact {id: $i}) RETURN a.resolved_intent AS ri",
                                i=aid).single()
            finally:
                drv.close()
            if not rec or not rec["ri"]:
                return ()
            slots = (_json.loads(rec["ri"]) or {}).get("accepted_slots") or {}
            return tuple(sorted((k, str(v)) for k, v in slots.items()))
        except Exception:                                   # pragma: no cover - env-dependent
            return ()

    # ── 1. THE BASELINE MUST READ BACK AS RECORDED, BEFORE ANYTHING IS SPENT ────────────────
    before = [_verb_of(aid, "baseline") for aid in _PRE_PRIME_BASELINE]
    if before != _PRE_PRIME_VERBS:
        _void(f"the pinned pre-prime baseline no longer reads as recorded.\n"
              f"  recorded: {_PRE_PRIME_VERBS}\n  now:      {before}\n"
              f"A stored artifact changed under a `wipe: false` prime. Comparing against the "
              f"NEW value would silently redefine the experiment's own control")

    # ── 2. ONE SEED, AFTER THE PRIME ────────────────────────────────────────────────────────
    r = httpx.post(f"{base.rstrip('/')}/seed/portfolio_canvas",
                   json={"session_id": "seal3-postprime-b", "frontend_id": "cortex-ui-desktop"},
                   headers=headers, timeout=3600)
    r.raise_for_status()
    body = r.json()
    ids = body["artifact_ids"]
    if len(ids) != 5:
        _void(f"the seed returned {len(ids)} artifact ids, not five")
    if not any(i is not None for i in ids):
        detail = "; ".join(
            f"slot {x.get('slot')}: {x.get('status')} {x.get('detail') or ''}".strip()
            for x in (body.get("results") or []) if x.get("status") != "ok")
        _void(f"NOTHING SEEDED (seeded={body.get('seeded')}/{body.get('total')}). Two empty sets "
              f"agree perfectly and mean nothing. Causes: {detail or 'unreported'}")

    unseeded = [i for i, a in enumerate(ids) if a is None]
    after = [None if a is None else _verb_of(a, f"post-prime slot {i}")
             for i, a in enumerate(ids)]
    unread = [i for i, v in enumerate(after) if v is None and i not in unseeded]
    if unread:
        _void(f"panels {unread} seeded but recorded no verb_iri — a null is UNREAD, not equal")

    # ── 3. THE COMPARISON — (verb, slots, ordinal), acceptance 3's full stated scope ────────
    before_slots = [_slots_of(aid) for aid in _PRE_PRIME_BASELINE]
    after_slots = [() if a is None else _slots_of(a) for a in ids]
    slots_available = any(before_slots) or any(after_slots)

    moved = [(i, (b, bs), (a, as_))
             for i, (b, a, bs, as_) in enumerate(zip(before, after, before_slots, after_slots))
             if b != a or (slots_available and bs != as_)]

    if not slots_available:
        # NARROWED, AND IT SAYS SO. A green from a verb-only comparison is a weaker claim than
        # a green from the full scope, and the two must not read alike in a report.
        print("\nWARNING: slots unavailable (no NEO4J_URI/NEO4J_PASSWORD) — this run compared "
              "VERB AND ORDINAL ONLY, which is narrower than acceptance 3's stated scope. A "
              "pass here does not cover slot-level divergence.")

    assert not moved, (
        "SEAL 3 BIT ACROSS A PRIME — the same phrases resolved differently after the ontology "
        "moved. This is the measured case for declared verbs, and it is the finding the "
        "original scoping was reaching for.\n"
        + "\n".join(f"  slot {i}: {b}  ->  {a}" for i, b, a in moved)
        + f"\n  unseeded this run: {unseeded or 'none'}")
