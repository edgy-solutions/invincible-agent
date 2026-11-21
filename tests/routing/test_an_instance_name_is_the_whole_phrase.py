"""An instance name is the WHOLE phrase the person gave, not its last word.

RULED (architect, 2026-11-21): "Defect 2, the name check: ... A name is the whole phrase the
person gave, not its last word. Include tests where the name ends in its own kind word. The
merge step: record the rejected match and why."

The measured pair: identifier `Revenue by Region dashboard` vs the one real claimant labelled
`Revenue by Region` (id `...revenue_by_region`, class Dashboard). The old gate compared last
words (`dashboard` vs `region`) and refused it. It was also too loose: `Fleet Readiness`
passed `Crew Readiness`.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from agent_fleet.ontology_service.instance_resolution import (
    InstanceCandidate,
    decide,
    passes_candidate_specificity,
    rejected_match_note,
)

_REPO = Path(__file__).resolve().parents[2]
_DASH = "http://x/datahub#Dashboard"
_URN = "urn:li:dashboard:(superset,revenue_by_region)"


def _dash(label="Revenue by Region", instance_id=_URN, cls=_DASH, score=0.85):
    return InstanceCandidate(instance_id=instance_id, class_uri=cls, label=label,
                             score=score, provider="engine_d")


def _passes(identifier, cand):
    return passes_candidate_specificity(identifier, cand)


# ── the real failing pair ─────────────────────────────────────────────────────────────

def test_the_real_failing_pair_passes():
    assert _passes("Revenue by Region dashboard", _dash())


def test_the_real_failing_pair_resolves_through_decide():
    d = decide([_dash()], identifier="Revenue by Region dashboard")
    assert d.subject_uri == _DASH
    assert d.provenance["instance_match"] != "not_specific"


# ── names that end in their own kind word ─────────────────────────────────────────────

@pytest.mark.parametrize("ident", ["Fleet Readiness Dashboard", "fleet readiness dashboard",
                                   "Fleet Readiness"])
def test_a_label_ending_in_its_own_kind_word_passes(ident):
    cand = _dash(label="Fleet Readiness Dashboard", instance_id="urn:x:fleet_readiness_dashboard")
    assert _passes(ident, cand)


def test_a_two_word_kind_is_dropped_whole():
    cand = InstanceCandidate(instance_id="urn:x:ca-1", class_uri="http://x/pcn#ControlAccount",
                             label="Integration and Test", score=0.9, provider="p")
    assert _passes("Integration and Test control account", cand)
    assert _passes("Integration and Test", cand)


# ── controls: must stay refused ───────────────────────────────────────────────────────

P_CAGE = InstanceCandidate(instance_id="urn:li:dataset:(urn:li:dataPlatform:minio,publog/p_cage,PROD)",
                           class_uri="http://x/pcn#Table", label="p_cage", score=0.9, provider="p")


@pytest.mark.parametrize("ident", ["cage", "p_caeg", "publog"])
def test_control_the_old_substring_defects_stay_refused(ident):
    assert not _passes(ident, P_CAGE)


@pytest.mark.parametrize("ident", ["p_cage", "publog p_cage", "publog.p_cage",
                                   "publog's p_cage", "minio-svc.publog-lake/publog/p_cage"])
def test_control_the_qualified_forms_still_pass(ident):
    assert _passes(ident, P_CAGE)


def test_control_fleet_readiness_is_not_crew_readiness():
    cand = InstanceCandidate(instance_id="urn:x:crew", class_uri="http://x/p#Metric",
                             label="Crew Readiness", score=0.9, provider="p")
    assert not _passes("Fleet Readiness", cand)


def test_control_a_trailing_word_that_is_not_its_own_kind_is_not_dropped():
    assert not _passes("Revenue by Region chart", _dash())


def test_control_a_kind_word_alone_does_not_name_the_candidate():
    assert not _passes("dashboard", _dash())
    assert decide([_dash()], identifier="dashboard").provenance["instance_match"] == "not_specific"


# ── the 2026-10-16 ruling is preserved for single-token identifiers ────────────────────

def test_a_single_token_identifier_is_still_refused_against_a_spaced_label():
    """Mirrors test_7b: `PN_9001` against label `pn 9001` stays not_specific."""
    c = InstanceCandidate(instance_id="CSI-7001", class_uri="http://x/safety#SafetyCriticalItem",
                          label="pn 9001", score=0.9, provider="p")
    assert not _passes("PN_9001", c)
    assert decide([c], identifier="PN_9001").provenance["instance_match"] == "not_specific"


def test_residual_a_phrase_identifier_passes_a_separator_variant_label():
    """QUESTION FOR THE ARCHITECT, pinned as built: `PN 9001` (whitespace, so a phrase) passes
    against label `pn_9001`. Should it be refused? This rule passes it."""
    c = InstanceCandidate(instance_id="CSI-7001", class_uri="http://x/safety#SafetyCriticalItem",
                          label="pn_9001", score=0.9, provider="p")
    assert _passes("PN 9001", c)


# ── the refusal is recorded with why ──────────────────────────────────────────────────

_CREW = InstanceCandidate(instance_id="urn:x:crew", class_uri="http://x/p#Metric",
                          label="Crew Readiness", score=0.9, provider="p")


def test_a_not_specific_decision_records_the_rejected_top_and_why():
    d = decide([_CREW], identifier="Fleet Readiness")
    prov = d.provenance
    assert prov["instance_match"] == "not_specific"
    assert prov["instance_rejected_n"] == 1 and prov["instance_identifier"] == "Fleet Readiness"
    top = prov["instance_rejected_top"]
    assert len(top) == 1
    assert set(top[0]) == {"instance_id", "label", "class_uri", "score", "why"}
    assert top[0]["label"] == "Crew Readiness"
    assert "fleet readiness" in top[0]["why"] and "crew readiness" in top[0]["why"]


def test_rejected_top_is_capped_at_three_best_first():
    cands = [InstanceCandidate(f"urn:x:{i}", "http://x/p#Metric", f"Crew {i}", 0.75 + i / 100, "p")
             for i in range(5)]
    top = decide(cands, identifier="Fleet Readiness").provenance["instance_rejected_top"]
    assert [t["instance_id"] for t in top] == ["urn:x:4", "urn:x:3", "urn:x:2"]


def test_the_note_is_one_sentence_for_a_refusal_and_empty_otherwise():
    prov = decide([_CREW], identifier="Fleet Readiness").provenance
    note = rejected_match_note(prov)
    assert note.startswith("The instance lookup found 'Crew Readiness' (Metric) and refused it: ")
    assert prov["instance_rejected_top"][0]["why"] in note
    assert rejected_match_note(decide([_dash()], identifier="Revenue by Region").provenance) == ""
    assert rejected_match_note(decide([], identifier="x").provenance) == ""
    assert rejected_match_note({"instance_match": "not_specific"}) == ""
    assert rejected_match_note({}) == ""


# ── the merge ─────────────────────────────────────────────────────────────────────────
# No harness in tests/routing drives /resolve() itself with a stubbed classifier, so the merge is
# pinned in two halves: the real `_resolve_instance` carries the record into the provenance the
# merge reads, and the call site on the weak path appends the note (source seal).

def _main():
    try:
        from agent_fleet.ontology_service import main
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ontology_service not importable here ({type(exc).__name__}: {exc})")
    return main


class _Outcome:
    def __init__(self, candidates):
        self.provider, self.candidates = "prov", candidates
        self.status, self.endpoint_url, self.elapsed_s = "ok", "http://stub", 0.01


def test_resolve_instance_hands_the_merge_the_rejected_record(monkeypatch):
    main = _main()
    resolvers = [{"provider": "prov", "endpoint_url": "http://p", "timeout_s": None,
                  "domains": ["D"]}]
    monkeypatch.setattr(main, "_discover_instance_resolvers",
                        lambda *a, **k: main.MeshResult.answered(resolvers))

    async def _call(resolver, term, query, **_caller):
        return _Outcome([_CREW])

    async def _no_chains(uris):
        return {}, "unavailable"

    monkeypatch.setattr(main, "_call_resolver", _call)
    monkeypatch.setattr(main, "_read_class_chains", _no_chains)
    subject, prov = asyncio.run(main._resolve_instance(
        "Fleet Readiness", "q", ["D"], user_email="c@example.org", entitled_domains=["D"]))
    assert subject is None
    assert prov["instance_match"] == "not_specific"
    assert prov["instance_rejected_top"][0]["label"] == "Crew Readiness"
    assert main._ir_rejected_match_note(prov).endswith(prov["instance_rejected_top"][0]["why"] + ".")


def test_the_weak_path_appends_the_note_and_keeps_the_classifiers_subject():
    src = (_REPO / "agent_fleet" / "ontology_service" / "main.py").read_text(encoding="utf-8")
    i = src.index("candidates, result.reasoning, instance_provenance,")
    block = src[i:i + 900]
    assert "_ir_rejected_match_note(instance_provenance)" in block
    assert re.search(r"_reason = f\"\{_reason\} \{_rejected_note\}\"", block)
    assert "resolved_uri=str(result.resolved_uri)" in block, "the subject returned must not change"
    assert "provenance=_prov" in block, "provenance must survive the guard"
    # the guard copies the provenance dict, so the record survives it
    from agent_fleet.ontology_service.recall_guard import recall_override_guard
    prov = {"instance_match": "not_specific", "instance_rejected_top": [{"why": "w"}]}
    _c, _r, kept = recall_override_guard("u", 0.5, [], "r", prov)
    assert kept["instance_rejected_top"] == [{"why": "w"}]
