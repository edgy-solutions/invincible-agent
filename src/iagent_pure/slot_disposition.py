"""`route | ask | abstain` — the third behavior, decided from data already in hand.

ADR-0033, Accepted 2026-08-29 (woken by REACHABILITY, not frequency). Between "confident
enough to route" and "abstain with an honest card" sits **ask**, and this module is the
decision. It runs at one line in `execute_subtask` — immediately after `accept_slots`,
which is the only place in the system where the phrase, the routed verb, the verb's
declarations and the accepted slots are all simultaneously in hand.

THE TRIGGER IS DETERMINISTIC AND MODEL-FREE, AND THE ALTERNATIVE IS CLOSED ON EVIDENCE.
A slot declared `spoken-mandatory` that is absent after filling asks. Not a confidence
threshold: the 48-case corpus measured correct fills bottoming at 0.93, wrong fills
reaching 0.96, the one genuine miss at 0.96, and four CORRECT empties at 0.00. No
threshold separates them in either direction, and the reason is structural —
**confidence reports certainty about the values the model DID produce, never whether it
produced everything the question named.** It cannot flag an omission, and an omission is
exactly what `ask` detects. See docs/measurements/slot-fill-accuracy-v1.md.

PLUS THE TRI-STATE, because a presence test cannot see an unresolvable value. Fix (1)
made `/fill_slots` report resolution per slot and REMOVE an unresolved referent from
`slots` rather than passing the spoken name through. Without that, `E05` ("the ERP
Modernization project" → an Initiative, against a slot declaring Project) would arrive
with `project_id` present-and-wrong, dispatch, and 422. Here it arrives ABSENT, with the
candidate reported.

AND THE CANDIDATE IS NOT A MENU, which is the one place the obvious reading of the
tri-state is wrong. `wrong_class` is by definition a candidate whose class is not the
slot's referent, so the class filter that makes menu integrity hold removes exactly the
candidate that was kept: offering `I1` for `project_id` would 422 with the user's own
click behind it. **A retained cross-class candidate is EVIDENCE, not an OPTION** — it
becomes context in the ask's text ("I found 'ERP Modernization', which is not that kind
of thing") and the menu comes from the option ladder instead.

THE GUARDRAIL IS THE HALF THAT KEEPS THIS FROM BECOMING CLIPPY. ADR-0033 #4:
*"a system that asks when it knows is worse than one that guesses when it doesn't."*
Measured against run 5, the residue is three MISSED and **this trigger fires on exactly
one of them**:

    E05  misses project_id       spoken-MANDATORY  -> ASK
    E04  misses direction        spoken-optional   -> ROUTE, a default IS the answer
    C04  misses site_id, window  spoken-optional   -> ROUTE, and it is the flaky case

Both declines are genuine misses of information the user actually supplied, and both must
still route. A feature that catches all the residue has the wrong trigger. Optional slots
are unreachable from this module by construction — the loop only walks mandatory ones —
so the guardrail is a property of the code rather than a number someone tuned.

ONE ASK PER DISPATCH. ADR-0033 #3 bounds the exchange at one turn, and the census makes
that free today: the maximum spoken-mandatory slots on any one verb is **1**. A tripwire
test asserts that maximum, so the day a verb declares two the held-promise question
re-opens by failing rather than by someone remembering.

PURE AND DEPENDENCY-FREE, same posture and for the same reason as `slot_acceptance`: it is
imported by the Dagster supervisor, by tests, and (eventually) by the BFF, and none of
those should have to stand up the others. The enumeration provider is INJECTED as a
callable rather than imported, so this module never learns an engine's URL.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Mapping, NamedTuple, Sequence

from iagent_pure.slot_acceptance import decode_declarations

#: THE MENU BOUND — a HUMAN-ATTENTION bound: the number of options a person can choose from
#: in one turn. That makes it a fact about readers, so it must be the SAME number wherever a
#: menu is built. Read from the same env var Engine P's enumerator reads rather than
#: restated here — one bound, single-sourced by environment.
#:
#: **CORRECTED 2026-08-30: ruled at 8 on 2026-08-29, corrected to 10.** The original ruling
#: contradicted its own worked example (*"nine capabilities is a menu"*), and the
#: contradiction cost `capability_id` — the most-asked slot in the corpus — its menu. The
#: wrong number is recorded rather than renumbered away; see
#: `agent_fleet/planning_agent/main.py`'s `_MENU_BOUND` for the full note and
#: `docs/measurements/enumerate-probe-2026-08-30.md` for the measurement that decided it.
#:
#: THE DEFAULTS MUST AGREE. This one and the provider's are two defaults over one env var,
#: and if they diverge the disposition and the provider disagree about what a menu IS —
#: pinned by `test_the_menu_bound_default_agrees_with_the_providers`.
MENU_BOUND = int(os.getenv("ENUMERATE_MENU_BOUND", "10"))

#: Resolution outcomes that mean "the phone book had something, and it was not conclusive."
#: These carry candidates, so they are DISAMBIGUATION — ADR-0033 #2's ORIGINAL option source
#: (the top-k from `resolveInstance`), not the amendment's fourth one.
ASK_WITH_CANDIDATES = frozenset({"fuzzy", "mixed", "not_specific", "wrong_class"})

#: The one outcome that does NOT ask. `empty` means the providers answered cleanly and there
#: is no such thing — offering a menu here would be offering an empty menu, which fails
#: ADR-0033 #2's menu-integrity rule. `instance_resolution.decide()` already split `empty`
#: out of `not_specific` precisely so this distinction could be made; this is the consumer
#: that needed it.
ABSTAIN_OUTCOMES = frozenset({"empty"})

#: The outcome recorded for a slot the user PICKED from a menu, as opposed to one the
#: filler resolved from the phrase. A third provenance, and it needs its own name: a
#: pick was neither spoken-and-narrowed nor refused, and calling it "resolved" would
#: claim the resolver did work it did not do.
BOUND = "bound"

ROUTE = "route"
ASK = "ask"
ABSTAIN = "abstain"

#: THE OUTPUT CLASS OF AN ASK, and the reason a status was not enough.
#:
#: The presentation agent selects an archetype from the response's SUBJECT, and until this
#: existed `slot_disposition` set a status and no output type — so an ask had no subject, the
#: agent could not select for it, and the card landed on `KNOWLEDGE_DOCUMENT`. A status is a
#: string a consumer may recognise; a class is a thing the mesh knows about.
#:
#: Declared `rdfs:subClassOf mesh:Response` in `setup/ontologies/mesh_system.ttl`, which also
#: keeps it OUT OF THE GROUNDING POOL for free — response shapes are not subjects anyone asks
#: about, and `[[response-classes-compete-for-grounding]]` is the measured cost of letting them
#: compete.
SLOT_ELICITATION_URI = "http://invincible-agent/mesh#SlotElicitation"

#: ⛔ ONE STATUS FOR TWO DISPOSITIONS WAS A DEFECT, found by the cortex walk 2026-09-03.
#:
#: `ask_card` emitted `status: "slot_elicitation"` for BOTH `ask` and `abstain`, so a surface
#: switching on status draws an options field on an abstain — which says *nothing was run and
#: there is nothing to choose from*. The seal that was supposed to catch it asserted "never
#: renders on a non-ask status" and would have PASSED while the defect shipped, because the
#: status it named does not discriminate the case it meant.
#:
#: Two statuses, so a consumer switching on EITHER `status` or `disposition` is correct. The
#: card's own fix is to read `disposition`; this is the producer's half, and it is the half
#: that makes the wrong lever unavailable rather than merely discouraged.
STATUS_BY_DISPOSITION = {ASK: "slot_elicitation", ABSTAIN: "slot_abstain"}

#: Where an ask's options came from. `none` is permitted ONLY with a reason (see
#: `free_text_reason` below) — a menuless ask that cannot say why is the open question
#: ADR-0033 retired, wearing a slot's name.
SRC_RESOLUTION = "resolution"
SRC_DECLARATION = "declaration"
SRC_ENUMERATION = "enumeration"
SRC_NONE = "none"

#: Why an ask has no menu. THE CLOSED SET IS THE POINT. ADR-0033 permits free text only
#: where the substrate genuinely cannot enumerate — "never as a default, never as a
#: convenience, and never because enumeration was not attempted." Two of these are the
#: provider's own report; the third names the gap honestly and is the one that must
#: disappear as providers register.
FT_TOO_MANY = "too_many"        # provider: the class is real and larger than a menu
FT_UNSUPPORTED = "unsupported"  # provider: I do not enumerate this class
FT_NO_PROVIDER = "no_provider"  # nobody was asked — the gap, named rather than hidden
FT_NO_REFERENT = "no_referent"  # the slot names a literal, not a referent; nothing to list
FREE_TEXT_REASONS = frozenset({FT_TOO_MANY, FT_UNSUPPORTED, FT_NO_PROVIDER, FT_NO_REFERENT})


class Option(NamedTuple):
    """One entry on the menu. MENU INTEGRITY (ADR-0033 #2, ADR-0032 verbatim): every
    offered option must route successfully when chosen, which is why `value` is always the
    thing the verb takes — an id or a declared literal — and never a display string."""
    value: str
    label: str


class Disposition(NamedTuple):
    action: str                      # route | ask | abstain
    slot: str | None = None          # the slot being asked about
    reason: str = ""                 # slot-unfilled | the resolution outcome | empty
    options: tuple[Option, ...] = ()
    option_source: str = ""          # resolution | declaration | enumeration | none
    free_text_reason: str | None = None
    spoken: str = ""                 # what the user said for this slot, when they said it
    truncated_from: int = 0          # candidates before the menu bound, 0 if untruncated
    total_count: int = 0             # how many EXIST, when a provider counted them
    detail: str = ""                 # provider colour for the honest fallback text
    found: str = ""                  # a cross-class candidate: what WAS found, as context

    @property
    def is_ask(self) -> bool:
        return self.action == ASK


def _mandatory(declared: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [d for d in declared if d.get("kind") == "spoken-mandatory"]


def _from_candidates(
    cands: Sequence[Mapping[str, Any]],
    *,
    referent: str,
    menu_bound: int,
) -> tuple[tuple[Option, ...], int]:
    """Candidates → a bounded menu.

    FILTERED BY THE SLOT'S OWN `referent`, which is what makes `E05` answerable rather than
    merely detected: "the ERP Modernization project" resolved to `I1`, an Initiative, on a
    slot declaring `#Project`. Offering `I1` for `project_id` would break menu integrity —
    the option would not route. A candidate of the wrong class is evidence the user was
    understood, not an option they can pick.

    TRUNCATION IS LEGITIMATE HERE AND NOWHERE ELSE. Resolver candidates are SCORED and
    arrive ranked, so top-k is ADR-0033 #2's own phrase ("the top-k from resolveInstance").
    Enumeration returns members with no ranking, and truncating those would invent a rank —
    which is why the enumerator answers `too_many` instead of sending its first eight.
    """
    if referent:
        cands = [c for c in cands if not c.get("class_uri") or c.get("class_uri") == referent]
    # DEDUPED BY VALUE, FIRST OCCURRENCE WINS — found by the elicitation corpus, run 1.
    # `"what does the Module Build depend on"` came back `mixed` with candidates
    # [P3, P4, P3] and the menu offered P3 TWICE. Every option routed, so menu integrity
    # in its narrow reading held — and a person reading "Finance Module Build" twice is
    # looking at a broken menu. The resolver may legitimately return one instance more
    # than once (several providers, or one provider matching on two fields); making the
    # MENU unique is the consumer's job, not the phone book's.
    #
    # First occurrence wins because candidates arrive RANKED — dropping the earlier copy
    # would silently demote a candidate the resolver scored higher.
    seen: set[str] = set()
    opts_list: list[Option] = []
    for c in cands:
        value = str(c.get("instance_id") or "")
        if not value or value in seen:
            continue
        seen.add(value)
        opts_list.append(Option(value, str(c.get("label") or value)))
    opts = tuple(opts_list)
    if len(opts) > menu_bound:
        return opts[:menu_bound], len(opts)
    return opts, 0


def decide_disposition(
    *,
    accepted: Mapping[str, Any] | None,
    declared: Any,
    resolution: Mapping[str, Any] | None = None,
    enumerate_class: Callable[[str], Mapping[str, Any]] | None = None,
    menu_bound: int = MENU_BOUND,
) -> Disposition:
    """`route | ask | abstain`, from the declarations and the fill's own report.

    `accepted`  — what survived `accept_slots`, i.e. what will actually reach the verb.
    `declared`  — the verb's `mesh_slots`, raw or decoded (JSON string tolerated).
    `resolution`— `/fill_slots`' per-slot report: `{slot: {outcome, spoken, candidates}}`.
    `enumerate_class` — injected `class_uri -> {outcome, members, count}`; None means no
                  provider is reachable, which is reported as `no_provider` and never as
                  silence.

    FAIL SAFE TOWARD `route`. Every unreadable input degrades to routing, which is exactly
    the pre-ask behaviour: the verb runs and either answers or refuses on its own terms.
    An `ask` interrupts a flow that currently completes, so a bug in THIS module must not
    be able to invent an interruption — the same trade `_fill_slots_from_query` makes when
    it returns honest-empty on every failure.
    """
    accepted = dict(accepted or {})
    resolution = dict(resolution or {})
    try:
        decls = decode_declarations(declared)
    except Exception:  # noqa: BLE001 — see FAIL SAFE above
        return Disposition(ROUTE)

    for decl in _mandatory(decls):
        name = str(decl.get("name") or "")
        if not name or name in accepted:
            continue

        res = resolution.get(name) or {}
        outcome = str(res.get("outcome") or "")
        found = ""  # a cross-class candidate's label, set below when one was dropped
        spoken = str(res.get("spoken") or "")
        referent = str(decl.get("referent") or "")

        # ---- ABSTAIN. The phone book answered and there is no such thing. ------------
        if outcome in ABSTAIN_OUTCOMES:
            return Disposition(
                ABSTAIN, slot=name, reason=outcome, spoken=spoken,
                detail=f"nothing in the model matches {spoken!r}" if spoken else "",
            )

        # ---- ASK, disambiguation. A name WAS spoken and candidates exist. ------------
        if outcome in ASK_WITH_CANDIDATES:
            opts, truncated = _from_candidates(
                res.get("candidates") or [], referent=referent, menu_bound=menu_bound,
            )
            if opts:
                return Disposition(
                    ASK, slot=name, reason=outcome, options=opts,
                    option_source=SRC_RESOLUTION, spoken=spoken, truncated_from=truncated,
                )
            # ── A RETAINED CROSS-CLASS CANDIDATE IS EVIDENCE, NOT AN OPTION ────────────
            #
            # This branch is `wrong_class`'s home, and it is the one place where the
            # obvious reading of the tri-state is wrong. `/fill_slots` synthesises a
            # candidate from the winner so that "every non-empty outcome carries at least
            # the candidate it found" — but `wrong_class` is BY DEFINITION a candidate
            # whose class is not the slot's referent, so the class filter above removes
            # exactly the candidate that was kept. **A `wrong_class` outcome can never
            # supply a menu for its own slot.**
            #
            # Offering it anyway would break ADR-0033 #2's menu-integrity rule at the one
            # point it matters most: `project_id="I1"` is an Initiative, the verb takes a
            # Project, and the pick 422s — the same 422 the whole tri-state exists to
            # prevent, now with the user's own click behind it.
            #
            # So the candidate becomes CONTEXT in the message ("I found X, but that is an
            # initiative") and the ask falls through to the option ladder for a real menu.
            # The user was understood; they named the wrong kind of thing.
            cross = [
                str(c.get("label") or c.get("instance_id"))
                for c in (res.get("candidates") or [])
                if c.get("instance_id")
            ]
            if cross:
                found = cross[0]

        # ---- ASK, elicitation. Nothing usable was resolved; build a menu. ------------
        reason = outcome or "slot-unfilled"

        values = decl.get("values")
        if values:
            # FREE — the declaration's own vocabulary, read out of the `Literal` (or
            # attached at registration for data-dependent ones like fiscal periods).
            return Disposition(
                ASK, slot=name, reason=reason, spoken=spoken, found=found,
                options=tuple(Option(str(v), str(v)) for v in values),
                option_source=SRC_DECLARATION,
            )

        if not referent:
            # A literal the speaker supplies, with no closed vocabulary anywhere. There is
            # nothing to enumerate; free text is correct, and it says so.
            return Disposition(
                ASK, slot=name, reason=reason, spoken=spoken, found=found,
                option_source=SRC_NONE, free_text_reason=FT_NO_REFERENT,
            )

        if enumerate_class is None:
            return Disposition(
                ASK, slot=name, reason=reason, spoken=spoken,
                option_source=SRC_NONE, free_text_reason=FT_NO_PROVIDER,
                found=found, detail="no enumeration provider was reachable",
            )

        try:
            enumerated = dict(enumerate_class(referent) or {})
        except Exception as exc:  # noqa: BLE001 — an unreachable provider is not a menu
            return Disposition(
                ASK, slot=name, reason=reason, spoken=spoken,
                option_source=SRC_NONE, free_text_reason=FT_NO_PROVIDER,
                detail=f"{type(exc).__name__}",
            )

        eout = str(enumerated.get("outcome") or "")
        if eout == "members":
            members = enumerated.get("members") or []
            opts = tuple(
                Option(str(m.get("instance_id") or ""), str(m.get("label") or ""))
                for m in members
                if m.get("instance_id")
            )
            if opts:
                return Disposition(
                    ASK, slot=name, reason=reason, spoken=spoken, found=found,
                    options=opts, option_source=SRC_ENUMERATION,
                )
            # `members: []` is a real answer and an empty menu is not a menu. The class is
            # enumerable and holds nothing, which is closer to `empty` than to a question.
            return Disposition(
                ABSTAIN, slot=name, reason="no_members", spoken=spoken,
                detail=f"nothing of that kind exists yet",
            )

        if eout == "too_many":
            # THE BOUNDARY WORKING AS DESIGNED, not a gap. The provider reports that the
            # class is real and larger than a menu, so free text is LEGITIMATE here — this
            # is the condition ADR-0033's clause actually names, as opposed to "nobody
            # built the capability."
            # THE COUNT IS CONTENT, NOT COLOUR. It reached the card only inside `message`
            # prose, so a surface wanting to say "14 projects" had to parse an English
            # sentence — presence-is-not-content in a field. `truncated_from` did not cover
            # it either: that counts what was CUT, and `too_many` cuts nothing because the
            # provider returns no members at all. Two different numbers, and the one a
            # reader wants was the missing one.
            count = enumerated.get("count") or 0
            return Disposition(
                ASK, slot=name, reason=reason, spoken=spoken, found=found,
                option_source=SRC_NONE, free_text_reason=FT_TOO_MANY,
                total_count=int(count),
                detail=f"{count} to choose from" if count else "",
            )

        # `unsupported`, or an outcome this module does not know. Both are "the provider
        # did not give a menu", and both are reported rather than silently defaulted —
        # an unknown outcome degrading to a silent free-text ask is the discard-pattern
        # trap ADR-0033 #4 guards against on the tier side.
        return Disposition(
            ASK, slot=name, reason=reason, spoken=spoken,
            option_source=SRC_NONE, found=found,
            free_text_reason=FT_UNSUPPORTED if eout == "unsupported" else FT_NO_PROVIDER,
            detail=str(enumerated.get("reason") or eout or ""),
        )

    return Disposition(ROUTE)


def ask_card(
    disp: Disposition,
    *,
    verb_iri: str,
    sub_query: str,
    accepted: Mapping[str, Any] | None,
) -> dict:
    """The ask, as a payload — a DISPOSITION, not a component.

    ADR-0033's archetype-unity constraint is deliberately respected by NOT shipping a card
    component here: this and ADR-0032's goal-shape card are one archetype, designed once
    with cortex in the room. What this returns is the typed result the surface will render
    when it exists, and which degrades to honest prose until then (per the
    registered-or-honest-fallback rule — an unregistered kind must degrade visibly, never
    borrow another species' affordances, which is exactly how the triage card shipped
    Approve/Reject on a failure).

    `accepted_slots` IS LOAD-BEARING AND IS THE WHOLE RE-ROUTE MECHANISM. `execute_subtask`
    reads `spoken = dict(config.slots or {})` and only fills when that is empty — so a
    re-route pre-binding ONLY the answered slot would suppress filling of every other slot
    the first turn already got right. Carrying the accepted set back means the re-route
    re-issues `{**accepted_slots, slot: chosen}` and makes NO second model call: the second
    turn cannot parse the phrase differently than the first did. The re-route is
    reconstructed, never re-parsed.
    """
    return {
        # PER-DISPOSITION, so a consumer switching on status cannot draw an abstain as an ask.
        "status": STATUS_BY_DISPOSITION.get(disp.action, "slot_elicitation"),
        "disposition": disp.action,
        # THE TYPED SUBJECT the presentation agent selects an archetype from. Without it the
        # ask had no output class and landed on KNOWLEDGE_DOCUMENT.
        "output_uri": SLOT_ELICITATION_URI,
        "verb_iri": verb_iri,
        "sub_query": sub_query,
        "slot": disp.slot,
        "reason": disp.reason,
        "spoken": disp.spoken,
        "found": disp.found,
        "options": [{"value": o.value, "label": o.label} for o in disp.options],
        "option_source": disp.option_source,
        "free_text_reason": disp.free_text_reason,
        "truncated_from": disp.truncated_from,
        "total_count": disp.total_count,
        # The merge, per the docstring above.
        "accepted_slots": dict(accepted or {}),
        "message": ask_message(disp),
        # ── THE FALLBACK'S CONTRACT, AND WHY THIS IS DUPLICATED ON PURPOSE ──────────────
        #
        # Stamping `output_uri` made the presentation agent select on it — which is the fix
        # — and until the ELICITATION archetype is admitted, selection lands on
        # KNOWLEDGE_DOCUMENT. That fallback composes its body from `summary` /
        # `summary_text` / `structured_data` on the expert_response
        # (`presentation_agent/main.py:265`), reads NONE of the fields above, and when it
        # finds nothing emits the literal string "No content available."
        #
        # SO THE INTERIM WAS WORSE THAN THE STATE IT REPLACED. Before the stamp there was no
        # output_uri, the legacy path ran, and a user saw "Which program?"; after it they saw
        # an empty card. That is the registered-or-honest-fallback rule inverted — an
        # unregistered kind must degrade VISIBLY, and this degraded to silence.
        #
        # `message` stays as the typed field the real card reads. `summary` is the alias the
        # fallback reads, carrying the same prose. Two keys with one string is a smell worth
        # accepting here, because the alternative is renaming `message` and coupling the
        # typed contract to a fallback's field names — which would outlive the fallback.
        # When ELICITATION is admitted this alias becomes dead weight rather than a lie, and
        # `test_the_fallback_renders_the_ask_rather_than_silence` is what will say so.
        "summary": ask_message(disp),
        # And the ask's own content, so the fenced JSON block the fallback appends carries
        # the options rather than an empty answer. A user meeting the interim sees the
        # question AND what they may choose — degraded, and not silent.
        "structured_data": {
            "slot": disp.slot,
            "options": [{"value": o.value, "label": o.label} for o in disp.options],
            "option_source": disp.option_source,
            "free_text_reason": disp.free_text_reason,
            "total_count": disp.total_count,
            "already_known": dict(accepted or {}),
        },
        "data": "",
        "sources": [],
    }


def ask_message(disp: Disposition) -> str:
    """The honest fallback prose, for every surface that cannot yet render a menu.

    Written so that a user reading it in a plain card is not worse off than one reading a
    422 or a Python signature error — which is the bar this whole disposition exists to
    clear.
    """
    # `project_id` -> "project". The `_id` suffix is a fact about the signature, not about
    # the thing, and reading it back to a person ("which project id?") asks them for an
    # opaque key when the whole point of the menu is that they do not have one.
    slot = (disp.slot or "").removesuffix("_id").replace("_", " ")
    if disp.action == ABSTAIN:
        if disp.spoken:
            return f"I could not find anything called {disp.spoken!r}. Nothing was run."
        return f"I need a {slot} and there are none to choose from yet. Nothing was run."

    if disp.found:
        # Names what WAS found, because "not one of them" throws away the most useful thing
        # the system knows: it understood the user, and they named another species.
        heard = f" I found {disp.found!r}, but that is not one."
    elif disp.spoken:
        heard = f" I heard {disp.spoken!r}, which is not one of them."
    else:
        heard = ""
    if disp.options:
        listed = ", ".join(o.label or o.value for o in disp.options)
        more = (
            f" (showing {len(disp.options)} of {disp.truncated_from})"
            if disp.truncated_from else ""
        )
        return f"Which {slot} did you mean?{heard} Options: {listed}{more}."
    if disp.free_text_reason == FT_TOO_MANY:
        extra = f" There are {disp.detail}." if disp.detail else ""
        return f"Which {slot}?{heard}{extra} Too many to list — name it and I will run this."
    return f"Which {slot}?{heard} Name it and I will run this."


# ═══════════════════════════════════════════════════════════════════════════════════════
# THE ANSWER SIDE — validating a pick and reconstructing the re-route
# ═══════════════════════════════════════════════════════════════════════════════════════
#
# The half above asks. This half receives, and it exists because MENU INTEGRITY WAS
# ENFORCED AT CONSTRUCTION AND NOT AT ACCEPTANCE. Measured, before this was written:
#
#     accept_slots({"project_id": "TOTALLY-MADE-UP"}, slots_for("plan_dependency_neighborhood"))
#       ->  accepted: {"project_id": "TOTALLY-MADE-UP"}   refusals: []
#
# It passes because an instance slot declares `type: "str"` with NO `values` — there is no
# closed vocabulary for that guard to test membership against. Latent while no re-route
# path exists to return a pick; live the day the surface lands.
#
# AND IT DOES NOT BELONG IN `accept_slots`. That module's contract is "THE DECLARATIONS
# ARE THE ACCEPTANCE SCHEMA", and an offered menu is a PER-TURN ARTIFACT, not a
# declaration. Putting it there would make a deliberately pure, conversation-free module
# depend on conversation state. Two different acceptance questions, kept apart:
#
#     accept_slots   : may this verb take this parameter at all?      (declarations)
#     validate_pick  : was this value one of the options WE offered?  (this turn)


class PickRefused(ValueError):
    """A pick was not in the set that was offered. Select-from-authorized-set ENFORCED,
    not merely prompted — the same refusal `spo_interview.PickRefused` raises."""


def validate_pick(pick: str, options: Sequence[Any], *, key: str = "value") -> str:
    """Server-side select-from-authorized-set enforcement.

    MIRRORED FROM `agent_fleet/restate_analyst/spo_interview.validate_pick`, NOT IMPORTED,
    and the reason is packaging rather than preference: engine images do not ship
    `iagent_pure` (`ontology_service` mirrors `decode_declarations` for exactly this
    reason and says so), so an import in either direction breaks an image. The agreement
    is pinned by a test instead — the same trade `SLOT_KINDS` already makes with the
    planning package.

    The behaviour is deliberately identical, including *suggest-closest-but-refuse-hard*:
    naming the near misses helps a caller correct itself, and refusing anyway is what
    stops a model smuggling a fabricated pick past the gate.

    Accepts `Option` tuples or plain dicts, so a card that has been through JSON round-trips
    validates the same as one held in memory — the surface will hand back the latter.
    """
    allowed: list[str] = []
    for o in options or ():
        if isinstance(o, Option):
            allowed.append(o.value)
        elif isinstance(o, Mapping):
            allowed.append(str(o.get(key) or ""))
        else:
            allowed.append(str(o))
    if pick in allowed:
        return pick
    close = [a for a in allowed if pick and (pick.lower() in a.lower() or a.lower() in pick.lower())]
    raise PickRefused(
        f"{pick!r} was not one of the options offered. "
        + (f"Closest: {', '.join(close[:3])}." if close else "No close match.")
    )


#: What a re-route should DO with the answer. Not a formality — the two are dispatched
#: completely differently, and conflating them reopens the hole this section closes.
BIND = "bind"            # the answer is an id we offered; it is already routable
RESPEAK = "respeak"      # there was no menu; the answer is WORDS and must be resolved


class Reroute(NamedTuple):
    action: str                    # bind | respeak
    slots: dict                    # for BIND: the merged, ready-to-dispatch parameters
    query: str = ""                # for RESPEAK: the user's ORIGINAL phrase, byte-equal
    slot: str = ""
    #: For RESPEAK: what the user typed as the answer, carried AS A FIELD.
    #:
    #: THIS USED TO BE CONCATENATED INTO `query` as `"<phrase> (<slot>: <answer>)"`, and that
    #: string became what a person read on the rail: `Provide the current funding status.
    #: (program_id: meridian)` — a question nobody asked, in machine syntax, on top of a
    #: phrase that was already the planner's paraphrase. Two composers, one string, neither
    #: half the user's words.
    #:
    #: RULED 2026-09-05: nothing is composed. The rail shows the user's phrase and the answer
    #: is displayed beneath it as `spoken -> resolved`, three facts as three facts. What the
    #: RESOLVER receives is a separate question from what the RAIL displays — the resolver
    #: gets this value to resolve for `slot`, with `query` as context — and an implementation
    #: input must never become the thing a person reads.
    spoken_answer: str = ""


def resolve_ask(card: Mapping[str, Any], answer: str) -> Reroute:
    """Turn a user's answer to an ask into the next route.

    TWO SHAPES, AND THE DISTINCTION IS THE WHOLE POINT.

    **A menu pick BINDS.** Its value came from a provider enumeration or a resolver
    candidate, so it is an id the verb accepts — that IS menu integrity, and validating it
    against the offered set is what makes trusting it safe. It rides back on
    `config.slots`, which already outranks the filler, so the re-route makes NO second
    model call and cannot re-parse the phrase differently than the first turn did.

    **A free-text answer must be RE-SPOKEN, never bound.** Both live ask cases fall to free
    text today (`too_many` on Capability's 9 and Project's 14 against a bound of 8), and a
    free-text answer is *words*, not an identifier: binding `project_id="Wave 1 Cutover"`
    directly is precisely the `TOTALLY-MADE-UP` hole with a human's typing in it, and it
    would reach the engine as a 422 — the failure the whole tri-state exists to prevent.
    So it goes back through the normal path as a phrase, where the filler and the resolver
    run on it exactly as they would on any question. Nothing enters a verb unresolved.

    This is ADR-0033's *"stateless re-route with the clarified subject substituted"* read
    literally: for a pick the clarified value substitutes into the slots; for free text the
    clarified wording substitutes into the query. Neither holds state between turns.
    """
    slot = str(card.get("slot") or "")
    accepted = dict(card.get("accepted_slots") or {})
    options = card.get("options") or []
    answer = (answer or "").strip()

    if not slot:
        raise PickRefused("the card names no slot; nothing can be answered")
    if not answer:
        raise PickRefused("an empty answer is not a pick")

    if options:
        # A menu was offered, so the answer must be ON it. This is the branch that was
        # missing entirely, and it is the one a fabricated pick would have walked through.
        value = validate_pick(answer, options)
        return Reroute(BIND, {**accepted, slot: value}, slot=slot)

    # No menu. The reason is already recorded on the card (too_many / unsupported /
    # no_provider / no_referent) — every one of them means "we could not offer a list",
    # never "anything is acceptable".
    # NOTHING IS COMPOSED. `query` is the phrase as it was asked; the answer rides as a
    # field. The resolver is handed `spoken_answer` as the value to resolve for `slot`, with
    # `query` as context — see the Reroute docstring for why those are different questions.
    return Reroute(
        RESPEAK,
        dict(accepted),
        query=str(card.get("sub_query") or ""),
        slot=slot,
        spoken_answer=answer,
    )


def validate_bound_slots(
    bound: Mapping[str, Any] | None,
    *,
    declared: Any,
    enumerate_class: Callable[[str], Mapping[str, Any]] | None = None,
    resolve_identifier: Callable[[str, str], Sequence[Mapping[str, Any]]] | None = None,
    menu_bound: int = MENU_BOUND,
) -> tuple[dict, list[str]]:
    """Validate slots a CLIENT says the user picked, by RECOMPUTING what was offered.

    THE PROBLEM THIS SOLVES, AND WHY THE OBVIOUS ANSWERS ARE WRONG. A pick comes back over a
    stateless request, so "validate it against what was offered" needs the offered set — and
    the two easy ways to get one are both unsound:

      * **the client echoes the menu it was shown** — self-certifying, and worth nothing: a
        caller that can send the pick can send the menu that permits it;
      * **the server holds the menu between turns** — a held lifetime, which is exactly what
        the stateless re-route was chosen to avoid.

    **THE MENU IS RECOMPUTABLE, so neither is needed.** Options came from the slot's own
    `referent` class or from a resolution on what the speaker said; given the verb and the
    slot, the authorized set can be derived again from the same sources. That is the SPO
    interview's rule for the same reason it gives — *"recomputed for the exact proposed
    subject, so the verb is checked against the right subject's eligibility, never a stale
    set"* — and it buys freshness for free: a pick against a menu that has since changed is
    refused, rather than honoured because a stale copy still permits it.

    REFUSALS ARE RETURNED, NEVER RAISED, matching `accept_slots`. A refused pick is a thing to
    report honestly, not a crash — and the caller decides whether that is an abstain or a
    re-ask.

    WHAT THIS DOES NOT VALIDATE, stated because the gap is deliberate: a slot with no
    `referent` (a literal the speaker supplies) and a slot whose class the provider reports as
    `too_many` have **no menu to check against** — nothing was offered, so nothing can be
    validated as having been offered. Those arrive as free text and are the RESPEAK path's
    business, where the value re-enters as words and the resolver adjudicates it. Accepting
    them here unchecked would be the fabricated-pick hole; the answer is that they must not
    come through this door at all, and a caller sending one gets it refused as `no_menu`.
    """
    bound = dict(bound or {})
    if not bound:
        return {}, [], {}
    try:
        decls = {d["name"]: d for d in decode_declarations(declared)}
    except Exception:  # noqa: BLE001 — fail closed, same posture as accept_slots
        return {}, [f"{n}: declarations unreadable" for n in sorted(bound)], {}

    out: dict = {}
    refusals: list[str] = []
    #: {slot: {outcome, spoken, instance_id}} — the same record shape `_fill_slots_from_query`
    #: produces, so the strip renders a pick and a fill through one path.
    resolution: dict[str, dict] = {}
    for name, value in sorted(bound.items()):
        decl = decls.get(name)
        if decl is None:
            refusals.append(f"{name}: not a declared slot")
            continue
        if decl.get("kind") in ("handle", "ceremony"):
            # The boundary `accept_slots` exists for, restated here because this door is new:
            # a caller supplying route-supplied state is not answering an ask.
            refusals.append(f"{name}: route-supplied, never offered")
            continue

        values = decl.get("values")
        if values:
            if value in values:
                out[name] = value
                # A declared-vocabulary pick has no separate label: the value IS what was
                # shown. Recorded anyway, so every bound slot has a row and the strip never
                # has to distinguish "no record" from "no label".
                resolution[name] = {
                    "outcome": BOUND, "spoken": str(value), "instance_id": str(value),
                }
            else:
                refusals.append(f"{name}={value!r}: not in the declared vocabulary")
            continue

        referent = str(decl.get("referent") or "")
        if not referent:
            refusals.append(f"{name}: no_menu — a literal slot offers no options to pick from")
            continue

        offered: list[str] = []
        labels: dict[str, str] = {}
        if enumerate_class is not None:
            try:
                enumerated = dict(enumerate_class(referent) or {})
            except Exception as exc:  # noqa: BLE001
                refusals.append(f"{name}: option source unreachable ({type(exc).__name__})")
                continue
            if str(enumerated.get("outcome") or "") == "members":
                # LABELS ARE KEPT, NOT DISCARDED. They used to be dropped here — `offered`
                # held ids only — so nothing downstream could say WHAT THE USER CLICKED, and
                # the disclosure strip had no row for a bound slot. The fact existed at the
                # only point that knew it and was thrown away one line later.
                for m in (enumerated.get("members") or []):
                    if m.get("instance_id"):
                        offered.append(str(m["instance_id"]))
                        labels[str(m["instance_id"])] = str(m.get("label") or "")
        if not offered and resolve_identifier is not None:
            # The disambiguation menu: candidates for what the speaker actually said, filtered
            # to the slot's class exactly as `_from_candidates` filters them.
            try:
                cands = resolve_identifier(name, referent) or []
            except Exception as exc:  # noqa: BLE001
                refusals.append(f"{name}: resolver unreachable ({type(exc).__name__})")
                continue
            for c in cands[:menu_bound]:
                if c.get("instance_id") and (
                    not c.get("class_uri") or c.get("class_uri") == referent
                ):
                    offered.append(str(c["instance_id"]))
                    labels[str(c["instance_id"])] = str(c.get("label") or "")

        if not offered:
            refusals.append(f"{name}: no_menu — nothing was offered for this slot")
            continue
        try:
            out[name] = validate_pick(str(value), [{"value": v} for v in offered])
        except PickRefused as exc:
            refusals.append(f"{name}: {exc}")
            continue
        # THE THIRD PROVENANCE. A slot the filler resolved has a row; a slot that was
        # REFUSED has a row. A slot the user PICKED FROM A MENU had neither, so the
        # disclosure strip — which renders rows from `slot_resolution` — drew nothing for
        # the one thing the person had most directly done. `spoken` is the option LABEL,
        # because the label is what they clicked and therefore what they said.
        resolution[name] = {
            "outcome": BOUND,
            "spoken": labels.get(out[name]) or str(out[name]),
            "instance_id": str(out[name]),
        }
    return out, refusals, resolution
