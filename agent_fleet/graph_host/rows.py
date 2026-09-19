"""The SOURCE_LEDGER row vocabulary — shared by every graph in this host.

EXTRACTED AT THE SECOND CONSUMER, which is this repo's rule and has been paid for twice: the
card and the routing record each had a rule for picking the primary subtask, the two agreed in a
docstring, and they disagreed in production. A second copy of a vocabulary is a second
vocabulary the moment either is edited.

── THE CONTRACT ────────────────────────────────────────────────────────────────────────────
A ledger row is emitted for EVERY declared source, whatever happened to it. That is the whole
property: a reader can tell "three sources, one unsummarised" from "two sources", so a narrowed
answer is visible rather than invisible. The absences are ENTRIES, NOT OMISSIONS — which is what
the archetype's name carries and what distinguishes it from a list of findings.

── WHICH DISPOSITIONS A GRAPH CAN REACH IS A FUNCTION OF ITS `refusal` CLAUSE ───────────────
Not every graph can produce every term, and the difference is declared rather than incidental:

    refusal: named-hole   all five. A refused inner call becomes a NAMED HOLE in the answer.
    refusal: fail         the three non-hole terms ONLY. A refused inner call RAISES, so the
                          graph never returns a row for it — there is no partial answer to put
                          one in.

`reachable_for` derives that rather than leaving each graph's seal to hand-list a subset, which
is the form that quietly goes stale when a row's refusal clause changes.

── WHERE THIS SHOULD EVENTUALLY LIVE, NAMED RATHER THAN DECIDED ────────────────────────────
ADR-0046 route C is a team running THEIR OWN host against the same contract. If the ledger row
is part of that contract, this belongs in `iagent-mesh` beside `GraphManifest` and
`enforce_refusal`, not here — a convention only this host implements is one route C will not
inherit, which is the argument that moved `enforce_refusal` into the SDK. That is an SDK release
and a fleet-wide pin bump, so it is NAMED here and left to the architect rather than taken.
"""
from __future__ import annotations

from typing import Any

#: THE PUBLIC SURFACE, DECLARED. Without it `Any` and `annotations` are part of this module's
#: surface, and a package re-exporting `*` inherits them — which is how v0.7.0 shipped a release
#: whose whole point was a shared function that the package did not re-export, and how
#: `SLOT_KINDS` stayed unexported for two releases after. The SDK's ref-coverage seal is derived
#: from this list, so anything missing here is missing there.
__all__ = [
    "ROW_DISPOSITIONS",
    "HOLE_DISPOSITIONS",
    "NON_HOLE_DISPOSITIONS",
    "VERDICT_KEYS",
    "verdict_of",
    "has_content",
    "disposition_for",
    "row",
    "holes_from",
    "reachable_for",
    "fetch_row",
]

#: THE FULL VOCABULARY. See `fin_program_brief` for the ruling (R-073) and for why
#: `unsummarised` is not a hole and `empty` is not `unsummarised`.
ROW_DISPOSITIONS = ("finding", "unsummarised", "empty", "unentitled", "unavailable")

#: The ADR-0049 Ruling 2 set — the terms `holes_from` projects.
HOLE_DISPOSITIONS = ("unentitled", "unavailable")

#: The positive counterpart, written down so the partition has both halves and neither is an
#: "everything else". A term in neither is UNCLASSIFIED and the seal fails rather than guessing.
NON_HOLE_DISPOSITIONS = ("finding", "unsummarised", "empty")

#: The keys a payload may lead with, in order. One list, so the prose and the row cannot
#: disagree about what a verdict is.
VERDICT_KEYS = ("headline", "summary", "value", "verdict")


def verdict_of(payload: dict) -> str | None:
    """The payload's own verdict, or None. NONE IS A RESULT, not a failure to find one."""
    for key in VERDICT_KEYS:
        if isinstance(payload.get(key), (str, int, float)):
            return str(payload[key])
    return None


def has_content(payload: dict) -> bool | None:
    """Does this payload carry anything a reader could open? None means CANNOT TELL.

    Derived from the fleet envelope: an engine's measure response carries `rows`, and omits
    `verdict` entirely when there is nothing to say. So `rows: []` on an answered verb is
    genuinely nothing, and that is a different fact from a verdict being absent.

    THE THIRD ANSWER IS THE POINT. The two wrong guesses are not symmetric — calling it `empty`
    HIDES content a reader could have opened; calling it `unsummarised` sends them to look and
    they find nothing. The second is recoverable by looking, the first is invisible. So this
    returns None and the caller chooses in the open rather than inheriting a falsy default.
    """
    rows = payload.get("rows")
    if rows is None:
        return None
    return bool(rows)


def disposition_for(payload: dict, verdict: str | None) -> str:
    """Three-way over an ANSWERED verb. Each arm is a different fact with a different repair."""
    if verdict is not None:
        return "finding"
    return "empty" if has_content(payload) is False else "unsummarised"


def row(source: str, label: str, disposition: str, *,
        artifact: str | None = None, verdict: str | None = None,
        reason: str | None = None) -> dict:
    """One ledger row. THE ARTIFACT IS A FIELD ON EVERY ROW, present even when null.

    Absent-versus-empty: a refused verb HAS no artifact, and saying so is a different statement
    from not mentioning it. On an `empty` row the artifact stays populated deliberately — the
    link is HOW A READER CHECKS THE CLAIM, and nulling it would make "the verb answered and had
    nothing" unfalsifiable from their side. The disposition governs how loudly a card invites
    the click; the fact stays.
    """
    assert disposition in ROW_DISPOSITIONS, f"undeclared row disposition: {disposition!r}"
    return {"row": source, "label": label, "disposition": disposition,
            "artifact": artifact, "verdict": verdict, "reason": reason}


def holes_from(rows: list[dict]) -> list[dict]:
    """The named holes a set of rows implies. THE ONLY PLACE `holes` IS BUILT.

    `holes` is what the SDK's `enforce_refusal` reads, so it cannot simply be dropped as a
    duplicate of `rows` — that would silently retire ADR-0049 Ruling 2. Deriving it instead
    means one emission and one truth, and a consumer reading either sees the same set.
    """
    return [
        {"source": r["row"], "label": r["label"], "reason": r["reason"]}
        for r in rows
        if r["disposition"] in HOLE_DISPOSITIONS
    ]


def reachable_for(refusal: str) -> set[str]:
    """Which dispositions a graph with this `refusal` clause can actually emit.

    DERIVED FROM THE CLAUSE, so a graph's seal cannot hand-list a subset that goes stale when
    the ratified row changes its disposition. A `fail` graph raises on a refused inner call, so
    it never RETURNS a row for one — the hole terms are unreachable for it, and a seal asserting
    all five against it would be asserting an outcome the contract forbids.
    """
    if refusal == "fail":
        return set(NON_HOLE_DISPOSITIONS)
    return set(ROW_DISPOSITIONS)


def fetch_row(fn: str, label: str, payload: dict[str, Any]) -> dict:
    """The row an ANSWERED verb produces. The one place the success path is shaped."""
    verdict = verdict_of(payload)
    return row(fn, label, disposition_for(payload, verdict),
               artifact=payload.get("artifact_id") or payload.get("id"),
               verdict=verdict)
