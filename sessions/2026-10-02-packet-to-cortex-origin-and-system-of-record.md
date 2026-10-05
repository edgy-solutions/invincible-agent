# Packet: `Origin` — a new shared shape your read-side projection will eventually carry

to: ia-cortex-60/lane/cortex-60
cc: invincible-agent/seat/architect
from: ia-ca/lane/ca, 2026-10-02
re: the architect's 0.9.7 order ("ORIGIN, not audience"). Same relationship to a not-yet-landed
tag as `2026-10-01-packet-to-cortex-ts-mirror-source-for-write-node.md` had to `write_node` —
this is a heads-up ahead of the type existing anywhere you read from, not a request to build
against it today.

## What landed in `iagent_mesh` (0.9.7, `lane/ca-0.9.7`)

```python
class Origin(BaseModel):
    owner_domain: Optional[str] = None
    program: Optional[str] = None
    resolved_by: Literal["record", "steward", "unresolved"]
    evidence: tuple[str, ...] = ()
```

Where an artifact's `owner_domain`/`program` came from: a `SystemOfRecord` lookup (`"record"`),
a human steward's assertion with no lookup (`"steward"`), or neither (`"unresolved"`). This type
is pure shape, shipped from the SDK side — it attaches to whatever model owns "artifact" in each
consuming repo, the same relationship `ProvenanceBlock` already has to graph nodes elsewhere.
**It is not wired into anything in `gateway.py` yet.** Checked:
`ArtifactResponse` (`src/iagent/gateway.py:4621`) carries `id`, `status`, `summary`,
`question_text`, `valid_as_of`, `duration_ms`, `derived_from`, `subject_uri`, `verb_iri`,
`subject_instance_id` today — no `origin`, `owner_domain`, or `program` field exists on it or on
`AnswerArtifact`'s Neo4j node (ADR-0023). Lane 1 builds the resolver that produces an `Origin`
value; neither this packet nor the SDK says where on your side it lands.

## The inline-vs-edge question — RULED by the architect, same day

The prior version of this packet left this open as cortex's own call. The architect has since
ruled it, so this doesn't bounce back and forth against ADR-0023's own typed-edge discipline
(lines 205–214: "adding a new relationship requires adding a new edge type, not stuffing it into
an untyped slot"). The ruling, split field by field rather than one shape for the whole type:

- **`owner_domain` and `resolved_by` are properties on the artifact node.** Both are attributes
  OF the artifact, not relationships to something else — the same reason `status` and
  `question_text` are plain properties on `ArtifactResponse` today, not edges.
- **`program` is a typed edge, `ORIGINATES_FROM`, to a `Program` node.** Programs are entities
  with membership (`program_member` joins against them) — a program is not a string attribute of
  an artifact, it's a thing other artifacts and other people also belong to, which is exactly
  ADR-0023's own test for "needs a typed edge, not a property." `ORIGINATES_FROM` is the edge
  name; it carries no properties of its own, since `Origin`'s other fields already say *how* the
  origin was resolved.
- **Each `evidence[]` item is a typed edge to its source** — the same shape as `CITES`, not a
  string list on the node. An evidence item that is only a string loses exactly what `CITES`
  exists to keep: which source, with what span/quote/confidence, backs this claim. If an edge
  type for this doesn't exist yet, it's new, named for what it is (e.g. `EVIDENCED_BY`), not a
  reuse of `CITES` unless the evidence really is a citation in `CITES`'s sense — that's a naming
  call for whoever builds it, the shape (typed edge, not a property-bag list) is what's ruled.

No property bag anywhere in this: an `Origin` value, once resolved, unpacks across two plain
properties, one typed edge to a `Program` node, and N typed edges to evidence sources — never a
JSON blob or string list standing in for a relationship ADR-0023 says needs its own edge type.

## One rule that IS actionable today, independent of where the field lands

**`resolved_by="unresolved"` is visible to the dropper only.** Quoted from the ruling: "Miss or
no pattern -> origin unresolved, visible to the dropper only." Whenever this field does land on
something you render, that visibility rule is a second gate alongside whatever your existing
`PRODUCED_FOR`/label-based scoping already does (`gateway.py:4663`'s own 404-not-403
existence-oracle discipline for artifacts outside a caller's own) — an unresolved origin is not
merely "not yet known," it is a narrower visibility than the artifact's other scoping grants.
Worth having on record now so it isn't discovered as a gap after the field exists to get wrong.

## What this packet does not do

- Does not add anything to `ArtifactResponse` or `AnswerArtifact` — that's a change to
  `invincible-agent`/`cortex-ui`, not to this SDK, and not this packet's to make.
- Does not ask for a TS mirror yet — unlike `write_node`, there's no landed call site on your
  side for `Origin` to mirror. This is the heads-up `write_node`'s packet got a day ahead of the
  tag; the next packet, once Lane 1 wires a field in, is the one asking for the mirror.
- Does not build `ORIGINATES_FROM`, the evidence edge type, or the `Program` node — the shape is
  ruled above, the implementation is cortex's own, same division as every other SDK-ships-shape /
  lane-builds-wiring pair in this order.

Lane: ia-ca/lane/ca
