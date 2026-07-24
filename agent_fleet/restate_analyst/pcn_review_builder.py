"""PCN/PDN upstream composer — chain the sealed cores into the workflow's server-authored batch.

The seam the review flagged: [[pcn_workflow]] consumes a SERVER-AUTHORED batch, and THIS is what
authors it — the five-layer chain that was sealed-but-never-chained. Given the loaded ruleset (from the
disposition-rules graph) and two injected seams — ``resolve_subject`` (the resolveInstance provider)
and ``can_act`` (Topaz) — compose:

    build_part_items  ->  run_funnel  ->  resolve residue subjects  ->  grouped_review

Subjects are resolved only for the RESIDUE: filtered/auto-disposed parts never reach a human, so their
subject is irrelevant, and an UNRESOLVED residue subject is KEPT (the re-link path), not dropped.

The first live batch over IPCN25300X must be diffed against what the pure-core tests predicted — part
count, the UNVERIFIED (needs_review) rows, and the proposals matching the live ruleset at its current
``ruleset_ref`` (tests/test_pcn_review_builder.py). That diff is the one class of bug the per-core
green suites structurally can't see: drift between the fixture-shaped assumptions the seals were built
on and what the live graph actually feeds them. Red→green on the batch shape, the D4 "three named
tables" discipline applied to the batch.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Optional

import requests

try:  # lazy-import dance (container flattens the dir)
    from workflow_bulk_resolve import FunnelResult, ReviewBatch, grouped_review, run_funnel  # type: ignore[no-redef]
    from pcn_disposition_proposer import build_part_items  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.restate_analyst.workflow_bulk_resolve import (
        FunnelResult, ReviewBatch, grouped_review, run_funnel,
    )
    from agent_fleet.restate_analyst.pcn_disposition_proposer import build_part_items

ENGINE_O_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://iagent-engine-o:8084")
_HTTP_TIMEOUT = float(os.getenv("AGENT_HTTP_TIMEOUT", "30"))


@dataclass
class ReviewBuild:
    """The composed result. ``batch`` is the per-approver batch the workflow consumes; ``funnel`` keeps
    every bucket (Seal 1 conservation survives the composition); ``resolved``/``unresolved`` count the
    residue subjects (unresolved -> the re-link path, not a drop)."""
    batch: ReviewBatch
    funnel: FunnelResult
    ruleset_ref: str
    resolved: int
    unresolved: int


def build_review_batch(
    *,
    impacted_parts: list[dict],
    doc_type: str,
    categories: Optional[list[str]],
    in_scope_mpns: set,
    ruleset: list[dict],
    category_classes: dict,
    ruleset_ref: str,
    approver: str,
    resolve_subject: Callable[[str], Optional[str]],
    can_act: Callable[[str, object], bool],
    relevance_floor: float = 1.0,
    auto_dispose_when=None,
) -> ReviewBuild:
    """Compose the five upstream layers into ONE per-approver batch. ``resolve_subject`` and ``can_act``
    are the injected seams (the live resolveInstance provider and Topaz); everything else is the sealed
    pure cores run for real. Resolve subjects for the residue only, keeping unresolved ones for re-link."""
    items = build_part_items(
        impacted_parts, doc_type=doc_type, categories=categories, in_scope_mpns=in_scope_mpns,
        ruleset=ruleset, category_classes=category_classes, ruleset_ref=ruleset_ref,
    )
    funnel = run_funnel(items, relevance_floor=relevance_floor, auto_dispose_when=auto_dispose_when)

    resolved = unresolved = 0
    for it in funnel.residue:
        it.subject = resolve_subject(it.mpn)
        if it.subject:
            resolved += 1
        else:
            unresolved += 1

    batch = grouped_review(funnel.residue, approver, can_act=can_act)
    return ReviewBuild(batch=batch, funnel=funnel, ruleset_ref=ruleset_ref, resolved=resolved, unresolved=unresolved)


def resolve_subject_via_engine_o(mpn: str, *, engine_o_url: str = ENGINE_O_URL) -> Optional[str]:
    """LIVE resolveInstance adapter (deploy-gated): POST the identifier to engine-o's pcn provider and
    take the top candidate's ``instance_id``, or None (abstain — empty candidates). The provider already
    ran the exact/fuzzy/abstain decision table; this picks the winner. An unresolved subject is NOT an
    error — it routes to the re-link path in the driver."""
    resp = requests.post(f"{engine_o_url}/resolve_pcn_instance", json={"identifier": mpn}, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    candidates = resp.json().get("candidates", [])
    return candidates[0]["instance_id"] if candidates else None
