# PCN driver LIVE kill-seal — run card + evidence (exhibit)

The offline seal proved the LOGIC (journaling → exactly-one, two-direction, mutation-proven-to-bite,
`d5b1d56`). This proves the RUNTIME: a real engine-a process death mid-dispatch, on the real cluster,
converges to EXACTLY ONE task + EXACTLY ONE state. Journal-CONFIRMED (not assumed), both directions,
evidence banked here (same exhibit class as the batch diff), test residue cleaned after.

## Mechanism
`PcnDispatchItem.dispatch` has two env-gated durable pauses (`87ddcde`): `PCN_SEAL_PAUSE_AFTER_MINT_S`
(window A — between mint and state) and `PCN_SEAL_PAUSE_AFTER_STATE_S` (window B — between state and the
exactly-one marker). The durable sleep is journaled in the Restate server, so killing engine-a during
it is a true process-death test and the journal shows the exact resume point.

## Procedure (per direction)
1. Set the window env on engine-a; roll; confirm the pause is live.
2. Invoke `PcnDispatchItem/dispatch` for a TEST-keyed item (`killseal:<ts>:<part>`), cortex-bff + engine-o real.
3. During the durable pause, KILL the engine-a pod. **ANNOUNCE + timestamp each kill.**
4. Restart; let Restate re-invoke on the new pod.
5. JOURNAL-VERIFY: the invocation shows mint completed BEFORE the kill, the sleep pending at kill, and
   the second write completing only on resume (the kill was inside the window).
6. ASSERT exactly-one: cortex-bff has exactly ONE task for the key; engine-o `/pcn_parts_by_state` (or
   the graph) has exactly ONE state stamp for the subject.
7. Clean the test residue (task + state) — fixture, not residue.

## Evidence — RAN 2026-07-24 on sandbox `edge` (both directions PROVEN)

**Preamble — the driver runs end-to-end live (smoke test).** `PcnDispatchItem/killseal-smoke/dispatch`
(no pause) returned `{task_minted: true, state_written: true}` — cortex-bff register + engine-o write
both landed on the real cluster.

**Two real bugs found live before the seal could run (the live session's whole thesis):**
- `ruleset_ref` hashed the whole graph → drifted against the co-tenant SUSTAINMENT graph. Fixed to
  content-only (`51b146b`); fixture==live==`rules@2915ddb229e4`.
- `_mint_dispatch_task` omitted `requested_by` → cortex-bff register 422s → the demo mint would park.
  Fixed by threading the approver (`2f1c5ca`); regression pinned.

### Direction A — kill AFTER mint, BEFORE state (`inv_1d4ops6jS6JM2rr3iKtYWkFRqAjZp7Eqs1`, key `killseal-A2`)
- SEND 14:47:01Z → mint ran ~14:47:02 → 75s durable sleep (window A).
- **KILL announced + SIGKILL 14:47:17Z** (16s in — mint journaled, sleep pending, state NOT yet).
- engine-a restarted, Restate re-invoked, sleep resumed, wrote on resume; **completed 14:48:19Z**.
- **Journal: `Command: Run` `mint_task` ×1, `write_state` ×1** — EXACTLY ONE each across the process death.
- Substrate: `http://internal/components/KILLSEALA2` state stamp present, once.

### Direction B — kill AFTER state, BEFORE the marker (`inv_1l1IRcsLCWK72931nQnumbDTZnKQfzfKil`, key `killseal-B2`)
- SEND 14:51:33Z → mint+state ran ~14:51:34-35 → 75s durable sleep (window B, before the exactly-one marker).
- **KILL announced + SIGKILL 14:51:48Z** (15s in — BOTH writes journaled, marker NOT yet).
- Restarted, re-invoked, resumed, set the marker; **completed 14:52:49Z**.
- **Journal: `mint_task` ×1, `write_state` ×1** — neither write re-ran on resume; marker set once.
- Substrate: `KILLSEALB2` state stamp present, once.

**Verdict:** a real engine-a process death (SIGKILL) mid-dispatch converges to EXACTLY ONE task +
EXACTLY ONE state, in BOTH windows, journal-confirmed on the real Restate runtime. The offline logic
seal (`d5b1d56`, mutation-proven) now has its live runtime twin. Method: [[feedback_lifecycle_state_observable]].

### Cleanup (done)
- Test env reset: `PCN_SEAL_PAUSE_AFTER_MINT_S` / `_AFTER_STATE_S` unset on engine-a; pod healthy;
  all three pcn services survived the SIGKILLs and stay registered.
- State stamps: SPARQL `DELETE` of all `http://internal/components/KILLSEAL*` in `SUSTAINMENT_INSTANCES`
  (Fuseki, HTTP 200); `/pcn_parts_by_state` now returns 0 — verified gone.
- Test tasks (`killseal-*` in cortex-bff): recipients:[] (Topaz dark → no actors resolved), so they are
  INVISIBLE in every queue. cortex-bff exposes no delete at `/internal/human_tasks`; left as harmless
  invisible test rows (removed by a task-store reset). Honest residue note, not a silent skip.
