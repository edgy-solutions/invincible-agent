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
from pathlib import Path
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
    param: Optional[str] = Field(
        default=None,
        description=("The verb PARAMETER this slot binds as, when it differs from `name`. "
                     "`program_finance` asks about `program` but every one of its six verbs "
                     "takes `program_id` — `name` is the ASK's identity (what §3.1 offers one "
                     "menu for), `param` is the DISPATCH identity (what the verb's signature "
                     "spells). None means they are the same word."))

    @property
    def bind_as(self) -> str:
        """The verb parameter this slot's bound value is passed under. `param or name` —
        read through one property so a caller never has to repeat the fallback."""
        return self.param or self.name


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
    subject: Optional[str] = Field(
        default=None,
        description="The verb's INPUT CLASS, full IRI form (e.g. "
                    "`http://invincible-agent/fin#Program`) — exactly the string "
                    "`find_compatible_verbs`/`dispatch_pre_resolved` compare as `subject_uri`, "
                    "and exactly the producing engine's own VERBS catalogue `input_uri` for this "
                    "verb. THE TEMPLATE DECLARES IT; nothing here looks it up. A seed_panel turn "
                    "reads this field directly as `subject_uri` — the mesh still CONFIRMS it on "
                    "every dispatch via `find_compatible_verbs`, so a stale or wrong declaration "
                    "fails visibly (FALL_BACK) rather than silently routing. Unset on a panel "
                    "that cannot be dispatched directly from a seed (e.g. portfolio's panels).")


class Package(BaseModel):
    """A template declares itself packageable by naming WHO it may be disclosed to.

    `audience` is a closed set of one value today, `program_office` — a `Literal`, not a bare
    `str`, so an unratified audience fails at load rather than at the first packageExport call.
    Absent on a template (e.g. `portfolio`) means that template has no recipient and
    packageExport has nothing to compute a scope for.
    """
    model_config = ConfigDict(extra="forbid")

    audience: Literal["program_office"] = Field(
        ..., description="Who a packageExport of this template may be disclosed to.")


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
    package: Optional[Package] = Field(
        default=None,
        description="Set when this template is a package definition for some audience — see "
                    "`recipient_scope_for`. Unset means this template cannot be packageExported.")


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
        # `bind_as`, NOT `name`. A `param` change repoints which verb parameter the ask's
        # answer lands on — same ask, different dispatch — so it is semantic content exactly
        # as `consumes`/`slots` are, and must mint a new ref.
        "shared_slots": [{"name": s.name, "bind_as": s.bind_as} for s in t.shared_slots],
        "panels": [
            {"ordinal": i, "verb": p.verb, "role": p.role,
             "slots": p.slots, "consumes": sorted(p.consumes), "subject": p.subject}
            for i, p in enumerate(t.panels)
        ],
        # `audience` only — a template packaged for a different audience is a different
        # disclosure, and must mint a new ref.
        "package": {"audience": t.package.audience} if t.package else None,
    }


def template_ref(t: CanvasTemplate) -> str:
    """`<template_id>@<first 12 hex of sha256 over the canonicalised semantic content>`."""
    digest = hashlib.sha256(_canonical(semantic_content(t)).encode("utf-8")).hexdigest()
    return f"{t.template_id}@{digest[:12]}"


# ── §4 — the ratified set, DERIVED from the directory ───────────────────────────────────────
#
# The seed verb's `template_id` slot is "enumerated from the ratified set", per the model's own
# docstring. That enumeration is read off `policy/canvases/` and NEVER kept beside it.
#
# A HAND-KEPT LIST IS A SECOND POPULATION, and it drifts in the direction that hides: a template
# ratified and not listed is simply unofferable, with nothing anywhere reading as an error. Three
# separate instances of exactly this shape landed on 2026-09-08/09 — a manifest key regex that
# could not express `neo4j_expert`, a census join that guessed a deployment from an env var, and
# a frontend registry whose known-ids list sat beside the registry rather than being read from it.
#
# THE FILENAME IS THE ID, and the model already requires `template_id` to equal the stem. That is
# checked here rather than trusted, because a file whose stem and id disagree is offerable under
# one name and loadable under the other.

_CANVAS_DIR = Path(__file__).resolve().parents[2] / "policy" / "canvases"


def ratified_template_ids(directory: "Path | None" = None) -> list[str]:
    """Every ratified template id, sorted. Derived from the directory each call.

    NOT CACHED: the set changes when a file is ratified, and a process holding a stale set
    offers a menu that no longer matches the substrate — the same staleness that makes a
    registration outlive the thing it registered.
    """
    d = directory or _CANVAS_DIR
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.yaml"))


def load_template(template_id: str, directory: "Path | None" = None) -> CanvasTemplate:
    """Load and VALIDATE one ratified template. Raises rather than returning a default.

    `KeyError` when the id is not ratified — never a fallback to a default template. A seed
    that quietly builds the portfolio board because it did not recognise the id produces a
    board that is WRONG rather than absent, and a wrong board is harder to notice than a
    missing one: it draws, every card is real, and nothing reports it.
    """
    import yaml  # local: the gateway imports this module at startup and yaml is not free

    d = directory or _CANVAS_DIR
    path = d / f"{template_id}.yaml"
    if not template_id or not path.is_file():
        raise KeyError(
            f"no ratified canvas template {template_id!r}; ratified: "
            f"{ratified_template_ids(d)}"
        )
    t = CanvasTemplate.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    if t.template_id != template_id:
        # Offerable under one name, loadable under the other — the menu and the substrate
        # would disagree about what the caller picked.
        raise ValueError(
            f"{path.name} declares template_id {t.template_id!r}, which is not its stem"
        )
    return t


# ── §3 — ONE DISPATCH, READ BY SEEDING AND BY packageExport ────────────────────────────────
#
# `panel_dispatch` is the pre-resolved route a panel compiles to: its verb, its subject (the
# mesh's own `subject_uri`, still CONFIRMED on every dispatch — this function only declares it)
# and its bound params. `gateway.py`'s `_pre_resolved_from_seed_panel` calls this rather than
# recomputing it, and packageExport calls it for the same panel to build the same params it
# would seed with. Two implementations that happen to agree is exactly the defect this item
# exists to close — there is one function, and both callers read it.
def panel_dispatch(
    template: CanvasTemplate, panel_idx: int, bindings: dict[str, Any],
) -> tuple[str, Optional[str], dict[str, Any]]:
    """`(verb, subject, params)` for one panel, bound against `bindings`.

    `params` starts from the panel's own declared `slots` (panel-local, never asked at load)
    and adds every consumed shared slot that `bindings` actually supplies, under its `bind_as`
    — the DISPATCH identity, not the ask's. An unbound consumed slot is OMITTED, never sent as
    `None`: a param this verb never received is a param it should see as absent, not as null.
    """
    panel = template.panels[panel_idx]
    by_name = {s.name: s for s in template.shared_slots}
    params: dict[str, Any] = dict(panel.slots)
    for slot_name in panel.consumes:
        slot = by_name.get(slot_name)
        if slot is None:
            continue
        value = bindings.get(slot_name)
        if value in (None, ""):
            continue
        params[slot.bind_as] = value
    return panel.verb, panel.subject, params


def recipient_scope_for(template: CanvasTemplate, bindings: dict[str, Any]) -> str:
    """`<package.audience>.<bound program>` — the recipient one packageExport is scoped to.

    THE SEPARATOR IS `.`, NEVER `:`: the scope becomes a filename
    (`fin-package-{scope}.html`), and a colon is not a safe filename character everywhere
    this runs.

    THE BOUND PROGRAM IS DERIVED, never hard-coded to `"program"` — it is whichever shared
    slot this template's own panels `consumes`, read in the template's declared order, so a
    template whose ask is spelled differently is not a special case here.

    Raises `ValueError` when this template declares no `package`, when none of its shared
    slots is consumed by any panel, or when that slot is unbound — a packageExport has no
    recipient in any of those states.
    """
    if template.package is None:
        raise ValueError(
            f"{template.template_id!r} declares no package; packageExport has no recipient"
        )
    consumed = {name for p in template.panels for name in p.consumes}
    program_slot = next((s for s in template.shared_slots if s.name in consumed), None)
    if program_slot is None:
        raise ValueError(
            f"{template.template_id!r} consumes no shared slot; packageExport has no recipient"
        )
    value = bindings.get(program_slot.name)
    if value in (None, ""):
        raise ValueError(
            f"{template.template_id!r}'s shared slot {program_slot.name!r} is unbound; "
            f"packageExport has no recipient"
        )
    return f"{template.package.audience}.{value}"


# ── R-005's gate, factored out so `canvas_seed` and packageExport read ONE function ─────────
#
# This is `canvas_seed`'s own binding-validation block (ADR-0050 §4, R-005), extracted rather
# than copied: item 3 needs the SAME three checks before it will compute a recipient scope or
# dispatch a panel, and a second hand-kept copy beside this one is exactly the "two
# implementations that happen to agree" defect `panel_dispatch`'s own docstring exists to
# foreclose. The three outcomes keep their ORIGINAL wording verbatim —
# `tests/planning/test_shared_slots_are_template_scoped.py` asserts substrings of it — so this
# extraction changes WHERE the checks run, never WHAT they say.

class UndeclaredConsumption(ValueError):
    """A panel consumes a shared slot the template itself never declares — a fault in the
    TEMPLATE, which no binding can fix. 422."""


class UnknownBinding(ValueError):
    """`bindings` names a shared slot this template does not declare — a fault in the
    REQUEST, most often a typo. 422."""


class UnboundRequiredSlot(ValueError):
    """A declared, consumed shared slot has nothing bound to it yet — the ADR-0050 §3 carry,
    not a fault in either the template or the request. 409."""


def validate_bindings(template: CanvasTemplate, bindings: dict[str, Any]) -> dict[str, Any]:
    """The bound slots a seed or a packageExport may dispatch with, or a raise naming which
    of the three R-005 outcomes applies. Strips `None`/`""` values from `bindings` first — an
    empty string counts as NOT supplying the slot, so a picker sending `{"program": ""}` is
    treated as having bound nothing, never as carrying an empty value to a verb that requires
    one.
    """
    declared = {s.name for s in template.shared_slots}
    consumed = {c for p in template.panels for c in p.consumes}

    undeclared = sorted(consumed - declared)
    if undeclared:
        raise UndeclaredConsumption(
            f"template {template.template_id!r} has panel(s) consuming shared slot(s) "
            f"{undeclared} that the template does not declare. This is a fault in the "
            f"template, not a missing binding — declaring them is the fix."
        )

    clean = {k: v for k, v in (bindings or {}).items() if v not in (None, "")}

    unknown = sorted(set(clean) - declared)
    if unknown:
        raise UnknownBinding(
            f"template {template.template_id!r} does not declare shared slot(s) "
            f"{unknown} named in `bindings`."
        )

    unbound = sorted(consumed - set(clean))
    if unbound:
        raise UnboundRequiredSlot(
            f"template {template.template_id!r} has panel(s) consuming shared slot(s) "
            f"{unbound} that nothing binds yet, so those panels would refuse. Supply it "
            f"in `bindings`. This is the ADR-0050 §3 carry, not a fault in the template or "
            f"the request."
        )
    return clean
