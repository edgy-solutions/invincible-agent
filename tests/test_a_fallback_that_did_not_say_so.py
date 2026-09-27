"""A generalist answer that reaches the wire without its disclosure.

RULED 2026-09-26. ADR-0008's routing is not in question here and this file asserts nothing about
it: when nothing in the registry matched, the generalist IS the honest answer. The defect is one
layer up — that answer arrived as a confident card indistinguishable from a specialist's, which
ADR-0008 already forbids in the same breath as it requires the fallback: the generalist *"should
say 'I am answering as a generalist because no registered tool matched your request' rather than
presenting as authoritative."*

── WHY THIS SEAL EXISTS, AND WHY MUTATION TESTING WOULD NOT HAVE FOUND IT ──────────────────────

Nothing was broken. `gateway.py:3500-3531` has emitted all three markers of that sentence since
Part 0 — `fallback: true`, a structured `fallback_reason`, `provider: engine_a_fallback` — and
every one of them was correct. NOTHING READ THEM. A field written by one side and read by none is
free to be wrong for as long as nobody looks, and no mutant of the producer would have reddened
anything, because there was no consumer to redden. Same shape as `abstained` before
[[engine_abstain]], and the same repair: one rule in `iagent_pure`, both sides calling it.

So the first arm here is not about a defect at all. It is the ANCHOR — the real projection, on a
real fallback materialization, asserted to disclose. Without it every arm below tests a fixture I
wrote against a predicate I wrote, and the pair could agree perfectly while pointing at nothing.

── THE POPULATION IS DERIVED FROM BOTH PRODUCERS, NOT FROM EITHER DOCSTRING ────────────────────

`fallback_reason` has TWO producers and the consumer sees the union. The supervisor's closed enum
passes through verbatim; when a pre-Part-0 materialization carries no structured reason, the
GATEWAY invents one from its own four-literal heuristic, two of which (`no_subject`,
`no_predicate_matched`) are in no supervisor enum. `REASONS` was first written from the supervisor
half alone and would have called a legacy-but-fully-disclosed answer *"reason outside the closed
enum"* — a false red, with the reader sent to the wrong file. The reach arms below parse both
source files and red when either grows a literal the module has not been told about.

The gateway docstring additionally names `low_confidence` and `"ADR-0019 Contract B"`. No path
emits either, and neither is in `REASONS`: a reach test is derived from what the shipping code is
forced to spell, never from prose about it. One arm below fires exactly that distinction.

Hermetic. Builds the Dagster materialization shape and calls the pure projection and the pure
judge. No cluster, no store, nothing written.

Run:  PYTHONPATH=src pytest tests/test_a_fallback_that_did_not_say_so.py -v
"""
from __future__ import annotations

import ast
import re
import sys
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iagent.gateway import _project_route_decision  # noqa: E402
from iagent_pure.generalist_fallback import (  # noqa: E402
    FALLBACK,
    FALLBACK_FIELD,
    GATEWAY_ONLY_REASONS,
    REASON_FIELD,
    REASONS,
    SUPERVISOR_REASONS,
    answered_by_generalist,
    discloses,
    missing_disclosure,
)
from iagent_pure.walk_census import (  # noqa: E402
    DISPOSITIONS,
    FAIL,
    PASS,
    CensusRow,
    judge,
)

_GATEWAY_SRC = _SRC / "iagent" / "gateway.py"
_SUPERVISOR_SRC = _SRC / "iagent" / "defs" / "dynamic_supervisor.py"


def _mat(**fields) -> dict:
    """A Dagster materialization from label→value, entry shape chosen by Python type.

    LIFTED FROM `tests/test_route_decision_projection.py`, whose own comment records the trap: bool
    is checked before int because bool IS an int subclass, and a `fallback` landing in `intValue`
    reads back as `1` — truthy, not `True`, and therefore invisible to precisely the `is True`
    check this file exists to defend.
    """
    entries = []
    for label, value in fields.items():
        if isinstance(value, bool):
            entries.append({"label": label, "boolValue": value})
        elif isinstance(value, float):
            entries.append({"label": label, "floatValue": value})
        elif isinstance(value, int):
            entries.append({"label": label, "intValue": value})
        else:
            entries.append({"label": label, "text": str(value)})
    return {"metadataEntries": entries}


def _fallback_mat(reason: str = "no_compatible_verbs", **over) -> dict:
    """A fallback as the supervisor actually captures one: subject ground, no verb, `no_match`.

    `route_status` IS `"no_match"` AND THAT IS NOT COSMETIC. The first draft of this fixture said
    `"fallback"`, a value no producer emits — `_call_engine_a_fallback` returns the literal
    `"no_match"` at dynamic_supervisor.py:1842 and the materialization's own contract comment lists
    the status vocabulary as `matched | no_match | infra_error`. The projection branches on
    `route_status == "matched" and handler_endpoint`, so an invented status lands in the fallback
    branch too and every arm below would have passed — against an input the fleet cannot produce,
    and blind to the `no_match` line the judge actually emits for a real one.
    """
    base = dict(
        route_status="no_match",
        subject_uri="http://iagent.local/ont#MaintenanceProgram",
        subject_confidence=0.91,
        verb_iri="UNKNOWN",
        classify_called=False,
        fallback_reason=reason,
    )
    base.update(over)
    return _mat(**base)


def _specialist_mat(**over) -> dict:
    base = dict(
        route_status="matched",
        subject_uri="http://iagent.local/ont#MaintenanceProgram",
        subject_confidence=0.94,
        verb_iri="http://iagent.local/ont#explainVariance",
        classify_called=True,
        handler_endpoint="http://iagent-engine-fin:8080",
        handler_provider="iagent-engine-fin",
    )
    base.update(over)
    return _mat(**base)


def _row(*dispositions: str) -> CensusRow:
    """A census row accepting exactly the given dispositions.

    Built through the dataclass rather than through the YAML loader, so a fixture cannot be
    rejected by the sheet's proper-subset guard — that guard is a different subject with its own
    seal, and routing these fixtures through it would make this file fail for its reasons.
    """
    return CensusRow(
        id="fixture-row",
        sheet="fixture",
        sheet_index=1,
        question="q",
        user="alice",
        persona="PROGRAM_FINANCE_ANALYST",
        domains=("FINANCE",),
        frontend_id="fixture-frontend",
        expect_verb=None,
        expect_archetype=None,
        min_rows=0,
        dispositions=tuple(dispositions),
    )


# ── THE ANCHOR: the real producer, on a real fallback, discloses ────────────────────────────────

def test_the_real_projection_discloses_its_fallback():
    """Not a defect arm. If this ever reds, every arm below is testing a fixture against a
    predicate with no production subject behind either."""
    decision = _project_route_decision(_fallback_mat())
    assert decision is not None
    assert answered_by_generalist(decision), (
        f"the gateway's own fallback branch does not identify as one: "
        f"{FALLBACK_FIELD}={decision.get(FALLBACK_FIELD)!r} "
        f"provider={(decision.get('handled_by') or {}).get('provider')!r}"
    )
    assert missing_disclosure(decision) == [], missing_disclosure(decision)


def test_the_real_projection_of_a_SPECIALIST_is_not_read_as_a_fallback():
    """The negative control, differing from the arm above in CONTENT, not shape: same projection,
    same function, same key set — a grounded verb instead of `UNKNOWN`. Identical behaviour from
    the two would indict the projection; only a difference here shows the predicate discriminates
    on what it claims to discriminate on."""
    decision = _project_route_decision(_specialist_mat())
    assert decision is not None
    assert not answered_by_generalist(decision)
    assert missing_disclosure(decision) == [], (
        "a specialist answer has no disclosure to make; reporting one as undisclosed is an "
        "over-strict arm whose symptom is a false red"
    )


@pytest.mark.parametrize("reason", REASONS)
def test_every_reason_the_wire_can_carry_survives_the_render_seam_disclosed(reason):
    """Each member of the closed enum, through the real projection, still disclosed. The enum's
    whole purpose is that the distinctions drawn upstream reach the reader; a member arriving
    undisclosed would be a distinction that reached nobody."""
    decision = _project_route_decision(_fallback_mat(reason=reason))
    assert decision[REASON_FIELD] == reason
    assert discloses(decision), missing_disclosure(decision)


# ── REACH: the module's population covers what the two producers can spell ──────────────────────

def test_the_gateways_own_heuristic_literals_are_all_in_the_wires_enum():
    """THE ARM THAT CAUGHT A FALSE RED IN THIS FILE'S OWN SUBJECT.

    The gateway's backward-compat branch invents a reason for materializations carrying no
    structured one. Its literals are parsed out of the source rather than listed here, so a fifth
    literal added there reds HERE — instead of being reported as "reason outside the enum" against
    a legacy row that disclosed perfectly.
    """
    src = _GATEWAY_SRC.read_text(encoding="utf-8")
    m = re.search(
        r"\n    structured_reason = md\.get\(\"fallback_reason\"\).*?\n    return \{", src, re.S
    )
    assert m, (
        "the gateway's fallback_reason heuristic could not be located — this arm is measuring "
        "nothing and must be repaired, not deleted"
    )
    block = textwrap.dedent(m.group(0).split("return {")[0]).strip()
    literals = {
        n.value
        for n in ast.walk(ast.parse(block))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    literals.discard("fallback_reason")  # the metadata KEY it reads, not a reason it emits
    literals.discard("UNKNOWN")  # the sentinel it compares subject/verb against
    # AND THE EMPTY STRING, which is the `or ""` default on the structured read — the marker for
    # "this materialization carried no reason" and the very condition that makes the heuristic run.
    # Excluded on a derived predicate, not by name: a reason has to be something a reader can read,
    # and `missing_disclosure` already reds on an empty one from the other side.
    literals = {lit for lit in literals if lit.strip()}
    assert len(literals) >= 4, (
        f"the heuristic yielded only {sorted(literals)} — the parse is under-reaching, and an "
        f"under-reaching population passes for the wrong reason"
    )
    missing = sorted(lit for lit in literals if lit not in REASONS)
    assert not missing, (
        f"gateway.py can put {missing} on the wire and generalist_fallback.REASONS does not list "
        f"it, so a fully disclosed answer would be reported as carrying an unknown reason"
    )
    assert set(GATEWAY_ONLY_REASONS) <= literals, (
        f"GATEWAY_ONLY_REASONS claims {sorted(GATEWAY_ONLY_REASONS)} come from this heuristic, but "
        f"it spells {sorted(literals)} — the comment has outlived the code it describes"
    )


#: THE THREE SPELLINGS THE SUPERVISOR IS FORCED TO USE, and the reason the arm below is a table.
#:
#: A single-pattern matcher over `fallback_reason` found four literals and MISSED four, because the
#: subject-resolution branches assign to a LOCAL (`_fb_reason`, `fb_reason`) and only then put it
#: under the key. Nothing warns you: a matcher that finds some literals returns a population that
#: looks like an answer. Each pattern is positive-controlled below — one that stops matching
#: anything reds on its own count rather than silently shrinking the union.
_REASON_PATTERNS = {
    "kwarg or dict key": r'fallback_reason(?:"\s*:|\s*=)\s*"([a-z_]+)"',
    "local fb_reason": r'\b_?fb_reason\s*=\s*"([a-z_]+)"',
    "engine-o passthrough gate": r'_ENGINE_O_ABSTENTION_REASONS = frozenset\(\{([^}]*)\}\)',
}


@pytest.mark.parametrize("label,pattern", sorted(_REASON_PATTERNS.items()))
def test_each_reason_spelling_still_matches_something(label, pattern):
    """THE POSITIVE CONTROL, one arm per pattern. Without it the union arm below keeps passing as
    each pattern quietly stops matching — a broken matcher's empty output reads as a clean finding,
    which is how the four missing literals got missed in the first place."""
    src = _SUPERVISOR_SRC.read_text(encoding="utf-8")
    assert re.findall(pattern, src), (
        f"the {label!r} matcher found nothing in dynamic_supervisor.py. Either the spelling moved "
        f"or the pattern rotted; a reason population derived from it is now smaller than the code's"
    )


def test_every_reason_the_supervisor_SPELLS_is_in_the_wires_enum():
    """The other producer, all three spellings, derived from source and never from the module
    docstring — which enumerates the subject-resolution branches only and would have left the most
    common fallback in the fleet, `no_predicate_matched`, out of the population."""
    src = _SUPERVISOR_SRC.read_text(encoding="utf-8")
    found: set[str] = set()
    for pattern in _REASON_PATTERNS.values():
        for hit in re.findall(pattern, src):
            # The frozenset pattern captures a block; the other two capture one literal each.
            found.update(re.findall(r'"([a-z_]+)"', hit) or ([hit] if hit.isidentifier() else []))
    assert len(found) >= 6, f"only {sorted(found)} found — the union is under-reaching"
    missing = sorted(f for f in found if f not in REASONS)
    assert not missing, (
        f"the supervisor spells {missing}, absent from generalist_fallback.REASONS — a disclosed "
        f"fallback would be reported as carrying an unrecognised reason"
    )


def test_the_two_reason_populations_are_disjoint():
    """They retire differently — `GATEWAY_ONLY_REASONS` empties out as pre-Part-0 materializations
    age out — and a literal in both would make that unmeasurable."""
    assert not (set(SUPERVISOR_REASONS) & set(GATEWAY_ONLY_REASONS))
    assert set(REASONS) == set(SUPERVISOR_REASONS) | set(GATEWAY_ONLY_REASONS)


def test_no_supervisor_path_spells_the_gateways_own_literal():
    """What makes `GATEWAY_ONLY_REASONS` true rather than a label. If the supervisor ever starts
    emitting `no_subject`, the constant's name is a lie and the retirement it is meant to measure
    stops being measurable."""
    src = _SUPERVISOR_SRC.read_text(encoding="utf-8")
    for reason in GATEWAY_ONLY_REASONS:
        assert f'"{reason}"' not in src, (
            f"{reason!r} is named GATEWAY_ONLY but dynamic_supervisor.py spells it"
        )


def test_a_reason_the_gateway_DOCSTRING_names_is_STILL_not_in_the_enum():
    """The negative control for the arms above, and the reason they parse code rather than prose.

    `_project_route_decision`'s docstring says `fallback_reason` carries `low_confidence` and
    `"ADR-0019 Contract B"`. It is RIGHT about the first — the reach arm above found
    `low_confidence` at dynamic_supervisor.py:2563 while this file's own docstring was asserting
    that nothing emits it — and wrong about the second, which no path spells. That is exactly why
    prose is not the source: it was half true, and the half that was true is the half I disbelieved.
    """
    assert not any("ADR-0019" in r for r in REASONS)
    assert "low_confidence" in REASONS  # found in CODE, not taken from the docstring


def test_a_fallbacks_route_status_is_never_matched():
    """THE ONE CASE THAT WOULD MAKE A FALLBACK INVISIBLE TO EVERY ARM IN THIS FILE.

    The projection reads `route_status == "matched" and handler_endpoint` as a specialist dispatch.
    The `low_confidence` fallback is reached from a predicate that DID match, so if its telemetry
    kept `matched` and an endpoint, the answer would project as a specialist — no `fallback` flag,
    no provider, nothing for this seal to read, and an undisclosed fallback that is undetectable
    rather than merely unreported.

    It does not, and this pins why: `_call_engine_a_fallback` overrides the status to the literal
    `no_match` on its way out, with its own comment saying a fallback must never outrank a match.
    Asserted against the source, because the property belongs to the producer.
    """
    src = _SUPERVISOR_SRC.read_text(encoding="utf-8")
    fn = src.split("def _call_engine_a_fallback(", 1)
    assert len(fn) == 2, "_call_engine_a_fallback not found — this arm measures nothing"
    body = fn[1].split("\ndef ", 1)[0]
    assert '"route_status": "no_match"' in body, (
        "the generalist fallback no longer forces route_status=no_match. A fallback whose "
        "materialization keeps `matched` plus a handler_endpoint projects as a SPECIALIST, and "
        "every disclosure arm in this file goes blind on it."
    )


# ── THE DEFECT: each marker dropped, one at a time ──────────────────────────────────────────────

def test_a_fallback_with_the_flag_dropped_still_counts_as_one_and_reds():
    """THE UNION, NOT THE INTERSECTION. Dropping `fallback` must not remove the answer from the
    population being guarded — a guard whose subject can be deleted by the same edit that breaks
    it defends nothing. It is still a generalist answer, by its provider, and it now fails."""
    d = _project_route_decision(_fallback_mat())
    d.pop(FALLBACK_FIELD)
    assert answered_by_generalist(d)
    assert not discloses(d)
    assert any(FALLBACK_FIELD in g for g in missing_disclosure(d)), missing_disclosure(d)


def test_a_fallback_with_the_provider_rewritten_still_counts_as_one_and_reds():
    """The mirror image: the other marker broken, the first one carrying the population."""
    d = _project_route_decision(_fallback_mat())
    d["handled_by"] = dict(d["handled_by"], provider="iagent-engine-fin")
    assert answered_by_generalist(d)
    assert any("provider" in g for g in missing_disclosure(d)), missing_disclosure(d)


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_a_fallback_with_no_reason_reds(bad):
    """`fallback: true` alone is a badge, not a sentence. ADR-0008 asks for *"because no registered
    tool matched"* — the because is this field."""
    d = _project_route_decision(_fallback_mat())
    d[REASON_FIELD] = bad
    assert any(REASON_FIELD in g for g in missing_disclosure(d)), missing_disclosure(d)


def test_a_reason_outside_the_wires_enum_is_REPORTED_and_still_a_disclosure():
    """Reported, not refused. The user WAS told it is a fallback and told why; what the value is
    not is something downstream can key on. Both halves are asserted, because collapsing them
    would make an unknown-but-honest reason indistinguishable from silence."""
    d = _project_route_decision(_fallback_mat())
    d[REASON_FIELD] = "vibes"
    gaps = missing_disclosure(d)
    assert len(gaps) == 1 and "vibes" in gaps[0], gaps
    assert answered_by_generalist(d)


@pytest.mark.parametrize("truthy", ["false", "true", 1, "1", [1]])
def test_a_TRUTHY_flag_is_not_a_True_flag(truthy):
    """The JSON crosses an SSE boundary and the string `"false"` is truthy. `1` is in the list
    because an int `fallback` would route through `intValue`; a reader using truthiness would call
    every one of these a disclosed fallback, including the one that says false."""
    d = _project_route_decision(_fallback_mat())
    d[FALLBACK_FIELD] = truthy
    assert any(FALLBACK_FIELD in g for g in missing_disclosure(d)), (
        f"{truthy!r} was accepted as {FALLBACK_FIELD}=True"
    )


@pytest.mark.parametrize(
    "junk", [None, "", 0, [], {"handled_by": None}, {"handled_by": "x"}, {"handled_by": {}}]
)
def test_junk_is_not_a_generalist_answer(junk):
    """A shape the reader has never seen must not be read as a fallback. A projection that failed
    to parse is an INSTRUMENT failure, and reporting it as an undisclosed fallback would file an
    instrument defect as a fleet defect."""
    assert not answered_by_generalist(junk)
    assert missing_disclosure(junk) == []


# ── THE CONSUMER: the walk census scores it, and reds on an undisclosed one ─────────────────────

def _result(decision: dict, components=(("KPI_GRID", {"rows": [{"a": 1}]}),)) -> dict:
    """An /orchestrate result carrying one route_decision event and a drawn card.

    The card MATTERS: a fallback that drew nothing scores `none`, and the disposition arms below
    would then pass for a reason that has nothing to do with the fallback.
    """
    return {
        "final": {"components": [{"archetype": a, "payload": p} for a, p in components]},
        "events": [{"event": "route_decision", "data": decision}],
    }


def test_the_census_scores_a_generalist_answer_FALLBACK_and_not_DRAWN():
    """The whole ruling in one arm. The generalist draws a card, so `drawn` was TRUE — true,
    passing, and silent about the answer having come from the maintenance ontology. Three of the
    four docs rows reported as passing on disposition exactly this way."""
    state, why = judge(_row("drawn"), _result(_project_route_decision(_fallback_mat())))
    assert state == FAIL
    assert any(f"disposition {FALLBACK!r}" in w for w in why), why
    assert not any("disposition 'drawn'" in w for w in why), why


def test_the_fallback_verdict_carries_the_REASON_with_it():
    """A verdict saying only `fallback` sends the reader to open the payload for the content of the
    finding. The reason IS the finding."""
    _, why = judge(
        _row("drawn"),
        _result(_project_route_decision(_fallback_mat(reason="domain_scope_excluded"))),
    )
    assert any("domain_scope_excluded" in w for w in why), why


def test_a_row_that_ACCEPTS_a_fallback_passes_when_the_fallback_disclosed():
    """The accepting side, fired. An arm that only exercises the refusal cannot distinguish a guard
    that discriminates from one that refuses everything — and this side is load-bearing: the docs
    rows are expected to land here once the empty pool is fixed."""
    state, why = judge(_row("drawn", FALLBACK), _result(_project_route_decision(_fallback_mat())))
    assert state == PASS, why


def test_a_row_that_ACCEPTS_a_fallback_still_reds_on_an_UNDISCLOSED_one():
    """NOT EXEMPTED, deliberately. A row that expects a fallback expects a DISCLOSED fallback.
    Exempting the expected case would blind the seal precisely where fallbacks live, which is a
    guard that cannot fire inside its own population."""
    d = _project_route_decision(_fallback_mat())
    d.pop(FALLBACK_FIELD)
    state, why = judge(_row("drawn", FALLBACK), _result(d))
    assert state == FAIL
    assert any(w.startswith("UNDISCLOSED FALLBACK") for w in why), why


def test_a_specialist_answer_is_scored_DRAWN_and_carries_no_fallback_line():
    """The control for the four arms above: same judge, same row, same card shape, differing only
    in what the routing says happened."""
    state, why = judge(_row("drawn"), _result(_project_route_decision(_specialist_mat())))
    assert state == PASS, why
    assert not any("FALLBACK" in w or "fell back" in w for w in why), why


def test_the_fallback_is_reported_ONCE_when_the_disposition_already_said_it():
    """Two lines for one fact is how the abstain arm was nearly built, and the comment beside it
    records why it was not. Checkable rather than asserted: the disposition line carries the
    reason, so a standalone `fell back:` line would be a second accusation for one fact."""
    _, why = judge(_row("drawn"), _result(_project_route_decision(_fallback_mat())))
    assert not any(w.startswith("fell back:") for w in why), why


def test_but_an_ABSTAIN_that_also_fell_back_still_reports_the_fallback():
    """The tail the arm above must not close. When another disposition wins, the `fell back:` line
    is the ONLY place the fallback and its reason appear at all — closed by CHANGING SUBJECT rather
    than by widening an assertion."""
    d = _project_route_decision(_fallback_mat(reason="instance_not_found"))
    result = _result(d, components=(("ELICITATION", {}),))
    result["final"]["components"][0]["disposition"] = "ask"
    _, why = judge(_row("slot_required"), result)
    assert any("fell back: instance_not_found" in w for w in why), why


def test_FALLBACK_is_a_member_of_the_census_vocabulary():
    """Without this the sheet's loader rejects `fallback` in a row's `dispositions`, and the
    accepting arm above could never be expressed in a real sheet."""
    assert FALLBACK in DISPOSITIONS
    assert FALLBACK == "fallback"
