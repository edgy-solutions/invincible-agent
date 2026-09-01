"""ARITY IS DERIVED FROM THE SIGNATURE, NOT FROM THE PROSE.

`arity` is the query-shape half of verb eligibility: `_filter_verbs_by_arity` drops a
verb declaring "single" from a set-shaped query (`query_is_set = not
subject_instance_id`), so a question that named no instance stops being routed to a verb
that cannot answer it. Today that same question routes there and gets a 400 for a missing
mandatory slot, two hops later.

WHY A DERIVATION AND NOT A LITERAL. The registration loop next door already derives
`slots` from each measure's signature, precisely so the declaration cannot drift from the
code. A hand-written arity map is the drift shape that discipline exists to prevent: a
signature gains a required parameter, the map does not, and the verb keeps advertising a
shape it no longer has — silently, because nothing compares them.

WHY *THIS* RULE. `plan_dependency_neighborhood` and `plan_dependency_violations` sit a
paragraph apart in the VERBS table with opposite arities, and their descriptions argue
about it at length. The load-bearing discriminator is not in the prose — it is
`project_id: str` with NO default versus no such parameter at all. A REQUIRED REFERENT
means the question has to name something. An OPTIONAL referent is a filter on a
portfolio-wide answer (`plan_schedule`'s `scope_initiative_id`) and leaves the verb
set-shaped.

HISTORY WORTH KEEPING: until 2026-08-31 `arity` reached no Neo4j edge from any of the five
write sites, so the gate read null for every verb, treated null as "never exclude", and
excluded nothing on any cluster since it shipped — while its own unit tests stayed green,
because they build their verb dicts by hand. See
docs/plans/two-eligibility-gates-were-inert-and-green.md.

Run: uv run --frozen pytest tests/planning/test_arity_is_derived_from_the_signature.py -v
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agent_fleet.planning_agent import measures  # noqa: E402
from agent_fleet.planning_agent.slots import arity_for, slots_for  # noqa: E402

# The four measures that cannot run without one named instance. Written out so the SET is
# reviewable — a derivation nobody has looked at is just a different place to be wrong.
_SINGLE = {
    "plan_dependency_neighborhood",   # project_id
    "plan_capability_path",           # capability_id
    "plan_process_evolution",         # process_id
    "plan_tech_footprint",            # tech_id
}


def _measure_names() -> list[str]:
    from agent_fleet.planning_agent.main import VERBS
    return [v["fn"] for v in VERBS]


def test_the_derivation_matches_the_reviewed_set():
    got = {fn for fn in _measure_names() if arity_for(fn) == "single"}
    assert got == _SINGLE


def test_everything_else_declares_nothing():
    """None, not "any" and not "set". The gate reads null as never-exclude, and a verb
    that has not thought about its arity must not assert one."""
    for fn in _measure_names():
        if fn not in _SINGLE:
            assert arity_for(fn) is None, fn


def test_single_is_TRUE_of_each_signature_independently():
    """THE ANTI-TAUTOLOGY ARM. The two tests above compare the derivation against a set I
    wrote down; if I copied that set FROM the derivation they are both vacuous. This one
    re-derives from `inspect.signature` directly — no slots.py — so the claim is checked
    against the code rather than against itself."""
    for fn in sorted(_SINGLE):
        sig = inspect.signature(getattr(measures, fn))
        required = [
            n for n, p in sig.parameters.items()
            if p.default is inspect.Parameter.empty and n not in ("state", "self")
        ]
        assert required, f"{fn} is declared single but has no required parameter"


def test_an_OPTIONAL_referent_does_not_make_a_verb_single():
    """`plan_schedule` takes `scope_initiative_id` — a referent, and a FILTER. Narrowing a
    portfolio-wide answer is not the same as needing one named thing to answer at all, and
    conflating them would strip the whole planning surface out of set-shaped routing."""
    names = {d["name"] for d in slots_for("plan_schedule") if d.get("referent")}
    assert names, "plan_schedule should still declare referent slots"
    assert arity_for("plan_schedule") is None


def test_a_ROUTE_SUPPLIED_handle_cannot_make_a_verb_single():
    """`plan_commit_scenario` has the most slots of any measure and is set-shaped. A handle
    is resolved by the dispatcher from the store and was never something a speaker names,
    so it must not count as a referent the question has to supply. This falls out of
    `slots_for` marking `referent` on spoken slots only — the test pins the consequence."""
    assert slots_for("plan_commit_scenario"), "expected slots on plan_commit_scenario"
    assert arity_for("plan_commit_scenario") is None


def test_the_gate_actually_excludes_the_derived_set():
    """Close the loop on the real filter, using declarations built by the real derivation."""
    sys.path.insert(0, str(_REPO / "src"))
    from iagent.defs.dynamic_supervisor import _filter_verbs_by_arity  # noqa: PLC0415

    verbs = [{"verb_iri": fn, "arity": arity_for(fn)} for fn in _measure_names()]
    kept, dropped = _filter_verbs_by_arity(verbs, query_is_set=True)
    assert {v["verb_iri"] for v in dropped} == _SINGLE
    assert len(kept) == len(verbs) - len(_SINGLE)

    # An instance-shaped query keeps everything — the conservative direction.
    kept2, dropped2 = _filter_verbs_by_arity(verbs, query_is_set=False)
    assert dropped2 == [] and len(kept2) == len(verbs)
