"""PCN/PDN upstream composer sealed — the seam-diff: live batch shape vs pure-core prediction.

This is the assertion the per-core green suites structurally can't make: when the sealed-but-never-
chained cores compose for the first time (build_part_items -> run_funnel -> resolve residue subjects ->
grouped_review), does the batch that reaches the workflow MATCH what the pure cores predict? Built over
a real-shaped IPCN25300X input against the REAL ruleset loaded from setup/ontologies/
pcn_disposition_rules.ttl at its CURRENT ruleset_ref — so drift between fixture-shaped assumptions and
the live policy surfaces here, red→green on the batch shape (the D4 "three named tables" discipline).

The two live seams (resolveInstance, Topaz) are INJECTED — the legitimate composition boundary, not a
mock in the data path ([[feedback_synthetic_data_no_mock_leak]]): real-shaped parts flow through the
real proposer/funnel/review; only subject-resolution and can-act are stubbed at their seam.

Run:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest --with rdflib \
        pytest ../../tests/test_review_composer.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_RA = _REPO / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.restate_analyst.review_composer import build_review_batch  # noqa: E402
from agent_fleet.restate_analyst.policy_rules_loader import load_disposition_rules  # noqa: E402

_TTL = _REPO / "setup" / "ontologies" / "pcn_disposition_rules.ttl"


def _load_real_ruleset():
    """Load the REAL policy artifact at its current content — ruleset + ruleset_ref straight from the
    TTL a prime would ingest. Predictions are diffed against THIS, not an invented ruleset."""
    import rdflib
    g = rdflib.Graph()
    g.parse(str(_TTL), format="turtle")
    return load_disposition_rules(g)


# --- Real-shaped IPCN25300X input: a PCN carrying a form/fit/function (Process) change. --------------
# 4 affected parts: 2 clean in-scope, 1 UNVERIFIED in-scope (needs_review), 1 out-of-scope. One
# in-scope part's subject won't resolve (re-link path). Shapes mirror doc-tools' PCN/PDN extraction.
_DOC_TYPE = "PCN"
_CATEGORIES = ["Process"]  # -> change_class form_fit_function -> RuleFormFitFunctionChange -> qualify
_IN_SCOPE = {"NSR01L30NXT5G", "MPN-NEEDSREVIEW", "MPN-UNRES"}
_IMPACTED = [
    {"affected_mpn": "NSR01L30NXT5G", "replacement_mpn": "NSR01L30NXT5G-R", "needs_review": False},
    {"affected_mpn": "MPN-NEEDSREVIEW", "replacement_mpn": "", "needs_review": True},
    {"affected_mpn": "MPN-OUTOFSCOPE", "replacement_mpn": "", "needs_review": False},
    {"affected_mpn": "MPN-UNRES", "replacement_mpn": "", "needs_review": False},
]
_KNOWN_IRIS = {
    "NSR01L30NXT5G": "http://internal/components/NSR01L30NXT5G",
    "MPN-NEEDSREVIEW": "http://internal/components/MPN-NEEDSREVIEW",
    # MPN-UNRES deliberately absent -> resolveInstance abstains -> re-link path
}


def _resolve(mpn):  # the resolveInstance seam (exact-match provider stand-in)
    return _KNOWN_IRIS.get(mpn)


def _build(can_act=lambda approver, item: True):
    ruleset, category_classes, ruleset_ref = _load_real_ruleset()
    return build_review_batch(
        impacted_parts=_IMPACTED, doc_type=_DOC_TYPE, categories=_CATEGORIES, in_scope_mpns=_IN_SCOPE,
        ruleset=ruleset, category_classes=category_classes, ruleset_ref=ruleset_ref,
        approver="qa", resolve_subject=_resolve, can_act=can_act,
    ), ruleset_ref


# ===========================================================================
# The seam-diff — PREDICTED (what the pure cores say) vs the COMPOSED live-shaped batch
# ===========================================================================
def test_funnel_conservation_and_bucket_counts_match_prediction():
    """PREDICTION: input 4 = filtered 1 (out-of-scope) + auto_disposed 0 + residue 3; review_forced 1."""
    build, _ = _build()
    c = build.funnel.counts()
    assert c["input"] == 4
    assert c["filtered"] == 1          # MPN-OUTOFSCOPE below relevance floor (not in scope)
    assert c["auto_disposed"] == 0
    assert c["residue"] == 3           # 2 clean in-scope + 1 needs_review (forced)
    assert c["review_forced"] == 1     # MPN-NEEDSREVIEW
    assert c["filtered"] + c["auto_disposed"] + c["residue"] == c["input"]  # Seal 1 survives composition


def test_all_residue_propose_qualification_at_the_live_ruleset():
    """PREDICTION from the REAL ruleset: a PCN with a form/fit/function change -> dispatchQualification
    (RuleFormFitFunctionChange). Every residue row proposes it, stamped with the loaded ruleset_ref."""
    build, ruleset_ref = _build()
    assert ruleset_ref.startswith("rules@") and len(ruleset_ref.split("@")[1]) == 12
    for it in build.funnel.residue:
        assert it.proposed_disposition == "dispatchQualification", f"{it.mpn} proposed {it.proposed_disposition}"
        assert it.proposed_by_ruleset == ruleset_ref, "residue item not stamped with the live ruleset_ref"


def test_unverified_row_is_in_residue_flagged():
    """PREDICTION: the needs_review row is in residue (never an automated lane), and still carries the
    flag — the workflow's refusal-routing will force an explicit override for it."""
    build, _ = _build()
    unverified = [it for it in build.funnel.residue if it.needs_review]
    assert [it.mpn for it in unverified] == ["MPN-NEEDSREVIEW"]
    assert [it.mpn for it in build.funnel.review_forced] == ["MPN-NEEDSREVIEW"]


def test_residue_subject_resolution_counts_match_prediction():
    """PREDICTION: residue subjects resolve for 2 (NSR01L30NXT5G, MPN-NEEDSREVIEW), 1 abstains
    (MPN-UNRES) -> kept for re-link, not dropped. Resolution runs on residue only (out-of-scope
    filtered part is never resolved)."""
    build, _ = _build()
    assert build.resolved == 2
    assert build.unresolved == 1
    unres = [it for it in build.funnel.residue if it.subject is None]
    assert [it.mpn for it in unres] == ["MPN-UNRES"]  # kept in residue, subject None -> re-link


def test_grouped_review_all_can_act_yields_full_residue_batch():
    build, _ = _build(can_act=lambda approver, item: True)
    assert {it.mpn for it in build.batch.items} == {"NSR01L30NXT5G", "MPN-NEEDSREVIEW", "MPN-UNRES"}
    assert build.batch.audit_withheld == []


def test_grouped_review_is_per_approver_filtered_through_composition():
    """Seal 2 survives the composition: an approver who cannot act on one residue item gets a smaller
    batch; the withheld item is audit-recorded, never surfaced."""
    build, _ = _build(can_act=lambda approver, item: item.mpn != "MPN-UNRES")
    assert {it.mpn for it in build.batch.items} == {"NSR01L30NXT5G", "MPN-NEEDSREVIEW"}
    assert [it.mpn for it in build.batch.audit_withheld] == ["MPN-UNRES"]
