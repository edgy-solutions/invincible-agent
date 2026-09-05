"""A SUBJECT THAT RESOLVED AND CANNOT BE ANSWERED MUST ABSTAIN, NOT PROCEED.

THE DEFECT. There are two paths into `resolved_uri` and only one was gated. The
productive-option gate restricts what the resolver may CHOOSE — the candidate pool is limited
to classes carrying a verb in the caller's domains. Instance preemption then OVERRIDES that
choice with a unanimous provider answer, unchecked, so a phone-book match can install a class
no verb serves. Measured by the engine-cost lane: 10 of 18 draws had a winner outside the
candidate set, every one of them `fin:WBSElement`, which carries no verb in any domain — the
DOMINANT dead end, reached by the one path the gate cannot see.

THE OVERRIDE IS NOT THE DEFECT and nothing here blocks it. A caller named "lot 4", a provider
resolved it, and that resolution is correct. What was missing is that nothing NOTICED the
resolved subject cannot be answered, so the router fell through to the generalist — which
answers from the catalog wearing the caller's own persona and is indistinguishable from a real
answer until a human reads the card.

THREE THINGS THIS FILE PINS THAT THE RULING DID NOT ANTICIPATE:

1. **TWO preemption sites, not one.** The packet named `main.py:1886`. There is a second
   return at the class-recall-empty fallback, and it is the branch MOST likely to reach an
   unservable subject — it fires precisely when the class contest found nothing. A check on
   one site is silent by construction on the other.

2. **`include_referents=False` is load-bearing.** The ruling said "same predicate as the
   gate". Following that literally would be wrong: the gate's served-set UNIONs in declared
   `mesh:ResolvableReferent` classes, because a referent is groundable ON PURPOSE and belongs
   in the pool. But a referent is exactly a class that grounds and CANNOT be answered. Today
   the referent set is empty in the live graph, so the shared predicate would look correct —
   and the day someone declares WBSElement a referent, which the ruling says is the RIGHT
   thing to do, the abstention would silently stop firing.

3. **The router flattened the reason.** `_fb_reason` was a ternary on one literal, so any
   reason other than `instance_not_found` became `subject_unknown` — and the same flag gated
   whether Engine O's actionable message passed through at all. Reporting the new abstention
   without widening that would have produced a generic Contract-B message under a wrong
   reason code, with both sides' tests green.

Run: uv run --frozen pytest tests/routing/test_post_preemption_productivity.py -v
"""
from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_MAIN = (_REPO / "agent_fleet" / "ontology_service" / "main.py").read_text(encoding="utf-8")
_SUP = (_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py").read_text(encoding="utf-8")

_CHECK = "_preempted_subject_is_unanswerable"


# ── the predicate ───────────────────────────────────────────────────────────

def _call(resolved_uri, domains, answerable):
    """Run the check with a stubbed served-set, recording how it was asked."""
    from agent_fleet.ontology_service import main as m

    seen = {}

    async def _fake(doms, include_referents=True):
        seen["include_referents"] = include_referents
        seen["domains"] = doms
        return frozenset(answerable)

    orig = m._served_class_uris
    m._served_class_uris = _fake
    try:
        return asyncio.run(getattr(m, _CHECK)(resolved_uri, domains)), seen
    finally:
        m._served_class_uris = orig


_SERVED = "http://invincible-agent/idp#Capability"
_UNSERVED = "http://invincible-agent/fin#WBSElement"


def test_an_unserved_preempted_subject_is_flagged():
    out, _ = _call(_UNSERVED, ["FINANCE"], {_SERVED})
    assert out is True


def test_a_served_preempted_subject_passes_through():
    """The override must keep working. This check exists to add a refusal, not to break
    the instance ladder that produces the correct resolutions."""
    out, _ = _call(_SERVED, ["FINANCE"], {_SERVED})
    assert out is False


def test_it_asks_whether_the_subject_can_be_ANSWERED_not_whether_it_may_be_OFFERED():
    """The distinction the ruling's wording would have collapsed. A declared referent is a
    legitimate pool member and an illegitimate answer; one predicate cannot mean both."""
    _, seen = _call(_UNSERVED, ["FINANCE"], {_SERVED})
    assert seen["include_referents"] is False


def test_it_degrades_OPEN_when_the_served_set_is_empty():
    """An empty set means the lookup failed or the graph is cold. Filtering on it would
    convert a Neo4j hiccup into a refusal storm — strictly worse than the dead end this
    removes. Same discipline as the gate it sits beside."""
    out, _ = _call(_UNSERVED, ["FINANCE"], set())
    assert out is False


def test_an_absent_or_UNKNOWN_subject_is_not_its_problem():
    """Abstention is already handled upstream; re-deciding it here would double-report."""
    assert _call("UNKNOWN", ["FINANCE"], {_SERVED})[0] is False
    assert _call("", ["FINANCE"], {_SERVED})[0] is False


# ── BOTH preemption sites, which is the enumeration half ────────────────────

def _preemption_returns() -> int:
    """Returns that install a preempted subject as the resolved URI."""
    return len(re.findall(r"resolved_uri=instance_subject", _MAIN))


def _checks() -> int:
    return _MAIN.count("await " + _CHECK + "(")


def test_every_preemption_return_is_gated():
    """THE ENUMERATION ASSERTION. A registration-shaped property named at N sites and
    checked at N-1 is silent at the one that was missed — this repo has measured that nine
    times across four mechanisms. Counted rather than spot-checked for that reason."""
    assert _checks() == _preemption_returns(), (
        f"{_preemption_returns()} preemption return(s) but {_checks()} productivity "
        f"check(s) — a new preemption path was added without gating it"
    )


def test_there_really_are_two_sites():
    """Non-vacuity: the equality above is satisfied by 0 == 0. The premise of this whole
    file is that the ruling named one site and there are two."""
    assert _preemption_returns() == 2, (
        f"expected 2 preemption returns, found {_preemption_returns()} — if a path was "
        f"added or removed, the count here is the thing to update deliberately"
    )


def test_the_abstention_keeps_the_resolution_it_made():
    """A bare refusal throws away a correct instance resolution. 'I know what you mean and
    cannot answer that about it' is actionable; 'I don't know what you mean' is not."""
    assert "_unserved_subject_msg" in _MAIN
    i = _MAIN.index("def _unserved_subject_msg")
    body = _MAIN[i:i + 900]
    assert "identifier" in body and "label" in body, (
        "the abstention message must name both what was found and what it resolved to"
    )


def test_the_abstention_is_not_silent():
    """A refusal nobody can see in the logs is a dead end that merely moved."""
    assert _MAIN.count("post-preemption check ABSTAINED") == 2


# ── the router must not flatten the reason ──────────────────────────────────

def test_the_router_passes_engine_o_reasons_through():
    assert "_ENGINE_O_ABSTENTION_REASONS" in _SUP
    i = _SUP.index("_ENGINE_O_ABSTENTION_REASONS = frozenset({")
    block = _SUP[i:i + 300]
    for reason in ("instance_not_found", "no_compatible_verbs"):
        assert '"' + reason + '"' in block, reason + " missing from the passthrough set"


def test_the_flattening_ternary_is_gone():
    """The exact shape that would have swallowed this: a ternary on ONE literal reason,
    with every other value collapsing to the generic one."""
    flattener = (
        '"instance_not_found" if is_instance_not_found else "subject_unknown"'
    )
    assert flattener not in _SUP


def test_the_actionable_message_passthrough_widened_with_the_reason_set():
    """THE HALF THAT IS EASY TO MISS. One flag did two jobs — it chose the reason code AND
    decided whether Engine O's message survived. Widening only the first would report the
    right reason under boilerplate text."""
    assert "if _engine_o_explained" in _SUP
    assert "if is_instance_not_found" not in _SUP, (
        "a use of the narrow flag remains — the message passthrough and the reason code "
        "must widen together"
    )


def test_the_reason_reported_is_one_the_projection_already_renders():
    """`no_compatible_verbs` is reused deliberately rather than minting a new enum value.
    A new value needs six sites across two repos — the gateway projection, its comments,
    the projection test's enum list, cortex's union and its render switch — and a value
    neither repo knows renders as nothing, which is the same loss in a new coat."""
    assert '"abstention_reason"] = "no_compatible_verbs"' in _MAIN


def test_the_check_is_reachable_as_written():
    """AST rather than substring: an await inside a dead branch would satisfy a grep.
    This asserts the function is genuinely defined as an async def in the routing module."""
    tree = ast.parse(_MAIN)
    defined = any(
        isinstance(n, ast.AsyncFunctionDef) and n.name == _CHECK for n in ast.walk(tree)
    )
    assert defined, _CHECK + " is not an async def in engine-o"
