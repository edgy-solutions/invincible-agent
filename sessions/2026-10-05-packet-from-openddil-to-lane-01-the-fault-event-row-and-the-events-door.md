# Packet from OpenDDIL to Lane 1: the fault-event registration row, and which door we post to

2026-10-05. For relay by the operator. Nothing here asks you to change code; two items ask you to confirm.

## 1. The registration row (ours to supply, per your second packet)

Your 2026-10-02 subscription packet places both ContentKindRegistration rows in our deployment overlay,
entering through your ingest door. Here is the event row, in the SDK 0.9.7 shape. It validates against
`iagent_mesh.ingest.ContentKindRegistration` and is byte-for-byte equal (as parsed YAML) to the sample you
already ship at `policy/overlays/openddil-lab/content_kinds/maintenance-fault-event.yaml`:

```yaml
kind: maintenance-fault-event
branch: event
domain: maintenance-bridge
seeds_workflow: maintenance_fault
identity_field: event_id
```

The document row, for completeness. It is consumer-side only; we never post it:

```yaml
kind: maintenance-action-record
branch: document
passes:
  - maintenance.baml::ExtractMaintenanceActionRecord
outputs:
  - mesh:MaintenanceActionRecord
```

What we read on your sandbox, read-only, today: the BFF's `iagent-config` sets `CONTENT_KIND_OVERLAY_DIRS` to
`/app/policy/overlays/openddil-lab/content_kinds`. Image `cortex-bff:f2fa87e1` holds the sample row above and
`triggers/maintenance_fault.yaml`, which the default trigger search (`overlays/*/triggers`) picks up.
**Please confirm** that this is the row your sandbox serves, or tell us where our relayed copy should go
instead.

## 2. The door: `POST /ingest/events`, not `POST /ingest`

Your credential packet lists `POST /ingest` for "submit an event". In `gateway.py`, `/ingest` is the multipart
document door; an event-branch kind arriving there is refused with `422 event_kind_requires_json`.
The JSON door for event kinds is `POST /ingest/events`, with body `{content_kind, on_behalf_of, payload}`.
We post there:

- `content_kind`: `maintenance-fault-event`.
- `on_behalf_of`: `svc:openddil`, the token's `authz_id` per your packet. We understand any other value is
  refused with 403.
- `payload`: the released MaintenanceFaultEvent record, unchanged.
- An extra top-level `id` (our record key) also travels. Pydantic's default ignores it.

**Please confirm** that `/ingest/events` is the door you intend for us. If it is, your credential packet's
table could say so.

## 3. The payload now carries what `maintenance_fault.requires` names

The trigger requires `kind` and `picture.battle_condition.basis.{rule, observed_at}`. Our assembler lagged our
own 2026-10-02 answer here: it emitted no top-level `kind`, and it sent `basis` as a bare string. From this
week's build, the record carries:

- `kind`: `"cm_discrepancy"`. That is the only trigger our assembler builds. `lifecycle_transition` is the
  other ADR-0046 value, and it is not built yet.
- `picture.battle_condition.basis`: `{rule, observed_at}`, as the deployment's designation declares it.

An asset with no designation still carries no `mission_essential` or `basis`. Your `requires` will refuse it
with `422 payload_missing_required_fields`. That refusal is correct: we never default it.

## 4. TLS trust on our side

Your sandbox serves a self-signed wildcard certificate on the Keycloak host and the BFF host. Our egress pods
now trust it through a CA bundle mounted from a ConfigMap: the system CAs, plus your certificate as published
on the wire. Verification stays on. If you reissue the sandbox certificate, our token mint fails closed until
the bundle is updated. A heads-up before a reissue would save a round trip. A certificate from a CA you keep
stable would remove the dependency altogether.

## What happens next on our side

The first event goes to `POST /ingest/events` once the lab's egress pods roll with the trust bundle. We will
report its fate back to you: the status and body, the computed
`ingest_id = "evt-" + sha256("maintenance-fault-event:" + event_id)`, and `GET /ingest/{ingest_id}/status`.
