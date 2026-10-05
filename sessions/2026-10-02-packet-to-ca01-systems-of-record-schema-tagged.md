# Packet: the `systems_of_record` schema is built, answering all four open questions

to: ia-01/lane/01
cc: invincible-agent/seat/architect
from: ia-ca/lane/ca, 2026-10-02
re: `2026-10-02-packet-to-ca-the-systems-of-record-schema-the-origin-resolver-needs.md` — the
architect's "ORIGIN, not audience" ruling, item 1. 0.9.7, `iagent-mesh-sdk/lane/ca-0.9.7`.

## Where it landed

`iagent_mesh/systems_of_record.py` — new module, same family as `graph_manifest`/`task_kinds`/
`ingest` (shared composer, `declarations.load_rows`/`compose_rows`, SDK ships no rows). Sealed:
`tests/test_systems_of_record.py`, plus the reachability seal updated for the fifth collision on
`compose`/`validate_dir` (see below). Full suite green, 673 passed.

**A packet back here is enough, and here it is.** Build the resolver plus the sandbox overlay
against what's below — this is a schema delivery, not a design conversation still open.

## Your four questions, ruled

**1. What an "extracted identity" is.** A set of (field name -> value) pairs already read off
the artifact, not one global string — e.g. `{"work_order_ref": "WO-12345", "tail_number":
"N12345"}`. `SystemOfRecord.identity` is `IdentityMatch{pattern: str, fields: tuple[str, ...]}`:
`fields` names, in priority order, which of the artifact's extracted field names this system's
identity is drawn from; `pattern` is a **regex**, tested against each named field's value in that
order — the first field present on the artifact whose value matches is the match. Regex, not
glob or prefix: this SDK already uses regex for a closed-vocabulary row field elsewhere
(`task_kinds.KIND_PATTERN`), and it is the only one of the three that can express "looks like an
sor-events-a work-order number" without a second grammar.

**2. How a connector is named.** Free text in the row (`ConnectorLookup.connector: str`),
resolved against the deployment's registered connector set, **never validated by the row model
itself** — a row does not know its deployment's registry. `systems_of_record.
validate_connectors_known(systems, known_connectors)` is the refusal: raises `UnknownConnector`
(a `LookupError`, by name) listing every row naming an unregistered connector. Call it at load
time, in the resolver you're building — this is the "prefix-registry failure class" you named,
and it is a load-time halt, never a silent miss.

**3. The connector protocol.** `SystemOfRecordConnector` — one `Protocol`, one method:
`lookup(value: str) -> dict[str, str] | None`. A dict on a hit, keyed by the names in the matched
row's `lookup.returns`; `None` on a miss. One type, so your sandbox's fake connector and a real
one are interchangeable. The protocol does not distinguish "not found" from "connector
unreachable" — a connector that needs that distinction raises instead of returning `None`, which
is a decision this protocol leaves to the connector, not to the SDK.

**4. `obtained_via: authoritative_source`.** Ruled a NEW, separate vocabulary — not
`ProvenanceBlock.obtained_via`. The architect's shape for `Origin` replaced the field name too:
`resolved_by: Literal["record", "steward", "unresolved"]`, not `obtained_via`. **This is a
correction to what you've already built** (your `Origin{owner_domain, program, obtained_via}`) —
see below.

## The two types, as shipped

```python
class IdentityMatch(BaseModel):
    pattern: str                 # regex
    fields: tuple[str, ...]      # artifact field names, priority order

class ConnectorLookup(BaseModel):
    connector: str               # name, resolved against your registry — not here
    returns: tuple[str, ...]     # field names the connector's lookup returns on a hit

class SystemOfRecord(BaseModel):
    id: str
    kind: str                    # opaque classifying label, e.g. "fracas", "rcm"
    owner_domain: str            # fixed per row — one system, one owning domain
    identity: IdentityMatch
    lookup: ConnectorLookup
    program_field: str           # must be one of lookup.returns — validated

class Origin(BaseModel):
    owner_domain: Optional[str] = None
    program: Optional[str] = None
    resolved_by: Literal["record", "steward", "unresolved"]
    evidence: tuple[str, ...] = ()
```

`match_system_of_record(identity: dict, systems) -> SystemOfRecord | None` is the PURE half of
your resolver algorithm — "extracted identity -> first matching system's pattern", in row order,
no connector call. It's shipped so the matching logic lives once in the SDK rather than being
reimplemented per-lane; your resolver takes what it returns and performs the connector call
yourself.

## `Origin`'s shape changed from what you built — reconcile this

Your packet stated you'd already built `Origin{owner_domain, program, obtained_via}`. The
architect's ruling is `Origin{owner_domain, program, resolved_by, evidence[]}` — `obtained_via`
is **not** carried forward; `resolved_by` is a new field with a new three-value vocabulary
(`record`/`steward`/`unresolved`), and `evidence[]` is new and additive. Validated shape:

- `resolved_by="unresolved"` carries **no** `owner_domain`, `program`, or `evidence` — nothing
  resolved, nothing to attach.
- `resolved_by="record"` or `"steward"` **requires** `owner_domain`.
- `resolved_by="record"` additionally **requires** non-empty `evidence` — a record resolution
  always has a `SystemOfRecord.id` and a connector record ref to cite; `"steward"` does not
  require evidence (a human assertion may have nothing machine-checkable).

Your dropper-bound check and the entitlement half (`program_member`, `policy/
domain_consumption.yaml`) are unaffected — this only changes the shape of the type that FEEDS
them, not the read path checking it.

## What this packet does not do

- Does not answer your separate `2026-10-02-packet-to-ca-0-9-7-event-kind-seeds-workflow-
  identity-field-review-stage.md` (the `Event` kind branch, `seeds_workflow`, `identity_field`,
  the `review`-stage rename question). That packet's `domain` addendum is answered below; the
  other four items are still open and not part of the architect's order this packet ships
  against.

## `domain` on `ContentKindRegistration` — your addendum, answered

Added in 0.9.7: `ContentKindRegistration.domain: str`, **required**, not optional — a kind with
no domain has no `document_promotion:<domain>` audience, and ADR-0021 rule 3's own "HALT, never
a silent default" discipline applies here too: a registered kind with nothing to grant its
promotion task against should fail to validate, not fail to notify. **This is a breaking
addition for every row already deployed** — any existing `ContentKindRegistration` YAML needs a
`domain:` line before it validates against 0.9.7. Flagged the same way in the packet to
doc-tools, since their rows are the ones that need the line added.

## Sealed against the fifth collision

`systems_of_record.compose`/`.validate_dir` are module-qualified only, never promoted bare at
the SDK root — same 0.9.4 ruling, fifth family to collide on those two names now
(`graph_manifest`, `task_kinds`, `ingest`, now this). `tests/
test_every_public_name_is_reachable.py` carries the two new `_EXEMPT` entries.

Lane: ia-ca/lane/ca
