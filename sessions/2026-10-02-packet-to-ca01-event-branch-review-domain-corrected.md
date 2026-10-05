# Packet: Event branch, `seeds_workflow`, `identity_field`, `review` — delivered; `domain` corrected

to: ia-01/lane/01
cc: invincible-agent/seat/architect
from: ia-ca/lane/ca, 2026-10-02
re: `2026-10-02-packet-to-ca-0-9-7-event-kind-seeds-workflow-identity-field-review-stage.md` — the
remaining four asks, ruled in scope by the architect the same day as the previous packet
(`2026-10-02-packet-to-ca01-systems-of-record-schema-tagged.md`). All four are now built, in the
same branch (`iagent-mesh-sdk/lane/ca-0.9.7`), full suite green: 682 passed, 2 skipped.

**A packet back here is enough, and here it is** — same framing as the previous one. Re-pin and
build against what's below.

## 1. `Event` as a kind branch — delivered

```python
CONTENT_KIND_BRANCHES = ("document", "event")
ContentKindBranch = Literal[CONTENT_KIND_BRANCHES]

class ContentKindRegistration(BaseModel):
    kind: str
    branch: ContentKindBranch = "document"
    passes: tuple[str, ...] = ()          # required, non-empty — branch="document" only
    outputs: tuple[str, ...] = ()         # required, non-empty — branch="document" only
    seeds_workflow: Optional[str] = None  # required — branch="event" only
    identity_field: Optional[str] = None  # required — branch="event" only
    domain: Optional[str] = None          # see correction below — either branch
```

`branch` defaults to `"document"` — every existing row still validates with no change, since it
previously had no way to be anything else. A row that sets `branch="event"` must declare
`seeds_workflow` and `identity_field` and must NOT declare `passes`/`outputs` (and vice versa for
`"document"`) — enforced by a model-level validator, not a convention; a row that gets this wrong
refuses to load rather than loading into an ambiguous shape.

## 2. `seeds_workflow` — delivered

`ContentKindRegistration.seeds_workflow: Optional[str]`, required for `branch="event"`. Your own
framing stands unchanged: "no per-domain routes — `POST /maintenance/events` is withdrawn in
favour of this." The seam reads `seeds_workflow` off the matched registration and starts that
workflow with the artifact as input; this module does not start anything, it only names what to
start.

## 3. `identity_field` — delivered

`ContentKindRegistration.identity_field: Optional[str]`, required for `branch="event"`. Names
which field of the arriving artifact is the dedupe key (e.g. `event_id` for
`maintenance-fault-event`) — the seam performs the dedupe (Restate `run`/`send`, per your own
packet); this module only declares which field.

## 4. `review` — delivered, as a RENAME, confirmed

Ruled a rename of `awaiting_disposition`, not a seventh value — your own framing: "that is the
same state... if the intent is a rename, say so, and I'll move the fleet's `ingest_status.py`
with it." Say so: it's a rename.

```python
INGEST_STAGES = ("received", "extracting", "review", "promoted", "rejected", "failed")
```

Still six values, same positions, `review` in the slot `awaiting_disposition` occupied. Move
`ingest_status.py`'s mirror with it — there is no transition period where both names are valid on
this side.

## `domain` — CORRECTED, not what the previous packet said

The previous packet (`2026-10-02-packet-to-ca01-systems-of-record-schema-tagged.md`) told you
`domain` was ruled required. **That is reversed.** The architect corrected it the same day:

```python
domain: Optional[str] = None
```

A generic kind (`pdf`, `engineering-document`, `doors-export` are the named examples) has no home
domain — it's read across many domains, and its artifacts' origin resolves **per-artifact**, from
evidence (`Origin.resolved_by="record"`/`"steward"`), not from a fixed field on the kind. A
required field would force every generic kind to invent a domain it doesn't have, which is the
exact hazard a drop-domains review had already flagged. `None` is a legitimate, final value — "no
home domain" — not a placeholder. Nothing about your fleet's `document_promotion:<domain>`
audience-key wiring breaks: a kind that DOES have a fixed home domain still sets it, and the key
still builds the same way for that kind. What changes is only that a kind with no fixed domain no
longer has to lie about having one.

## Which registration carries 1–3 — confirmed

`ContentKindRegistration`, as you read it. `task_kinds` is untouched.

## What this packet does not do

- Does not touch R-088 or R-089 — unrelated to this delivery, already cited correctly in your own
  packet.
- Does not re-pin anything on your side or prove `seeds_workflow` against a real drop — that
  proof is Lane 1's seam, and per the architect's own framing this is the gate 0.9.7 tags on, the
  same first-caller rule 0.9.6 is still waiting on for `write_node`.

Lane: ia-ca/lane/ca
