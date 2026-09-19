# Handoff — Lane 1, 2026-09-19: the roll is armed and NOT fired

to: ia-01/lane/01
read-by:
from: session `invincible-agent-45 [ede2b5]` (route by the worktree/branch pair, never the bare
name — two live sessions have shared a name before, and a session address predicts neither half)

**The roll is prepared, verified twice, and deliberately not run. Do not roll until items 1a–1c
below are all true.**

---

## 1. THE EXACT NEXT STEP

Environment commands are in this repo's **declared** form. `uv sync` bare is AGENTS.md HAZARD 2
and voided a run this session — it drops the `agent-fleet` extra and the suite cannot collect.

    # 0. environment, in the declared form. NEVER the bare form.
    cd C:\Users\cnogr\git\ia-01
    uv sync --extra agent-fleet

    # 1a. the four image probes MUST pass at the roll sha
    #     ROLL SHA = c0005142a610bc7759cfc8953666aee7c6064632
    docker manifest inspect ghcr.io/edgy-solutions/invincible-agent/ontology-service:c0005142a610bc7759cfc8953666aee7c6064632
    docker manifest inspect ghcr.io/edgy-solutions/invincible-agent/cortex-bff:c0005142a610bc7759cfc8953666aee7c6064632
    docker manifest inspect ghcr.io/edgy-solutions/invincible-agent/mesh-registrar:c0005142a610bc7759cfc8953666aee7c6064632
    docker manifest inspect ghcr.io/edgy-solutions/invincible-agent/restate-analyst:c0005142a610bc7759cfc8953666aee7c6064632
    # CI was BUILDING at handoff time (run queued on c000514). Probe a bogus 40-char sha as a
    # NEGATIVE CONTROL in the same breath — a probe that says EXISTS to anything is not a probe.

    # 1b. re-run the EXACT roll command as a dry run and READ THE FRONTEND LINE
    helm --kube-context edge upgrade iagent helm/invincible-agent -n sandbox \
      --reuse-values \
      -f helm/invincible-agent/values-roll-frontend-digest.yaml \
      --set global.imageTag=c0005142a610bc7759cfc8953666aee7c6064632 \
      --no-hooks --dry-run
    # PASS = the frontend renders `cortex-ui/frontend@sha256:c8d6553f…`, NOT `:latest`.
    # DIFF THE FULL MANIFEST, NOT THE IMAGE LINES. See §5 — an image-line diff looked clean on a
    # command that blanked DATAHUB_TOKEN.

    # 1c. CHRIS AUTHORIZES. Then, and only then, drop --dry-run.

**AFTER the roll, in this order (the architect's list, unchanged):**

    2. kubectl --context edge -n sandbox exec <cortex-ui pod> -- cat /usr/share/nginx/html/version.json
       -> report the sha AND the digest actually running.
    3. kubectl --context edge -n sandbox exec <consumer pod> -- ls /app/policy/decisions
       -> then tell ia-74/lane/74 it is live.
    4. nearObject(self) on Predicate + the row count. 135 retrievable => NO Predicate backfill.
    5. Walk census, SAVED, diffed against the lexical baseline (§4). No backfill has run, so
       OntologyClass routes should NOT move; any that do are findings.

**Port-forwards die across every roll.** The census needs keycloak and bff. **Assert endpoint
IDENTITY before trusting any number** — see §5, a stray stub cost a whole census run.

---

## 2. STATE

    branch          lane/01
    head            4731705bcd1cf45ed151ed1ae8d0d5984715d4d0
    ahead/behind    0 / 0 against origin/lane/01
    tree            CLEAN

    master          c0005142a610bc7759cfc8953666aee7c6064632  (pushed; = THE ROLL SHA)
    master tree     C:\Users\cnogr\git\invincible-agent — CLEAN, 0 ahead, 0 behind
    chart version   0.4.6   (deployed is 0.4.4, revision 146)
    SDK pin         iagent-mesh v0.9.3, PROVEN by direct_url.json:
                    commit_id b6d597f0aecf…, requested_revision v0.9.3

**Files I left untracked, anywhere, with absolute paths:** NONE that are mine.
Both `invincible-agent` worktrees are clean. `docs/BOARD.md` shows dirty after any suite run —
it is LINE-ENDING churn only (`git diff --numstat` is empty); `git restore` it, never stage it.

Untracked in `C:\Users\cnogr\git\doc-tools` — **NOT MINE, do not touch, another session's tree:**

    C:\Users\cnogr\git\doc-tools\.mcp.json
    C:\Users\cnogr\git\doc-tools\eval_draft.json
    C:\Users\cnogr\git\doc-tools\mfg_corpus_report.json
    C:\Users\cnogr\git\doc-tools\mfg_corpus_report2.json
    C:\Users\cnogr\git\doc-tools\tests\fixtures\manufacturing\_repro_response_current_current.json
    C:\Users\cnogr\git\doc-tools\tests\fixtures\manufacturing\_repro_response_structured_current.json

I committed in `doc-tools` (3 commits, pushed) and `cortex-ui` (1 commit, pushed), **staged by
named file only, nothing outside `sessions/`**. Both are 0 unpushed.

---

## 3. MEASURED vs INFERRED — marked per claim

**MEASURED (I ran it and read the output):**

* The roll sha contains `96d7feb`, `2733628`, `6c07d57`, `deda8a9`, `14b23c2`, `db579f8`
  (`merge-base --is-ancestor`, each).
* `--reuse-values` does NOT apply the digest — dry-run rendered `:latest`.
* `-f values-sandbox.yaml` blanks `DATAHUB_TOKEN` — full-manifest diff.
* The scoped overlay changes ONLY timestamp + chart label + frontend image line; token survives.
* Frontend pod runs `imageID sha256:70a0eead…`, `spec.image :latest`, `pullPolicy Always`;
  `/version.json` reports `git_sha df702ca5cf0c…`, built `2026-09-19T16:08:25Z`.
* `:latest` today = `81407e58…`/`f8dc4533…` — a DIFFERENT image from both the pin and the pod.
* The pinned digest resolves in GHCR, multi-arch OCI index, **arm64 present**.
* Four cross-repo images in the chart; **three still `:latest` + `pullPolicy: Always`**
  (`dag-tools/central-gateway`, `dag-tools/user-deployment`, `pub-tools`). Other 16 non-ours
  images all carry real version tags.
* Chart-version floor already dangling **at 0.4.4** — `0.4.4` and `0.4.5` both MISSING in GHCR
  for `ontology-service`, `cortex-bff`, `graph-host`. Running pods use full-sha tags.
* Walk census: **8 pass / 12 fail / 0 blocked**, and the FIRST run was void (§5).
* `git diff 51db099 <roll sha> -- policy/task_kinds` — **EMPTY**, with a control showing the
  path exists and tracks 4 files.
* Suite on the roll candidate `db579f8`: **4460 passed, 1 failed** (the sequenced projector row).
* IOF_Core twice in `CANONICAL_TTL_MANIFEST` (`prime_databases.py:174`, `:229`), same upstream
  URL (`:176`, `:231`); names AND s3_keys differ, so only the URL exposes it.
  Weaviate uuid = `generate_uuid5(uri)` (`ontology_assets.py:653`, used `:698`).
* 7f's 7 failures: their venv held a strict SUBSET (11 of v0.9.1's 18 modules), 7 absent = 7
  failures. `interfaces.py` present at v0.9.0/0.9.1/0.9.2/0.9.3, so the pin move could not
  have caused it.
* `uv lock --check` in doc-tools: exit 0, "Resolved 384 packages in 19ms", lock untouched.

**INFERRED — labelled a guess, not a cause I measured:**

* **GUESS:** that CI will publish images at `c000514` shortly. The run was QUEUED when I
  handed off. **Probe; do not assume.**
* **GUESS:** that the three sibling `:latest` images have actually drifted. I measured the TAG
  and the PULL POLICY, not that their content changed under us.
* **GUESS:** that the release retag never published `0.4.4`. I measured ABSENCE for three
  images; whether the retag ran and failed, or published elsewhere, I did not establish.
* **NOT MINE, reported by 7f and read in their tree, not independently re-derived:** the
  `ontology_assets.py:861/:877` vectorless-row shape, their CI export finding, their PR result.

---

## 4. RULED vs OPEN

**RULED (this order and the earlier ones, 2026-09-19):**

* Cause 1 WITHDRAWN — no `iof_mro.ttl` manifest row. (Verified 3 ways; `iof_mro.ttl` is a
  self-described dummy, `IOF_MRO` already in the manifest at `:181`, 74 found it at `f18bc9a`.)
* Pool leg **ON HOLD** — not shipping was right; it waits on 7f's writer fix MERGED AND RUNNING,
  a re-sync, and a read of a live node.
* Item-8 correction accepted: the docs-walk-sheet successor entry was the right target.
* `narrowed_by`, not `scoped_by`, for the slot field. No cut; rides the next pin.
* Committing ca's untracked packets was the ruled route (done 3×).
* eo hold lifted; lane/32 binding merged; the floor finding accepted as measured.
* Digest pinned in a **declared values file**, never a bare `--set` (R-034).
* Standing: no roll during a backfill, no backfill during a roll.

**OPEN, with owners:**

| item | owner |
|---|---|
| `_PROJECTED_ARCHETYPES` row for SOURCE_LEDGER (runbook site 2, after roll→prime→ask the graph) | Lane 1 |
| producer case + `_EXEMPT` amendment (sites 5/6) | Lane 1, after site 2 |
| `mesh:SourceLedger` definition names a sibling class — listed as DEBT in `KNOWN_SIBLING_BLEED` | **ia-32/lane/32** |
| three sibling `:latest` images, `pullPolicy: Always` | architect — not tonight's |
| retag-by-digest: did it ever publish `0.4.4`? | **HELD until four walks draw** |
| where seats may write in the shared tree | architect — held for after the walks |
| lane-less addressee vocabulary (inbox seal has no word for a seat) | architect |
| "when a PR build goes green, ask whether it PUSHED" | standing question, everyone |
| IOF_Core twice in the manifest | Lane 1 (manifest shape); no reshape until the walks draw |
| `review_request` consumer | ia-74/lane/74 — **merged**, awaiting the roll |
| re-embed path (none exists in doc-tools; "backfill" promised 4× across 3 writers) | architect to commission; NOT built |

**HELD — the pool leg, and the number it waits on:**

**I did NOT take the `mesh:explain` cosine measurement.** I wrote the probe and never ran it.
It is at
`C:\Users\cnogr\AppData\Local\Temp\claude\c--Users-cnogr-git-invincible-agent\1d41a1f7-726b-4b16-b48d-df0fbc54d8d5\scratchpad\explain_cosine_probe.py`
— **scratchpad, not the repo, so treat it as a draft and re-derive the identifiers.** It embeds
the docs walk's own questions and cosines them against stored `OntologyClass` vectors, read-only,
per 74's packet §5. `mesh:explain`'s subject is `mesh:DocPage` (`docs_agent/main.py:105`).
**State 74's caveat with any number it produces:** a hand-scored ranking over stored vectors is
NOT the pool a fixed search would build. **The pool leg stays held until that number exists.**

**The lexical census baseline — path and sha:**

    docs/measurements/walk-census-run-2026-09-19-lexical-baseline.txt
    committed 76b9733 · run against repo sha b7ea6b080af262a19bd2a90c971a7249d80dcd26
    8 pass / 12 fail / 0 blocked · fleet MIXED(91d8d34,d3ca169)

Its 12 failures are partitioned IN THE FILE, written before the fact: (a) six share the dead
vector half's signature, (b) two are fixed-and-unrolled, (c) four are finance payload/shape.
**Every PASS in it is a LEXICAL pass.**

**doc-tools PR #1 is GREEN and UNMERGED. Chris lands main.** The full backfill's precondition is
**that image RUNNING**, plus 74's script, plus Chris — not the branch.

---

## 5. WHAT I GOT WRONG, AND WHAT CAUGHT IT

1. **I nearly recommended a roll command that would have blanked `DATAHUB_TOKEN`.** I diffed the
   IMAGE LINES of `-f values-sandbox.yaml`, found exactly one difference, and was one step from
   sending it. **The full-manifest diff caught it.** The check is the manifest, not the images.
2. **My "retrieval is ruled out" was a control that could not fire.** I reported `"falling back
   to BM25"` — 0 hits, matcher positive-controlled at 141 `resolve` hits. The control proved the
   HAYSTACK was searchable; the message only prints when `embed_query` RAISES, and it never
   raises. **74's independent measurement caught it.** Control the EMITTER, not the matcher.
3. **I almost saved a void census as the lexical baseline.** 0 pass / 20 fail, "keycloak refused
   a token: 500". Port 18083 — the runner's DEFAULT keycloak port — is held by a **stray stub
   running since 2026-09-10** answering `{"component":"cortex-bff","git_sha":"deadbeef…"}`.
   **Asking what was actually behind the port caught it.** A live forward to the wrong service
   is worse than a dead one.
4. **A clean merge that was semantically broken.** git auto-merged `seed_sandbox_predicates.py`
   with NO conflict and produced my `vector_config=` AND 74's `**_named_vector_config()` in one
   `create()` call — duplicate kwarg, `TypeError` at runtime. **Grepping the merged file caught
   it.** A textual merge with no conflict is not a semantic merge.
5. **My shape D was worse than 74's and I retired it.** I spelled `"default"` three times and
   wrote a seal to DETECT disagreement; they put `VECTOR_SPACE` in one module so disagreement is
   IMPOSSIBLE. Their helper also handled the `weaviate-client>=4.5.4` RANGE I had noticed and not
   closed. My seal file is DELETED, not kept — it parsed a literal that no longer exists.
6. **I expected the chart bump to dangle 17 tags; my own control disagreed.** `0.4.4` was ALREADY
   missing, so the bump moved an already-dangling pointer. **Verify the figure that agrees with
   you.**
7. **I misattributed a CI defect to my repo and had to check twice.** 7f flagged a bare
   `uv sync`; it was THEIR workflow, and my three sync steps already read `--locked --extra
   agent-fleet`. I then tested the comment's ACTUAL claim (`uv lock --check`) rather than 7f's
   neighbour of it (`uv sync --locked`).
8. **I warned a live session off its own work.** My first doc-tools amendment said "do not
   checkout, stash or restore that file" about 624 uncommitted lines that turned out to be 7f's
   in-progress task. Corrected and pushed within the hour; they confirmed the tree was never at
   risk.

---

## 6. STANDING

* **Nothing touches a shared store without Chris.** No re-sync, no re-ingest, no backfill, no
  write to Weaviate/Neo4j/Jena/MinIO. I made cluster READS only this session.
* **No instrument work until four walks draw.**
* **Never release commits you did not write.** I committed three ca packets and one lane-32
  `to:` line — all `sessions/`-only, staged by named file, each with its reason in the message.
  That is the ruled route for an UNDELIVERED PACKET, not a licence to land others' code.
* **Stage by named file in any checkout you do not own.** Never `git add -A` outside your own
  worktree — another session was working in `doc-tools` while I committed there.
* **A session name is not a seat.** Route by worktree/branch pair and confirm with
  `git worktree list` + `branch --contains`.

Lane: ia-01/lane/01
