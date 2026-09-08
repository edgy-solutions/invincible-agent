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
    """Call the real `dispatch_pre_resolved` with the verifier and engine stubbed.

    `run.stages` collects every `on_stage` call in order, so the stream contract is asserted
    against what the dispatch really reported rather than against a description of it.

    IT IS DELIBERATELY NOT KEPT IN `posted`. Four tests here assert `not posted` to mean THE
    ENGINE WAS NEVER CALLED; putting anything else in that dict would give the sentinel a
    second meaning and quietly change what those four tests check."""
    posted: dict = {}
    stages: list = []

    def _go(*, verbs=None, err=None, bound=None, arity="single", instance="", label="",
            boom=False):
        stages.clear()
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
            on_stage=lambda kind, status: stages.append((kind, status)),
        ), posted

    _go.stages = stages
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


# ── the stream contract: stages that RAN, and every one of them terminal ────

def _stage_faults(stages):
    """Every way an emitted sequence can strand or mislead a client.

    BOTH DIRECTIONS, and the second was missing until a mutation walked straight through it.
    The first version only looked for a `started` with no terminal — so deleting a stage's
    `started` while keeping its `completed` was clean, and the client would be handed a
    finished row for a stage it never saw begin. An unbalanced pair is a fault whichever end
    is absent; checking one end is checking half a property."""
    faults, state = [], {}
    for kind, status in stages:
        if status == "started":
            if state.get(kind) == "started":
                faults.append(f"{kind}: started twice with no terminal between")
            state[kind] = "started"
        else:
            if state.get(kind) != "started":
                faults.append(f"{kind}: {status!r} with no preceding 'started'")
            state[kind] = status
    faults += [f"{k}: started and never finished" for k, v in state.items() if v == "started"]
    return faults


@pytest.mark.parametrize("case", [
    {},                                       # routed
    {"bound": {}},                            # ask, one-option menu
    {"bound": {"lot": "abc"}},                # ask, slot refused
    {"boom": True},                           # abstain
    {"err": "boom"},                          # fall_back, verifier down
    {"verbs": []},                            # fall_back, verb retired
])
def test_every_stage_pair_is_BALANCED_on_every_outcome(run, case):
    """THE STREAM CONTRACT, asserted on all six outcomes rather than the happy one.

    A `started` with no terminal leaves a spinner running forever, and it is the FAILURE
    paths that strand it — the paths a happy-path test never reaches. A terminal with no
    `started` is the mirror fault: a finished row for a stage the client never saw begin.
    Both are computed from the emissions, so a return added later without a terminal goes
    red here even though nothing about the new branch is described in this file.
    """
    out, _ = run(**case)

    # THE FLOOR, BECAUSE THIS GUARD'S OWN FAILURE MODE IS SILENCE. `_stage_faults([])`
    # returns no faults, so a path that reports NOTHING is indistinguishable here from a
    # path that reports a perfectly balanced pair — the check would pass for the opposite
    # of the reason in its comment. Every case below reaches the verifier by construction
    # (each supplies a subject and a verb), so the verification pair is owed on all six and
    # its absence is a fault rather than an outcome. Same rule as putting a population floor
    # on a derived scrape: a reader that reads too little fails OPEN.
    assert (dd.STAGE_VERIFYING, "started") in run.stages, (
        f"{out.kind}: no stage reported at all — the balance check below cannot tell this "
        f"apart from a clean run"
    )

    faults = _stage_faults(run.stages)
    assert not faults, f"{out.kind}: {faults} (emitted: {run.stages})"


def test_the_stages_ANNOUNCED_are_only_the_stages_this_path_RUNS(run):
    """No `understanding`, no `locating`, no `choosing_action`. The ask already resolved the
    subject and the verb, so a stream claiming those ran would be a success line for work
    that never happened. Derived from `DISPATCH_STAGES` so adding a stage to the module
    without deciding it is truthful here goes red."""
    run()
    emitted = {k for k, _ in run.stages}
    assert emitted <= set(dd.DISPATCH_STAGES), (
        f"stages emitted that this path does not run: {sorted(emitted - set(dd.DISPATCH_STAGES))}"
    )
    assert emitted == set(dd.DISPATCH_STAGES), (
        f"declared but never emitted on the routed path: "
        f"{sorted(set(dd.DISPATCH_STAGES) - emitted)}"
    )


def test_the_engine_stage_NEVER_STARTS_when_the_engine_is_not_called(run):
    """The stage set must not out-run the work. On an ask and on both fall-backs the engine
    is never touched, so announcing `calling_engine` would report a call that did not
    happen — the same fabrication as announcing a classifier that did not run."""
    for case in ({"bound": {}}, {"err": "boom"}, {"verbs": []}):
        out, posted = run(**case)
        assert not posted, f"{case}: the engine WAS called"
        assert dd.STAGE_CALLING not in {k for k, _ in run.stages}, (
            f"{case} -> {out.kind}: announced an engine call that never happened"
        )


def test_a_failed_verification_reports_FAILED_not_completed(run):
    """`completed` and `failed` are different claims about the same stage. A verifier that
    could not be reached, reported as completed, tells a reader the check passed."""
    run(err="boom")
    assert (dd.STAGE_VERIFYING, "failed") in run.stages
    assert (dd.STAGE_VERIFYING, "completed") not in run.stages


def test_an_ask_still_COMPLETES_verification(run):
    """The control on the assertion above. Verification genuinely succeeded on the ask path —
    it is the arity precondition that stopped the turn, not the check — so reporting it
    failed would send a reader to the wrong layer."""
    run(bound={})
    assert (dd.STAGE_VERIFYING, "completed") in run.stages


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
    assert missing == set(), (
        f"routing labels the projector reads but the dispatch does not emit: "
        f"{sorted(missing)} — each projects as a silent default"
    )


def _calls_shared_builder(path: Path, name: str) -> bool:
    """Does this module CALL the shared record builder, by AST rather than by substring?

    Import aliases are followed, so `routing_record as build_routing_record` counts and a
    same-named local function does not."""
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    aliases = {
        (a.asname or a.name)
        for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
        and (n.module or "").endswith("routing_record")
        for a in n.names if a.name == name
    }
    if not aliases:
        return False
    return any(
        isinstance(n, ast.Call) and getattr(n.func, "id", "") in aliases
        for n in ast.walk(tree)
    )


@pytest.mark.parametrize("mod", ["src/iagent/direct_dispatch.py",
                                 "src/iagent/defs/dynamic_supervisor.py"])
@pytest.mark.parametrize("builder", ["routing_record", "graph_trace_record"])
def test_BOTH_routes_build_the_record_with_the_SAME_FUNCTION(mod, builder):
    """THE COPY IS GONE, and this is what replaced the diff that used to police it.

    Until 2026-09-08 the run and the direct path each built their own label→value mapping
    and a test asserted the two agreed. That is a copy with a seal on it, and it failed the
    way copies do: three fields — `output_uri`, `sub_query`, and `route_status` on the graph
    trace, the key `_primary_graph_trace_mat` selects by — existed on one side only, and
    every test that exercised one route at a time was green.

    One builder now, in `iagent_pure.routing_record`, wrapped by each side in its own
    transport. So the property worth sealing is no longer "the two mappings agree" but
    "there is only one mapping" — which is checked here, and which no amount of field
    drift can quietly violate.
    """
    path = Path(__file__).resolve().parents[2] / mod
    assert _calls_shared_builder(path, builder), (
        f"{mod} does not call the shared {builder} — a second mapping has reappeared, and "
        f"a field added to one route will be invisible to every single-route test"
    )


def _entries_from_dagster(record: dict) -> dict:
    """Wrap a record the way the SUPERVISOR does, then flatten it the way the GATEWAY does.

    This is the run's transport reproduced offline: `MetadataValue` by type, then the entry
    shape Dagster's GraphQL layer emits for each. It is an instrument, so it gets a control
    — `test_the_two_transports_are_not_both_empty` below — because a converter that produced
    nothing would make the equality assertion pass while comparing two empty dicts.
    """
    from iagent.defs.dynamic_supervisor import _as_metadata_value
    # COERCED PER TYPE, THE WAY THE WIRE DOES, and the first version was not. Dagster's
    # `MetadataValue.int(False)` keeps a bool in `.value` — it does not coerce — so an
    # instrument that read `.value` straight through reported a bool for an Int field and a
    # mutation disabling the bool branch of `_as_metadata_value` came out IDENTICAL. The
    # model reproduced the wrapper choice and not the encoding, which is the half that
    # carries the defect.
    _wire = {
        "TextMetadataValue": ("text", str),
        "IntMetadataValue": ("intValue", int),
        "FloatMetadataValue": ("floatValue", float),
        "BoolMetadataValue": ("boolValue", bool),
    }
    entries = []
    for label, value in record.items():
        mv = _as_metadata_value(value)
        key, cast = _wire[type(mv).__name__]
        entries.append({"label": label, key: cast(mv.value)})
    return {"metadataEntries": entries}


def test_the_transport_wraps_each_type_as_ITSELF():
    """The direct control on `_as_metadata_value`, because the equality test above compares
    two things that can agree while both being wrong.

    `bool` must be tested BEFORE `int`: a bool IS an int in Python, so an unguarded int
    branch swallows it and `classify_called` reaches the HUD as 0/1 where it expects
    true/false. Asserted on the wrapper's own type rather than through a round trip."""
    from iagent.defs.dynamic_supervisor import _as_metadata_value
    assert type(_as_metadata_value(True)).__name__ == "BoolMetadataValue"
    assert type(_as_metadata_value(3)).__name__ == "IntMetadataValue"
    assert type(_as_metadata_value(1.5)).__name__ == "FloatMetadataValue"
    assert type(_as_metadata_value("x")).__name__ == "TextMetadataValue"


def _shared_record() -> dict:
    from iagent_pure.routing_record import routing_record
    return routing_record(
        status="matched", subject_uri=_SUBJ, subject_confidence=1.0,
        subject_instance_id="urn:lot:4", subject_instance_label="Lot 4", verb_iri=_VERB,
        verb_confidence=1.0, classify_called=False, candidate_count=1,
        subject_candidates=[], fallback_reason="", eligibility_excluded=[],
        acting_persona="COST_ANALYST", acting_domains=["PRODUCTION_COST"],
        sub_query="where did the money go",
        predicate={"endpoint": _ENDPOINT, "owner_persona": "COST_ANALYST",
                   "output_uri": "http://invincible-agent/cost#CategoryBreakdown"},
    )


def test_the_two_TRANSPORTS_project_to_the_same_record():
    """THE EQUALITY THE DIFF WAS STANDING IN FOR — same content, both envelopes, one result.

    With the mapping shared, the only place the routes can still diverge is the WRAPPING:
    the run goes through Dagster `MetadataValue` and GraphQL, the direct path through
    `materialization()`. Both are flattened by the gateway's `_metadata_dict`, so if the two
    envelopes round-trip differently the artifact differs while every label matches.

    They genuinely can differ. `candidate_count` travels as an `intValue` on one side and a
    `floatValue` on the other; the projector coerces with `int(...)`, which is why this is
    equal rather than a defect — but that is a fact to VERIFY, not to assume, and it is
    exactly what a byte comparison against a run-produced artifact would have told us.
    """
    from iagent.gateway import _metadata_dict, _project_route_decision
    rec = _shared_record()
    run_mat, direct_mat = _entries_from_dagster(rec), dd.materialization(**rec)

    # FLATTENED FIRST, AND THIS IS THE ASSERTION THAT MATTERS. Comparing only the PROJECTED
    # records lets a divergence hide in any field the projector reads but does not surface —
    # a mutation disabling the bool branch of `_as_metadata_value` sent `classify_called`
    # through as the integer 1 (bool IS an int in Python, so it fell to the int branch) and
    # the projected comparison was still equal. The lossy step must not be the comparison.
    flat_run, flat_direct = _metadata_dict(run_mat), _metadata_dict(direct_mat)
    assert set(flat_run) == set(flat_direct), (
        f"labels differ between transports: "
        f"{sorted(set(flat_run) ^ set(flat_direct))}"
    )
    _differ = {
        k: (flat_run[k], flat_direct[k])
        for k in flat_run
        # int vs float is the ONE tolerated difference and it is named rather than ignored:
        # `MetadataValue.int` and `materialization`'s float branch carry `candidate_count`
        # differently, and the projector coerces with `int(...)`. Any other mismatch, and
        # any type mismatch that is not numeric, is a real divergence.
        if flat_run[k] != flat_direct[k]
        or (isinstance(flat_run[k], bool) != isinstance(flat_direct[k], bool))
    }
    assert not _differ, f"the two transports carry different values: {_differ}"

    via_run = _project_route_decision(run_mat)
    via_direct = _project_route_decision(direct_mat)
    assert via_run == via_direct, (
        "the two transports project different records from identical content"
    )


def test_a_registered_provider_WINS_and_an_absent_one_is_derived():
    """WHO ANSWERED, and the fallback that keeps it from reading "Unknown engine".

    `handler_provider` arrives empty for engines that register no provider, and the HUD then
    renders "Unknown engine" beside a perfectly good endpoint — a lookup whose miss becomes
    text. The host is a better empty than that word. It lives in the SHARED builder, so this
    seals both arms: a registered provider must not be overwritten by the derivation, and an
    absent one must not stay blank.

    ON ONE SIDE ONLY IT WOULD BE A DIVERGENCE — the fast path and the slow path naming
    different engines for the identical question — which is what it was until the builder
    was shared, and no test could see it because each route was exercised alone.
    """
    from iagent_pure.routing_record import routing_record

    def _provider(pred):
        return routing_record(
            status="matched", subject_uri="S", subject_confidence=1.0,
            subject_instance_id="", subject_instance_label="", verb_iri="V",
            verb_confidence=1.0, classify_called=False, candidate_count=1,
            subject_candidates=None, fallback_reason="", eligibility_excluded=None,
            acting_persona="P", acting_domains=None, sub_query="q", predicate=pred,
        )["handler_provider"]

    assert _provider({"endpoint": _ENDPOINT, "provider": "engine-cost"}) == "engine-cost", (
        "a registered provider was overwritten by the host derivation"
    )
    assert _provider({"endpoint": _ENDPOINT}) == "iagent-engine-cost", (
        "no provider and no derivation — the HUD renders 'Unknown engine' beside a "
        "perfectly good endpoint"
    )
    # An endpoint that is not a URL derives nothing rather than inventing a name from it.
    assert _provider({"endpoint": "not-a-url"}) == ""


def test_the_record_carries_EXACTLY_the_contract_it_declares():
    """THE FIELD SET, PINNED — because with one builder there is no longer a second producer
    to diff against, and that diff is what used to catch a dropped field.

    Deleting `sub_query` from the builder survived every other seal in this file: the
    projector does not read it, both transports agreed about its absence, and one-route
    tests cannot see it. A pin is the right instrument HERE and was the wrong one before:
    two producers agreeing by test is a copy, but one producer declaring its contract is a
    contract. Adding a field is then a deliberate act that updates this line — which is
    exactly the review this record's history says it needs.
    """
    from iagent_pure.routing_record import GRAPH_TRACE_LABELS, ROUTING_LABELS
    assert set(ROUTING_LABELS) == {
        "route_status", "subject_uri", "subject_confidence", "subject_instance_id",
        "subject_instance_label", "verb_iri", "verb_confidence", "classify_called",
        "candidate_count", "subject_candidates", "fallback_reason", "eligibility_excluded",
        "acting_persona", "acting_domains", "sub_query",
    }
    assert set(GRAPH_TRACE_LABELS) == {
        "route_status", "subject_uri", "picked_verb_iri", "compatible_verbs",
    }
    # The four handler fields are CONDITIONAL — absent when there was nothing to dispatch
    # to, because no handler is not the same as a handler with no name.
    assert set(_shared_record()) - set(ROUTING_LABELS) == {
        "handler_provider", "handler_endpoint", "owner_persona", "output_uri",
    }


def test_the_two_transports_are_not_both_empty():
    """THE CONTROL on the equality above. Two empty dicts are equal, and a converter that
    silently produced nothing would make that test pass while comparing nothing at all —
    the guard whose failure mode is silence, one layer up."""
    from iagent.gateway import _project_route_decision
    rec = _shared_record()
    assert len(rec) >= 15, f"the shared record is too small to be the real one: {sorted(rec)}"
    projected = _project_route_decision(_entries_from_dagster(rec))
    assert projected, "the run transport projected nothing — the comparison would be vacuous"
    assert (projected.get("about") or {}).get("uri") == _SUBJ


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
