"""5.2's third clause: a missing mandatory slot on the hosted graph is an ASK, not a guess.

The routing rows in `tests/routing/test_classify_route.py` prove the graph's question REACHES
the graph. They say nothing about what happens when the question does not carry what the graph
needs — and the honest answer to "give me a brief" with no program named is a question back,
not a program chosen for the caller.

WHY THIS IS PURE AND NOT A LIVE PROBE. `decide_disposition` is the layer that decides
`route | ask | abstain`, and it is dependency-free by design so it can be proven by fixtures
with no model in the loop. Asserting this against a live LLM would make the seal depend on a
model's willingness to leave a slot empty, which is the thing under test rather than the
instrument.

WHAT IT WOULD MEAN IF THIS WERE `route` INSTEAD. The graph's `program_id` is spoken-mandatory
with a `fin:Program` referent. Routed without it, the host's own 422 fires — which is correct
but arrives as an error to somebody who asked a reasonable question a sentence away from being
answerable. ADR-0033's whole point is that the one thing missing was one sentence away and the
system had no way to ask for it.

`decide_disposition` FAILS SAFE TOWARD `route` by design — every unreadable input degrades to
routing, because an `ask` interrupts a flow that currently completes. That makes `ask` the
harder outcome to obtain and therefore the one worth sealing: a bug in that module cannot
invent an interruption, so a green here is not an accident of a permissive default.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_POLICY = _ROOT / "policy" / "graphs"


def _graph_declarations() -> list[dict]:
    """The graph's OWN declared slots, from its ratified row — not a hand-written copy.

    Read through the SDK loader so this seal and the registration payload cannot disagree: a
    fixture that restated the slots would keep passing after the row changed.
    """
    from iagent_mesh.graph_manifest import load_manifests

    rows = [m for m in load_manifests(_POLICY) if m.graph_id == "fin_program_brief"]
    assert rows, "fin_program_brief has no ratified row — this seal has no subject"
    return [s.model_dump(exclude_none=True) for s in rows[0].slots]


def test_the_row_actually_declares_a_mandatory_slot():
    """POSITIVE CONTROL, first. If nothing is mandatory there is nothing to ask for, and the
    ask assertion below would pass by describing a verb that takes no required input."""
    decls = _graph_declarations()
    mandatory = [d for d in decls if d.get("kind") == "spoken-mandatory"]
    assert mandatory, f"no spoken-mandatory slot in {decls} — the ask test would be vacuous"
    assert any(d.get("referent") for d in mandatory), (
        "the mandatory slot carries no referent, so there is no instance for a menu or an ask "
        "to be about — which is what makes this an ask rather than a 400"
    )


def test_a_brief_with_no_program_named_is_an_ASK():
    from iagent_pure.slot_disposition import decide_disposition

    d = decide_disposition(
        accepted={},                      # nothing survived the fill: no program was named
        declared=_graph_declarations(),
        resolution={},                     # the filler reported nothing for program_id
    )
    assert d.action == "ask", (
        f"a brief requested with no program named came back {d.action!r}. Routed, the host's own "
        f"422 fires — correct, and arriving as an error to somebody whose question was one "
        f"sentence away from answerable. decide_disposition FAILS SAFE TOWARD route, so this "
        f"is the harder outcome and the one worth sealing: {d}"
    )
    assert d.is_ask, "the Disposition's own is_ask disagrees with its action field"
    assert d.slot == "program_id", f"the ask names the wrong slot: {d.slot!r}"
    assert d.reason, "an ask with no reason gives the caller nothing to act on"


def test_a_brief_WITH_a_program_named_ROUTES():
    """THE NEGATIVE CONTROL, and it is the one that matters here.

    Without it, "missing slot asks" is indistinguishable from "this verb always asks" — a
    disposition that interrupts every call would satisfy the test above while making the graph
    unreachable. A seal for an interruption needs proof the interruption is conditional.
    """
    from iagent_pure.slot_disposition import decide_disposition

    d = decide_disposition(
        accepted={"program_id": "PGM-001"},
        declared=_graph_declarations(),
        resolution={"program_id": {"outcome": "spoken", "spoken": "PGM-001"}},
    )
    assert d.action == "route", (
        f"a brief WITH its program named came back {d.action!r} — the graph would be unreachable "
        f"even when the caller supplied everything it declared: {d}"
    )
