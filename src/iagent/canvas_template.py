"""CANVAS TEMPLATES — a panel is a pre-resolved step, not a phrase.

ADR-0050 §1/§2/§7. A template is **ratifiable config** in the same sense as grants, the trust
table and workflow definitions: it lives in `policy/canvases/<template_id>.yaml`, is diffable and
greppable, and enters only by PR.

WHY THESE MODELS ARE THE SCHEMA'S SOURCE. §1.2 requires the committed JSON Schema to be
GENERATED from the models the seed verb itself loads, with a drift test, so the two cannot
disagree — one is projected from the other. Hand-authoring a schema beside these classes would be
the two-masters defect at config scale, and the first divergence would be invisible.

PURE ON PURPOSE. No store, no transport, no YAML reading — the same reason `decision_record.py`
and `provenance.py` are pure: the shape must be testable without a substrate, and the substrate
must be replaceable without touching the shape.

WHAT A PANEL IS NOT. It is not a phrase. Today's seeder carries five natural-language questions
and lets the classifier re-derive a verb per run (`gateway.py` PORTFOLIO_CANVAS_QUESTIONS), which
is why subject resolution has been observed to MOVE across a single prime. A panel names its verb
directly and is dispatched through the ADR-0029 Decision 5 structural gate, never the classifier.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# §7 — a panel's layout declares its SLOT ROLE, never pixels. `anchor` spans the top; `pair`
# members sit in the rows beneath it. The ORDINAL is the panel's position in the list, because
# `ORDER IS THE DECLARATION` (gateway.py) is preserved verbatim: position 0 is the anchor, the
# client never sorts, the projection never reorders or dedupes. Geometry that realises a role
# stays in cortex's TEMPLATES builder, keyed by template_id — the client's coordinates are
# derived from viewport aspect and MEASURED CONTENT HEIGHTS, so there is no set of numbers a
# YAML could carry that would survive a different pane.
SlotRole = Literal["anchor", "pair"]


class SharedSlot(BaseModel):
    """A slot the template's panels share — `program` is §3's worked case.

    ONE ASK, N PANELS. An unfilled shared slot fires exactly one elicitation at load, through
    ADR-0033's `slot-unfilled` -> ask disposition, and the answer binds into every panel that
    declares it. This is a CONSUMER of the elicitation surface, not a second one.
    """
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1,
                      description="Slot name as the verbs' signatures spell it.")
    description: str = Field(..., min_length=1,
                             description="What the ask means, in the words a user would hear.")
    required: bool = Field(
        default=True,
        description=("Whether the template refuses to load unfilled. §3.4: a shared slot is the "
                     "BOARD'S SUBJECT, so a caller not entitled to it refuses the TEMPLATE, not "
                     "the panel — every panel would be a hole."))


class Panel(BaseModel):
    """`{verb, slots, layout}` — ADR-0050 §2.

    `slots` are PANEL-LOCAL declared values; `consumes` names template-level shared slots. Both
    are declarations, not requests: §3 is BLOCKED until the dispatch boundary carries slots, so a
    slice-1 template declares the verbs' OWN DEFAULTS, which is true today and produces the same
    board whether or not the carry has landed. The declaration documents reality rather than
    hoping for it — and when the carry lands, a declared default that changes the card is the
    carry ARRIVING, which is a correction to record, not a regression.
    """
    model_config = ConfigDict(extra="forbid")

    verb: str = Field(..., pattern=r"^[a-zA-Z][a-zA-Z0-9_]*:[A-Za-z][A-Za-z0-9_]*$",
                      description="Prefixed verb IRI, e.g. `mesh:planCostCurve`. Dispatched "
                                  "through the stage-2 structural gate, never the classifier.")
    role: SlotRole = Field(..., description="§7 slot role. Ordinal is this panel's list index.")
    slots: dict[str, Any] = Field(
        default_factory=dict,
        description="Panel-local slot declarations. Never asked at load (§3.1).")
    consumes: list[str] = Field(
        default_factory=list,
        description="Names of template-level shared slots this panel binds (§3.1).")
    note: Optional[str] = Field(
        default=None,
        description="Why this panel declares what it does — carried into review, not into "
                    "`template_ref`, so an explanation can be improved without minting a ref.")


class CanvasTemplate(BaseModel):
    """One file, one template (§1.1)."""
    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$",
                             description="Must equal the filename stem. The seed verb's "
                                         "`template_id` slot is enumerated from the ratified "
                                         "set, so this string is a menu option (§4).")
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    shared_slots: list[SharedSlot] = Field(default_factory=list)
    panels: list[Panel] = Field(..., min_length=1)


# ── §1.5 — `template_ref` is a CONTENT hash, minted deliberately ────────────────────────────
#
# Format follows `ruleset_ref` so refs read alike in a record: `<template_id>@<12 hex>`.
# Canonicalisation follows `cost_agent/export.py`'s `_canonical` — `sort_keys=True,
# separators=(",",":")` — because the separators pin is the one thing `policy_rules_loader`'s
# version lacks, and an UNPINNED SEPARATOR IS A REF THAT MOVES when a serialiser's defaults do.
#
# THE HASH COVERS SEMANTIC CONTENT, NOT FILE BYTES: panels, their verbs, their declared slots,
# their slot roles. A reordered key, a reflowed comment or a changed description does NOT mint a
# new ref; a changed panel does. Inherited from `ruleset_ref` deliberately, including its stated
# cost — `template_ref` says "THIS panel set", and nothing about the state of anything else.
def _canonical(obj: Any) -> str:
    """Stable JSON for hashing. Pinned here rather than left to `json.dumps` defaults."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def semantic_content(t: CanvasTemplate) -> dict[str, Any]:
    """The subset `template_ref` covers. Everything omitted here is deliberately NOT identity.

    `title`, `description`, `note` and a shared slot's prose are omitted so wording can be
    improved without minting a ref. `consumes` and `slots` ARE covered: they change what the
    panel computes.
    """
    return {
        "template_id": t.template_id,
        "shared_slots": [s.name for s in t.shared_slots],
        "panels": [
            {"ordinal": i, "verb": p.verb, "role": p.role,
             "slots": p.slots, "consumes": sorted(p.consumes)}
            for i, p in enumerate(t.panels)
        ],
    }


def template_ref(t: CanvasTemplate) -> str:
    """`<template_id>@<first 12 hex of sha256 over the canonicalised semantic content>`."""
    digest = hashlib.sha256(_canonical(semantic_content(t)).encode("utf-8")).hexdigest()
    return f"{t.template_id}@{digest[:12]}"
