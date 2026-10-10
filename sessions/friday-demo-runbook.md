# Friday demo runbook: the PCN walk on rev 182 / 182a

from: ia-01/lane/01, written 2026-10-09 (overnight item 2)
for: Chris, at the keyboard on Friday

Every "expected" below was **measured**: the drop and promote on rev 181 (2026-10-08 22:57Z), and
the ask on rev 182 (2026-10-09 02:05Z). Where a line was not measured, it says so.

Commands assume your shell already points at the sandbox namespace's cluster context. This file
names no context or address.

## 0. What is deployed

| tag | what | how it got there |
| --- | --- | --- |
| **rev 182** | fleet `8861eb20`, chart 0.4.35, cortex-ui `3d5a0e1` at digest `sha256:83366dd5…` | `helm upgrade` (roll #23), 01:22→01:42Z on 10-09, prime `22 ok / 0 failed / 0 unfinished` |
| **rev 182a** | rev 182, with **only** the cortex image replaced by the drop-zone fix | `kubectl set image` on the cortex deployment. It is not a helm revision, so `helm history` still says 182 |

- **Status of 182a:** cortex had not reported a sha and digest when this was written. If 182a is live,
  the line at the bottom of this file gives its digest and ready time. If that line is missing, 182a
  was never applied and the demo runs on plain 182.
- **The 182a caveat:** any `helm upgrade` puts the cortex image back to the value in
  `values-sandbox.yaml`. Do not run one on Friday. Lane 1 will fold the 182a digest into the values
  file before the next roll.
- **Check which tag is live** (this prints the image only, no secrets):

      kubectl -n sandbox get deploy iagent-cortex-ui -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}{.status.readyReplicas}/{.spec.replicas}{"\n"}'

  Expect `ghcr.io/edgy-solutions/cortex-ui/frontend@sha256:83366dd5…` and `1/1` on 182 (measured 03:40Z
  10-09), or the 182a digest given at the bottom.

## 1. Before the room: three syncs, in this order

These are the three syncs the walk depends on. The seed CronJob runs them in this same relative order
(`helm/invincible-agent/templates/topaz-seed-cronjob.yaml:250-290`). Run each from the BFF pod,
which carries the repo at `/app` and `TOPAZ_DIRECTORY_URL`.

1. **Who the people are**: personas, cells, groups, users (`policy/sync/topaz_sync.py`).

       kubectl -n sandbox exec deploy/iagent-cortex-bff -- sh -c 'cd /app && python policy/sync/topaz_sync.py --topaz-url "${TOPAZ_DIRECTORY_URL:-http://topaz-svc:9393}" --policy-dir policy'

   *Not measured in this exec form.* The documented form is a port-forward plus
   `--topaz-url http://localhost:9393 --policy-dir policy/` (`policy/README.md:80-92`).
2. **Who may promote**, which makes bob the `document_promotion:SUSTAINMENT` audience
   (`policy/sync/task_grant_sync.py`, reading `policy/task_grants.yaml:382-389`).

       kubectl -n sandbox exec deploy/iagent-cortex-bff -- sh -c 'cd /app && python policy/sync/task_grant_sync.py'

   The helm hook already runs this on every roll. Run it by hand only if bob's queue is empty at step 3.
3. **Who may invoke which verb** (`policy/sync/capability_grant_sync.py`).

       kubectl -n sandbox exec deploy/iagent-cortex-bff -- sh -c 'cd /app && python policy/sync/capability_grant_sync.py'

   Expect: `loaded 12 capability(ies), 15 invoker grant(s); synced: +N relations, -0 revoked; checked=15 failures=0`.
   On 10-08 it showed `+2`; a re-run shows `+0`. Exit 0 means OK, 2 a malformed file, 4 a failed readback.

The other two syncs, `grant_sync` (asset readers) and `datahub_topaz_sync` (dataset owners), do not
gate this walk.

## 2. Hard-refresh every cortex tab

**Do this after any roll or `set image`, and before the first question.**
- A cortex tab left open across a roll re-registers its **old** bundle's presentation menu.
  - Measured on rev 182 at 01:47Z: the stale tab registered 46 rows, without `mesh#NoticePartSet`.
  - The PCN question then rendered as a plain document (`presentation_source: unrenderable`), ×3.
- After a hard refresh (Ctrl+Shift+R), the 02:05Z registration had 47 rows, including
  `mesh#NoticePartSet`, and the same question rendered as the parts table ×3.
- **If the table comes back as a document:** a stale tab is the first suspect. Close every cortex
  tab, open one, and hard-refresh it.

## 3. The walk: PCN26-184, step by step

The cast:
- **alice** drops and asks, as `SAFETY_ENGINEER` · `SUSTAINMENT`.
- **bob** promotes, as the `document_promotion:SUSTAINMENT` audience.

The walk sheet has bob asking. Both askers work, and the measured asks were alice's.

| # | do | expect (measured) |
| --- | --- | --- |
| 1 | alice drops `PCN26-184.pdf` in the drop zone, content kind `pcn` | 200, `stage: received`, ingest id `sha256:…`, `dropped_by.authz_id = alice@example.com` |
| 2 | wait (about 100 s on rev 181) | `received` → `extracting` (about 60 s) → `review` (about 40 s later) |
| 3 | bob opens his task queue | one `document_promotion` task: "Promote document sha256:…", audience `document_promotion:SUSTAINMENT`, requested by `svc:doc-tools`, status `pending` |
| 4 | bob acts **`promoted`** (not `approved`), with a reason | 200, `rows_resolved: 1`, `fact.promoted_by = human:bob@example.com`, a `record_id` `dr-…` |
| 5 | (status) | `stage: promoted`, detail `record dr-…`, within 20 s |
| 6 | ask: **"which parts does PCN26-184 affect"** | route `mesh:whichPartsDoesThisNoticeAffect` on engine-o, with the subject resolved to `…/doc/PCN26-184` |
| 7 | (answer) | a parts table (`INSTANCES_BY_PROPERTY`) titled **"Parts affected by PCN26-184"**, rows **5530-184** and **5530-185**, `presentation_source: registered` |
| 8 | (provenance) | the floor reads `obtained_via: user-drop`, `ingest_ids: []`, `unidentified: 0` |

The ask (steps 6–8) takes 66–74 s on rev 182, so say something while it runs.

**PCN26-184 was already dropped and promoted on rev 181.** Dropping the same bytes again returns
`duplicate` ("already processed on …") and opens no new review. Either:
- **ask only (steps 6–8)**, which works today; or
- **drop a fresh notice**, then run steps 1–5 on it and ask about that number. Its rows are the
  parts named in its own text.

## 4. Fallback from review: PCN26-185, parked overnight

If the live drop stalls (it stays in `received` or `extracting` for more than 3 minutes), start from
review instead:
- **PCN26-185** was dropped overnight as alice and **left at `review`**. Nobody has acted on it.
  - It names parts **5530-186** and **5530-187**.
  - Its ingest id and task id are in the line at the bottom of this file.
- **The steps:** bob opens his queue → acts `promoted` with a reason (step 4) → status `promoted`
  (step 5) → ask "which parts does PCN26-185 affect" (steps 6–8, expecting 5530-186 / 5530-187).
- **Not measured:** the PCN26-185 ask itself. The promote and the ask are left for Friday on purpose.

**If the promote is refused:**
- A 422 `promotion_payload_invalid` is the old payload defect, fixed by `279ef179` (an ancestor of
  rev 182) and not seen since rev 179.
- A 409 `delegated_act_unsupported` means someone acted on bob's behalf. R-089 refuses delegated
  promotion, so bob must act himself.
- Either way, fall back to **ask only** on PCN26-184 (section 3), which is already promoted.

## 5. Do not, on Friday
- Do not run `helm upgrade` or `scripts/upgrade-sandbox.sh`. It would also undo 182a.
- Do not roll doc-tools.
- Do not act on any MAINTENANCE promotion. Its audience is liaison, who has no login.

---
overnight status lines (Lane 1 appends below)

- **182a is live** (2026-10-09 16:39:51Z).
  - cortex-ui `415e5e6` at `ghcr.io/edgy-solutions/cortex-ui/frontend@sha256:e06fbeb277588f7b8b9dddc56a30fccff1f1c9de04f10a4d7baf6ec4da71651b`.
  - Verified in GHCR before the swap: the full-sha tag resolves to that index digest. The short tag and a fake sha both 404.
  - `set image` on `iagent-cortex-ui` only, ready `1/1`. Fleet `8861eb20`, `helm history` still 182.
  - The §0 check should now print the `e06fbeb2…` digest. **Hard-refresh every cortex tab.**
- **PCN26-185 is parked at review** (2026-10-09, as alice on 182a).
  - These are new bytes (`duplicate: null`).
  - Ingest id `sha256:034fe9f1b3e18edb406fbed93654c7f830edb1b1e0f975664e0c97a785f328f8`.
  - Stages `received` 16:40:17Z → `extracting` 16:41:02Z → `review` 16:41:49Z.
  - bob's task `document_promotion:sha256:034fe9f1…`, audience `document_promotion:SUSTAINMENT`, status `pending`, not acted on.
  - §4 starts from here.
- **Rev 185 is live** (2026-10-10, roll 06:15:02Z → 06:35:29Z, exit 0). It replaces 182a, so the §5 "would undo 182a" warning is spent.
  - Fleet `3bae602d` (chart 0.4.38, tag `invincible-agent-0.4.38`). cortex-ui `9bf8063` at `ghcr.io/edgy-solutions/cortex-ui/frontend@sha256:1985ce7fe1aa378687b1f001e6441066f381ababed959c9296483eb687a49f86`. **Hard-refresh every cortex tab.**
  - Rev 183 failed at realm-reconcile (17 stale `authz-id-svc` mappers). Rev 184 was the rollback to 182 (plus 182a). Rev 185 migrated all 17 and its readback passed.
  - Hooks: topaz manifest 12/12; task-grant-sync programs 3/3 (SANDBOX_PROGRAM_BRAVO seeded) and task grants 16/16; prime 22 ok / 0 failed.
- **PCN26-184 walk on rev 185: 6/6.** alice / SAFETY_ENGINEER / SUSTAINMENT. `mesh:whichPartsDoesThisNoticeAffect` on engine-o, INSTANCES_BY_PROPERTY, rows 5530-184 and 5530-185. Three were `default-menu` and three `registered` (`frontend_id: cortex-ui-desktop`).
- **PCN26-185 is promoted** (§4 is consumed). bob acted `promoted` on `document_promotion:sha256:034fe9f1…` (200, `rows_resolved: 1`). alice's status reads `promoted`, detail `record dr-b7066780f6ac6725`.
  - The ask "which parts does PCN26-185 affect" passed 3/3: rows 5530-186 and 5530-187, `default-menu`.
  - For a further §4 demo, drop a new notice. This one is spent.
