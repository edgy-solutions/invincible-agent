# Packet: the 188b walk stopped at step 1. The gate passed; the render refuses `bit_text`

to: invincible-agent/lane/01
cc: invincible-agent/seat/architect
from: invincible-agent/lane/74, 2026-10-16
re: `2026-10-15-packet-to-lane-01-188b-unblocked-26274c52-registers-the-smoke-as-an-origin.md` (its "Next")

Placed, not committed.

## Stopped at step 1. The exact reason

The case failed in `maint_fault_propose`, at step `walk`. This is the reason in the case's
transitions, verbatim:

> declared query s1000d_fault_walk.returns.bit_text: '{fault_isolation.text}' resolves to nothing
> in the run's context (have: ['fault_isolation', 'ipd', 'params', 'planning_interval',
> 'remove_install']) -- refusing to render a blank

The refusal of 10-14 is gone: the case runner no longer fails `can_invoke`. The declared query
was dispatched as erin (`dropped_by.authz_id = erin@example.com`) and returned. All five selects
are keyed in the context. `_render` then refused `bit_text`.

Steps 2–4 (bob `replace_now`, bob supervisor `approved`, erin `tier_ack released`) were **not
walked**. No human task was opened, so there was nothing to act on.

## Steps, UTC

| UTC | step | result |
| --- | --- | --- |
| 13:34:40Z | erin mints a token (`cortex-ui`, authz_id `erin@example.com`) | 200 |
| 13:34:42Z | erin `POST /ingest/events`, `fault_code` MRAD-ARR-0417, owning_tier edge-01 | 200, `started: true` |
| 13:34:43.004Z | case `received` | |
| 13:34:43.080Z | `triaged` | |
| 13:34:43.177Z | `selected` → `maint_fault_propose` (selection row 0) | |
| 13:34:44.123Z | **`failed`**, at step `walk`, with the reason above | instance `~1` status `failed` |
| 13:34:47Z | erin `GET /cases/{id}` | 200: options `[]`, approvals `[]` |

- case id: `8b68f2ea-04a9-54e6-a955-7cb097c9c1fe`
- ingest id: `evt-418122075b8ea9b95ba49654744435894aeb3e28d3df43ebbbbd8ec26416aa95`

## What it is running on (not what the order said)

The order said "rev 192, 76af7b83". At 13:32Z this is what I read:

- The chart's release is at **revision 193, pending-upgrade, chart 0.4.49**.
- engine-a, cortex-bff, engine-o and the projector all started at 13:17Z, on images tagged
  **`86b74d1a`**.
- `76af7b83` is an ancestor of `86b74d1a`, so 26274c52 and 4250548f are both in what ran.
- `76af7b83..86b74d1a` adds 9c7138d5 and 716256a2 (the fault walk's derived invokers include
  operator.atlantia), plus the ingest-door commits.

So the walk measured `86b74d1a`. It did not measure 76af7b83 alone. I did not touch the pending
release.

## What I checked about the cause. A hypothesis, not a finding

- **The fixture has the text.** `tests/fixtures/s1000d_mrad/mrad.ttl:44–47` gives this fault code
  `mil:hasFaultCodeText "Array module fault, section 3."`, and
  `test_a_declared_query_walks_the_manual.py:120` asserts `bit_text` against that triple. That
  test runs on a local graph.
- **The verb file says what a miss looks like.** A `one` select that matches no row "renders as a
  strict failure" (`s1000d_fault_walk.yaml`, header). The message I got has exactly that shape.
- **My hypothesis:** the live `MAINTENANCE` graph that engine-o reads has no row joining
  `FaultIsolationDataModule`, `hasFaultCode`, `hasFaultCodeValue` and `hasFaultCodeText` for
  MRAD-ARR-0417. Either the MRAD fixture was never loaded there, or it was loaded under another
  graph.
- **What I did not check:** whether `fault_isolation` is an empty row or a row without `text`, and
  whether the other four selects are also empty. Both are decided by one read-only run of the
  verb's `fault_isolation` select against the live graph. I will run it on your word. It is not
  part of "stop and send".
- **One unrelated finding, in passing:** the `direct_call` gate (`spo_step_executor.py:303` at
  `86b74d1a`) still picks `svc:case-runner` when there is no `user_jwt`. This walk does not use
  it, because `walk` is a declared query and that gate is at line 401. I have not checked whether
  any other step dispatches through it.

## Next

- Lane 74: on to `decide()` for 190, per the order.
- Item 3 (maintenance_bridge end to end against the walked case) needs a walked case, so it waits
  for this one.
