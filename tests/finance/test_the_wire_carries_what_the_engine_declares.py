"""Two wire-level seals, and the second is the one that would have caught the real drop.

WHAT HAPPENED, 2026-09-03. `reference` and `verdict` were added to two finance envelopes and
arrived at no card. The reporting lane read it as a producer bug -- "report says emitted, wire
says absent" -- and asked for a seal on the measure endpoint's response body.

**THE MEASURE ENDPOINT WAS CORRECT THE WHOLE TIME.** Verified on the deployed pod: its HTTP
body carries `reference`, `verdict`, and a `series` list with `unit` and `dashed` intact. A seal
on that endpoint would have PASSED while the cards stayed wrong -- measuring the neighbour,
which is the very failure the request was trying to avoid.

The drop was `_PROJECTED_ARCHETYPES`: the projector carries the payload key plus a declared
tuple of passthrough fields and NOTHING ELSE, and that tuple predated both additions.

AND THE CONTRAST IS THE WHOLE LESSON. `favourable` shipped in the same commit and arrived fine,
because it rides inside `rows`, which pass through verbatim. So a ROW-level addition needs no
declaration and an ENVELOPE-level addition needs one -- and nothing anywhere reported the
difference. Two fields added, one silently discarded.

So: seal 1 is what was asked for and guards the engine. Seal 2 guards the seam that actually
broke, and is derived from the engine's own declaration tables rather than a remembered list.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.finance_agent import measures  # noqa: E402
from agent_fleet.finance_agent.seed import build_seed  # noqa: E402

_STATE = build_seed()
_KW = {"fin_eac_calculation": {"method": "CPI"}}


def _envelope(fn: str) -> dict:
    """The response body `/measure/<fn>` builds, via the app itself rather than a copy of it."""
    from fastapi.testclient import TestClient
    from agent_fleet.finance_agent.main import app
    with TestClient(app) as client:
        r = client.post(f"/measure/{fn}",
                        json={"params": {"program_id": "NP-MERIDIAN", **_KW.get(fn, {})}})
    assert r.status_code == 200, f"{fn}: {r.status_code} {r.text[:200]}"
    return r.json()


# -- SEAL 1 -- the engine's own wire, as requested --------------------------------------

def test_the_measure_response_BODY_carries_every_declared_envelope_field():
    """Asserted on the real HTTP body, not on the measure function's return value.

    The declaration tables are the population, so a seventh verb that declares a reference
    inherits this without an edit here.
    """
    for fn, decl in measures.SERIES.items():
        body = _envelope(fn)
        assert body.get("series") == decl, (
            f"{fn}: `series` on the wire is {body.get('series')!r}, declared {decl!r}"
        )
    for fn, ref in measures.REFERENCE.items():
        assert _envelope(fn).get("reference") == ref, f"{fn}: `reference` absent or altered"
    for fn, verdict_of in measures.VERDICT.items():
        # `_KW` HERE TOO. `_envelope` above honours it and this direct call did not, so a
        # verb with a mandatory slot raised TypeError the moment it gained a VERDICT
        # entry. Two call sites in one seal disagreeing about how to invoke a verb.
        rows = getattr(measures, fn)(_STATE, program_id="NP-MERIDIAN", **_KW.get(fn, {}))
        expected = verdict_of(rows)
        body = _envelope(fn)
        if expected is None:
            assert "verdict" not in body, f"{fn}: emitted a null verdict key"
        else:
            assert body.get("verdict") == expected, (
                f"{fn}: verdict on the wire {body.get('verdict')!r} != {expected!r}"
            )


def test_series_entries_keep_their_unit_and_dashed_on_the_wire():
    """`dashed` and `unit` are the fields most likely to be dropped by a serializer, because
    they are OPTIONAL and per-entry. The burn card's dashed plan line depends on one of them
    reaching the card, and it was specifically doubted."""
    burn = _envelope("fin_burn_rate")["series"]
    plan = [s for s in burn if s["key"] == "planned"]
    assert plan and plan[0].get("dashed") is True, "the plan series lost `dashed` on the wire"
    assert all(s.get("unit") == "USD" for s in burn), "a burn series lost its `unit`"
    idx = _envelope("fin_performance_indices")["series"]
    assert all("unit" not in s for s in idx), (
        "a dimensionless index gained a unit -- absence is the assertion, per the contract"
    )


# -- SEAL 2 -- the seam that actually broke ---------------------------------------------

def _projector_passthrough() -> dict:
    """Parsed from the projector's own source, because presentation_agent/main.py imports
    baml_client and cannot be imported outside its container -- the same reason
    `capability_slug` was untestable until it moved."""
    src = (_ROOT / "agent_fleet" / "presentation_agent" / "main.py").read_text(encoding="utf-8")
    block = re.search(r"_PROJECTED_ARCHETYPES: Dict\[str, tuple\] = \{(.*?)^\}", src, re.S | re.M)
    assert block, "could not find _PROJECTED_ARCHETYPES -- the projector's shape moved"
    out = {}
    for name, key, rest in re.findall(
        r'^\s*"(\w+)":\s*\("(\w+)",\s*\(([^)]*)\)\)', block.group(1), re.M
    ):
        out[name] = (key, tuple(re.findall(r'"(\w+)"', rest)))
    assert out, "parsed no entries -- the regex is stale, not the table"
    return out


def _fin_bindings() -> dict:
    from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES
    by_output = {uri: fn for fn, uri in measures.OUTPUT_URI.items()}
    out = {}
    for cap in PRESENTATION_CAPABILITIES:
        subj = cap["subject_uri"]
        if not subj.startswith("fin:"):
            continue
        full = subj.replace("fin:", "http://invincible-agent/fin#", 1)
        fn = by_output.get(full) or by_output.get(subj)
        if fn:
            out[fn] = cap["archetype"]
    return out


def test_every_envelope_field_a_verb_declares_survives_its_archetype_passthrough():
    """THE SEAL THE MEASURE-ENDPOINT ONE COULD NOT BE.

    The projector carries `rows` plus a declared tuple and DISCARDS THE REST SILENTLY. So an
    envelope-level field is only real if its archetype declares it, and nothing connected the
    two declarations until this test.

    Derived from three sources that must agree -- the engine's declaration tables, the
    capability bindings, and the projector's own table -- so a new field, a new verb or a
    rebinding each fail here rather than at a card.
    """
    passthrough = _projector_passthrough()
    bindings = _fin_bindings()
    assert bindings, "derived no fin bindings -- the derivation is stale"

    declared_by_fn: dict = {}
    for table, field in ((measures.SERIES, "series"),
                         (measures.REFERENCE, "reference"),
                         (measures.VERDICT, "verdict")):
        for fn in table:
            declared_by_fn.setdefault(fn, set()).add(field)

    missing = []
    for fn, fields in sorted(declared_by_fn.items()):
        archetype = bindings.get(fn)
        assert archetype, f"{fn} declares {sorted(fields)} but is bound to no archetype"
        spec = passthrough.get(archetype)
        assert spec, f"{archetype} is not in the projector table -- {fn} cannot render at all"
        carried = set(spec[1])
        for f in sorted(fields - carried):
            missing.append(f"{fn} declares {f!r} -> {archetype} passthrough {spec[1]} drops it")
    assert not missing, (
        "envelope fields DISCARDED by the projector, silently:\n  " + "\n  ".join(missing)
        + "\n\nThe engine emits them and no card receives them. Add the field to that "
          "archetype's passthrough tuple, or stop emitting it."
    )


def test_row_level_fields_need_NO_declaration_and_that_is_why_favourable_survived():
    """The contrast, pinned, because it is what made the drop invisible.

    `favourable` was added in the same commit as `reference` and `verdict` and arrived at the
    card, because rows pass through verbatim. Anyone reasoning "the other field arrived, so the
    payload is fine" was reasoning from a real observation about a different mechanism.
    """
    key, carried = _projector_passthrough()["MULTI_SERIES"]
    assert key == "rows", "MULTI_SERIES no longer projects `rows` -- this test's premise moved"
    tree = measures.fin_variance_analysis(_STATE, program_id="NP-MERIDIAN")[0]
    assert "favourable" in tree, "the tree stopped emitting a verdict"
    assert "favourable" not in carried, (
        "`favourable` is declared as a passthrough field -- it is a ROW field and needs no "
        "declaration; listing it here would suggest row additions require one, which is the "
        "confusion that hid this bug"
    )


# ── THE ARCHETYPE AXIS, widened 2026-09-05 ────────────────────────────────────────────
#
# The seal above derives its population from THIS ENGINE's declaration tables, so it covers
# every archetype a fin: verb produces and NOTHING ELSE. ELICITATION is produced by the
# supervisor's ask path, not by a measure verb, so it sat outside the population entirely — and
# a whole archetype with no projector entry fell through to KNOWLEDGE_DOCUMENT silently, which
# is the same drop as `reference`/`verdict` one level up: not a field discarded, a card.
#
# So the axis is now derived from CORTEX'S CONTRACTS — every archetype the frontend declares it
# can draw — rather than from what this engine happens to emit. That is the population the
# projector actually has to cover.

_CORTEX = _ROOT.parent / "cortex-ui"


def _cortex_declared_archetypes() -> dict:
    """archetype -> set(required field names), parsed from cortex's *.contract.ts."""
    out = {}
    if not _CORTEX.is_dir():
        return out
    for p in _CORTEX.rglob("*.contract.ts"):
        src = p.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'archetype:\s*"([A-Z_]+)"', src)
        if not m:
            continue
        fields = re.search(r"fields:\s*\{(.*?)\n  \}", src, re.S)
        req = set()
        if fields:
            for fname, body in re.findall(r"(\w+):\s*\{([^}]*)\}", fields.group(1)):
                if "required: true" in body:
                    req.add(fname)
        out[m.group(1)] = req
    return out


def _flat_archetypes() -> dict:
    src = (_ROOT / "agent_fleet" / "presentation_agent" / "main.py").read_text(encoding="utf-8")
    block = re.search(r"_FLAT_ARCHETYPES: Dict\[str, tuple\] = \{(.*?)^\}", src, re.S | re.M)
    if not block:
        return {}
    out = {}
    for name, groups in re.findall(r'^\s*"(\w+)":\s*\((.*?)\),\n', block.group(1), re.S | re.M):
        out[name] = tuple(re.findall(r'"(\w+)"', groups))
    return out


def test_ELICITATION_is_projected_and_carries_the_field_its_contract_REQUIRES():
    """The specific regression: an ask with no menu drew as KNOWLEDGE_DOCUMENT.

    Pinned on the REQUIRED field rather than the whole list, because the optional ones are
    absent-means-something and asserting their presence would forbid a legitimate ask.
    """
    flat = _flat_archetypes()
    assert "ELICITATION" in flat, (
        "ELICITATION has no projector entry — an archetype with no path falls through to "
        "KNOWLEDGE_DOCUMENT by construction, which is a whole card lost silently"
    )
    declared = _cortex_declared_archetypes()
    if "ELICITATION" not in declared:
        pytest.skip("cortex-ui not checked out beside this repo")
    missing = declared["ELICITATION"] - set(flat["ELICITATION"])
    assert not missing, (
        f"ELICITATION's projector does not carry {sorted(missing)}, which cortex's contract "
        f"marks required — the card mounts and cannot say what it is asking for"
    )


def test_an_ask_with_NO_MENU_is_still_projectable():
    """⛔ THE CASE THAT MOTIVATED A SECOND TABLE, and the one a list projector rejects.

    `options` is legitimately EMPTY whenever no provider could enumerate the slot — the producer
    says why in `free_text_reason`, and "which program? I could not list them" is a complete
    ask. The list projector returns None on an empty payload, which is correct for a grid and
    exactly wrong here: it would reject the asks that most need to render.

    So ELICITATION must NOT be in the list-projected table, and this asserts that separation
    rather than trusting it.
    """
    passthrough = _projector_passthrough()
    assert "ELICITATION" not in passthrough, (
        "ELICITATION is in _PROJECTED_ARCHETYPES, whose projector requires a NON-EMPTY list "
        "under its payload key. An ask with no menu has none, so every menu-less ask would "
        "silently degrade — the failure this separation exists to prevent."
    )
    flat = _flat_archetypes()
    assert "options" not in flat["ELICITATION"][:1], (
        "`options` is declared REQUIRED for ELICITATION; an ask with no menu is legitimate"
    )


def test_every_archetype_cortex_can_draw_has_SOME_projector_path():
    """The widened axis. Reported per archetype so a gap names itself.

    An archetype cortex declares and the backend cannot project is a card that will never
    render — and it degrades to KNOWLEDGE_DOCUMENT rather than erroring, so nothing goes red.
    Archetypes served by a hardened BAML renderer are legitimately absent from both tables, so
    those are listed rather than asserted: this fails only for an archetype with NO path at all.
    """
    declared = _cortex_declared_archetypes()
    if not declared:
        pytest.skip("cortex-ui not checked out beside this repo")
    projected = set(_projector_passthrough()) | set(_flat_archetypes())
    hardened = {"CHART_WIDGET", "KNOWLEDGE_DOCUMENT", "PROCESS_TOPOLOGY",
                "HAZARD_DECLARATION", "ASSET_STATE_METRIC", "GROUPED_REVIEW",
                "APPROVAL_TASK", "WORKFLOW_OBSERVATION", "INSTANCES_BY_PROPERTY",
                "DECISION_RECORD", "CANVAS_SEED"}
    orphans = sorted(set(declared) - projected - hardened)
    assert not orphans, (
        f"{len(orphans)} archetype(s) cortex declares with NO backend projection path: "
        f"{orphans}. Each degrades to KNOWLEDGE_DOCUMENT silently. Add a projector entry, or "
        f"add it to the hardened-renderer set in this test if a BAML renderer serves it."
    )


# ═══════════════════════════════════════════════════════════════════════════
# THE VOID PATH ITSELF — because it had NEVER EXECUTED
# ═══════════════════════════════════════════════════════════════════════════

def test_THE_SKIP_PATH_ACTUALLY_WORKS(monkeypatch):
    """A VOID PATH THAT ONLY EXECUTES WHERE THE VOID IS NEEDED IS UNTESTED BY CONSTRUCTION.

    This file called `pytest.skip(...)` in two places and never imported pytest. Every lane has
    cortex-ui checked out beside the repo, so that branch had **never once run** — and on a CI
    runner, where cortex-ui is absent, it raised `NameError: name 'pytest' is not defined`.
    **A test written to VOID instead FAILED, and only in the condition the void exists for.**
    It took down all three jobs of the first full suite run in 22 days.

    So the branch is forced here, on a machine that HAS cortex-ui, by making the parser return
    what it returns when the sibling repo is missing. Without this the import is fixed until the
    next person writes a skip the same way, and nothing in the suite can tell.

    WHAT THIS CANNOT DISTINGUISH: a skip that fires for the right reason from one that fires for
    any reason. It asserts the mechanism raises Skipped rather than NameError — which is the
    failure that actually happened — not that the condition was correctly judged.
    """
    # DERIVED IN TWO HOPS, because one hop stopped being enough on 2026-09-15. The original
    # filter was "a test whose own body names pytest.skip" — and three new tests skip through a
    # HELPER (`_mirrors`) instead, so the population silently lost them. **A derivation that
    # stops at the direct case reads as complete and is a sample.**
    #
    # Hop 1: every module-level function whose body names `pytest.skip(` — helpers included.
    # Hop 2: every zero-argument test that names one of those, transitively.
    src = Path(__file__).read_text(encoding="utf-8")
    # NAMED VIA chr(10), NOT AN ESCAPE. A backslash-n written into a patch script run
    # through a heredoc collapses into a real newline and splits the string literal — the
    # same collapse that has cost this lane three times. Name the character.
    _NL = chr(10)
    bodies = {}
    for b in src.split(_NL + 'def '):
        name, _, rest = b.partition('(')
        if name and name.replace('_', '').isalnum():
            bodies[name] = (rest, b)

    skipping = {n for n, (_, b) in bodies.items() if 'pytest.skip(' in b}
    # Transitive closure: a helper that calls a skipping helper also skips.
    for _ in range(len(bodies)):
        grown = skipping | {
            n for n, (_, b) in bodies.items() if any(s + '(' in b for s in skipping)
        }
        if grown == skipping:
            break
        skipping = grown

    skippers = []
    for name in sorted(skipping):
        if not name.startswith('test_'):
            continue          # a helper is reached THROUGH its test, not called directly
        if name == 'test_THE_SKIP_PATH_ACTUALLY_WORKS':
            continue          # names pytest.skip itself; calling it would recurse
        if bodies[name][0].split(')', 1)[0].strip():
            continue          # takes fixtures - not directly callable
        skippers.append(name)
    assert len(skippers) >= 4, (
        f"expected at least the four known skipping tests, derived {skippers} — the derivation "
        f"is stale, and a shrinking population is how this seal goes quiet rather than red"
    )

    # ⚠ THE POPULATION IS DERIVED; THE FORCING IS NOT, AND THAT IS THE SEAM.
    # This seal finds every skipping test by reading the source — which it did, immediately, for
    # the mirror seal added 2026-09-15 — but each skip has its OWN condition, and neutralising
    # one says nothing about another. The list below is therefore a hand-kept part inside a
    # derived seal, and the failure mode is loud on purpose: a new skip whose condition is not
    # neutralised here runs to completion and this test FAILS with "DID NOT RAISE", naming it.
    #
    # Loud is the requirement. A forcing mechanism that silently missed a condition would report
    # the skip path tested when it had never run — the exact defect this seal exists to catch,
    # one level up.
    monkeypatch.setattr(sys.modules[__name__], "_cortex_declared_archetypes", lambda: {})
    monkeypatch.setattr(sys.modules[__name__], "_CORTEX", Path("no-such-sibling-repo.ts"))
    monkeypatch.setattr(sys.modules[__name__], "_CONTRACT_FILE", Path("no-such-contract.ts"))
    for name in skippers:
        fn = getattr(sys.modules[__name__], name)
        with pytest.raises(pytest.skip.Exception):
            fn()


def test_EVERY_pytest_SKIP_IN_THIS_FILE_HAS_ITS_IMPORT():
    """THE GENERAL FORM, cheap and derived. A file naming `pytest.skip` without importing pytest
    is a void that becomes a NameError in exactly the environment it was written for.

    Scanned from the source rather than trusted to review, because the defect is invisible on
    every machine where the branch does not fire.
    """
    src = Path(__file__).read_text(encoding="utf-8")
    if "pytest." in src:
        assert re.search(r"^import pytest$", src, re.M), (
            "this file calls into pytest and never imports it — the skip path raises NameError "
            "in the only condition it exists to handle"
        )


# -- SEAL 4 -- the join that was missing, from the other direction -----------------------
#
# The passthrough seal above asks "does a field this verb declares survive its archetype".
# It cannot ask "does this archetype have a verb at all", and that is how COMPETING_MEASURES
# sat in the projector from 2026-09-11 to 2026-09-15 with a component, a contract, a glyph
# and a contract header naming its first consumer BY NAME — claimed by no backend row, so the
# verb its passthrough was written for rendered as nothing.
#
# The registrar's unrenderable-output refusal, from the other end: an archetype nothing binds
# is registered and drawable by nobody.

#: Archetypes in the projector with no BACKEND capability row, each with the reason it needs
#: none. NOT a convenience list — every entry is a claim, and every claim was checked.
#:
#: All five are bound in cortex-ui's `DERIVED_BINDINGS`
#: (`src/registry/assembleCapabilities.ts`), read 2026-09-15. Their subjects are `mesh:`
#: vocabulary rather than an engine namespace, and this backend's table advertises the subjects
#: ITS OWN engines produce. Two mirrors of one binding set, split by who owns the subject.
#:
#: ⚠ THE SPLIT IS OBSERVED, NOT RATIFIED. Nobody has written down that `mesh:` subjects are the
#: frontend's to bind; it is what the two files DO. Recorded as the reason because it is the
#: true one, and flagged because a reason describing a pattern is weaker than one citing a
#: decision.
_ARCHETYPES_BOUND_IN_THE_FRONTEND_MIRROR = {
    "CANVAS_SEED": "mesh:CanvasSeedResult -> mesh:CanvasSeed, in DERIVED_BINDINGS",
    "INTERVAL_TIMELINE": "mesh:IntervalSchedule and mesh:ContributionSequence, in DERIVED_BINDINGS",
    "MATRIX_GRID": "mesh:MaturityMatrix -> mesh:MatrixGrid, in DERIVED_BINDINGS",
    "PERIOD_SERIES": "mesh:PeriodCostSeries -> mesh:PeriodSeries, in DERIVED_BINDINGS",
    "THRESHOLD_GRID": "mesh:LoadThresholdGrid -> mesh:ThresholdGrid, in DERIVED_BINDINGS",
}


def test_every_archetype_in_the_projector_is_CLAIMED_or_EXCUSED_BY_NAME():
    """PARTITIONED, not filtered: every archetype the projector can draw is either claimed by a
    backend capability row or carries a written reason it is not.

    A name in neither set FAILS. That is the whole mechanism — an archetype quietly added to
    the projector and bound by nobody is the state this seal exists to end, and it is the state
    COMPETING_MEASURES was in for four days.
    """
    from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES

    projected = set(_projector_passthrough())
    claimed = {c["archetype"] for c in PRESENTATION_CAPABILITIES}
    excused = set(_ARCHETYPES_BOUND_IN_THE_FRONTEND_MIRROR)

    orphans = sorted(projected - claimed - excused)
    assert not orphans, (
        "these archetypes are in the projector's table, claimed by no capability row, and "
        f"carry no stated reason: {orphans}\n"
        "An archetype nothing binds is registered and drawable by nobody. Either add a "
        "capability row whose `archetype` is this name, or add it to "
        "_ARCHETYPES_BOUND_IN_THE_FRONTEND_MIRROR WITH the binding that covers it."
    )

    # AND THE EXCLUSION LIST IS NOT A DRAWER. An entry for an archetype the projector no longer
    # carries is a stale excuse that keeps excusing nothing — the same shape as a tombstone for
    # a row the seed does not ship, which keeps deleting nothing.
    stale = sorted(excused - projected)
    assert not stale, f"excused archetypes no longer in the projector: {stale}"

    # A REASON IS REQUIRED TO BE ONE. An empty string satisfies the partition and says nothing,
    # which is how every exclusion list rots.
    for name, why in _ARCHETYPES_BOUND_IN_THE_FRONTEND_MIRROR.items():
        assert why and len(why) > 20, f"{name} is excused without a usable reason"


def test_the_partition_can_actually_FAIL():
    """THE CONTROL. A partition over two sets passes by construction unless something can fall
    outside both — so a name in neither must be shown to fall out."""
    projected = set(_projector_passthrough())
    from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES

    claimed = {c["archetype"] for c in PRESENTATION_CAPABILITIES}
    excused = set(_ARCHETYPES_BOUND_IN_THE_FRONTEND_MIRROR)
    assert (projected | {"AN_ARCHETYPE_NOBODY_DECLARED"}) - claimed - excused, (
        "a name in neither set does not fall out of the partition; the seal above cannot fail"
    )


# -- SEAL 5 -- the cross-repo mirror, for the subjects THIS engine owns -------------------

_CORTEX = _ROOT.parent / "cortex-ui" / "src" / "registry" / "assembleCapabilities.ts"


def _expand(uri: str) -> str:
    """Compact and expanded spellings are the SAME binding, and this repo has already paid for
    forgetting it: six `fin:` rows were refused by Contract D because the subject was emitted
    COMPACT. A diff over unexpanded URIs reports every cost row as a mismatch — measured, it
    reported seven — and a prefix absent from the map passes through verbatim, so the row
    registers, reports accepted, and never matches.
    """
    # THE PRIVATE NAME ON PURPOSE. `_IRI_PREFIXES_FOR_LOOKUP` is the ONE map the module
    # expands with, and a second copy transcribed into this seal would agree with itself
    # while disagreeing with the code — which is the defect this whole file is about.
    from agent_fleet.presentation_agent.capabilities import (
        _IRI_PREFIXES_FOR_LOOKUP as PREFIXES,
    )

    for p, full in PREFIXES.items():
        if uri.startswith(p):
            return full + uri[len(p):]
    return uri


_MESH = "http://invincible-agent/mesh#"
_SAFETY = "http://internal/sustainment/safety#"

#: THE 18 ROWS THAT WERE ALREADY OUT OF STEP WHEN THE MIRROR WAS RATIFIED (2026-09-15).
#:
#: A DEBT REGISTER, NOT AN EXCLUSION LIST, and the difference is enforced below: an entry that
#: STOPS being a mismatch FAILS this seal. It can only shrink, and a lane that fixes a row must
#: delete its line in the same commit. That is what keeps it from becoming the drawer every
#: exclusion list turns into.
#:
#: OWNING LANE IS ATTRIBUTED BY SUBJECT NAMESPACE, and that is a heuristic, not a record: the
#: `mesh:` rows are the planning/cortex vocabulary and the `safety:` rows are the safety lane's.
#: Nobody signed for them — **a citation is not a signature** — so Lane 1 routes, and this
#: comment says how the guess was made rather than presenting it as an assignment.
_MIRROR_GAPS_AT_RATIFICATION = {
    # FRONTEND BINDS, BACKEND DOES NOT ADVERTISE — 15, all mesh: vocabulary.
    # Drawable by a registered frontend; the mesh advertises nothing, so nothing routes to them.
    (_MESH + "CanvasSeedResult", _MESH + "CanvasSeed"),
    (_MESH + "ContributionSequence", _MESH + "IntervalTimeline"),
    (_MESH + "DecisionArtifact", _MESH + "DecisionRecord"),
    (_MESH + "EffectSet", _MESH + "DeltaSet"),
    (_MESH + "FundingGapSet", _MESH + "ShortfallGrid"),
    (_MESH + "HumanApprovalTask", _MESH + "ApprovalTask"),
    (_MESH + "InstancesByProperty", _MESH + "InstancesByProperty"),
    (_MESH + "IntervalSchedule", _MESH + "IntervalTimeline"),
    (_MESH + "LoadThresholdGrid", _MESH + "ThresholdGrid"),
    (_MESH + "MaturityMatrix", _MESH + "MatrixGrid"),
    (_MESH + "PartObsolescenceReviewBatch", _MESH + "GroupedReview"),
    (_MESH + "PeriodCostSeries", _MESH + "PeriodSeries"),
    (_MESH + "SlotElicitation", _MESH + "AskCard"),
    (_MESH + "WithheldPanel", _MESH + "NamedHole"),
    (_MESH + "WorkflowObservation", _MESH + "WorkflowObservation"),
    # BACKEND ADVERTISES, FRONTEND DOES NOT BIND — 3, the safety lane's.
    # Registered to the mesh; no component will ever be chosen for them.
    (_SAFETY + "DeferralRiskCard", _MESH + "KnowledgeDocument"),
    (_SAFETY + "OrphanedHazardSet", _MESH + "ContributionRanking"),
    (_SAFETY + "RiskAssessmentDraft", _MESH + "KnowledgeDocument"),
}


def _mirrors() -> tuple[set, set]:
    """The two mirrors, both sides expanded. Skips where cortex-ui is not a sibling."""
    if not _CORTEX.is_file():
        pytest.skip("cortex-ui is not a sibling on disk; the cross-repo half cannot run here")

    from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES

    back = {
        (_expand(c["subject_uri"]), _expand(c["object_uri"]))
        for c in PRESENTATION_CAPABILITIES
    }
    front = {
        (_expand(s), _expand(o))
        for s, o in re.findall(
            r'subject_uri:\s*"([^"]+)",\s*\n\s*object_uri:\s*"([^"]+)"',
            _CORTEX.read_text(encoding="utf-8"),
        )
    }
    assert len(back) >= 20 and len(front) >= 30, (
        f"a mirror parsed to almost nothing (back={len(back)}, front={len(front)}); "
        f"a mirror check over an empty set agrees perfectly"
    )
    return back, front


def test_the_two_MIRRORS_agree_FLEET_WIDE():
    """RATIFIED 2026-09-15, and no longer scoped to `fin:`.

    **`PRESENTATION_CAPABILITIES` is the declaration the mesh advertises** — the presentation
    agent registers every row of it at lifespan through `register_presentation_to_mesh` — and
    cortex-ui's `DERIVED_BINDINGS` is the mirror. **Every row must appear in both, and a row in
    one only is a defect regardless of prefix.**

    ⚠ READ THIS BEFORE CONCLUDING `capabilities.py` IS RETIRED. `capability_registry.union_menu`
    carries a prominent note — *"WHY NOT `capabilities.py` … every row it held is now DERIVED on
    the UI side"* — which reads like the file is out of the live path. It is not. That note is
    about the **anonymous fallback MENU**, which reads the runtime registry instead of this
    table. Mesh registration is a different consumer and still reads it. Two consumers, one
    file, opposite conclusions if you stop at the first comment you find.

    ── WHAT THIS CATCHES, MEASURED ──────────────────────────────────────────────────────────
    `fin:EstimateAtCompletionComparison` was in the frontend mirror and not this one for four
    days: bound, drawable, contract and glyph in place, and **never advertised by the engine
    that produces it**. Each mirror was complete on its own side, so no per-repo check could
    see it. **A mirror check is the only instrument that sees a row present in one master and
    absent from the other.**
    """
    back, front = _mirrors()
    gaps = (front - back) | (back - front)
    new = sorted(gaps - _MIRROR_GAPS_AT_RATIFICATION)
    assert not new, (
        "these bindings are declared in ONE mirror only and are not in the ratification "
        "register:\n  "
        + "\n  ".join(f"{s} -> {o}" for s, o in new)
        + "\n\nA row the backend advertises and the frontend does not bind is registered with "
        "no component that will ever be chosen for it. A row the frontend binds and the "
        "backend does not advertise is drawable and unroutable. Add the missing side, or — if "
        "this is a deliberate staging step — add it to _MIRROR_GAPS_AT_RATIFICATION and route "
        "it, remembering the register only ever shrinks."
    )


def test_the_mirror_register_ONLY_SHRINKS():
    """THE RATCHET, and it is what makes the register a debt rather than a drawer.

    An entry that has stopped being a mismatch must be DELETED, not left standing. A register
    that keeps excusing rows nobody needs excused is how an exclusion list stops being read —
    the same shape as a tombstone for a row the seed no longer ships, which keeps deleting
    nothing while reading as deliberate.
    """
    back, front = _mirrors()
    gaps = (front - back) | (back - front)
    fixed = sorted(_MIRROR_GAPS_AT_RATIFICATION - gaps)
    assert not fixed, (
        "these are registered as known mirror gaps and are no longer gaps:\n  "
        + "\n  ".join(f"{s} -> {o}" for s, o in fixed)
        + "\n\nDelete them from _MIRROR_GAPS_AT_RATIFICATION in the commit that fixed them. "
        "The register only shrinks; an entry left behind reads as an open defect to everyone "
        "who checks the list instead of the mirrors."
    )


def test_the_mirror_check_can_actually_FAIL():
    """THE CONTROL. Two sets compared against a register that already contains every
    difference will pass no matter what the sets say, unless a difference outside the register
    can exist."""
    back, front = _mirrors()
    invented = ("http://invincible-agent/mesh#NoSuchSubject", "http://invincible-agent/mesh#X")
    assert invented not in _MIRROR_GAPS_AT_RATIFICATION
    gaps = ((front | {invented}) - back) | (back - (front | {invented}))
    assert gaps - _MIRROR_GAPS_AT_RATIFICATION, (
        "a one-sided binding outside the register does not surface; the seal above cannot fail"
    )

_CONTRACT_FILE = (_ROOT.parent / "cortex-ui" / "src" / "components" / "planning"
                  / "CompetingMeasures.contract.ts")


# -- SEAL 6 -- the field-name join, which is the half that renders blanks ----------------
#
# Binding an archetype is not the same as feeding it. `COMPETING_MEASURES`' passthrough was
# written the same day the archetype was, from the engine's summary keys — and the engine emits
# the low/high pair under TWO names, saying beside them that `lowest_eac` is a coined summary
# name with "no claim to stay". The allowlist kept the one the contract does NOT read.
#
# So the row could have been bound and the card would have drawn a blank high and low, with the
# engine's tests green (it emits the field), the contract's tests green (it declares it), and
# the projector's own shape test green (the tuple parses). **Every endpoint verified, the join
# asserted nowhere.**

#: Contract envelope fields this engine supplies PER ROW rather than on the envelope, with the
#: reason. Checked 2026-09-15: `scope_label` is on the rows of every finance verb and on the
#: envelope of none — the response assembler builds `value_unit`, `value_label`, `series`,
#: `reference` and `verdict` at envelope level and has never built this one.
#:
#: ⚠ WHAT THIS DOES NOT CLAIM: that a card reads it from the rows and is therefore fine. That is
#: unchecked. It is listed as a KNOWN DIVERGENCE with its scope, not as a resolved one — the
#: difference between a residue named and a residue excused.
_CONTRACT_FIELDS_SUPPLIED_PER_ROW = {
    "scope_label": (
        "on the rows of every finance verb, on the envelope of none; the assembler in "
        "finance_agent/main.py builds value_unit/value_label/series/reference/verdict at "
        "envelope level and never this one. Fleet-wide, not specific to this verb."
    ),
}


def test_every_field_the_COMPETING_MEASURES_contract_reads_ARRIVES():
    """CROSS-REPO, AND THE ONE THAT WOULD HAVE CAUGHT THE BLANK CARD.

    Reads the frontend contract's own envelope list — not a copy of it kept here, which would
    agree with itself — and checks each name against BOTH the projector's allowlist and a LIVE
    payload from the verb. A field must be emitted AND survive the passthrough; either alone
    renders nothing and looks correct from that side.
    """
    if not _CONTRACT_FILE.is_file():
        pytest.skip("cortex-ui is not a sibling on disk; the cross-repo half cannot run here")

    text = _CONTRACT_FILE.read_text(encoding="utf-8")
    block = text.split("COMPETING_MEASURES_ENVELOPE_FIELDS")[1].split("]")[0]
    declared = set(re.findall(r'"(\w+)",', block))
    assert len(declared) >= 8, (
        "parsed almost nothing from the contract — the export moved, and an empty expectation "
        "is satisfied by any payload at all"
    )

    from fastapi.testclient import TestClient

    from agent_fleet.finance_agent.main import app

    passthrough = set(_projector_passthrough()["COMPETING_MEASURES"][1])
    with TestClient(app) as client:
        payload = client.post(
            "/measure/fin_eac_comparison", json={"params": {"program_id": "NP-MERIDIAN"}}
        ).json()

    expected = declared - set(_CONTRACT_FIELDS_SUPPLIED_PER_ROW)

    dropped = sorted(expected - passthrough)
    assert not dropped, (
        f"the contract reads {dropped} and the projector's allowlist drops them — the card "
        f"draws blanks while the engine, the contract and the tuple's own shape test all pass"
    )
    unemitted = sorted(expected - set(payload))
    assert not unemitted, (
        f"the contract reads {unemitted} and the payload carries no such key — declared by the "
        f"consumer and emitted by nobody, which is what `reference_value` was until today"
    )

    # THE RESIDUE IS NOT A DRAWER EITHER. An entry for a field the contract stopped declaring
    # is a standing excuse for nothing, and one that starts arriving on the envelope should be
    # deleted from here rather than left reading as a known gap.
    for name, why in _CONTRACT_FIELDS_SUPPLIED_PER_ROW.items():
        assert name in declared, f"{name} is excused but the contract no longer declares it"
        assert name not in payload, (
            f"{name} now arrives on the envelope — delete its entry rather than leave a "
            f"resolved divergence reading as an open one"
        )
        assert len(why) > 40, f"{name} is excused without a usable reason"
