"""A service identity never gets a program: the program-filtered safety verbs dispatch as the asker.

engine-safety's ADR-0056 measures filter records by the PROGRAMS the caller belongs to. The
caller is read from the bearer token's entitlement claim only (`current_caller().authz_id`), and
`_visible_records` raises `NoPerson` for an empty or `svc:` caller. Dispatched as svc:supervisor
those verbs refuse 422 `no_person` on every ask. The supervisor's person channel is
`_CALLER_IDENTITY_VERBS`; this seals that every verb whose measure can refuse `NoPerson` is in it.

The population is DERIVED from safety's source (read as text / AST, never imported), not listed.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest

_SAFETY = Path(__file__).resolve().parents[2] / "agent_fleet" / "safety_agent"


def _derive():
    """Return (seeds, derived, fn_to_verb) from safety's source."""
    tree = ast.parse((_SAFETY / "measures.py").read_text(encoding="utf-8"))
    funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    def raises_no_person(fn):
        for n in ast.walk(fn):
            if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call) \
                    and isinstance(n.exc.func, ast.Name) and n.exc.func.id == "NoPerson":
                return True
        return False

    def callees(fn):
        return {n.func.id for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}

    seeds = {f.name for f in funcs if raises_no_person(f)}
    derived = set(seeds)
    changed = True
    while changed:
        changed = False
        for f in funcs:
            if f.name not in derived and callees(f) & derived:
                derived.add(f.name)
                changed = True
    src = (_SAFETY / "main.py").read_text(encoding="utf-8")
    fn_to_verb = dict(re.findall(r'"fn":\s*"(\w+)",\s*\n\s*"verb":\s*"(mesh:\w+)"', src))
    return seeds, derived, fn_to_verb


def test_every_verb_whose_measure_can_refuse_no_person_dispatches_as_the_asker():
    from iagent.defs.dynamic_supervisor import _verb_needs_caller_identity

    seeds, derived, fn_to_verb = _derive()
    assert seeds, "no module-level function in safety's measures.py raises NoPerson: the derivation is blind"
    registered = sorted(fn for fn in derived if fn in fn_to_verb)
    assert len(registered) >= 2, f"derived {sorted(derived)}; only {registered} have a registered verb"
    unregistered = sorted(fn for fn in derived if fn not in fn_to_verb)
    for fn in registered:
        verb = fn_to_verb[fn]
        assert _verb_needs_caller_identity({"verb_iri": verb}), (
            f"{verb} (fn {fn}) would dispatch as svc:supervisor and refuse no_person "
            f"(info: derived fns with no registered verb: {unregistered})"
        )


def test_the_derivation_sees_the_rejected_rule():
    """The fixture distinguishes the rule: the derivation is not 'every safety verb'."""
    _, derived, fn_to_verb = _derive()
    assert "draft_risk_assessment" in fn_to_verb and "assess_deferral_risk" in fn_to_verb
    assert "draft_risk_assessment" not in derived
    assert "assess_deferral_risk" not in derived


def test_a_safety_verb_without_a_program_filter_still_dispatches_as_the_service():
    from iagent.defs.dynamic_supervisor import _verb_needs_caller_identity

    assert not _verb_needs_caller_identity({"verb_iri": "mesh:draftRiskAssessment"})
    assert not _verb_needs_caller_identity({"verb_iri": "mesh:assessDeferralRisk"})


@pytest.mark.parametrize("name", ["whatFailedOnThisPart", "failureTrendForThisPlatformByMonth"])
@pytest.mark.parametrize("fmt", ["mesh:{}", "https://w3id.org/iagent/mesh#{}", "{}"])
def test_both_spellings(name, fmt):
    from iagent.defs.dynamic_supervisor import _verb_needs_caller_identity

    verb = fmt.format(name)
    assert _verb_needs_caller_identity({"verb_iri": verb}), f"{verb} would dispatch as svc:supervisor"
