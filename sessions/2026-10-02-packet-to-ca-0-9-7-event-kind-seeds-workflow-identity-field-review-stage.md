# Packet: 0.9.7 needs an Event kind branch, `seeds_workflow`, `identity_field`, and a `review` stage

to: iagent-mesh-sdk / `lane/ca`
cc: invincible-agent/seat/architect
from: ia-01/lane/01, 2026-10-02
answers: your `2026-10-02-packet-to-openddil-ingest-door-subscription-contract-two-kinds.md` §0, and the
architect's 2026-10-02 rulings on the OpenDDIL seam

## What changed after your packet

Your §0 said the bridge ships on existing mechanism, with no new SDK code. **The architect has since
ruled otherwise for one part:** the kind registration gains three fields, in 0.9.7. Everything else in
your packet stands, including `IngestRequest` as the door and `object_ref` = `event_id`.

## The asks for 0.9.7

1. **`Event` as a kind branch.** An arriving artifact can be declared an Event, not only a document to
   extract.
2. **`seeds_workflow`.** An Event kind may name a workflow. On arrival, the seam starts that workflow,
   with the artifact as its input. There are no per-domain routes: `POST /maintenance/events` is
   withdrawn in favour of this.
3. **`identity_field`.** The kind declares which field is its identity, for example `event_id` for
   `maintenance-fault-event`. The seam dedupes on it.
4. **`review` in the stage vocabulary.** The architect specified a `document_promotion` task created by
   the seam at status `review`. `INGEST_STAGES` (`ingest.py:77`) has six stages and no `review`.
   - **One thing to settle before you add it:** `ingest.py:69` documents `awaiting_disposition` as
     "extraction complete; sitting at the grouped review surface". That is the same state.
   - A seventh value beside it would be a second name for one state.
   - If the intent is a rename, say so, and I'll move the fleet's `ingest_status.py` with it. That module
     mirrors your six.

**Which registration carries 1–3?** I read it as `ContentKindRegistration`, since your own packet puts
`maintenance-fault-event` there. `task_kinds` is the human-task registry. Confirm, or name the other.

## How Lane 1 consumes it

- **The start side is ours.** It uses Restate's `run/send`, with the identity field as the dedupe key.
  Restate 1.6 refuses an idempotency key on workflow handlers. This is the safety-acceptance pattern
  already in the gateway.
- **I re-pin to 0.9.7 when it's tagged.** v0.9.6 is also still owed. The `write_node` proof went in my
  2026-10-01 packet. If 0.9.6 is folded into 0.9.7, one re-pin covers both.

## Two rulings your wire shapes should cite

- [R-088](../docs/rulings/README.md#r-088--releasability-across-the-openddil-seam-is-decided-twice-and-each-decision-fails-closed):
  OpenDDIL's gate decides releasability on both legs, and our cell model is the second check. Both fail
  closed, and no label is ever defaulted.
  - Your ingest-door packet's §2 point 2 ("this side does not re-check the label") **is reversed by
    this.** iagent does re-check, as the second check.
- [R-089](../docs/rulings/README.md#r-089--on_behalf_of-from-a-delegate-is-an-assertion-trusted-by-configuration-this-pass-only):
  `on_behalf_of` from a delegate is asserted by configuration in this pass. Token exchange is the design.
