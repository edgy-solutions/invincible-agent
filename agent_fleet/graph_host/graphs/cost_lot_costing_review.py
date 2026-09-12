"""cost_lot_costing_review — one lot, three cost views, one vintage, under the initiator.

engine-lg's SECOND hosted graph, and its job is to be evidence: ADR-0046 slice 1 claims the
host is a place a team plugs a graph into rather than one graph with scaffolding. A second
graph admitted without touching the host is the only thing that settles it, and
`tests/graph_host/test_a_second_graph_is_a_row_only.py` asserts that as a file diff.

It differs from `fin_program_brief` in every way the ROW controls — different subject, domain,
inner engine, refusal disposition, checkpointer, and slot count — because a second graph that
matched the first would show the host can load two files, not that a row is a contract.

── `refusal: fail`, AND WHY THIS GRAPH IS NOT THE OTHER ONE ────────────────────────────────
`fin_program_brief` declares `named-hole`: a brief missing one of three findings is still a
brief, with the gap named where the reader can see it. **This graph declares `fail`, and that
is a judgement about what its answer MEANS.** The review's whole claim is that three views of
one lot AGREE under one vintage; two of three cannot support it, and a "review" built from two
would be a narrowed answer presented as a whole one. So a refused inner verb ends the graph.

**THE HOST DOES NOT ENFORCE THIS — the row declares it and this module honours it.** That gap
is real and filed rather than papered over: a contract clause a manifest declares and nothing
checks is exactly the shape this engine exists to refuse, and a graph could declare `fail` and
quietly return partial results with nothing going red. Named in the seal's docstring too.

── `rate_vintage` IS ENGINE-COST'S DESIGNED REFUSAL, INHERITED ─────────────────────────────
`cost_agent/slots.py` says it plainly: *"a refusal the router cannot see is a refusal that
never fires."* A graph that composed those verbs without declaring `rate_vintage` would be the
place that refusal got lost — the caller would reach the graph, the graph would reach
engine-cost, and engine-cost would refuse on a slot nobody had asked for. Declared in the row,
required here.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, TypedDict

import httpx
from langgraph.graph import END, StateGraph

ENGINE_COST_URL = os.getenv("ENGINE_COST_URL", "http://iagent-engine-cost:8097")

#: verb -> the view it contributes. Declared, not enumerated from the engine: a graph that
#: discovered engine-cost's verbs would compose a different review every time that engine
#: gained one, and the row's contract says what this verb produces.
_VIEWS = [
    ("cost_lot_breakdown", "five-bucket decomposition"),
    ("cost_price_composition", "base-cost-to-price build-up"),
    ("cost_rate_comparison", "applied versus estimating rates"),
]


class RefusedInner(RuntimeError):
    """An inner verb refused for the initiator, and this row declares `fail`.

    A distinct type rather than a bare RuntimeError so the host's 500 carries which verb
    refused and for whom — "the graph failed" sends the reader to the graph, and the answer is
    almost always an entitlement.
    """


def _merge(a: list, b: list) -> list:
    return (a or []) + (b or [])


class ReviewState(TypedDict, total=False):
    lot: int
    rate_vintage: str
    #: The initiator's credential, threaded from the host's request. Never this engine's own:
    #: it holds no standing credential, which is what makes "runs as the initiator" structural.
    identity: dict[str, str]
    views: Annotated[list[dict], _merge]
    summary: str


def _fetch(fn: str, label: str):
    def node(state: ReviewState) -> dict[str, Any]:
        ident = state.get("identity") or {}
        if not ident.get("authorization"):
            raise RefusedInner(
                f"{fn}: no initiator identity on the request. Proceeding would run a governed "
                f"cost read as the HOST, which is the laundering ADR-0029 Decision 5 forbids."
            )
        r = httpx.post(
            f"{ENGINE_COST_URL}/measure/{fn}",
            json={"params": {"lot": state["lot"], "rate_vintage": state["rate_vintage"]}},
            headers={k: v for k, v in ident.items() if v},
            timeout=60.0,
        )
        if r.status_code in (401, 403):
            raise RefusedInner(
                f"{fn}: the caller is not entitled to it. This row declares refusal=fail "
                f"because a costing review's claim is that its three views AGREE — two of "
                f"three cannot support it, and a partial review presented as a review is a "
                f"narrowed answer wearing a whole one's clothes."
            )
        r.raise_for_status()
        payload = r.json()
        # engine-cost answers a missing/!invalid slot with a 200 REFUSAL BODY rather than a
        # status code, so status alone is not the check — read the body it actually returns.
        if isinstance(payload, dict) and payload.get("refusal"):
            raise RefusedInner(f"{fn} refused: {payload.get('refusal')} {payload.get('detail','')}")
        return {"views": [{"source": fn, "label": label, "payload": payload,
                           "artifact": payload.get("artifact_id") or payload.get("id")}]}

    return node


def review(state: ReviewState) -> dict[str, Any]:
    """Compose the three views. CITE-OR-OMIT: every line names the artifact it came from.

    Deliberately not an LLM. The producer computes and the renderer displays; a model asked to
    reconcile three cost payloads is a second implementation of the arithmetic, free to emit a
    figure in none of them — and on a costing review that figure is the answer.
    """
    views = state.get("views") or []
    if len(views) != len(_VIEWS):
        # UNREACHABLE BY DESIGN and asserted anyway. Every fetch node raises rather than
        # returning empty, so a short list here means a node found a fourth way to fail
        # quietly. An invariant is worth more than the guard it replaces.
        raise RefusedInner(
            f"review reached with {len(views)} of {len(_VIEWS)} views — refusal=fail means the "
            f"graph should have ended at the refusal, so this is a node failing silently"
        )
    lines = [f"Lot {state['lot']} under rate vintage {state['rate_vintage']}:"]
    for v in views:
        cite = v.get("artifact") or v["source"]
        lines.append(f"  - {v['label']}: {_headline(v['payload'])}  [{cite}]")
    return {"summary": "\n".join(lines)}


def _headline(payload: dict) -> str:
    """The figure a payload leads with, taken FROM it and never recomputed."""
    for key in ("headline", "summary", "verdict", "total", "value"):
        if isinstance(payload.get(key), (str, int, float)):
            return str(payload[key])
    return "reported (see artifact)"


def build() -> StateGraph:
    """The builder the ratified row names. Returns UNCOMPILED — the host compiles it, which is
    what keeps `checkpointer: false` the row's decision rather than this module's."""
    g = StateGraph(ReviewState)
    prev = None
    for fn, label in _VIEWS:
        g.add_node(fn, _fetch(fn, label))
        if prev is None:
            g.set_entry_point(fn)
        else:
            g.add_edge(prev, fn)
        prev = fn
    g.add_node("review", review)
    g.add_edge(prev, "review")
    g.add_edge("review", END)
    return g
