"""PCN/PDN disposition proposer — MECHANISM only; the policy is DATA (feeds [[workflow_bulk_resolve]]).

Turns a notice's affected parts into ``PartItem``s for ``run_funnel``: a relevance score (is this part
in OUR scope) and a SYSTEM-PROPOSED disposition (what to do about it).

**Mechanism / policy split (the arc's thesis: drive from standards, not code).** The condition→
disposition DECISION TABLE is NOT here — it lives in ``setup/ontologies/pcn_disposition_rules.ttl``,
ingested via the manifest partition path, versioned + reproducible + owner-ratifiable like every
standards artifact (so ``prov:wasDerivedFrom`` can cite the governing clause and the drift-check
covers policy too). This file keeps ONLY the sealed mechanism: evaluate a part against a ruleset,
degrade honestly when no rule matches, and ABSTAIN rather than pick when rules conflict. The
``ruleset`` + ``category_classes`` are INPUTS (the driver loads them from the graph); the pure core is
sealed against a fixture ruleset. Keep the rules a flat decision table — a rule LANGUAGE would be
code-as-policy's revenge.

Honest degradation, two forms, both → no proposal → the part can't ride accept-all (approver disposes
explicitly): (a) UNCLASSIFIABLE — no rule matched; (b) CONFLICT — matching rules disagree. The system
proposes only what it is sure of.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

try:  # same lazy-import dance as the other restate_analyst cores
    from workflow_bulk_resolve import PartItem  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.restate_analyst.workflow_bulk_resolve import PartItem

# Outcomes.
MATCHED = "matched"
UNCLASSIFIABLE = "unclassifiable"   # no rule matched
CONFLICT = "conflict"               # matching rules disagree -> abstain rather than pick


@dataclass
class DispositionProposal:
    """The proposer's verdict for one part. ``disposition`` is None for both no-proposal outcomes;
    ``outcome`` distinguishes them (observability + the growth loop: unclassifiable/conflict cases
    are candidate rules once a human disposes them)."""
    disposition: Optional[str]
    outcome: str


def _rule_matches(rule: dict, *, doc_type: str, has_replacement: bool, change_classes: set) -> bool:
    """A rule matches a part iff EVERY stated condition holds (an absent condition is a wildcard).
    Fixed, closed condition schema — no rule language."""
    nt = rule.get("whenNoticeType")
    if nt and str(nt).upper() != str(doc_type).upper():
        return False
    hr = rule.get("whenHasReplacement")
    if hr is not None and bool(hr) != bool(has_replacement):
        return False
    any_cc = rule.get("whenAnyChangeClass")
    if any_cc and any_cc not in change_classes:
        return False
    all_cc = rule.get("whenAllChangeClass")
    if all_cc and change_classes != {all_cc}:
        return False
    return True


def evaluate_rules(
    *,
    doc_type: str,
    has_replacement: bool,
    categories: Optional[list[str]],
    ruleset: list[dict],
    category_classes: dict,
) -> DispositionProposal:
    """All-match-must-agree evaluation. Collect every rule whose conditions hold; if they all name
    ONE disposition → propose it; if they disagree → CONFLICT (abstain); if none match →
    UNCLASSIFIABLE. Both no-proposal outcomes leave the part unable to ride accept-all."""
    change_classes = {category_classes[c] for c in (categories or []) if c in category_classes}
    matched = [
        r for r in ruleset
        if _rule_matches(r, doc_type=doc_type, has_replacement=has_replacement, change_classes=change_classes)
    ]
    dispositions = {r.get("proposesDisposition") for r in matched}
    if not dispositions:
        return DispositionProposal(None, UNCLASSIFIABLE)
    if len(dispositions) > 1:
        return DispositionProposal(None, CONFLICT)   # abstain rather than silently pick one
    return DispositionProposal(next(iter(dispositions)), MATCHED)


def validate_ruleset(ruleset: list[dict], *, known_dispositions: set) -> list[str]:
    """Ingest-time gate (the rdflib-validated discipline applied to rules): a malformed ruleset fails
    at INGEST, not at an approver's screen. Errors: (1) a rule proposing an unregistered disposition;
    (2) two rules with IDENTICAL conditions but different dispositions (a direct contradiction — an
    always-conflict that would abstain every matching part). Legitimate overlaps that agree are fine;
    genuine ambiguity abstains at runtime by design."""
    errors: list[str] = []
    _COND = ("whenNoticeType", "whenHasReplacement", "whenAnyChangeClass", "whenAllChangeClass")
    seen: dict = {}
    for i, r in enumerate(ruleset):
        d = r.get("proposesDisposition")
        if d not in known_dispositions:
            errors.append(f"rule {i} ({r.get('id', '?')}): unregistered disposition {d!r}")
        key = tuple(r.get(c) for c in _COND)
        if key in seen and seen[key] != d:
            errors.append(
                f"rule {i} ({r.get('id', '?')}): identical conditions to rule {seen[key][1]} but "
                f"different disposition ({seen[key][0]!r} vs {d!r}) — direct contradiction"
            )
        seen.setdefault(key, (d, i))
    return errors


def score_relevance(mpn: str, *, in_scope_mpns: set) -> float:
    """1.0 if the affected part is in OUR scope (BOM/AVL), else 0.0 (the funnel filters it). Scope is
    an INPUT — no optimistic default: a part we don't own is not our problem, and an empty scope set
    means nothing is in scope (all filtered), which is honest, not a bug — supply the real scope."""
    return 1.0 if (mpn or "") in (in_scope_mpns or set()) else 0.0


def build_part_items(
    impacted_parts: list[dict],
    *,
    doc_type: str,
    categories: Optional[list[str]] = None,
    in_scope_mpns: set,
    ruleset: list[dict],
    category_classes: dict,
) -> list[PartItem]:
    """Assemble ``PartItem``s (funnel input) from a notice's impacted parts, using the injected
    ``ruleset`` + ``category_classes`` (loaded from the disposition-rules graph by the driver).
    ``subject`` is left None — filled by the resolveInstance step; the proposer owns DISPOSITION +
    RELEVANCE only. Both no-proposal outcomes (unclassifiable / conflict) leave
    ``proposed_disposition`` None, so the part can't ride accept-all."""
    items: list[PartItem] = []
    for p in impacted_parts:
        mpn = str(p.get("affected_mpn") or "").strip()
        if not mpn:
            continue
        has_replacement = bool(str(p.get("replacement_mpn") or "").strip())
        proposal = evaluate_rules(
            doc_type=doc_type, has_replacement=has_replacement, categories=categories,
            ruleset=ruleset, category_classes=category_classes,
        )
        items.append(PartItem(
            mpn=mpn,
            relevance=score_relevance(mpn, in_scope_mpns=in_scope_mpns),
            subject=None,  # filled by the resolveInstance step
            proposed_disposition=proposal.disposition,
            needs_review=bool(p.get("needs_review", False)),
        ))
    return items
