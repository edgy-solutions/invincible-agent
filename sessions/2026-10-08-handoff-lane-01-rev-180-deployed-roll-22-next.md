to: invincible-agent/lane/01-roll21
from: invincible-agent/lane/01-roll21
date: 2026-10-08
re: the 2026-10-08 day directive (items 1-4), where each stands
supersedes: 2026-10-07-handoff-lane-01-master-at-5cf7d879-roll-21-waits-on-doc-tools-anti-affinity.md

# Rev 180 is deployed at b02df03f; roll #22 is the next roll

Measurement: `docs/measurements/2026-10-08-lane-1-roll-21.md` (§5b is rev 179's post-roll legs, §6 is
rev 180).

## Item 1: done, apart from the rehearsal and two captures

- **Zombies and prime:** the two zombie runs (`b5798f47`, `a3d3674b`) were canceled with Chris's
  authorization. The re-roll gave rev 179 a clean prime (22 ok).
- **The fresh PCN, PCN26-121, end to end:** promoted. The ask did not reach it, and the floor was
  absent by construction (§5b).
- **The six mock modules:** in as `xml/s1000d-data-module`, and stuck at `received`. doc-tools has
  no `ingress-user/xml/` consumer, and the ask is with doc-tools/lane/7f (packet in
  `doc-tools/sessions/`, two addenda).
- **The safety deferral-risk walk:** fired ×3 on rev 179 and ×3 on rev 180, `fallback` each time.
  The subject `MaintenanceWorkOrderRecord` is MAINTENANCE-only, so the fix is scope. Answer sent to
  saf: caller stays.
- **The rehearsal (×3 plus one refusal): BLOCKED on the seam,** that is, on the six modules leaving
  `received`. It is not blocked on the fault walk, which is declared data at `b16ae935`.
- **Captures:**
  - The PCN26-121 promote capture is at `<scratchpad>/pcn21-capture.json`. Copying it into
    cortex-ui/sessions was DENIED by the auto-mode classifier as credential leakage. **Chris
    decides.** Do not retry.
  - Lot 3 DELTA_SET and a live `/cases/{id}`: not taken.

## Item 2: merged, rolled, measured

- **`lane/01-merge1008` at `b02df03f` went to master** and was rolled. Gate: 8 reds, all among the master baseline's 9. Master is now `c3c9f2aa`: this branch merged on the same 8 reds, docs only (the measurement and the saf packet). The fleet still runs `b02df03f`.
- **Rev 180:** values diff of 2 keys (imageTag, cortex digest). Prime 22 ok including
  `safety_extension`. Edges 193 / 83 / 55 / 59, one more of each than rev 179: the new verb.
- **ELICITATION on the wire:** `ask` comes with `slot_elicitation`, and `abstain` comes with
  `slot_abstain`. Both ×3.
- **NEW, sent to saf:** `safety-what-failed-on-this-part` falls back ×3. Its subject is
  SUSTAINMENT, the same domain as Platform, whose verb answers, so scope is not the cause.
  Undiagnosed.
- **Not in master:** lane/74's `23b6a30a` (the pre-flip engine fixes in ontology_service and
  restate_analyst). Only its test-only `091e2373` was merged. The rest waits for its own merge.

## Item 3: built on `lane/01-roll22` (75b0cd6d), not gated, not rolled

- Its contents: §8 path plus delegate admission; GET /artifacts via MeshArtifacts at the
  iagent-mesh 0.9.9 sha; the NetworkPolicy proposal.
- **Next step:**
  1. merge origin/master into roll22;
  2. gate it against the 8 known reds;
  3. merge by sha;
  4. wait for build-containers;
  5. values diff;
  6. roll #22.
- The secret values overlay is needed in whichever worktree rolls. It was copied (gitignored,
  sha256 prefix `1da169ef`) into `ia-01-merge1008/helm/invincible-agent/`, and roll22 does not have
  it.
- **NetworkPolicy stays off**, per the ruling. Gate-on is next week, with preconditions per
  `1f2f7ce4` / `75b0cd6d`.

## Item 4: done (R-082 onward)

## Owed

- **cortex-60:** rev 180 is placed in `cortex-ui/sessions/` and not committed. After roll #22, send
  the revision that carries item 4.
- **R1 overlay line:** land it when 7f says their PR is ready.
- **iagent-mesh-sdk/lane/ca:** two things are open, the tag for 0.9.9 and the `answer-artifact`
  kind question (packet placed). The SHA_PINS_PENDING_TAG backstop is 2026-10-29.

## For Chris

- Cleanup is yours:
  - `C:\Users\cnogr\git\ia-01-base1008`, a detached baseline worktree at `3e73bdc8` with its own
    venv;
  - the secret overlay copy in `ia-01-merge1008`.
- The PCN capture placement decision (above).
