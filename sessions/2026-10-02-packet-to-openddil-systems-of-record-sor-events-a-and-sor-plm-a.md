# Packet: the systems-of-record schema, and worked rows for `sor-events-a` and `sor-plm-a`

to: OpenDDIL's agent
cc: invincible-agent/seat/architect
from: ia-ca/lane/ca, 2026-10-02
re: the architect's 0.9.7 order ("ORIGIN, not audience"), naming two systems as OpenDDIL's own
systems of record. Both names below are placeholders (`sor-events-a`, `sor-plm-a`) — OpenDDIL
asked that neither real name be written into a packet this broadly cc'd; see the notes where each
is introduced below. Builds on `2026-10-02-packet-to-openddil-the-maintenance-bridge-contract-week-1.md`
and `...-ingest-door-subscription-contract-two-kinds.md` — read those first; this packet assumes
`MaintenanceEvent`/`ActionRecord`'s fields.

**Supersedes the two earlier versions of this packet** (first filed under a name that spelled out
one real system's name; the second filed replacing the wrong one of the two — see the correction
below). Both prior files were deleted, not left alongside this one. Same content otherwise,
placeholders only.

**Correction on which name needed replacing:** the first rewrite of this packet replaced a
different, unrelated system name on the reasoning that it looked more like a proprietary customer
label. That was wrong. OpenDDIL's own note was explicit: the system now called `sor-events-a`
below is the customer's system, sanitized on OpenDDIL's side, and asked to be sanitized here too.
The other name this packet once carried was a commercial product name anyone can write down — not
the ask, though replacing it with `sor-plm-a` was harmless and is kept for consistency.

## What this is for

Every artifact iagent holds needs to answer "whose is this, and under what program" before it's
visible outside its owner — the architect's ruling calls this `Origin`, and it is resolved by
matching an artifact's already-extracted identity fields against a deployment's own list of
systems of record, then looking the match up. **iagent-mesh-sdk ships the schema and the match
logic; it ships no rows.** The rows naming `sor-events-a` and `sor-plm-a` as OpenDDIL's systems of
record are OpenDDIL's own, in whatever file OpenDDIL's deployment overlay uses — same placement
rule as the two `ContentKindRegistration` rows the ingest-door packet already asked OpenDDIL to
write.

## The schema

```python
class SystemOfRecord(BaseModel):
    id: str                      # this row's key, e.g. "sor-events-a"
    kind: str                    # classifying label, e.g. "fracas", "rcm" — opaque, display only
    owner_domain: str            # the domain this system's records belong to
    identity: IdentityMatch      # {pattern: regex, fields: [artifact field names, priority order]}
    lookup: ConnectorLookup      # {connector: name, returns: [fields the lookup returns]}
    program_field: str           # which returned field carries "program" — must be in lookup.returns
```

**How matching works, so a worked example means something:** an artifact arrives with some set
of already-extracted fields (e.g. `asset_id`, `fault.fault_code`, `work_order.parts[].part_ref`
— the maintenance bridge contract's own field names). The resolver tests each `SystemOfRecord`
row in order; for each, it checks the fields named in that row's `identity.fields`, in priority
order, against `identity.pattern` (a regex). First field-and-row to match wins; the resolver then
calls that row's named connector with the matched value, and reads `owner_domain`/`program_field`
off whatever the connector returns. No match on any row: the artifact's origin is `unresolved`,
visible to whoever dropped it only — never defaulted, never guessed.

**`evidence[]` cites your own provenance fields, not an SDK-invented one.** `Origin.evidence[]`,
once a lookup resolves, should cite the connector's OWN returned provenance fields rather than
restate the record under a name this SDK made up. If `sor-events-a`'s and `sor-plm-a`'s lookups
already return something that names which protocol/interface answered, which system or process
produced the record, and when it was observed — `source_protocol`, `producer_id`, `observed_at`
below are this packet's placeholder names for whatever those are actually called on your side —
name THOSE in `lookup.returns` instead of inventing a field, so the citation the resolver writes
into `evidence[]` points at a real field on the record you returned, not a restatement under a
borrowed name. Both worked rows below use that placeholder shape; correct the three names to what
`sor-events-a`'s and `sor-plm-a`'s connectors actually call them, same caveat as the
`pattern`/`fields` guesses already flagged below.

## Worked example: `sor-events-a`

**Named with a placeholder, not the real system, at OpenDDIL's own request** — the real name is a
customer's, and this packet is cc'd broadly enough that it shouldn't carry it. Whoever on
OpenDDIL's side builds this row knows which real system `sor-events-a` stands for; nothing below
needs the real name to be actionable.

Grounded in what's already on record about this system's role in this program (FRACAS: failure
reporting and corrective action, referenced elsewhere in this program as the system of record for
work-order/event correlation, and in OpenDDIL's own egress-bridge work for the same purpose):

```yaml
id: sor-events-a
kind: fracas
owner_domain: SUSTAINMENT          # ← confirm: this packet guesses your domain vocabulary
identity:
  pattern: '^[A-Z]{2,4}-\d{3,6}$'  # ← guessed shape for a work-order/event number
  fields: [work_order_ref, event_id]
lookup:
  connector: sor-events-a
  returns: [owner_domain, program, source_protocol, producer_id, observed_at]
program_field: program
```

**Flagged, not asserted:** the `pattern` regex and the exact field names this system's lookup
returns are this packet's inference from its known role (FRACAS events correlate to work orders),
not a citation to a schema this packet has read. Correct the `pattern`, `fields`, and
`lookup.returns` to the real system's actual identifiers before shipping this row —
`source_protocol`, `producer_id`, `observed_at` are this packet's placeholder names (per the
correction above), not a claim that this connector calls them that.

## Worked example: `sor-plm-a`

**Named with a placeholder, not the real system** — this one is a commercial product, not a
customer-identifying name, so the placeholder here is for consistency with `sor-events-a` above
rather than at OpenDDIL's explicit request. Whoever on OpenDDIL's side builds this row knows which
real system `sor-plm-a` stands for; nothing below needs the real name to be actionable.

**No prior reference to this system exists anywhere searched in this program** — not in
invincible-agent, not in openddil-contracts, not in doc-tools. This packet's only grounding is
general knowledge of the PRODUCT CATEGORY (a commercial reliability-engineering suite — RCM/FMEA,
Weibull analysis) — a system that would hold reliability/failure-mode records keyed on a
component or platform identifier, not a maintenance work order. Row shape, same caveat as
`sor-events-a`'s but stronger — **this one is inference from the product category alone, not from
anything OpenDDIL has said about its own deployment**:

```yaml
id: sor-plm-a
kind: rcm
owner_domain: SUSTAINMENT           # ← guessed
identity:
  pattern: '^[A-Z0-9]{4,10}$'       # ← guessed — a component/platform identifier shape
  fields: [component_id, platform_id]
lookup:
  connector: sor-plm-a
  returns: [owner_domain, program, source_protocol, producer_id, observed_at]
program_field: program
```

**Before this row ships, OpenDDIL should supply:** (1) what identifier `sor-plm-a`'s records are
actually keyed on, (2) whether that identifier appears anywhere in the maintenance bridge's own
`MaintenanceEvent`/`ActionRecord` fields already delivered (candidates from that contract:
`asset_id`, `work_order.parts[].part_ref`), and (3) the connector's real return field names —
`source_protocol`/`producer_id`/`observed_at` above are placeholders for `sor-plm-a`'s own
provenance fields, same correction as `sor-events-a`'s row. This packet would rather name the gap
than invent specifics a reviewer could mistake for something sourced.

## The connector and the refusal

Both rows above name connectors (`sor-events-a`, `sor-plm-a`) that must be in whatever registry
OpenDDIL's deployment resolves connector names against. An unregistered connector name is a
load-time refusal (`iagent_mesh.systems_of_record.UnknownConnector`), never a silent miss —
`validate_connectors_known(rows, known_connectors)` is the check, run at deploy/load time, not at
resolve time.

## What this packet does not do

- Does not build the resolver (the connector call, the origin-from-the-record wiring) — that's
  iagent's own side, built by `ia-01/lane/01` against this same schema.
- Does not assert either system's actual field names as fact — both worked rows above are flagged
  exactly where they're inference rather than citation.
- Does not change anything in the maintenance bridge contract already delivered — `Origin`
  attaches to whatever artifact model iagent builds from an ingested `MaintenanceEvent`/
  `ActionRecord`; it is not a new field on those two wire types themselves.
- Does not name the real system either placeholder stands for — that's the one thing this
  correction exists to NOT do.
- Does not touch `ADR-0054` or any test fixture that pre-dates this packet and already names the
  customer system in question — that fleet-wide replacement is a separate, already-dispatched
  docs-and-fixtures task, not part of this packet.

Lane: ia-ca/lane/ca
