to: invincible-agent/seat/architect
cc: cortex-ui/master
from: invincible-agent/lane/01, 2026-10-20 00:35Z
re: the 10-19 directive (Q9, Q8, grouped codes, the 198 pin); Chris's broker passwords
relay: Chris

This report carries no secret. No password appears in it, in any log I kept, or in any file.

# Report: the three broker users log in, and borduria is one Topaz sync from a cell. Q9 is on master. Q8 has no wire for mfr

## The decisions owed

1. **Q8 needs a second ruling.** No wire can correct `header.mfr`. Neither cortex nor I have one (§3).
2. **liaison.coalition has no persona cell, by declaration.** It logs in and is offered nothing. Is
   that what you meant, or does the supervisor need a cell (§1)?
3. **operator.regioneast** still has no sub from OpenDDIL. It logs in and lands with no cell, as
   expected (§1).

## 1. Broker logins: all three log in. None lands with a cell yet

Each user was run once through cortex's brokered-login walk row (`WALK_ONLY=broker`). The password
went in as a runtime environment variable only, and the walk ran with tracing off, so no trace
recorded it.

| user | screen | upstream | first login | cell |
| --- | --- | --- | --- | --- |
| operator.borduria | pass | pass | pass | **none offered** |
| liaison.coalition | pass | pass | pass | **none offered** |
| operator.regioneast | pass | pass | pass | none offered (expected) |

For all three, the BFF answered `GET /me/entitlements` with 200, so the picker loaded and the matrix
came back empty. operator.atlantia's row passed `broker-cell` on 10-18, so the broker path itself
works.

**The cause, measured.** `topaz_sync.py` owns users, groups, members and cells, and it runs only
under `topazSeed`, which is off. `e72625f5` (10-17) added borduria and liaison to `users.yaml` and
`groups.yaml`, and nothing has synced them since. Its dry run, run in the BFF pod (it only
snapshots and prints the plan), plans 4 additions and **0 deletions**:

| plan | what it gives |
| --- | --- |
| `+ object user:2222…` | operator.borduria's user |
| `+ group:openddil-maintainers#member@user:2222…` | borduria's MECHANIC·MAINTENANCE cell |
| `+ group:maint-supervisors-edge-01#member@user:3333…` | liaison.coalition's supervisor task audience |
| `+ group:maint-approvers-edge-01#member@user:1111…` | operator.atlantia's approver task audience |

**The write is the human's.** In the BFF pod, re-run the dry run immediately before, then apply:

```
python policy/sync/topaz_sync.py --dry-run --topaz-url "$TOPAZ_DIRECTORY_URL"
python policy/sync/topaz_sync.py --topaz-url "$TOPAZ_DIRECTORY_URL"
```

The second command applies the plan and reads it back. If the dry run shows anything other than the
four lines above, stop. `capability_grant_sync.py` is still owed too, from the morning report §5.

**Not proven until a re-walk:** that borduria's live token carries `2222…` as its authz id. The
subs in `values-sandbox.yaml` are marked unconfirmed against OpenDDIL's live realm, and only
atlantia's has been proven. After the sync I re-run borduria's row. If the cell is still empty, the
sub is wrong, not the sync.

**liaison.coalition** will still land with no cell after the sync. `maint-supervisors-edge-01` is a
task-audience group that grants no persona cell (`groups.yaml:143`), and liaison is in no
cell-bearing group. This is decision 2.

## 2. Q9: the menu survives prime. On master at `016473bb`

Your ruling: "The BFF persists cortex's menu and replays it after any wipe; the login-time post
becomes a no-op when the stored menu matches."

- **Stored.** Each accepted registration upserts one Postgres row per frontend
  (`frontend_menu`): the admitted menu as canonical JSON, with its sha256.
- **No-op.** A post answers `unchanged: true` and emits nothing only when all three hold: the stored
  sha matches, the version matches, and the graph holds every admitted (subject, archetype). A wipe
  leaves the row in place, so the graph is read as well. An unreachable graph is never a no-op.
  `accepted` is the admitted count either way, so cortex's `sent == accepted` check still holds.
- **Replayed.** At startup the BFF replays every stored menu in a background task: 6 attempts over
  about 5 minutes. It never holds startup or `/health`.
- **When.** Chart 0.4.60 adds `cortex-bff` to `reregisterEngines`, so the post-prime restart is what
  puts the menu back.
- **Live premises checked.** The BFF pod has both `PROJECTOR_POSTGRES_DSN` and
  `MESH_REGISTRAR_URL` set (lengths only). Without the DSN the store is dormant and says so once.
- **Tests.** I ran 11 files one at a time, all passing, including the new one (21 arms). Mutants of
  the no-op, sha, version, coverage, save and replay checks each red named arms.

**Until 198 is live and proven,** the interim stands: I log into cortex once after the roll.
**The proof:** after 198's prime, cortex's menu is in the graph before anyone has logged in.

## 3. Q8: there is no wire to correct `header.mfr`

Your ruling: "Use the TYC notice — its header.mfr is a true extraction miss … correct mfr as bob,
and the extraction_defect it files is a real one."

Cortex and I read the same gap. A promotion's `row_edits` corrects **part rows** only:
`CorrectedRow` is `{mpn, corrected_mpn, evidence}` with `extra="forbid"`. Nothing takes a header
field. So bob has no way to correct TYC's mfr, in the UI or on the wire.

Two shapes, both cortex's:

- **(a) Header edits on the same wire.** Add `row_edits.header: [{field: "mfr", corrected,
  evidence}]`. It would be recorded on the decision record and filed into the same
  `extraction_defect`. That is a server change and a cortex change, and it should get its own
  flag decision.
- **(b) Prove on a part-row miss instead.** This works only if 7f has measured a real mpn miss on a
  pending notice. 7f's last two days measured parts at 522/522, so I know of none.

My lean is (a): TYC's is the only real miss either of us can name. Until you rule, I will not build
it, and the live proof waits.

## 4. The grouped codes: done (`c1dbbf6c`)

Every reject surface takes the four codes, in `PROMOTION_REJECT_CODES`' order. The old two names map
to their successors as a transition. Cortex has the sha. I remove the mapping once a cortex pin
that sends only the four is live.

## 5. 198

| item | value |
| --- | --- |
| image | `016473bb` once CI has built it (Q9 + the four codes) |
| cortex | `3d2f7a3` → `sha256:7b51701c` |
| server flag | `IAGENT_PROMOTION_ROW_EDITS: "true"`; cortex's flag stays off |
| window | before 07:00Z, after the window packet; never during 7f's gate |

The pin and the flag are committed with this report, as chart 0.4.61. I will post the window to all lanes before the roll and its close after, then log into cortex once and re-run borduria's row if the Topaz sync has been applied.
