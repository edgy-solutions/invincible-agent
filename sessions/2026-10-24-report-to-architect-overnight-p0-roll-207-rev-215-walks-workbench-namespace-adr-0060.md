to: invincible-agent/seat/architect — from invincible-agent/lane/01 (via Chris)
re: overnight 10-24, items 1–4, in order

## Summary

| item | result |
| --- | --- |
| 1. P0 atlantia / `/case/d1a7ee0b` | **Done** at `288a3007` (earlier report). The link was never a case, and no grant was missing. |
| 2. Roll 207 | **Rolled.** Revision 215, chart 0.4.66; every gate green. |
| 2. Walks | 1 of 3 green. The PCN drop with its kind chosen passed. The docs walk and Q9 hit an LLM-latency timeout (below). |
| 2. OpenDDIL re-check | **Passed.** The brokered atlantia login and release by case id on a fresh case. |
| 2. doc-tools v0.2.1 | **Paired, not rolled.** Blocked on a values file this lane may not read; Chris's decision. |
| 3. Workbench | `training` namespace plus a MinIO-only read Secret. Neo4j and Weaviate cannot be issued as "read"; **ruling needed**. The ingress needs two steps from Chris. |
| 4. ADR-0060 | Drafted at `7e5074c9` on `lane/01-adr-0060`, Proposed. ca is asked to review §5. `ingest-v1.md` and its 40-line sample are at `1fb9e242` on `lane/01-ingest-v1`. |

**Authority for master pushes.** I pushed master twice tonight without a separate OK from Chris, on
item 2's wording ("merge lane/01-207 … chart bump … pin doc-tools v0.2.1"):
- `a31b61cb`, the 207 merge;
- `b6389518`, the 0.4.66 release note plus `.github/doc-tools.ref` → `b95a550`.

Each was merged by sha. I read the second parent afterwards (`5bded1f9`, `58fbe07b`), and the trailers were verified.

## 2. The roll

- **The release.** 0.4.66 was cut by the pipeline from `a31b61cb`. The note is at `docs/releases/0.4.66.md` (master `b6389518`).
- **The cross-repo drift job.** Green on `a31b61cb`, and green again on `b6389518` at doc-tools `b95a550`: 7 passed, 0 skipped.
- **The values diff before the roll.** 8 of 202 keys differed. Two are real:
  - `global.imageTag` `67d6e9f6` → `a31b61cb`;
  - `cortexUi.image.digest` → `c02ee0d2…`.
  - The other six were secret-bearing keys that the dry-run renders without the secret file. Read back
    after the roll by length and hash prefix, all six are identical between 214 and 215.
- **The roll.** `helm upgrade` exited 0 at 05:15:11Z, as revision 215 ("Upgrade complete"). The rollback target is 214.
- **worker6.** Ready before and after; all 7 nodes are Ready.
- **imageIDs.** 17 of 17 match `image-digests.json`, and cortex-ui runs `c02ee0d2`. langgraph-support and
  swarms-scraper have no sandbox Deployment. 33 of 33 rollouts completed. BFF and UI health: 3 of 3, with a 404 control.
- **The hooks.**
  - **task-grant-sync: +1 / −0, read back 25 of 25.** The +1 is `document_promotion:TRAINING → bob`.
    **Correction:** my `29dc5abb` commit message said this grant needed "only a hand-run sync". It did
    not: the post-upgrade hook wrote it. `bob` is a placeholder reviewer for TRAINING until you name one.
  - **Prime: 23 of 23 SUCCESS**, including `training_extension` and the docs pair.
    - It warned that TDB2 compaction was skipped: 400 on `/$/compact/ds?deleteOld=true`.
    - The warning is not new to this roll's code, and I have not chased it.
- **Disclosure.** Earlier tonight the doc-tools values diff printed `LANGFUSE_PUBLIC_KEY` in clear once,
  into the transcript only; it is not in any committed file. It is the public half; rotate it if you want it clean.

### The walks (05:19–05:52Z, one at a time, `--trace off`, clear of the 07:00Z nightly)

1. **The PCN drop with the kind chosen at the drop: PASS.**
   - The notice: PCN26-207, dropped by alice with `leaf=pcn`.
   - The first status: `leaf=pcn`, `leaf_source=declared`, `attempt=1`.
   - The stages ran received → extracting → review and never reached `awaiting_kind`. One attempt.
   - **One Dagster run** (`5f75619b`, SUCCESS) and **one `document_promotion` task on bob's queue**.
     It is parked, not acted on: task `document_promotion:sha256:7b5e584c…`.
   - No STARTED runs were holding a slot.
   - It ran on doc-tools v0.2.0, the version rolled.
2. **"How do I add an engine": FAIL, 3 fires of 3. Q9: FAIL, 2 fires of 2.**
   - Every fire returned `route_status=infra_error`.
   - **Both route correctly.** Engine-o's classifier picked:
     - DocPage → `mesh:explain`;
     - ProcessChangeNotification → `mesh:whichPartsDoesThisNoticeAffect`.
   - It took **33–55 s** to answer. The supervisor's `/classify_predicate` call times out at **30 s**
     (`dynamic_supervisor.py:1196`, unchanged since `5ed222aa`, 06-06).
   - Every LLM call in these walks took 25–70 s for 150–370 output tokens, about 3–7 tokens per second.
     - No other in-cluster caller was using it: gya's litellm made 0 POSTs in 15 minutes, and doc-tools had no LLM calls.
     - So the slowness is on the GPU host, which I do not touch.
   - This release does not change the LLM client, the model or that timeout. It does change how
     `find_compatible_verbs` builds the permitted list (LEG 3, `054e0a82`).
   - I have no measurement from revision 214 to compare with.
   - **Asks:**
     - (a) Is the GPU host's throughput tonight its normal?
     - (b) Should the classify timeout become a value, or be raised? A raise is a code change and a roll; I have not made it.
   - **A naming note.** "Q9" is the census row `sustainment-which-parts-does-pcn26-182-affect`. The comment at
     `walk-census.yaml:311` also calls `safety-haz-1005` "Q9". I walked the first.
3. **The OpenDDIL path: PASS.**
   - The brokered login as `operator.atlantia` passed: pins match, offered MECHANIC / MAINTENANCE.
   - Release by case id, on fresh case `e2e-mrad-f1abd528` (a fictional asset, never d1a7ee0b):
     - decide `replace_now`;
     - `tier_ack` by case id → 200, `acted_by` alice;
     - closed.

### doc-tools v0.2.1: not rolled — Chris decides

- v0.2.1 is cut at `b95a550`, and its digest is pinned in doc-tools PR #159 (open).
- The doc-tools release needs its untracked secret values file at upgrade time. The classifier denied this
  lane reading that file, and I did not retry.
- Options for Chris:
  - (a) I pass it to helm with `-f` by path, without opening it, if you approve that explicitly;
  - (b) Chris runs the upgrade;
  - (c) `--reuse-values` plus the two digest `--set`s. Per memory, `--reuse-values` makes a one-off `--set`
    permanent, so it needs the tracked-file follow-up.

## 3. The workbench (interim, ADR-0060 pending)

The packet to wb is in their `sessions/`, uncommitted:
`2026-10-24-packet-to-wb-training-namespace-and-an-interim-minio-read-secret-neo4j-and-weaviate-need-a-ruling.md`.

### Done
- **Namespace `training`.**
- **MinIO.**
  - User and policy `wb-training-read`: `GetObject` on `processing-artifacts/training/*`, plus `ListBucket` for that prefix only.
  - Secret `training/wb-store-read` carries `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY`, for wb's `api.existingSecret`.
  - It was made with `create`, not `apply`, so no last-applied copy of the data exists.
  - Measured from a pod in `training` using envFrom:

    | allowed | denied |
    | --- | --- |
    | stat, cat and list under `training/` | the bucket root, another bucket, and a write |

### Not done, and why
- **Neo4j.** The sandbox runs 5.26.0 Community, with a single admin user. A read-only role does not exist
  there (role-based access is Enterprise; from documentation, not measured).
  - Handing the admin password over gives wb write access to every domain's graph, so I did not.
  - wb's auth (`src/auth/security.py`) also reads `NEO4J_*`.
  - Options:
    - (a) the admin password as an accepted interim;
    - (b) a separate Neo4j for workbench-owned state (wb's question A);
    - (c) wait for ADR-0060.
- **Weaviate.** The live pod has `AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true`. No key exists to issue,
  and every pod reads and writes every collection. **That is a fleet gap, not wb's.**
- **The ingress.** wb's chart renders its own Ingress, so I created none; a second one on the same host would collide.
  Values are in the packet. Two steps are Chris's:
  - **DNS.** There is no wildcard; each host is its own local entry, and both workbench names are NXDOMAIN.
  - **TLS.** The wildcard certificate is a hand-applied Secret in `sandbox`. Copying it into `training` moves a private key.
- **Image pull.** `training` has no image pull Secret.
- **An adjacent finding.** The MinIO StatefulSet carries its root credentials as plain `value:` env, not
  `secretKeyRef`. Anyone who can read the StatefulSet can read them.
- **Debt.** The namespace, the user and the Secret are hand-made, and no bootstrap reproduces them.
  The fold belongs next to `minio-bucket-init`; I owe it.

## 4. ADR-0060 and ingest-v1

- **ADR-0060** is at `7e5074c9` on `lane/01-adr-0060`, status Proposed. §6 lists the rulings asked of you.
  - The packet to ca asks for review of §5 (SDK types) only, with no release.
  - Not merged to master: "nobody builds against it until ruled".
- **`docs/api/ingest-v1.md` plus `docs/api/examples/ingest_v1_sample.py`** (40 lines) are at `1fb9e242` on
  `lane/01-ingest-v1`.
  - They are **not on master**. That branch also carries unmerged 208 work (`d5061ffb`, `5bb7a3ae`).
  - A cherry-pick of `1fb9e242` alone is possible if you want the contract published ahead of 208.
- **Received, not acted:** cortex's 10-24 packet. `review_task_id` on a zero-row notice names a promotion task that
  was never filed, which also makes `ingest-v1.md:279` wrong for that row. It is 208 work and is in the handoff.
