"""THE DIRECT PATH — executing a route the ask already established, without a Dagster run.

MEASURED 2026-09-08 on a pre-resolved pick: 24 seconds end to end, of which roughly ONE
second is work. Gateway 0.26s, run-launch 8.4s, the run 13.1s, write 1.5s. Routing inside
that run took 0.24s; the engine call about two seconds.

This file seals the dispatch core. It emits no SSE and writes no artifact — the gateway owns
both — so everything here is callable without a cluster.

THE FOUR OUTCOMES ARE THE DESIGN, and collapsing any two of them is the defect this repo has
removed repeatedly:

    ROUTED     the engine answered
    ASK        a second ask is owed — the one-option menu, or a refused slot
    ABSTAIN    the verb was right and the ENGINE did not answer
    FALL_BACK  the route could not be confirmed; run the full path

FALL_BACK and ABSTAIN are the pair most easily merged and must not be. "We could not check"
is not "there is no answer" — the same conflation that made Contract D's `missing` accuse the
ontology. And re-running through Dagster on an engine failure would call the same engine
again and fail twenty seconds later.

Run: uv run --frozen pytest tests/routing/test_the_direct_path_executes_a_settled_route.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iagent import direct_dispatch as dd  # noqa: E402
from iagent_pure.slot_acceptance import accept_slots  # noqa: E402

_VERB = "mesh:costCategoryBreakdown"
_SUBJ = "http://invincible-agent/cost#CostCategory"
_ENDPOINT = "http://iagent-engine-cost.sandbox.svc:8097/measure/cost_category_breakdown"


def _compat(arity: str = "single", verb: str = _VERB) -> dict:
    return {
        "verb_iri": verb, "verb_local": "costCategoryBreakdown", "input_uri": _SUBJ,
        "output_uri": "http://invincible-agent/cost#CategoryBreakdown",
        "endpoint_url": _ENDPOINT, "owner_persona": "COST_ANALYST",
        "domains": ["PRODUCTION_COST"], "arity": arity,
        "slots": json.dumps([{"name": "lot", "type": "integer", "required": True,
                              "kind": "spoken-mandatory"}]),
    }


class _Resp:
    def __init__(self, body=None, boom=False):
        self._body, self._boom = body or {"components": [{"rows": []}]}, boom

    def raise_for_status(self):
        if self._boom:
            raise RuntimeError("500 Server Error")

    def json(self):
        return self._body


@pytest.fixture()
def run(monkeypatch):
    """Call the real `dispatch_pre_resolved` with the verifier and engine stubbed."""
    posted: dict = {}

    def _go(*, verbs=None, err=None, bound=None, arity="single", instance="", label="",
            boom=False):
        # The stub honours `find_compatible_verbs`' REAL three-outcome contract, including
        # `(None, err)` on failure — never `([...], err)`. A fixture that hands back verbs
        # AND an error is a shape the function cannot produce, and it would let a caller
        # that ignores `err` pass here and dispatch in production.
        monkeypatch.setattr(
            dd, "find_compatible_verbs",
            lambda s, d, *, ontology_url, **k: (
                (None, err) if err is not None
                else ((verbs if verbs is not None else [_compat(arity)]), None)
            ),
        )

        def _post(url, json=None, headers=None, timeout=None):
            posted.update(url=url, body=json, timeout=timeout)
            return _Resp(boom=boom)

        return dd.dispatch_pre_resolved(
            pre_resolved={"subject_uri": _SUBJ, "verb_iri": _VERB,
                          "subject_instance_id": instance, "subject_instance_label": label},
            bound_slots=bound if bound is not None else {"lot": "4"},
            spoken_answer="", user_query="where did the money go",
            entitled_domains=["PRODUCTION_COST"], acting_persona="COST_ANALYST",
            ontology_url="http://engine-o", accept_slots=accept_slots, post=_post,
        ), posted

    return _go


# ── the happy path ──────────────────────────────────────────────────────────

def test_a_settled_route_dispatches_to_the_engine(run):
    out, posted = run()
    assert out.kind == dd.ROUTED, out.reason
    assert posted["url"] == _ENDPOINT
    assert out.engine_response is not None


def test_the_slot_reaches_the_engine_with_its_DECLARED_TYPE(run):
    """The integer defect, end to end on this path. A spoken answer is text; `lot` is declared
    integer; the engine indexes an int-keyed dict. Sending "4" produced a refusal that listed
    the value it had just rejected."""
    out, posted = run(bound={"lot": "4"})
    assert out.accepted_params == {"lot": 4}
    assert posted["body"]["params"] == {"lot": 4}
    assert isinstance(posted["body"]["params"]["lot"], int)


def test_the_user_phrase_travels_UNCOMPOSED(run):
    """The rewrite fold. The phrase the engine sees is what the person asked; the answer rides
    beside it in params, never concatenated into it."""
    _, posted = run()
    assert posted["body"]["query"] == "where did the money go"


# ── the verifier is not optional ────────────────────────────────────────────

def test_an_unreachable_verifier_FALLS_BACK_rather_than_abstaining(run):
    """COULD NOT CHECK is not NOTHING IS COMPATIBLE. The full run has its own handling; this
    path must not turn a substrate blip into a refusal."""
    out, posted = run(err="connection refused")
    assert out.kind == dd.FALL_BACK
    assert "verifier" in out.reason
    assert not posted, "the engine was called without a confirmed route"


def test_a_verb_that_is_no_longer_compatible_FALLS_BACK(run):
    """The invalidation. Entitlements revoked, engine retired, TTL re-primed — or the person
    PICKING has a different persona from the one who asked, since compatibility is re-read
    under the picker."""
    out, posted = run(verbs=[])
    assert out.kind == dd.FALL_BACK
    assert "no longer compatible" in out.reason
    assert not posted


def test_the_engine_is_never_called_before_the_verifier_confirms(run):
    """The ordering, which is the whole safety property. Asserted on both failure paths
    because a dispatch that happens and is then discarded has still happened."""
    for kwargs in ({"err": "boom"}, {"verbs": []}):
        _, posted = run(**kwargs)
        assert not posted, f"engine called despite {kwargs}"


# ── the arity gate, and the reason it gives ─────────────────────────────────

def test_a_single_asset_verb_with_no_slot_ASKS_rather_than_dispatching(run):
    """THE ONE-OPTION-MENU CASE. A pick that lands back here is a second ask, not an error —
    and the engine must not be called with a set query."""
    out, posted = run(bound={})
    assert out.kind == dd.ASK
    assert out.reason == "needs_instance"
    assert not posted


def test_a_REFUSED_slot_says_so_rather_than_claiming_needs_instance(run):
    """Both arrive with empty params and they are different events: an ask not yet answered,
    versus one answered and rejected. Reporting `needs_instance` for the second sends a
    reader looking for an answer they already gave — a plausible reason that is not the real
    one, which is the family of `classify_called` reporting false for a classifier that ran."""
    out, _ = run(bound={"lot": "abc"})
    assert out.kind == dd.ASK
    assert "refused" in out.reason and "wrong-shape" in out.reason
    assert [r["reason"] for r in out.refusals] == ["wrong-shape"]


def test_a_multi_arity_verb_does_not_ask(run):
    """The control on the gate. A flag that is always on would make every pick ask forever."""
    out, posted = run(arity="set", bound={})
    assert out.kind == dd.ROUTED
    assert posted


# ── the engine failing is not the same as the route being wrong ─────────────

def test_an_engine_that_does_not_answer_ABSTAINS_rather_than_falling_back(run):
    """The verb was right. Re-running through Dagster would call the same engine again and
    fail twenty seconds later — a slower copy of the same answer."""
    out, posted = run(boom=True)
    assert out.kind == dd.ABSTAIN
    assert "engine did not answer" in out.reason
    assert posted, "it should have tried"
    assert out.routing_mat is not None, "the routing record must survive an engine failure"


# ── the materializations the gateway will project ───────────────────────────

def _md(mat: dict) -> dict:
    out = {}
    for e in mat["metadataEntries"]:
        out[e["label"]] = e.get("text", e.get("floatValue", e.get("boolValue")))
    return out


def _projector_labels(fn_name: str) -> set:
    """The labels the gateway's projector actually reads, by AST — never a copied list.

    A literal set here would drift the moment someone adds a `md.get(...)` to the projector,
    and the drift is silent in exactly the direction that matters: the new label projects as
    a default and the card shows a blank where a fact belongs."""
    import ast
    import re
    gw = (Path(__file__).resolve().parents[2] / "src" / "iagent" / "gateway.py").read_text(
        encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(gw))
              if isinstance(n, ast.FunctionDef) and n.name == fn_name)
    return set(re.findall(r"md\.get\('([a-z_]+)'", ast.unparse(fn)))


def test_the_routing_record_carries_every_label_the_projector_reads(run):
    """ONE PROJECTOR, TWO PRODUCERS. `_project_route_decision` reads a fixed set of labels; a
    direct-path materialization missing one projects as a silent default — the producer/
    consumer defect this repo has closed four times.

    THIS TEST SURVIVED ITS OWN MUTATION ON 2026-09-08. It built a materialization from a
    hand-written kwarg list and asserted THAT covered the projector, so deleting
    `owner_persona` from the dispatch left it green: it was checking the fixture, not the
    code. It now runs the real dispatch and reads the record the real dispatch emitted.

    EXACT EQUALITY ON THE GAP, not a subset. `fallback_reason` is legitimately absent — there
    was no fallback, and `materialization` drops None rather than emitting an empty string
    that reads as a reason. Asserting equality means a label going missing goes red AND a
    label appearing that this test never reasoned about goes red too."""
    wanted = _projector_labels("_project_route_decision")
    assert len(wanted) >= 15, f"the projector contract looks wrong: {sorted(wanted)}"

    # An instance is supplied so `subject_instance_id`/`_label` are genuinely emitted; with
    # no instance they are correctly None-dropped and the assertion below would be weaker
    # for a reason unrelated to what it tests.
    out, _ = run(arity="set", instance="urn:lot:4", label="Lot 4")
    assert out.kind == dd.ROUTED, out.reason
    missing = wanted - set(_md(out.routing_mat))
    assert missing == {"fallback_reason"}, (
        f"routing labels the projector reads but the dispatch does not emit: "
        f"{sorted(missing - {'fallback_reason'})} — each projects as a silent default"
    )


def _run_producer_labels() -> tuple:
    """What the DAGSTER path emits, by AST, for (routing_decision, graph_trace).

    `_log_subtask_route_assets` builds `routing_meta` as a dict literal and then adds four
    more keys under `if predicate:` — the matched path, which is the only path the direct
    path can be on. Both are collected; a key added to either one appears here without
    anyone remembering to update a list.
    """
    import ast
    sup = (Path(__file__).resolve().parents[2] / "src" / "iagent" / "defs"
           / "dynamic_supervisor.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(sup))
              if isinstance(n, ast.FunctionDef) and n.name == "_log_subtask_route_assets")
    routing, trace = set(), set()
    for node in ast.walk(fn):
        # `routing_meta["x"] = ...` — the four keys added under `if predicate:`
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Subscript) and getattr(t.value, "id", "") == "routing_meta":
                    if isinstance(t.slice, ast.Constant):
                        routing.add(t.slice.value)
        # The dict literal itself. It is `routing_meta: Dict[str, Any] = {...}` — an
        # ANNOTATED assignment, so an `ast.Assign` walk finds only the four subscripts and
        # silently reports a 4-label contract. Caught by the `>= 15` floor below, which is
        # the whole reason a scrape gets a positive control: an under-reading scrape makes
        # the comparison PASS while checking almost nothing.
        elif isinstance(node, ast.AnnAssign):
            if (getattr(node.target, "id", "") == "routing_meta"
                    and isinstance(node.value, ast.Dict)):
                routing |= {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
        # the graph-trace materialization is an inline `metadata={...}` keyword
        if isinstance(node, ast.keyword) and node.arg == "metadata" and isinstance(
            node.value, ast.Dict
        ):
            keys = {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
            if "picked_verb_iri" in keys:
                trace |= keys
    return routing, trace


def test_the_two_producers_emit_THE_SAME_LABELS(run):
    """BYTE-EQUALITY AGAINST THE RUN, derived rather than transcribed.

    The Dagster run and this module both feed ONE projector. A label the run emits and this
    path does not is a field that appears or disappears depending on which path answered —
    invisible in every test that exercises one path at a time, and the exact shape of the
    card/routing-record divergence this repo already paid for.

    THIS COMPARISON FOUND THREE REAL OMISSIONS on 2026-09-08, none of which the
    projector-coverage test above could see because `_project_route_decision` does not read
    them: `output_uri`, `sub_query`, and — the load-bearing one — `route_status` on the graph
    trace, which is the key `_primary_routing_mat` selects by. A consumer that starts reading
    any of them would have found the fast path blank.

    ONE-WAY, DELIBERATELY. The direct path must emit everything the run does; it may emit
    MORE, because a path that knows something the run does not should say so. What it must
    never do is know less.
    """
    run_routing, run_trace = _run_producer_labels()
    assert len(run_routing) >= 15 and len(run_trace) >= 4, (
        f"the run-producer scrape looks wrong: {sorted(run_routing)} / {sorted(run_trace)}"
    )
    out, _ = run(arity="set", instance="urn:lot:4", label="Lot 4")

    missing_routing = run_routing - set(_md(out.routing_mat))
    assert missing_routing == {"fallback_reason"}, (
        f"the run emits routing label(s) the direct path does not: "
        f"{sorted(missing_routing - {'fallback_reason'})}"
    )
    missing_trace = run_trace - set(_md(out.graph_trace_mat))
    assert not missing_trace, (
        f"the run emits graph-trace label(s) the direct path does not: {sorted(missing_trace)}"
    )


def test_the_graph_trace_carries_every_label_ITS_projector_reads(run):
    """The second projector, sealed the same way. `_project_graph_trace` reads three labels
    and a missing one empties the decision-path fan with no error anywhere."""
    out, _ = run()
    missing = _projector_labels("_project_graph_trace") - set(_md(out.graph_trace_mat))
    assert not missing, f"graph-trace labels not emitted: {sorted(missing)}"


def test_numbers_are_emitted_as_NUMBERS_not_text(run):
    """`_metadata_dict` returns raw values by type. A float sent as text reads back as a
    string and every comparison against it silently fails — the confidence bar would render
    from a value that is never less than any threshold."""
    out, _ = run()
    md = _md(out.routing_mat)
    assert md["subject_confidence"] == 1.0 and isinstance(md["subject_confidence"], float)
    assert md["classify_called"] is False, "a bool sent as text is truthy for any non-empty"


def test_classify_called_is_FALSE_because_no_classifier_ran(run):
    """Recorded, not inferred — and true on this path by construction."""
    assert _md(run()[0].routing_mat)["classify_called"] is False


def test_the_graph_trace_names_the_verb_that_was_picked(run):
    out, _ = run()
    md = _md(out.graph_trace_mat)
    assert md["picked_verb_iri"] == _VERB and md["subject_uri"] == _SUBJ
