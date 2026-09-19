"""The caller's acting domains reach the resolver fan-out, so demotion can run.

MEASURED ON THE LIVE SANDBOX 2026-09-18, and it is the third of three defects behind the lot 4
regression — the one that made the other two fatal.

A COST_ANALYST asked *"how concentrated is purchasing on lot 4"*. Engine O's instrumented
emission site printed:

    terms=['lot 4', '4']  candidates=21  asked_domains=[]  demoted=[]
    claimants=['engine_cost_production_cost', 'engine_o_sustainment']
    subjects=['internal/sustainment/pcn#Component', 'invincible-agent/cost#ProductionLot']

**`asked_domains=[]`, so `demoted=[]`.** The SUSTAINMENT resolver answered a PRODUCTION_COST
caller because nothing told the fan-out who was asking. Two claimants naming two classes, and
`ambiguous_in_domain` fired — correctly — on a question with exactly one exact match. The `lot`
slot never bound, and the card asked "Which lot?" while offering the lot it had just rejected.

THE MECHANISM WAS NEVER MISSING. `_resolve_instance(identifier, query, asked_domains=None)` has
taken the parameter all along; the demote loop, its `demoted` reporting and its comment all
predate this seal. `/fill_slots` simply never passed it. **A correct mechanism with a wire nobody
connected** — R-076's shape, one layer in from where that ruling found it.

WHY IT SURVIVED A CODE BISECT. Rolling engine-o back to `cfa3f0d` reproduced the failure exactly,
because the defect is latent and was exposed by DATA ARRIVAL: the graph gained twenty
`pcn#Component` part numbers containing a 4, and the moment a second claimant existed, all three
defects fired at once. The bisect was not wasted — a negative result is what sent the search to
the data.

BOTH DIRECTIONS ARE ASSERTED, because a scoping change that demoted everything would also make
the ambiguity disappear, for the wrong reason and at the cost of every cross-domain answer.

Run: uv run --frozen pytest tests/routing/test_the_resolver_hears_the_callers_domains.py -v
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_ENGINE_O = _REPO / "agent_fleet" / "ontology_service" / "main.py"
_SUPERVISOR = _REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py"


def _engine_o() -> str:
    return _ENGINE_O.read_text(encoding="utf-8")


def _supervisor() -> str:
    return _SUPERVISOR.read_text(encoding="utf-8")


def test_the_request_model_carries_the_callers_domains():
    """The field has to exist before anything can travel on it."""
    tree = ast.parse(_engine_o())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "FillSlotsRequest":
            fields = {
                n.target.id for n in node.body
                if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
            }
            assert "acting_domains" in fields, (
                f"FillSlotsRequest has no `acting_domains`: {sorted(fields)} — the caller's "
                f"scope cannot reach the fan-out, so demotion never runs"
            )
            return
    raise AssertionError("FillSlotsRequest not found in engine-o")


def test_FILL_SLOTS_PASSES_THEM_TO_THE_RESOLVER():
    """THE WIRE, and its absence is the whole defect.

    `_resolve_instance` took `asked_domains` before this seal existed. Asserting the PARAMETER
    exists would therefore have passed throughout the outage — what has to be asserted is that
    the call site supplies it.
    """
    src = _engine_o()
    i = src.index("async def fill_slots(")
    body = src[i:src.index("\n@app.", i + 1)] if "\n@app." in src[i:] else src[i:]
    assert "_resolve_instance(" in body, "fill_slots no longer resolves instances at all"
    call = body[body.index("_resolve_instance("):]
    call = call[: call.index(")") + 1] if ")" in call else call
    assert "asked_domains" in call, (
        "fill_slots calls _resolve_instance WITHOUT asked_domains, so the fan-out runs unscoped "
        "and a SUSTAINMENT provider answers a PRODUCTION_COST caller"
    )


def test_THE_SUPERVISOR_SENDS_THE_DOMAINS_IT_HOLDS():
    """The other end. The supervisor has `config.entitled_domains` in scope at the call site and
    was sending three fields; the scope it already held never left the process."""
    src = _supervisor()
    i = src.index("def _fill_slots_from_query(")
    body = src[i:src.index("\ndef ", i + 1)]
    assert '"acting_domains"' in body, (
        "the /fill_slots request body does not carry acting_domains — the caller's scope stops "
        "at the supervisor"
    )
    # A WINDOW, NOT A BALANCED-PAREN MATCH. The first draft sliced to the next `)`, which is the
    # one inside `predicate.get("verb_iri")` — it read a TRUNCATED call and reported correct code
    # as broken. A slice that cannot see the whole construct answers about the part it saw.
    j = src.index("filled = _fill_slots_from_query(")
    call = src[j:j + 400]
    assert "acting_domains=" in call, (
        "the call site does not pass acting_domains, so the parameter defaults to empty and the "
        "wire carries nothing — a field that exists and is never filled"
    )
    assert "entitled_domains" in call, (
        "acting_domains is passed but not from the caller's entitlement — a scope invented here "
        "rather than carried"
    )


def test_AN_EMPTY_SCOPE_STILL_MEANS_UNSCOPED():
    """THE CONTROL ON THE DEFAULT, and the reason this is safe to roll.

    A caller that sends nothing must get today's behaviour exactly — an unscoped fan-out — or
    this stops being a restoration of intended behaviour and becomes a new refusal. The demote
    loop already guards on `if _asked and owns`, and that guard is what makes the default inert.
    """
    src = _engine_o()
    assert "if _asked and owns and not (owns & _asked)" in src, (
        "the demote loop no longer guards on a non-empty `_asked`, so an empty scope would "
        "demote every provider that declares a domain — every cross-domain answer lost"
    )


def test_THE_DEMOTION_IS_REPORTED_not_silent():
    """A provider removed from the pool is a fact a diagnosis needs. The instrumented emission
    site prints `demoted=[...]`, and `asked_domains=[]` with `demoted=[]` is exactly what named
    this defect — the two facts are only useful together."""
    src = _engine_o()
    assert "demoted" in src and "n_candidates" in src, (
        "the fan-out no longer records which providers it demoted, so an over-scoped request "
        "and an unscoped one look identical from outside"
    )
