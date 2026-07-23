"""PCN/PDN bulk-resolve — the PURE grouped-review core (ADR-0029 Case-2 substrate extension).

The DUAL of the Slice-5 join ([[workflow_join]]): the join is N-approvals-gate-1-step (fan-IN);
this is 1-approval-resolves-N-items (fan-OUT). A part-obsolescence notice fans out to N part-items;
a funnel reduces them (filter -> auto-dispose -> residue); an approver reviews their per-approver
batch and resolves it in ONE action that produces N per-item resolutions. Design:
docs/plans/pcn-pdn-bulk-resolve.md.

Pure — no Restate, no Topaz. The authz (`can_act`), relevance scores, `needs_review`, and the
system-proposed disposition are all INPUTS; the enforceable innovations are the four seals:

  Seal 1  honest funnel — nothing vanishes (filtered + auto_disposed + residue == input).
  Seal 2  grouped review is per-approver-filtered (existence-oracle at batch scale).
  §3      needs_review (weak extraction provenance) may NOT take an automated lane, and a
          resolution CARRIES it forward — a disposition never launders an unverified read
          ([[feedback_optimistic_defaults_are_dishonest]] / the Slice-4 weak-provenance seam,
          one layer down).
  §5      capture-why on override is STRUCTURAL (the type has no default reason).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

# Disposition kinds are open strings (the mesh verbs: dispatchLTB / dispatchQualification /
# dispatchAltSourcing / archive ...) — the core does not enumerate them, it routes them.


@dataclass
class PartItem:
    """One affected part from a notice, as doc-tools extracted + the mesh resolved it."""
    mpn: str                               # the affected manufacturer part number (item id)
    relevance: float = 1.0                 # [0,1] — is this part actually affected/in-scope
    subject: Optional[str] = None          # resolved ontology subject IRI (execution grain)
    proposed_disposition: Optional[str] = None  # system-proposed action, or None
    needs_review: bool = False             # doc-tools weak-extraction flag (provenance strength)


@dataclass
class FunnelResult:
    """Every bucket, not just the residue — Seal 1 (honest funnel, nothing hidden)."""
    residue: list[PartItem] = field(default_factory=list)        # a human must decide these
    filtered: list[PartItem] = field(default_factory=list)       # below relevance (not affected)
    auto_disposed: list[PartItem] = field(default_factory=list)  # FYI lane, no human
    review_forced: list[PartItem] = field(default_factory=list)  # needs_review -> residue (subset of residue)

    def counts(self) -> dict:
        return {
            "input": len(self.residue) + len(self.filtered) + len(self.auto_disposed),
            "residue": len(self.residue),
            "filtered": len(self.filtered),
            "auto_disposed": len(self.auto_disposed),
            "review_forced": len(self.review_forced),
        }


@dataclass
class ReviewBatch:
    """What one approver reviews. ``items`` is observer-facing (their batch); ``audit_withheld`` is
    the audit record of what was filtered out for THIS approver — never surfaced to them (Seal 2 +
    the Slice-3 observer_view/audit_record split)."""
    approver: str
    items: list[PartItem] = field(default_factory=list)
    audit_withheld: list[PartItem] = field(default_factory=list)


@dataclass
class Override:
    """An exception to the system-proposed disposition. ``reason`` has NO default — capture-why is
    structural (§5): you cannot construct an override without recording why. The core holds only a
    NON-EMPTY FLOOR (below); it does NOT judge reason QUALITY (whether "ok" suffices is a
    review-quality governance question — parked with Decision D, not invented in the lifecycle core).
    The reason is provenance about what a human doubted: it is AUDIT-grade (audit_record), not
    observer-facing, when a resolution is later projected for observation/reporting."""
    disposition: str
    reason: str

    def __post_init__(self) -> None:
        if not (self.reason or "").strip():
            raise ValueError("override reason must be non-empty (capture-why) — a blank reason does not record a decision")


@dataclass
class BulkDecision:
    """One human action over a whole batch: accept the system-proposed disposition for every item
    except those overridden. Accept-all-with-exceptions (§5)."""
    overrides: dict = field(default_factory=dict)  # mpn -> Override


@dataclass
class ItemResolution:
    """One resolved item — execution grain. Idempotent on ``notice_fingerprint x mpn``; carries the
    ``needs_review`` flag FORWARD so no disposition launders an unverified extraction (§3)."""
    mpn: str
    subject: Optional[str]
    disposition: str
    idempotency_key: str
    needs_review: bool
    override_reason: Optional[str] = None


def run_funnel(
    items: list[PartItem],
    *,
    relevance_floor: float,
    auto_dispose_when: Optional[Callable[[PartItem], bool]] = None,
) -> FunnelResult:
    """Reduce N items to the residue a human must decide, keeping every bucket (Seal 1).

    Order per item: a ``needs_review`` item is forced to residue FIRST — weak extraction provenance
    may take no automated lane (§3-rule-1: you cannot trust an automated relevance/disposition
    decision on an MPN you are unsure you read). Otherwise: below ``relevance_floor`` -> filtered;
    ``auto_dispose_when`` true -> auto_disposed; else -> residue."""
    res = FunnelResult()
    dispose = auto_dispose_when or (lambda _i: False)
    for it in items:
        if it.needs_review:
            res.residue.append(it)
            res.review_forced.append(it)
            continue
        if it.relevance < relevance_floor:
            res.filtered.append(it)
            continue
        if dispose(it):
            res.auto_disposed.append(it)
            continue
        res.residue.append(it)
    return res


def grouped_review(
    residue: list[PartItem],
    approver: str,
    *,
    can_act: Callable[[str, PartItem], bool],
) -> ReviewBatch:
    """The per-approver batch (Seal 2): ``residue ∩ {items this approver can act on}``. Two
    approvers on the same notice get different-sized batches, correctly; an item an approver cannot
    act on is withheld to the audit record, never surfaced to them. ``can_act`` is Topaz, injected;
    defaults are the driver's to inject — a driver that forgets fails CLOSED (empty batch)."""
    batch = ReviewBatch(approver=approver)
    for it in residue:
        if can_act(approver, it):
            batch.items.append(it)
        else:
            batch.audit_withheld.append(it)
    return batch


def resolve_batch(
    batch: ReviewBatch,
    decision: BulkDecision,
    *,
    notice_fingerprint: str,
) -> list[ItemResolution]:
    """One approval action -> N per-item resolutions (§1 execution grain). Each carries its own
    idempotency key (``notice_fingerprint:mpn``) and the ``needs_review`` flag FORWARD (§3-rule-2).
    A row with no proposed disposition and no override cannot be resolved — refuse honestly
    (``ValueError``) rather than dispatch an effect with no disposition."""
    out: list[ItemResolution] = []
    for it in batch.items:
        ov: Optional[Override] = decision.overrides.get(it.mpn)
        # A needs_review part is a MANDATORY EXCEPTION — it may NOT ride the default/bulk (accept-all)
        # path. Visibility is not friction: a human "reviews" an unverified MPN by not noticing it in
        # a batch of forty, which rebuilds the automated lane out of one click. An unverified part must
        # be handled with an EXPLICIT individual override (whose reason records the verification). This
        # blocks the whole batch until it is handled — the same discipline as the no-disposition guard.
        if it.needs_review and ov is None:
            raise ValueError(
                f"part {it.mpn!r} has an unverified MPN extraction (needs_review) and was not "
                f"individually dispositioned — an unverified part cannot ride accept-all; handle it "
                f"with an explicit override (which records the verifying reason)"
            )
        disposition = ov.disposition if ov is not None else it.proposed_disposition
        if not disposition:
            raise ValueError(
                f"part {it.mpn!r} has no system-proposed disposition and no override — "
                f"cannot resolve (would dispatch an effect with no disposition)"
            )
        out.append(ItemResolution(
            mpn=it.mpn,
            subject=it.subject,
            disposition=disposition,
            idempotency_key=f"{notice_fingerprint}:{it.mpn}",
            needs_review=it.needs_review,               # carried forward, visible — never laundered
            override_reason=(ov.reason if ov is not None else None),
        ))
    return out
