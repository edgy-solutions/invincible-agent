"""The graph manifest — a graph is a mesh verb only because a ratified row says so.

ADR-0046 §1: one graph, one verb, full contract. ADR-0046 §2 refuses ``run_any_graph`` by
name. **This module is what makes that refusal STRUCTURAL rather than a rule people follow.**
The host registers exactly the rows it loads from ``policy/graphs/*.yaml`` and has no other
way to learn a graph exists: a module sitting in ``graphs/`` with no ratified row is invisible
to the mesh, and ``tests/graph_host/test_no_manifest_row_no_verb.py`` asserts that against the
MESH's verb list rather than the host's file list.

WHY ``policy/graphs/<id>.yaml`` AND NOT A SINGLE ``graphs.yaml``. The dispatch named
``graphs.yaml``; the discipline it named — ADR-0050 §1 — is *one file, one template*, in
``policy/``, "diffable, greppable, reviewed like a grant, entering only by PR". Those two
disagree, and the discipline wins here because admitting a graph to the mesh is exactly the
kind of decision that should be one reviewable file: a single ``graphs.yaml`` makes every
graph's admission a shared diff, and the first two lanes adding graphs the same week collide
in it. **Flagged rather than assumed** — this is a one-line change if the architect wants the
single file.

WHAT A ROW MUST CARRY, and why each is here rather than inferred. Every field below maps to a
parameter of ``register_engine_to_mesh`` or to a clause of §1's contract table. Nothing is
derived from the graph module by inspection, and that is deliberate: ADR-0046 §7 refuses
auto-derivation of slot KIND as a non-goal, on Lane 1's finding that two ``str`` parameters can
have opposite provenance and no type system tells them apart.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: The four-kind slot vocabulary, reproduced verbatim and in order from the engines that
#: established it (finance_agent/slots.py, planning_agent/slots.py, cost_agent/slots.py), so a
#: consumer reading declarations from a hosted graph sees ONE vocabulary rather than a fourth
#: that agrees. When the slot_declarations extraction lands (Lane 1's), this constant is one of
#: the things it hoists — this module is that extraction's next consumer, and says so.
SLOT_KINDS = ("spoken-mandatory", "spoken-optional", "handle", "ceremony")

#: What a graph does when an inner verb refuses for the initiator. DECLARED PER ROW, never
#: decided at runtime — ADR-0049 Ruling 2's named hole is a design choice about what an answer
#: means, and a graph that picked it per-invocation would give two callers different contracts
#: for the same verb.
REFUSAL_DISPOSITIONS = ("fail", "named-hole")


class SlotDecl(BaseModel):
    """One declared slot. Mirrors what `slots_for()` emits in the three engines that have it."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: Literal[SLOT_KINDS]  # type: ignore[valid-type]
    type: str = "string"
    required: bool = False
    #: The CLASS URI of what this slot's value names, when the value is an instance reference.
    #: Declared, never sniffed from an `_id` suffix — Lane 1 measured the cost of guessing: the
    #: filler emitted a plausible value at 0.92 confidence and the engine answered an honest
    #: 422 to a perfectly answerable question.
    referent: Optional[str] = None
    values: Optional[list[str]] = None
    default: Optional[Any] = None

    @model_validator(mode="after")
    def _referent_only_on_spoken(self) -> "SlotDecl":
        if self.referent and self.kind not in ("spoken-mandatory", "spoken-optional"):
            raise ValueError(
                f"slot {self.name!r}: a referent belongs on a SPOKEN slot. A handle is resolved "
                f"by the dispatcher from the store and was never something a speaker names."
            )
        return self


class GraphManifest(BaseModel):
    """One ratified row. One row, one registered mesh verb — ADR-0046 §1."""

    model_config = ConfigDict(extra="forbid")

    graph_id: str
    #: Import path and callable that BUILDS the graph. Not the compiled graph: the host compiles
    #: it, so the checkpointer decision below is the host's to honour and not the module's to
    #: make. A module that compiled itself could attach a checkpointer this row said was off.
    module: str
    builder: str = "build"

    #: --- the mesh verb this row registers -------------------------------------------------
    verb: str
    name: str
    description: str
    input_uri: str
    output_uri: str
    owner_persona: Optional[str] = None
    domains: list[str] = Field(default_factory=list)
    cost_class: Literal["low", "medium", "high"] = "medium"
    requires_human_approval: bool = False
    timeout_s: Optional[float] = None

    #: --- the contract ---------------------------------------------------------------------
    slots: list[SlotDecl] = Field(default_factory=list)
    #: `single` means the question must name one instance. ADR-0046 §1: without arity the
    #: eligibility gate cannot drop a single-shaped verb from a set-shaped question, and the
    #: question routes to a verb that cannot answer it and 400s two hops later.
    arity: Optional[Literal["single", "set"]] = None
    refusal: Literal[REFUSAL_DISPOSITIONS] = "fail"  # type: ignore[valid-type]

    #: --- the one thing worth keeping from Engine B ------------------------------------------
    #: AsyncPostgresSaver keyed by thread_id. Per-graph and OFF by default: Engine B's memory
    #: was durable, real, and never read by any node, so a checkpointer nobody consults is
    #: storage cost with the appearance of statefulness (ADR-0046 §4, short-circuit 1).
    checkpointer: bool = False

    @field_validator("verb")
    @classmethod
    def _verb_is_prefixed(cls, v: str) -> str:
        if ":" not in v:
            raise ValueError(f"verb {v!r} must be a CURIE like 'mesh:finProgramBrief'")
        return v

    @field_validator("input_uri", "output_uri")
    @classmethod
    def _ends_are_absolute(cls, v: str) -> str:
        # CONTRACT D REFUSES ATOMICALLY IF EITHER END IS ABSENT, and a CURIE here reads as a
        # missing class at the registrar rather than as a malformed one — the fourth instance
        # of that confusion in this repo, and the one that lied.
        if not v.startswith("http"):
            raise ValueError(f"{v!r} must be an absolute class URI, not a CURIE")
        return v

    @model_validator(mode="after")
    def _arity_agrees_with_slots(self) -> "GraphManifest":
        referent_required = [
            s for s in self.slots if s.required and s.referent and s.kind == "spoken-mandatory"
        ]
        if referent_required and self.arity != "single":
            raise ValueError(
                f"{self.graph_id}: slot {referent_required[0].name!r} is both required and a "
                f"referent, which makes this verb single-instance — declare arity: single. "
                f"(signature-derived rule, planning_agent/slots.py)"
            )
        return self

    @model_validator(mode="after")
    def _no_payload_slot(self) -> "GraphManifest":
        # REFUSED BY NAME, ADR-0046 §2. A `payload: object` slot is `run_any_graph` wearing a
        # manifest: it declares a verb whose input the router cannot reason about, cannot know
        # is missing, and cannot scope an entitlement to.
        for s in self.slots:
            if s.type in ("object", "any", "dict") or s.name in ("payload", "params", "body"):
                raise ValueError(
                    f"{self.graph_id}: slot {s.name!r} of type {s.type!r} is an untyped "
                    f"passthrough — ADR-0046 §2 refuses it. Declare the fields the graph "
                    f"actually reads."
                )
        return self


def manifest_ref(m: GraphManifest) -> str:
    """`<graph_id>@<first 12 hex of sha256>` over SEMANTIC content, per ADR-0050 §1.5.

    Canonicalisation follows cost_agent/export.py's `_canonical` — `sort_keys=True` and the
    separators pin, which is the one thing policy_rules_loader's version lacks. An unpinned
    separator is a ref that moves when a serializer's defaults do.

    The hash covers the CONTRACT — verb, both Contract D ends, slots, arity, refusal — and not
    the file bytes, so a reflowed comment or a reordered key does not mint a new ref and a
    changed slot does.
    """
    semantic = {
        "graph_id": m.graph_id,
        "verb": m.verb,
        "input_uri": m.input_uri,
        "output_uri": m.output_uri,
        "arity": m.arity,
        "refusal": m.refusal,
        "slots": [s.model_dump(exclude_none=True) for s in m.slots],
    }
    blob = json.dumps(semantic, sort_keys=True, separators=(",", ":"))
    return f"{m.graph_id}@{hashlib.sha256(blob.encode()).hexdigest()[:12]}"


def load_manifests(policy_dir: Path) -> list[GraphManifest]:
    """Every ratified row, sorted by graph_id. RAISES on an invalid row.

    FAIL LOUD AT BOOT rather than skip the bad row. Engine F's rule and the reason is
    identical: a host that skipped an invalid manifest would come up healthy, serve every
    probe, and be missing exactly one verb — the failure mode with no symptom.
    """
    out: list[GraphManifest] = []
    for f in sorted(policy_dir.glob("*.yaml")):
        raw = yaml.safe_load(f.read_text(encoding="utf-8"))
        if raw is None:
            raise ValueError(f"{f.name} is empty — an empty ratified row is not a row")
        try:
            out.append(GraphManifest(**raw))
        except Exception as exc:  # pragma: no cover - message shape asserted in tests
            raise ValueError(f"{f.name} is not a valid graph manifest: {exc}") from exc
    ids = [m.graph_id for m in out]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate graph_id across ratified rows: {sorted(dupes)}")
    verbs = [m.verb for m in out]
    vdupes = {v for v in verbs if verbs.count(v) > 1}
    if vdupes:
        # ONE NAME PER (VERB, SUBJECT). The registrar's compensate-on-rescope sweep DELETES
        # rows matching (tool_urn, verb_iri) whose input_uri differs, so two rows sharing a
        # verb would silently replace each other rather than both registering.
        raise ValueError(f"two graphs registering the same verb: {sorted(vdupes)}")
    return out


def json_schema() -> dict:
    """The committed schema artifact, generated FROM the models (ADR-0050 §1.2).

    The models and the schema cannot disagree because one is generated from the other; the
    drift test asserts the committed file still equals this.
    """
    return GraphManifest.model_json_schema()
