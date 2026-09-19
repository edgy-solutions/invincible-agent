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
    #: DERIVED IN `synthesise` FROM `rows`, never accumulated from the nodes. Kept because the
    #: SDK's `enforce_refusal` reads it to enforce the row's `refusal` clause — it is the
    #: ADR-0049 Ruling 2 contract, not a display field.
    holes: list[dict]
    #: THE STRUCTURED PAYLOAD — one row per source, whatever happened to it. Accumulated by the
    #: same reducer as findings and holes, so a row exists for every node that ran and the card
    #: can tell "three sources, one unsummarised" from "two sources".
    rows: Annotated[list[dict], _merge]
    summary: str


# ── the ledger vocabulary, SHARED ───────────────────────────────────────────────────────────
# MOVED to `agent_fleet/graph_host/rows.py` when the cost review became the second consumer.
# The ruling that produced these terms (R-073) and the reasoning for each is recorded there;
# what stays here is the graph. Re-exported under the old names so every existing seal and any
# route-C reader keeps its import — a rename and a move in one change makes the diff about the
# rename.
from agent_fleet.graph_host.rows import (  # noqa: E402
    HOLE_DISPOSITIONS,
    NON_HOLE_DISPOSITIONS,
    ROW_DISPOSITIONS,
    VERDICT_KEYS,
    disposition_for as _disposition_for,
    fetch_row as _fetch_row,
    has_content as _has_content,
    holes_from,
    row as _row,
    verdict_of as _verdict_of,
)


def _fetch(fn: str, label: str):
    """One fetch node. Refuses ON BEHALF OF THE CALLER or records a named hole."""

    def node(state: BriefState) -> dict[str, Any]:
        ident = state.get("identity") or {}
        if not ident.get("authorization"):
            # NO STANDING CREDENTIAL TO FALL BACK ON. Proceeding here would run the read as the
            # host, which is exactly the laundering the identity ruling forbids. It is a hole,
            # named, rather than a silent success under the wrong subject.
            return {"rows": [_row(fn, label, "unentitled",
                                  reason="no initiator identity on the request")]}
        try:
            r = httpx.post(
                f"{ENGINE_FIN_URL}/measure/{fn}",
                json={"params": {"program_id": state["program_id"]}},
                headers={k: v for k, v in ident.items() if v},
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            return {"rows": [_row(fn, label, "unavailable", reason=f"unreachable: {exc}")]}

        if r.status_code in (401, 403):
            # THE INITIATOR'S REFUSAL, CARRIED. Not the graph's failure — this caller is not
            # entitled to this measure, and the brief says so where the reader can see it.
            return {"rows": [_row(fn, label, "unentitled",
                                  reason=f"the caller is not entitled to {fn}")]}
        if r.status_code >= 400:
            return {"rows": [_row(fn, label, "unavailable",
                                  reason=f"{fn} returned {r.status_code}")]}

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
    # PROJECTED, NOT READ. `holes` is no longer emitted by the fetch nodes — it is derived here
    # from the rows, so the two cannot disagree and the prose cannot describe a hole set that
    # differs from the structured one.
    holes = holes_from(state.get("rows") or [])
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
    return {"summary": "\n".join(lines), "holes": holes}


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
