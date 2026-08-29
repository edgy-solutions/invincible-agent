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

#: THE MENU BOUND — ruled 2026-08-29 at 8, and it is a HUMAN-ATTENTION bound: the number of
#: options a person can choose from in one turn. That makes it a fact about readers, so it
#: must be the SAME number wherever a menu is built. Read from the same env var Engine P's
#: enumerator reads rather than restated here — one bound, single-sourced, not mirrored.
MENU_BOUND = int(os.getenv("ENUMERATE_MENU_BOUND", "8"))

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

ROUTE = "route"
ASK = "ask"
ABSTAIN = "abstain"

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
    opts = tuple(
        Option(str(c.get("instance_id") or ""), str(c.get("label") or c.get("instance_id") or ""))
        for c in cands
        if c.get("instance_id")
    )
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
            count = enumerated.get("count")
            return Disposition(
                ASK, slot=name, reason=reason, spoken=spoken, found=found,
                option_source=SRC_NONE, free_text_reason=FT_TOO_MANY,
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
        "status": "slot_elicitation",
        "disposition": disp.action,
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
        # The merge, per the docstring above.
        "accepted_slots": dict(accepted or {}),
        "message": ask_message(disp),
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
