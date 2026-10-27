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
    not a fault in either the template or the request. 409, and a POLICY REFUSAL: it asks the
    caller to choose a value (`slot_refusal` names who widens the choice)."""

    def __init__(self, message: str, slots: "list[str] | tuple[str, ...]" = ()):
        super().__init__(message)
        self.slots = sorted(slots)


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
            f"the request.",
            unbound,
        )
    return clean


# ── WHAT A SHARED SLOT CAN BE ASKED ABOUT, AND WHERE THE ASK IS OWNED ──────────────────────
#
# `SharedSlot` carries a name, a description and a `param`; it does not carry a CLASS, so the
# server cannot say what to enumerate when a required one is unbound. This constant is the
# STOP-GAP until it does. Widening `SharedSlot` is a proposal for the architect, and it would
# touch the ratified yaml, which this change does not.
#
# Keyed by `param` (the dispatch identity, the word the verbs' signatures spell), valued by the
# class engine-fin declares for that parameter (`agent_fleet/finance_agent/slots.py`'s
# `_REFERENT_KIND`). `tests/planning/test_finance_canvas_asks_which_program.py` compares the
# two, so a class that moves on one side reads red rather than enumerating the wrong thing.
SHARED_SLOT_REFERENTS: dict[str, str] = {
    "program_id": "http://invincible-agent/fin#Program",
}

#: The (persona, domain) cell that OWNS each referent in `SHARED_SLOT_REFERENTS`: the cell the
#: second `mesh:seedCanvas` registration is made in, and the cell the 409's policy hint tells
#: a caller who cannot see any member to get into. One constant for both, so they cannot drift.
REFERENT_CELLS: dict[str, tuple[str, str]] = {
    "http://invincible-agent/fin#Program": ("PROGRAM_FINANCE_ANALYST", "PROGRAM_FINANCE"),
}


class DispatchParamsRefused(ValueError):
    """The supervisor's `params` could not be folded into a template and bindings. 422."""


def _consumed_names(t: CanvasTemplate) -> set[str]:
    return {c for p in t.panels for c in p.consumes}


def _slot_for_key(t: CanvasTemplate, key: str) -> Optional[SharedSlot]:
    """The shared slot a dispatch key addresses, by `param` or by `name`."""
    for s in t.shared_slots:
        if key == s.param or key == s.name:
            return s
    return None


def _load_all(directory: "Path | None" = None) -> dict[str, CanvasTemplate]:
    out: dict[str, CanvasTemplate] = {}
    for tid in ratified_template_ids(directory):
        try:
            out[tid] = load_template(tid, directory)
        except Exception:  # noqa: BLE001 - a template that will not load is not a candidate
            continue
    return out


def fold_dispatch_params(
    params: "dict[str, Any] | None",
    template_id: "str | None",
    bindings: "dict[str, Any] | None",
    directory: "Path | None" = None,
) -> tuple[str, dict[str, Any]]:
    """Fold the supervisor's dispatch `params` into `(template_id, bindings)`.

    The supervisor POSTs a bound verb's slots under `params`; `CanvasSeedRequest` had no such
    field, so a chat-routed seedCanvas lost its `template_id` and built the portfolio board.

    `template_id` comes back "" when neither source named one and `params` held nothing else:
    the caller then keeps today's `canvas_type` default. When `params` holds keys, a template is
    INFERRED from them and it is never the portfolio fallback: no match or several is a refusal.
    Raises `DispatchParamsRefused` (422) for every disagreement.
    """
    given = (template_id or "").strip()
    merged: dict[str, Any] = dict(bindings or {})
    p = dict(params or {})
    from_params = str(p.pop("template_id", "") or "").strip()

    if given and from_params and given != from_params:
        raise DispatchParamsRefused(
            f"template_id {given!r} in the request disagrees with template_id "
            f"{from_params!r} in params"
        )
    chosen = given or from_params
    if not p:
        return chosen, merged

    templates = _load_all(directory)
    if not chosen:
        def _matches(t: CanvasTemplate) -> bool:
            consumed = _consumed_names(t)
            for key in p:
                s = _slot_for_key(t, key)
                if s is None or s.name not in consumed:
                    return False
            return True

        hits = sorted(tid for tid, t in templates.items() if _matches(t))
        if not hits:
            raise DispatchParamsRefused(
                f"params {sorted(p)} match no shared slot consumed by any ratified template "
                f"(ratified: {sorted(templates)}); refusing rather than falling back to portfolio"
            )
        if len(hits) > 1:
            raise DispatchParamsRefused(
                f"params {sorted(p)} are ambiguous: they match templates {hits}; name one "
                f"with template_id"
            )
        chosen = hits[0]

    t = templates.get(chosen)
    if t is None:
        # Unknown id: the caller's template resolution refuses it by name (400).
        return chosen, merged
    for key, value in p.items():
        s = _slot_for_key(t, key)
        if s is None:
            raise DispatchParamsRefused(
                f"params key {key!r} matches no shared slot of template {chosen!r} "
                f"(declared: {[x.name for x in t.shared_slots]})"
            )
        if value in (None, ""):
            continue
        value = str(value)
        if s.name in merged and merged[s.name] not in (None, "") and merged[s.name] != value:
            raise DispatchParamsRefused(
                f"shared slot {s.name!r} is bound to {merged[s.name]!r} in `bindings` and "
                f"{value!r} in params"
            )
        merged[s.name] = value
    return chosen, merged


def referent_slots(
    templates: "dict[str, CanvasTemplate]", only: "set[str] | None" = None,
) -> list[dict[str, Any]]:
    """The referent-bearing slot declarations for the given templates, one per distinct `param`.

    ONE BUILDER FOR BOTH CONSUMERS: the second `mesh:seedCanvas` registration and the 409's ask
    read this, so what the router offers and what the seed route asks cannot drift. Only a
    shared slot some panel consumes counts; `only` narrows it to a set of slot NAMES.
    """
    out: dict[str, dict[str, Any]] = {}
    for t in templates.values():
        consumed = _consumed_names(t)
        for s in t.shared_slots:
            if s.name not in consumed or (only is not None and s.name not in only):
                continue
            referent = SHARED_SLOT_REFERENTS.get(s.bind_as)
            if referent is None or s.bind_as in out:
                continue
            out[s.bind_as] = {
                "name": s.bind_as, "type": "string", "required": True,
                "kind": "spoken-mandatory", "referent": referent,
                "description": s.description,
            }
    return list(out.values())


def seed_canvas_referent_slots(directory: "Path | None" = None) -> list[dict[str, Any]]:
    """The slots of the program-cell `mesh:seedCanvas` registration: each referent-bearing
    param, then an optional `template_id` whose menu is the templates consuming one."""
    templates = _load_all(directory)
    slots = referent_slots(templates)
    params = {s["name"] for s in slots}
    values = sorted(
        tid for tid, t in templates.items()
        if any(s.bind_as in params and s.name in _consumed_names(t) for s in t.shared_slots)
    )
    slots.append({
        "name": "template_id", "type": "string", "required": False,
        "kind": "spoken-optional", "values": values,
        "description": "Which ratified canvas template to build.",
    })
    return slots


def load_groups(path: "Path | None" = None) -> dict[str, Any]:
    """`policy/groups.yaml`'s `groups` mapping. Separate so a test can substitute it."""
    import yaml

    p = path or (_CANVAS_DIR.parent / "groups.yaml")
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("groups") or {}


def policy_hint(
    referent: str,
    groups: "dict[str, Any] | None" = None,
    *,
    held: bool = False,
    asked_in_cell: bool = False,
) -> dict[str, Any]:
    """Which cell owns `referent` and which groups grant it, for a caller whose enumeration
    came back EMPTY. DERIVED from `REFERENT_CELLS` and the groups file, never typed.

    THREE REPAIRS, AND THEY ARE DIFFERENT PEOPLE'S. `held` is whether the caller's token
    already carries the owning cell; `asked_in_cell` is whether the enumeration was scoped to
    it. A caller who holds the cell but asked from another one needs to SWITCH CELL — telling
    them to get a group they already have sends them to an administrator for nothing. A caller
    who holds it and asked from it sees no member because no member is granted to them (the
    per-asset grant). Only a caller who does not hold it needs the group.
    """
    persona, domain = REFERENT_CELLS[referent]
    noun = referent.rsplit("#", 1)[-1].rsplit("/", 1)[-1].lower() or "item"
    g = load_groups() if groups is None else groups
    names = sorted(
        name for name, body in g.items()
        if any(
            (x or {}).get("persona") == persona and (x or {}).get("domain") == domain
            for x in ((body or {}).get("grants") or [])
        )
    )
    cell = f"{persona} · {domain}"
    if held and not asked_in_cell:
        repair = "switch_cell"
        message = (
            f"You hold {cell}, but this was asked from another cell, which can see no "
            f"{noun}. Choose {cell} and ask again."
        )
    elif held:
        repair = "grant_member"
        message = (
            f"You hold {cell}, but no {noun} in it is granted to you. Ask an administrator "
            f"to grant you a {noun}."
        )
    elif names:
        repair = "join_group"
        who = " or ".join(f"`{n}`" for n in names)
        message = (
            f"You cannot see any {noun} from this cell. Ask an administrator to add you to "
            f"group {who} (policy/groups.yaml), which grants {cell}, then choose that cell."
        )
    else:
        repair = "declare_group"
        message = (
            f"You cannot see any {noun} from this cell. No group in policy/groups.yaml "
            f"grants {cell}; ask an administrator to add one."
        )
    return {"cell": {"persona": persona, "domain": domain}, "groups": names,
            "repair": repair, "message": message}


#: Which rail grants a caller one MEMBER of a referent: named by `slot_refusal` for `policy_hint`'s
#: `grant_member` repair ("ask an administrator to grant you a program") and for an ask's options,
#: which engine-fin filters by that grant (#113). One row per `REFERENT_CELLS` key (sealed by
#: `tests/security/test_every_policy_refusal_names_policy_binding_grantor.py`).
MEMBER_GRANTS: dict[str, tuple[str, str]] = {
    "http://invincible-agent/fin#Program": ("program_members", "can_view_program"),
}


def slot_refusal(template: CanvasTemplate, slots: "list[str] | tuple[str, ...]",
                 ask: "dict[str, Any] | None" = None) -> dict[str, Any]:
    """`policy_refusal`'s `policy_id`, `missing_binding` and `candidates` for an unbound shared
    slot -- the 409 is a policy refusal because it asks the caller to CHOOSE (architect,
    2026-10-25), so it names who can widen the choice (`src/iagent/authz/refusal.py`).

    THE FAMILY IS THE OWNING CELL'S. A slot whose referent a cell owns (`REFERENT_CELLS`) is
    chosen from what that cell sees, and a cell is granted by `groups`. A slot no cell owns is
    named under `code`: mapping it is a platform change. Several unbound slots name the first
    one's family; the message names them all.

    THE MENU IS THE MEMBER GRANT'S (architect, 2026-10-27). engine-fin lists and resolves only
    the members whose program the caller may view (`can_view_program`, #113), filtered before its
    limit, so the options a caller is offered are exactly what `program_members` grants them.
    When the ask carries options for a referent with a `MEMBER_GRANTS` row, that family is the
    grant that gates, and it is the one named. An ask with no options (a list too long to offer,
    or nobody asked) shows no menu the grant bounds, so it keeps the cell's family.

    WITH THE ASK (`gateway._canvas_seed_ask`) the refusal says what the ask says, and tells the
    caller nothing the ask does not already carry:
      options        candidates = the option values (the caller's own menu); policy_id =
                     `MEMBER_GRANTS`' family where the referent has one
      switch_cell    candidates = [the owning cell]; missing_binding = active_cell(<cell>)
      join_group     missing_binding = member_of(<group> | ...)
      declare_group  missing_binding = a_group_granting(<cell>)
      grant_member   `MEMBER_GRANTS`' family, named alone (object-scoped), and its relation
    A broken ask (`{"error": ...}`) or none gives the slot's default, never a 500.
    """
    slots = sorted(slots)
    by_name = {s.name: s for s in template.shared_slots}

    def _referent(slot: str) -> Optional[str]:
        s = by_name.get(slot)
        return SHARED_SLOT_REFERENTS.get(s.bind_as) if s is not None else None

    def _family(slot: str) -> str:
        return "groups" if _referent(slot) in REFERENT_CELLS else "code"

    family = _family(slots[0]) if slots else "code"
    named = [s for s in slots if _family(s) == family] or ["?"]
    out: dict[str, Any] = {"policy_id": family,
                           "missing_binding": ", ".join(f"bind({s})" for s in named),
                           "candidates": []}
    if not isinstance(ask, dict) or ask.get("error"):
        return out
    policy = ask.get("policy")
    if isinstance(policy, dict):
        cell = policy.get("cell") or {}
        label = f"{cell.get('persona')} · {cell.get('domain')}"
        repair = policy.get("repair")
        if repair == "switch_cell":
            out.update(missing_binding=f"active_cell({label})", candidates=[label])
        elif repair == "join_group" and policy.get("groups"):
            out.update(policy_id="groups",
                       missing_binding="member_of(" + " | ".join(policy["groups"]) + ")")
        elif repair == "declare_group":
            out.update(policy_id="groups", missing_binding=f"a_group_granting({label})")
        elif repair == "grant_member":
            grant = MEMBER_GRANTS.get(_referent(named[0]) or "")
            if grant is not None:
                out.update(policy_id=grant[0], missing_binding=f"{grant[1]}({named[0]})")
        return out
    options = ask.get("options") or []
    out["candidates"] = [o["value"] for o in options if isinstance(o, dict) and o.get("value")]
    grant = MEMBER_GRANTS.get(_referent(named[0]) or "")
    if out["candidates"] and grant is not None:
        out["policy_id"] = grant[0]
    return out
