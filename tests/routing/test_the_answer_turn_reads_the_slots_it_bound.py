"""The answer-after-a-pick turn reads the slots it bound — not the ask's empty subject.

WHAT WAS MEASURED, 2026-09-14, on the empty `finProgramBrief` card (artifact-2-1789404372153).
The user asked a set-shaped question, got a menu, and picked `NP-MERIDIAN`. The answer turn's
route came from `_pre_resolved_from_ask`, which copies `subject_instance_id` out of **the ask
artifact's** `resolved_intent` — and the ask is by construction the turn where no instance was
named, so that field is necessarily empty there. It rode forward onto the turn that finally
supplied one.

The picked value was never lost. It landed in the chain's bound slots as
`accepted_slots: {"program_id": "NP-MERIDIAN"}`, where nothing promoted it. So `not
subject_instance_id` reported SET on the exact turn that named the instance, the arity gate
flagged the verb `needs_instance`, and the dispatch **abstained FOR THE REASON THE ASK HAD JUST
BEEN ANSWERED.** `invincible-agent-22`'s finding; it is every engine's, not graph-host's.

**THE SET TRAVELS, NOT A LIST OF NAMES.** The ask turn's payload already failed to carry
something the answer turn needed; adding a bare `bound_slot_names` list would be a second thing
of exactly that shape, and the two turns would still not share a payload. The gateway forwards
the provenance-keyed union `_accumulated_slots` walks out of the lineage, and the site DERIVES
the names from it — so the ask turn and the answer turn finally have one payload shape.

**THE GATE COMES FREE BY CONSTRUCTION, AND THAT IS WHAT MAKES THIS SAFE TO SHIP.**
`turn_is_set_shaped` reads the verb's OWN declaration: a slot that is both `required` and a
`referent` is simultaneously the slot that FORCES `arity: single` (see
`GraphManifest._arity_agrees_with_slots`) and the slot whose binding supplies the instance. So a
verb declaring no such slot is unaffected — not by a branch someone could later simplify away,
but because the predicate's own body cannot reach a different answer for it.

That property is load-bearing rather than decorative. **Three engines of four never pass `arity`
at registration**, and `subject_instance_id` reaches the generalist fallback as
`resolved_instance_id`, after which Engine A does NOT re-resolve. An ungated promotion would have
changed Engine A's behaviour on every cost, finance and safety verb as a side effect of repairing
graph-host.

SCOPE IS THE PRE-RESOLVED SITE ONLY, DELIBERATELY. The other arity call site runs where the
classifier has just resolved the subject itself; it has no chain to read and no ask to answer.
Wiring it too would add a branch that can never differ from its input — **and a dead branch under
a seal reads as coverage.**

Run: uv run --frozen pytest tests/routing/test_the_answer_turn_reads_the_slots_it_bound.py -v
"""
from __future__ import annotations

from pathlib import Path

from iagent_pure.verb_eligibility import turn_is_set_shaped

_REPO = Path(__file__).resolve().parents[2]
_SUP = _REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py"
_GW = _REPO / "src" / "iagent" / "gateway.py"


def _slot(name: str, *, required: bool, referent: str | None) -> dict:
    d: dict = {"name": name, "required": required}
    if referent:
        d["referent"] = referent
    return d


_SINGLE = {
    "verb_iri": "fin:finProgramBrief",
    "arity": "single",
    "slots": [_slot("program_id", required=True, referent="fin:Program")],
}
#: A verb with NO required referent slot — the three-of-four case, and the generalist's.
_NO_REFERENT = {
    "verb_iri": "cost:summariseSpend",
    "slots": [_slot("period", required=True, referent=None)],
}


# ── THE PREDICATE ───────────────────────────────────────────────────────────────────────────

def test_THE_DEFECT_a_bound_referent_means_the_turn_is_NOT_set_shaped():
    """The measured failure, stated as the predicate that now refuses it."""
    assert turn_is_set_shaped("", _SINGLE, {"program_id"}) is False, (
        "the pick bound `program_id` and the turn still reports SET — the arity gate will flag "
        "`needs_instance` and the dispatch abstains for the reason the ask was just answered"
    )


def test_THE_CONTROL_an_unanswered_ask_IS_still_set_shaped():
    """Without this, a predicate that returned False unconditionally would satisfy the seal
    above while destroying the gate — trading a wrong abstention for a silent dispatch, which
    is the worse trade and the one `filter_verbs_by_arity` exists to prevent."""
    assert turn_is_set_shaped("", _SINGLE, set()) is True
    assert turn_is_set_shaped("", _SINGLE, None) is True, (
        "unknown bound slots must mean `nothing known to be bound`, never `assume an instance`"
    )


def test_THE_GATE_IS_FREE_a_verb_with_no_required_referent_is_unaffected():
    """THE PROPERTY THE ROLLOUT LEANS ON, asserted rather than assumed.

    Three engines of four declare no arity, and Engine A reads `subject_instance_id` without
    re-resolving. If this were false, repairing graph-host would silently change routing for
    every cost, finance and safety verb.
    """
    for bound in (set(), {"period"}, {"period", "program_id"}, None):
        assert turn_is_set_shaped("", _NO_REFERENT, bound) is True, (
            f"a verb with no required referent slot changed answer on bound={bound} — the gate "
            f"is NOT free by construction and the blast radius is every engine"
        )


def test_AN_OPTIONAL_REFERENT_DOES_NOT_PROMOTE():
    """`required` AND `referent` is the conjunction that forces `arity: single`. A slot with
    only one of the two is a different thing, and reading it here would be the sniffed link
    this predicate was written to avoid."""
    optional_ref = {"verb_iri": "x:v", "slots": [_slot("p", required=False, referent="x:C")]}
    assert turn_is_set_shaped("", optional_ref, {"p"}) is True


def test_A_RESOLVED_SUBJECT_SHORT_CIRCUITS():
    """When the subject field itself carries an instance there is nothing to promote."""
    assert turn_is_set_shaped("NP-MERIDIAN", _SINGLE, set()) is False


# ── THE WIRING, WHICH IS THE HALF A PREDICATE TEST CANNOT SEE ───────────────────────────────
#
# Every assertion above passes against a correct predicate that NOTHING CALLS. That is the
# shape this repo keeps meeting: registered is not participating.

def _src(p: Path) -> str:
    """Executable lines only. The comments here quote the defect verbatim to explain it, and a
    check matching a STRING cannot tell code from the commentary about code — this seal's own
    subject and instrument share a surface."""
    return "\n".join(
        ln for ln in p.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_THE_GATEWAY_CARRIES_THE_SET_not_a_list_of_names():
    """The contract change: `pre_resolved` carries the accumulated slot set."""
    src = _src(_GW)
    assert '_pre_resolved["accumulated_slots"] = _chain_slots' in src, (
        "the gateway does not forward the chain's accumulated slots onto the pre-resolved "
        "route, so the site below has nothing to derive names from and the promotion is inert"
    )


def test_THE_SITE_DERIVES_THE_NAMES_FROM_THE_CARRIED_SET():
    src = _src(_SUP)
    assert 'pre_resolved.get("accumulated_slots")' in src, (
        "the pre-resolved site does not read the carried set"
    )
    assert "turn_is_set_shaped(_pre_instance, _cv, _pre_bound)" in src, (
        "the site does not consult the per-verb predicate — the promotion is wired nowhere"
    )


def test_THE_OLD_BOOLEAN_IS_GONE_FROM_THE_PRE_RESOLVED_SITE():
    """`not _pre_instance` is the read that was wrong. Leaving it beside the new call would be
    two gates disagreeing, with the stricter one winning silently."""
    src = _src(_SUP)
    # ⛔ THIS MATCHED `not _pre_instance` BARE AND WENT RED AGAINST CORRECT CODE. The promotion
    # added `if not _pre_instance:` — a guard that is right, reads the same field, and is not
    # the gate at all. The assertion was written against a STRING and could not tell the gate's
    # ARGUMENT from an unrelated correct use of the same expression.
    #
    # Third time this shape has bitten in this file's lineage, so the fix is to anchor on what
    # makes it the gate: the trailing comma that marks it as `filter_verbs_by_arity`'s second
    # POSITIONAL ARGUMENT. `if not _pre_instance:` ends in a colon and cannot match.
    assert "not _pre_instance," not in src, (
        "the pre-resolved site still passes the ask's empty subject as the query shape — the "
        "gate's second argument is the bare boolean again"
    )


def test_THE_OTHER_CALL_SITE_IS_DELIBERATELY_UNCHANGED():
    """SCOPE, asserted so a later reader does not 'finish the job' into a dead branch.

    The classifier-path site resolves the subject itself and has no chain to read. A
    `turn_is_set_shaped` call there could never differ from `not subject_instance_id`.
    """
    src = _src(_SUP)
    assert "query_is_set = not subject_instance_id" in src, (
        "the classifier-path arity gate was changed too. It has no accumulated slots to read, "
        "so the call cannot differ from its input — and a dead branch under a seal reads as "
        "coverage. If this is intentional, the ruling has to say so."
    )
    assert src.count("turn_is_set_shaped(") == 1, (
        "turn_is_set_shaped is called from more than the pre-resolved site"
    )


# ── THE FLAG/EXCLUDE SPLIT, WHICH SHIPS IN THE SAME CHANGE ──────────────────────────────────

def test_FLAGGED_IS_NOT_EXCLUDED_at_the_consumer():
    """`eligibility_excluded` carries entries the gate KEPT. One list cannot say both, and the
    name says the opposite of what a `disposal: flagged` entry means."""
    src = _src(_GW)
    assert 'r.get("disposal") == "flagged"' in src, (
        "the gateway still reads one list for two dispositions — a live candidate renders "
        "under a key whose name says it was deleted"
    )
    assert '"flags": flags,' in src, "the split half is computed and never surfaced"


def test_THE_NARROWING_LANDED_AND_ONE_PARTITION_DECIDES_BOTH_HALVES():
    """The additive window is CLOSED, and this replaces the assertion that held it open.

    `test_THE_SPLIT_IS_ADDITIVE_UNTIL_THE_CONSUMER_READS_IT` lived here and named itself as
    the thing to delete when the consumer caught up. It was deleted by the commit that
    narrowed `excluded`, which is the expiry working as designed rather than a test being
    dropped — R-055's temporary state that could say it was temporary.

    THE GATE FOR DELETING IT WAS THE SERVING SURFACE, NOT `main`. cortex-ui `e1f9722` was
    verified in the pod (`version.json`, plus the rendered wording, with a positive control
    on the grep) before this landed. Merged-not-deployed is the same window one repo over,
    and it fails the same way with both suites green — R-055.1.

    WHAT IS ASSERTED NOW is the shape the consumer asked for and that is stronger than what
    the dispatch specified: ONE partition decides both halves. Two independent comprehensions
    would let a row that is neither `flagged` nor recognised land in both or in neither, and
    a `flagged` half computed as "everything not removed" absorbs any THIRD disposal the gate
    ever adds and renders it as a live candidate — a claim about a decision, made from not
    recognising a word.
    """
    src = _src(_GW)
    assert "flags, excluded = [], []" in src, (
        "the two halves are no longer computed from one partition — a row that is neither "
        "flagged nor recognised can now land in both or in neither"
    )
    assert "excluded = [r for r in excluded if not" not in src, (
        "the narrowing was re-implemented as a filter over the whole list, which is the "
        "derived-from-absence shape the partition exists to prevent"
    )
    assert '_raw_excluded' in src, (
        "the parsed payload and the narrowed half share a name again, so the partition reads "
        "its own output"
    )


def test_AN_ABSENT_DISPOSAL_READS_AS_REMOVED():
    """Deliberate, on this ruling's own trade. Every row predating the field meant removed,
    and a mislabel is visible where a disappearance is not — so the UNRECOGNISED case must
    fall to `excluded`, never to `flags`.

    Asserted on the branch rather than on data because this handler needs a live request, an
    authenticated user and a resolved projection row; what is checkable here is that the
    positive test is on `flagged` and the fallback is the other arm.
    """
    src = _src(_GW)
    assert 'if isinstance(_r, dict) and _r.get("disposal") == "flagged":' in src, (
        "the partition no longer tests POSITIVELY for `flagged` — if it tests for `removed` "
        "instead, an unrecognised third disposal renders as a live candidate"
    )


def test_THE_STALE_COMMENT_IS_GONE():
    """The gate stopped removing on 2026-09-04 and the comment above it still said `Remove`.
    A stale claim is pre-authenticated: true when written, read as true now.

    Asserted against the RAW text, not the stripped source, because the subject IS a comment —
    the one place where stripping comments would make the seal quantify over nothing.
    """
    raw = _SUP.read_text(encoding="utf-8")
    assert "so a set-query can never resolve to a single-asset verb" not in raw, (
        "the arity gate's comment still describes removal, directly above code that flags "
        "and keeps"
    )
