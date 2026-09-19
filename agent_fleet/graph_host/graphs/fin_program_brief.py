"""fin_program_brief — three finance verbs under the INITIATOR's identity, then a brief.

The exemplar for ADR-0046 slice 1. Chosen to answer a question a contracting officer actually
asks — *"how is this program doing"* — rather than to demonstrate the contract on a template.

── WHAT IT DEMONSTRATES, CLAUSE BY CLAUSE ──────────────────────────────────────────────────
* **multi-node state** — three fetch nodes and a synthesis node, not one function in a trench
  coat. The fan-in is the thing Engine B's `dagster_context` was supposed to be and never was:
  here the synthesis node READS what the fetch nodes wrote, and the brief is empty if it
  doesn't.
* **composition under identity** (ADR-0049 Ruling 1) — every inner call carries the INITIATOR's
  credential. The host holds no standing credential to fall back on, so a caller entitled to
  less sees less. An engine calling siblings under its own service identity would see
  everything it is entitled to and hand the result to a caller entitled to less, which is the
  laundering ADR-0029 Decision 5 forbids arriving through a door it did not name.
* **a refusal contract with a real refusal** (ADR-0049 Ruling 2) — a persona without
  `finBurnRate` gets a brief with that finding NAMED AS ABSENT, not a brief silently built from
  two. The disposition is declared in the ratified row (`refusal: named-hole`), never decided
  here, because a graph choosing per-invocation would give two callers different contracts for
  one verb.
* **cite-or-omit** — every figure in the brief carries the artifact it came from. The synthesis
  node cannot emit a number that is not in one of the three payloads, and the seal for that
  asserts it rather than trusting this docstring.

── WHY THE HOLES ARE PART OF THE ANSWER AND NOT AN ERROR PATH ──────────────────────────────
A brief built from two of three sources, presented as a brief, is a silently-narrowed answer —
the failure this project has paid for repeatedly. The named hole is what makes the narrowing
VISIBLE to the reader rather than known only to the log.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, TypedDict

import httpx
from langgraph.graph import END, StateGraph

ENGINE_FIN_URL = os.getenv("ENGINE_FIN_URL", "http://iagent-engine-fin:8096")

#: verb -> (measure fn, the finding's label in the brief). The three are DECLARED here rather
#: than discovered, because a graph that enumerated the finance engine's verbs would compose a
#: different brief every time engine-fin gained one — and the row's contract says what this
#: verb produces.
_SOURCES = [
    ("fin_variance_analysis", "cost and schedule variance"),
    ("fin_burn_rate", "cash burn against the phased plan"),
    ("fin_funding_status", "funding position"),
]


def _merge(a: list, b: list) -> list:
    return (a or []) + (b or [])


class BriefState(TypedDict, total=False):
    program_id: str
    #: The initiator's credential, threaded from the host's request. NOT the host's own: this
    #: engine holds no standing credential, by design.
    identity: dict[str, str]
    findings: Annotated[list[dict], _merge]
    holes: Annotated[list[dict], _merge]
    #: THE STRUCTURED PAYLOAD — one row per source, whatever happened to it. Accumulated by the
    #: same reducer as findings and holes, so a row exists for every node that ran and the card
    #: can tell "three sources, one unsummarised" from "two sources".
    rows: Annotated[list[dict], _merge]
    summary: str


#: THE FOUR ROW DISPOSITIONS, DECLARED IN ONE PLACE — R-073.
#:
#: A brief row is not a name plus a hope. `cortex-ui-60` raised this before the payload existed:
#: a row saying `{hole: "cost_variance"}` leaves the card choosing among three states with three
#: different repairs and three different readers, and the honest guess is NO RENDER AT ALL.
#:
#: Each maps onto the producer's contract (`presentation_agent/main.py:527`), and the mapping is
#: WHY the fourth exists rather than being folded into a hole:
#:
#:   finding       a verdict was emitted            -> the ordinary finding row
#:   unsummarised  content exists, verdict absent   -> a FINDING row, artifact linked, NEVER a
#:                                                     hole. The caller is entitled and the verb
#:                                                     ran; drawing a hole would tell a reader
#:                                                     they lack an entitlement they have.
#:   empty         the verb answered and has NOTHING -> the panel's own rowless card
#:   unentitled    the caller may not invoke it     -> NAMED_HOLE
#:   unavailable   failed, timed out, or refused    -> whole-board refusal
#:
#: `empty` ADDED 2026-09-18, and the correction underneath it matters more than the term. This
#: file claimed the dispositions mapped ONE-FOR-ONE onto the presentation contract. THEY DO NOT,
#: and cortex-ui-60 established it by comparing at source rather than accepting the claim:
#:
#:     here      finding · unsummarised · empty · unentitled · unavailable
#:     cortex              unsummarised · empty · unentitled · unavailable
#:
#: `finding` is the POSITIVE case and cortex's list is a vocabulary of ABSENCES, so it has no
#: slot for it — that asymmetry is fine. `empty` was not: it is an absence these rows can OCCUR
#: IN and could not NAME, so every verb that answered with nothing was called `unsummarised` —
#: which asserts CONTENT EXISTS and links an artifact holding none. **That is the exact collapse
#: R-073 refused, one layer over**, and the two have different lifetimes: `unsummarised` retires
#: when every verb emits a verdict; `empty` NEVER retires, because a variance analysis with no
#: variances is a correct answer forever.
#:
#: `unsummarised` IS TEMPORARY BY CONSTRUCTION and retires by TEST, not by memory: the seal beside
#: it asserts no built-in verb produces one. When lane 91's verdict lines cover every measure, the
#: disposition becomes unreachable and the seal says so.
ROW_DISPOSITIONS = ("finding", "unsummarised", "empty", "unentitled", "unavailable")

#: The keys a payload may lead with. Read FROM the payload, never recomputed — the same list
#: `_headline` uses, named once so the row and the prose cannot disagree about what a verdict is.
VERDICT_KEYS = ("headline", "summary", "value", "verdict")


def _verdict_of(payload: dict) -> str | None:
    """The payload's own verdict, or None. NONE IS A RESULT, not a failure to find one."""
    for key in VERDICT_KEYS:
        if isinstance(payload.get(key), (str, int, float)):
            return str(payload[key])
    return None


def _has_content(payload: dict) -> bool | None:
    """Does this payload carry anything a reader could open? None means CANNOT TELL.

    DERIVED FROM THE ENVELOPE, not guessed. engine-fin's response always carries `rows`
    (`finance_agent/main.py`), and omits `verdict` entirely when there is nothing to say — the
    same honest-absence rule. So an answered verb with `rows: []` has genuinely nothing, and
    that is a different fact from a verdict being absent.

    THE THIRD ANSWER IS THE POINT. A payload with no `rows` key at all is a shape this graph
    does not know, and the two wrong guesses are not symmetric:

        calling it `empty`        hides content a reader could have opened
        calling it `unsummarised` sends them to look and they find nothing

    The second is recoverable by looking; the first is invisible. So an unknown shape fails to
    `unsummarised`, and this returns None so the caller makes that choice in the open rather
    than inheriting it from a falsy default.
    """
    rows = payload.get("rows")
    if rows is None:
        return None
    return bool(rows)


def _disposition_for(payload: dict, verdict: str | None) -> str:
    """Three-way, and each arm is a different fact with a different repair."""
    if verdict is not None:
        return "finding"
    # `_has_content` returns None for a shape we cannot read; that fails to `unsummarised`,
    # which sends a reader to look, rather than to `empty`, which tells them not to bother.
    return "empty" if _has_content(payload) is False else "unsummarised"


def _row(source: str, label: str, disposition: str, *,
         artifact: str | None = None, verdict: str | None = None,
         reason: str | None = None) -> dict:
    """One brief row. THE ARTIFACT IS A FIELD ON EVERY ROW, present even when null.

    Absent-versus-empty, the same rule as `disposal` and `failure_cause`: a row with no
    `artifact` key at all makes a consumer guess whether the hop produced one, and a card that
    guesses draws the wrong thing confidently. A refused verb HAS no artifact, and saying so is
    a different statement from not mentioning it.
    """
    assert disposition in ROW_DISPOSITIONS, f"undeclared row disposition: {disposition!r}"
    return {"row": source, "label": label, "disposition": disposition,
            "artifact": artifact, "verdict": verdict, "reason": reason}


def _fetch(fn: str, label: str):
    """One fetch node. Refuses ON BEHALF OF THE CALLER or records a named hole."""

    def node(state: BriefState) -> dict[str, Any]:
        ident = state.get("identity") or {}
        if not ident.get("authorization"):
            # NO STANDING CREDENTIAL TO FALL BACK ON. Proceeding here would run the read as the
            # host, which is exactly the laundering the identity ruling forbids. It is a hole,
            # named, rather than a silent success under the wrong subject.
            _reason = "no initiator identity on the request"
            return {"holes": [{"source": fn, "label": label, "reason": _reason}],
                    "rows": [_row(fn, label, "unentitled", reason=_reason)]}
        try:
            r = httpx.post(
                f"{ENGINE_FIN_URL}/measure/{fn}",
                json={"params": {"program_id": state["program_id"]}},
                headers={k: v for k, v in ident.items() if v},
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            _reason = f"unreachable: {exc}"
            return {"holes": [{"source": fn, "label": label, "reason": _reason}],
                    "rows": [_row(fn, label, "unavailable", reason=_reason)]}

        if r.status_code in (401, 403):
            # THE INITIATOR'S REFUSAL, CARRIED. Not the graph's failure — this caller is not
            # entitled to this measure, and the brief says so where the reader can see it.
            _reason = f"the caller is not entitled to {fn}"
            return {"holes": [{"source": fn, "label": label, "reason": _reason}],
                    "rows": [_row(fn, label, "unentitled", reason=_reason)]}
        if r.status_code >= 400:
            _reason = f"{fn} returned {r.status_code}"
            return {"holes": [{"source": fn, "label": label, "reason": _reason}],
                    "rows": [_row(fn, label, "unavailable", reason=_reason)]}

        payload = r.json()
        artifact = payload.get("artifact_id") or payload.get("id")
        verdict = _verdict_of(payload)
        # THE ONLY PLACE THAT KNOWS. A verdict absent here is content-without-a-verdict; the
        # same absence read off the PROSE downstream is indistinguishable from a verb that was
        # never called, which is why the row is emitted where the payload is in hand.
        return {"findings": [{"source": fn, "label": label, "payload": payload,
                              "artifact": artifact}],
                "rows": [_row(fn, label, _disposition_for(payload, verdict),
                              artifact=artifact, verdict=verdict)]}

    return node


def synthesise(state: BriefState) -> dict[str, Any]:
    """Compose the brief. CITE-OR-OMIT: every line names the artifact it came from.

    Deliberately NOT an LLM call. The producer computes and the renderer displays; a model
    asked to "summarise these three payloads" is a second implementation of the arithmetic,
    free to produce a figure that is in none of them. What a model would add here is prose, and
    prose that can invent a number is worth less than three lines that cannot.
    """
    # STOPS AT PROSE, ENTIRELY. This node does not build, amend or re-derive `rows` — they are
    # emitted where the payload is in hand and travel untouched. Structure recovered from prose
    # is a parser guessing at a sentence this node wrote, and every such guess this project has
    # shipped has been wrong in a way nothing could see.
    findings = state.get("findings") or []
    holes = state.get("holes") or []
    lines = [f"Program {state['program_id']}:"]
    for f in findings:
        cite = f.get("artifact") or f["source"]
        lines.append(f"  - {f['label']}: {_headline(f['payload'])}  [{cite}]")
    for h in holes:
        # THE HOLE IS IN THE BRIEF, not only in the log. A reader must be able to see that this
        # brief is built from two of three sources without going to look.
        lines.append(f"  - {h['label']}: NOT AVAILABLE — {h['reason']}")
    if not findings:
        lines.append("  (no finding was retrievable for this caller; nothing below is omitted "
                     "silently — every source is named above)")
    return {"summary": "\n".join(lines)}


def _headline(payload: dict) -> str:
    """The prose line's verdict — THE SAME READ THE ROW MAKES, never a second one.

    This had its own copy of the key list. Two readings of "does this payload state a verdict"
    would agree today and diverge the first time one gained a key, and the divergence would be
    invisible: the row would say `finding` while the prose said "reported (see artifact)", or
    the reverse. One function, both callers.
    """
    return _verdict_of(payload) or "reported (see artifact)"


def build() -> StateGraph:
    """The builder the ratified row names. Returns UNCOMPILED — the host compiles it, so the
    checkpointer decision stays the host's to honour rather than this module's to make."""
    g = StateGraph(BriefState)
    prev = None
    for fn, label in _SOURCES:
        g.add_node(fn, _fetch(fn, label))
        if prev is None:
            g.set_entry_point(fn)
        else:
            g.add_edge(prev, fn)
        prev = fn
    g.add_node("synthesise", synthesise)
    g.add_edge(prev, "synthesise")
    g.add_edge("synthesise", END)
    return g
