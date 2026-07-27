"""pcn disposition-rules loader sealed against the REAL seed TTL (the TTL->runtime boundary).

Proves the boundary applies the block rule (conditions carried transparently, not hand-enumerated),
stamps a stable-yet-content-sensitive ruleset_ref, and that a schema-drift condition is carried by
the loader but rejected LOUDLY by validate_ruleset — transparent producer, enforcing consumer.

Needs rdflib:
  cd agent_fleet/restate_analyst && uv run --frozen --with pytest --with rdflib pytest ../../tests/test_policy_rules_loader.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")

_REPO = Path(__file__).resolve().parent.parent
_RA = _REPO / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.restate_analyst.policy_rules_loader import load_disposition_rules  # noqa: E402
from agent_fleet.restate_analyst.policy_evaluator import (  # noqa: E402
    evaluate_rules, validate_ruleset, MATCHED,
)

_TTL = _REPO / "setup" / "ontologies" / "pcn_disposition_rules.ttl"
_DISPOSITIONS = {"dispatchLTB", "dispatchQualification", "dispatchAltSourcing", "archive"}


def _graph(extra_ttl: str = "") -> "rdflib.Graph":
    g = rdflib.Graph()
    g.parse(str(_TTL), format="turtle")
    if extra_ttl:
        g.parse(data=extra_ttl, format="turtle")
    return g


def test_loads_the_seed_ruleset():
    ruleset, cats, ref = load_disposition_rules(_graph())
    assert len(ruleset) == 6
    assert cats["Material"] == "form_fit_function" and cats["Location"] == "administrative"
    fff = next(r for r in ruleset if r["id"] == "RuleFormFitFunctionChange")
    assert fff["whenNoticeType"] == "PCN"
    assert fff["whenAnyChangeClass"] == "form_fit_function"
    assert fff["proposesDisposition"] == "dispatchQualification"


def test_booleans_are_native():
    ruleset, _, _ = load_disposition_rules(_graph())
    r = next(r for r in ruleset if r["id"] == "RuleDiscontinuedWithReplacement")
    assert r["whenHasReplacement"] is True
    r2 = next(r for r in ruleset if r["id"] == "RuleDiscontinuedNoReplacement")
    assert r2["whenHasReplacement"] is False


def test_ruleset_ref_is_stable_and_content_sensitive():
    _, _, ref1 = load_disposition_rules(_graph())
    _, _, ref2 = load_disposition_rules(_graph())
    assert ref1 == ref2 and "@" in ref1                       # stable for identical content
    # a changed rule triple -> a different ref
    _, _, ref3 = load_disposition_rules(_graph(
        '@prefix pcn: <http://internal/sustainment/pcn#> .\n'
        'pcn:RuleNewSeed a pcn:DispositionRule ; pcn:whenNoticeType "PDN" ; pcn:proposesDisposition "archive" .'))
    assert ref3 != ref1


def test_block_pass_carries_an_unknown_condition_not_dropped():
    """The anti-discard property: a condition the schema grows is CARRIED by the loader, not silently
    dropped (the discard-pattern cure at the boundary)."""
    ruleset, _, _ = load_disposition_rules(_graph(
        '@prefix pcn: <http://internal/sustainment/pcn#> .\n'
        'pcn:RuleFuture a pcn:DispositionRule ; pcn:whenNoticeType "PCN" ; '
        'pcn:whenLifecyclePhase "prototype" ; pcn:proposesDisposition "archive" .'))
    future = next(r for r in ruleset if r["id"] == "RuleFuture")
    assert future["whenLifecyclePhase"] == "prototype"       # carried, not dropped


def test_schema_drift_condition_is_rejected_loudly():
    """...and the loudness lives in validate_ruleset: the carried-but-unknown condition fails at
    ingest rather than being silently ignored by the evaluator."""
    ruleset, _, _ = load_disposition_rules(_graph(
        '@prefix pcn: <http://internal/sustainment/pcn#> .\n'
        'pcn:RuleFuture a pcn:DispositionRule ; pcn:whenNoticeType "PCN" ; '
        'pcn:whenLifecyclePhase "prototype" ; pcn:proposesDisposition "archive" .'))
    errs = validate_ruleset(ruleset, known_dispositions=_DISPOSITIONS)
    assert any("whenLifecyclePhase" in e and "schema drift" in e for e in errs)


def test_seed_ttl_is_valid_and_evaluates():
    """End-to-end: the loaded seed ruleset passes validation AND drives the evaluator correctly."""
    ruleset, cats, ref = load_disposition_rules(_graph())
    assert validate_ruleset(ruleset, known_dispositions=_DISPOSITIONS) == []
    r = evaluate_rules(doc_type="PDN", has_replacement=True, categories=None,
                       ruleset=ruleset, category_classes=cats, ruleset_ref=ref)
    assert r.disposition == "dispatchQualification" and r.outcome == MATCHED and r.ruleset_ref == ref
