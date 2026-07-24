"""Policy-rules CLIENT sealed — the adapter that interprets the served Turtle, four failure modes.

The seam-diff at the adapter layer (where option 1 put the interpretation): the served Turtle, loaded
here, must yield the known-good answer (rules@edc21f242929) — and the four failure modes (not_found /
empty / invalid / ok) are decided HERE, each with its own test, since they're exactly what the SECOND
policy domain hits first (new domains arrive with empty graphs).

Run:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest --with rdflib \
        pytest ../../tests/test_policy_rules_client.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for p in (str(_REPO / "agent_fleet" / "restate_analyst"), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.restate_analyst.policy_rules_client import parse_policy_rules  # noqa: E402

_TTL = _REPO / "setup" / "ontologies" / "pcn_disposition_rules.ttl"
_KNOWN = ["dispatchQualification", "dispatchLTB", "dispatchAltSourcing", "archive"]


def _real_turtle() -> str:
    return _TTL.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# ok — the known-good diff (seam-diff at the adapter layer)
# ---------------------------------------------------------------------------
def test_ok_matches_known_good_answer():
    out = parse_policy_rules(_real_turtle(), graph_nonempty=True, known_dispositions=_KNOWN)
    assert out["status"] == "ok"
    assert out["valid"] is True and out["validation_errors"] == []
    assert out["registration_checked"] is True
    assert out["ruleset_ref"] == "rules@edc21f242929"
    assert len(out["ruleset"]) == 6
    assert out["category_classes"]["Material"] == "form_fit_function"


def test_ok_without_known_dispositions_skips_registration_honestly():
    """No known set -> structural checks still run (valid), but registration is honestly marked
    unchecked — never a false 'unregistered disposition'."""
    out = parse_policy_rules(_real_turtle(), graph_nonempty=True)
    assert out["status"] == "ok" and out["valid"] is True
    assert out["registration_checked"] is False
    assert out["ruleset_ref"] == "rules@edc21f242929"


# ---------------------------------------------------------------------------
# not_found vs empty — the distinction only this layer can make
# ---------------------------------------------------------------------------
def test_not_found_when_graph_has_no_triples():
    out = parse_policy_rules("", graph_nonempty=False)
    assert out["status"] == "not_found"
    assert out["ruleset"] == [] and out["ruleset_ref"] == ""


def test_empty_when_graph_present_but_no_rules():
    """Graph has triples but none are rules — the abstain-everything case, distinct from not_found."""
    onto_only = (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "<http://internal/sustainment/pcn/rules> a owl:Ontology ; rdfs:label \"empty ruleset\" .\n"
    )
    out = parse_policy_rules(onto_only, graph_nonempty=True)
    assert out["status"] == "empty"
    assert out["ruleset"] == []
    assert out["valid"] is True  # vacuously — no rules to be invalid; caller decides what empty means


# ---------------------------------------------------------------------------
# invalid — reported, not rejected
# ---------------------------------------------------------------------------
def test_invalid_reports_errors_but_still_returns_the_ruleset():
    """A subsumption violation (broad rule + specific override, different disposition) -> invalid with
    reasons, but the ruleset is RETURNED (report-don't-reject; the caller's policy decides)."""
    bad = (
        "@prefix pcn: <http://internal/sustainment/pcn#> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "<http://internal/sustainment/pcn/rules> a owl:Ontology .\n"
        "pcn:Broad a pcn:DispositionRule ; pcn:whenNoticeType \"PCN\" ; pcn:proposesDisposition \"dispatchQualification\" .\n"
        "pcn:Specific a pcn:DispositionRule ; pcn:whenNoticeType \"PCN\" ; pcn:whenHasReplacement true ; pcn:proposesDisposition \"archive\" .\n"
    )
    out = parse_policy_rules(bad, graph_nonempty=True, known_dispositions=_KNOWN)
    assert out["status"] == "invalid"
    assert out["valid"] is False
    assert out["validation_errors"], "expected subsumption error reported"
    assert len(out["ruleset"]) == 2, "invalid ruleset should still be returned, not dropped"
