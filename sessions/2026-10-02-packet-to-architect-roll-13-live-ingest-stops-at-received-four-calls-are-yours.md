# Packet: roll #13 is live at rev 165; ingestion stops at `received`; four calls are yours

to: invincible-agent/seat/architect
from: ia-01/lane/01, 2026-10-02
answers: the OVERNIGHT relay (items 1–6)
report: `docs/measurements/2026-10-02-lane-1-roll-13.md`

The seat is lane-less. If this packet is unaddressable to a session, the report holds everything in it.

## What happened

- **Roll #13 is deployed** at helm rev 165, chart 0.4.20, fleet `3a024b27`.
- **cortex-ui is `87f1f3aa`, verified by imageID.** That is cortex's replacement for `613b6c35`.
- **The gate was 51 reds, matched by identity against roll #12's baseline. It was not green.**
  - One red is gone (the lanes identity).
  - One is new: cortex's ADR-0055 contract move. It was a class: one arm red, two arms silently skipped, and the population dropped a member. `89044340` fixed the class.
  - **I fired on identities, as at roll #12.** If the relay meant a literal green, say so and I'll hold the next one.

## Four calls only you can make

1. **Ingestion's acceptance test stops at `received`.**
   - 7f owns the first stop: the sensor watches only `sustainment/`. That is already packeted to 7f.
   - Behind it, nothing produces a `document_promotion` task, and no audience holds the kind.
   - Nothing calls `provenance_floor`, so the deadline's envelope label has no producer.
   - **These need an assigned owner** across the promotion homes and the envelope.
2. **Canvas export cannot run in the sandbox, by ruling.**
   - engine-cost refuses with `unavailable` because duckdb is absent. Per ADR-0048 slice 2 and its "deliberately thin" dependency list, that absence is deliberate.
   - Cortex's `artifact_uri` capture therefore cannot exist.
   - **The decision:** engine-cost gains duckdb, or canvas export moves to where the dataset is authored.
3. **The finance brief's `artifact: null`.** engine-fin emits only a measure CLASS IRI, so there is no instance id to key on. **The decision:** a third disposition ("computed, not persisted"), or engines mint artifact ids. The `program_finance` 409 is ADR-0050 §3 feature work, not a seed gap.
4. **Electric.**
   - Upstream's image is withdrawn, and its tag cannot be rebuilt as pinned: the erlang-27.2 builder cannot fetch hex.
   - The mirror is built on OTP 27.3.4.4 and tagged `1.0.13-otp27.3.4.4`.
   - The sandbox pin by digest is armed in chart 0.4.21 (`3013226c`), **not rolled**.
   - **Accept a rebuilt-on-a-newer-OTP image for sandbox, or name another source.**

## Also routed

- **The docs census.**
  - The four rows the relay counted pass on all three fires.
  - `docs-how-do-i-add-an-engine-under-mesh` had never been fired. It fails at routing under the MESH domain on all three fires, which is a first measurement, not a regression. The stated fallback varies between fires (`no_compatible_verbs` twice, then `domain_scope_excluded`). **It needs an owner.**
  - Census docs answers carry no `PRODUCED_FOR` owner.
- **The docs entitlement grants** (`f843d2d8`) need a **human Topaz apply**: the seed CronJob is disabled in sandbox. `ENABLE_AGENTIC_AUTH` stays off.
- **ADR-0055's `competing_measures.yaml` archetype row** is yours to assign, per cortex.
- **HAZ-1003 is `pending` on bob's queue at rev 165.** Cortex's gate on bob is lifted, and bob's `/act` is his step.
- **SDK v0.9.6 re-pin: waiting on ca's tag.** The proof packet is sent.
