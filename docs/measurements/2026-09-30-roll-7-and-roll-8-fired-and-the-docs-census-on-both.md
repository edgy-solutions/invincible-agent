# Roll #7 (rev 158) and roll #8 (rev 159) fired, and the docs census on both — 2026-09-29/30

Lane 1 (`invincible-agent/master`), overnight dispatch items 1–4. The sections below the rule are the day's
earlier record and are kept as they were written.

## Item 1 — roll #7: fired, revision 158 `deployed`

- **Composition, and one deviation from the order.** Rev 158 is master `90fabab4`, with:
  - cause 1: the body store reads the names the pod has;
  - cause 3: the old explain row was deleted;
  - cortex-ui pinned to `sha256:79bcda2b…`;
  - chart `0.4.11`, fired with `--no-hooks`.

  **The lane/74 merge is NOT in it.** Its gate measured 12 new reds, each reproducible with its file
  run alone (table below the rule). I held the merge rather than ship reds, and packeted the worker
  (`sessions/2026-09-29-packet-from-lane-1-lane-74-merge-held-twelve-new-reds.md`). That departs from
  the order, which listed the merge as part of roll #7.
- **Pre-fire:** the engine-docs image exists at the full-sha tag. The registry answered 200; the controls were the prior tag at 200 and a one-character-altered sha at 404.
- **Verified by polling, not inferred from helm's exit.** Every `iagent-*` workload whose template
  carries the fleet tag runs `90fabab4` and is Ready. The rows not on the tag are all third-party or
  `:latest` images (`dag-tools`, `pub-tools`, `central-gateway`, `domain-broker`, clickhouse, redis,
  topaz, electric), and all of them are Ready. The cortex-ui pod's running imageID is `79bcda2b…`.
- **Cause 3: no re-registration.** After the restart, the Predicate query for `verb_local == "explain"`
  returns **one** row, `mesh:explain` (`14c38715…`). Its lastUpdate is 04:04:29Z, after the pod started
  at 04:02:11Z, so registration DID run on restart and did not bring back the old spelling. The
  deleted uuid `3f7a01b6…` returns 404; the live uuid, as a control, returns 200.
- **The architect's seal is green.** On the rolled fleet, engine-docs `/explain` with
  `{"fn":"explain","params":{"subject":"…mesh#Archetype"}}` returns HTTP 200, page
  `docs#runbook-adding-an-archetype`, body 8225 bytes, and a sha that passed the engine's own check.
  The control, subject `mesh#NoSuchThing`, gives a legible abstain (`no_page_explains_this_subject`).
  (A bare `{"subject":…}` gets a 422, because slots travel in `params`.)

## Item 2 — docs census on 158: 1 pass / 4 fail, identical ×3 (`repo=90fabab4 fleet=90fabab`)

| row | rev 157 (×3) | rev 158 (×3) |
| --- | --- | --- |
| safety-haz-1003 | `drawn` | `drawn` (unchanged; the fix is in roll #8, and the census row stays `drawn` until an SSE event carries the block, which is cortex's) |
| add-an-engine | ELICITATION, spoken `engine`, 0 candidates | same |
| what-is-an-archetype | reached engine-docs via the **stale** row as raw text `'archetype'`, got an abstain, drew 0 sections | **ELICITATION, spoken `archetype`, `reason=empty`, 0 candidates** |
| add-a-canvas-template | ELICITATION | route miss (`verb UNKNOWN`, `no_match`, fell back `no_verb_classified`) |
| roll-a-service-abstains | FAIL: `drawn` via the stale row | **PASS**: ELICITATION on `service`, which is what the row accepts |

**The architect's expectation, that "archetype" and "roll a service" would reach engine-docs with a
body, did not hold, and it could not have.** The stale row was the only path that carried a spoken
word to engine-docs, and engine-docs keys on an IRI, so on 157 it abstained anyway. With that row
deleted, every docs question goes through `mesh:explain`'s referent resolution, which does not bind
the spoken word `archetype` to `mesh#Archetype`, although that class exists and engine-docs serves a
body for it (the seal above). So the gap sits between the spoken word and the IRI, not in engine-docs
and not in the corpus.

**The worker corrected the corpus-gap premise, and I had forwarded that premise.**
`lane/74-acceptance-and-docs-subject` shows that both pages exist, declare `explains:`, and are in
the committed corpus. The rows fail at subject binding, before the corpus is consulted. **So the
re-prime of `docs_corpus.ttl` on my list would change nothing, and I did not do it.** The worker's fix
for binding is `lane/74-docs-subject-pool` (item 4).

## Item 3 — projector row: landed, reverted, then re-landed to cortex's spec

**First attempt, `3ada5e6c`: reverted in `8a5c7923`.**
- It added the row plus an arm that lifted `pages[].body` / `body` into `markdown_content`.
- The full suite showed 2 NEW reds, both from this commit, and my targeted sweep had missed
  `tests/routing`:
  - `test_the_fallback_renders_the_ask_rather_than_silence`. It is red alone. It is a seal with no
    recorded owner, and its partition treats every key the composer reads as markdown-bearing.
    I did not widen it.
  - The collection-order ratchet flagged the new seal's copied `baml_client` shim.

**Second attempt: cortex's own packet specified the card contract, and it removes the conflict.**
The packet is `cortex-ui/sessions/2026-09-29-packet-to-lane-1-docs-projector-half-…`, landed in
`a425186`.
- Cortex draws engine-docs' STRUCTURE when `pages` is a non-empty list or `abstained` is literally
  true. It asked Lane 1 to pass the six fields through and leave the markdown alone.
- So the composer is unchanged byte for byte, and a helper outside it carries `subject`, `pages`,
  `page_count`, `abstained`, `reason` and `body` beside the markdown. The helper's gate is cortex's
  own discriminator.
- These fields never feed the markdown, so they are not members of the slot-disposition seal's
  population. A new arm pins the composer's read-set to `{summary, summary_text, structured_data}`
  so the two stay separate.
- The seal uses `stub_modules`, not a shim, so the ratchet is unchanged.

**Seal: `tests/docs/test_the_doc_explanation_passes_its_structure_through.py`, 7 arms.**
- On the unfixed code: 3 red (the row, the HIT passthrough, the ABSTAIN passthrough).
- 4 green on both sides: the stray-field control, the two cortex-mirrored negatives
  (`pages: []`, `abstained: "true"`), and the read-set pin.
- After the change: 7/7.
- Targeted run of `tests/docs`, slot_disposition, the stub-harness ratchet and the mirror seal:
  134 passed.
- The mirror seal turned green: cortex had the row, and the backend had lost it with the revert.

**Committed as `ab9b2a4e`, pushed.** Full-suite gate against the `66efbe02` merge suite (junit
identities): 44 failed / 4967 passed, **NEW 0, FIXED 1**. The fixed test is the mirror seal.

The architect ruling packet drafted after the revert is withdrawn, because the contract owner's
spec answered it.

## Item 4 — the worker's two branches for roll #8

- `lane/74-overnight-safety-docs` `3ec5b3b0`: HAZ-1003, the ordinary path opens the acceptance.
  Touches gateway + supervisor; rolls cortex-bff and dagster.
- `lane/74-docs-subject-pool` `b4012650`: the DOCS subject pool is DocPage instances. Touches
  ontology_service; rolls engine-o.

The two touch disjoint files, and neither touches `3ada5e6c`. The worker reports each green in its area.
**Gate. Committed as `66efbe02`, pushed.**
- Full suite on the staged octopus: 45 failed / 4957 passed.
- Against the `3ada5e6c` baseline, by junit identities: NEW 1, FIXED 2.
- The FIXED 2 are the reds my reverted commit caused.
- The NEW 1 is `test_the_two_MIRRORS_agree_FLEET_WIDE`, which is also red when its file runs alone.
  Its one-sided pair is `docs#DocExplanation → mesh#KnowledgeDocument`.
  - cortex-ui's side landed overnight (`a425186`), and the seal reads the live sibling checkout.
  - The backend side is the row I had just reverted.
  - The staged diff mentions neither IRI.
  - So the red is caused by the revert, not the merge: **merge-caused reds 0**. The re-landed row
    in Item 3 closes it.
- These are the worker's roll-#8 pair, not the held lane/74 merge. `d246987d` (10 commits,
  12 new reds, Item 1) is still ahead of master, and **neither roll #7 nor this merge contains it**,
  as checked with `git merge-base --is-ancestor` against `90fabab4` and `66efbe02`.


## Roll #8: fired, revision 159 `deployed` at `ab9b2a4e`

- **What it carries:** the worker's pair (`66efbe02`) and the docs projector row (`ab9b2a4e`). The
  images were built by CI run 36676846584, with every job green.
- **`--no-hooks`:** `git diff 90fabab4 ab9b2a4e -- helm/ scripts/` is empty, so the image tag is the
  only change.
- **Verified by polling:**
  - 19 fleet-tag pods on `ab9b2a4e`, 0 on the old tag, all Ready.
  - The rows not on the tag are the same third-party / `:latest` set as roll #7, all Ready.
  - cortex-ui is still `79bcda2b`.
  - The engine-docs pod started 06:16:02Z.

### Docs census on 159: 0 pass / 5 fail, identical ×3. The card moved; the census did not.

Cards were captured separately (`post159_docs.json`). **Three of the four docs questions now draw
engine-docs' structure on the card:**

| row | rev 158 | rev 159 card | census verdict | why |
|---|---|---|---|---|
| add-an-engine | ELICITATION, 0 candidates | KNOWLEDGE_DOCUMENT, `pages` = 1 (`docs#runbook-adding-an-engine`, 77 KB body) | FAIL: 0 under `sections` | **instrument:** `ROW_KEY["KNOWLEDGE_DOCUMENT"] = "sections"` (`src/iagent_pure/walk_census.py:88`); the docs card carries `pages` |
| what-is-an-archetype | ELICITATION | same, `docs#runbook-adding-an-archetype`, 8 KB | FAIL: 0 under `sections` | same instrument cause |
| roll-a-service | PASS (ELICITATION accepted) | **answers**: `docs#runbook-rolling-a-service`, 14 KB | FAIL: `drawn`, row accepts `slot_required` | **the row's premise is stale.** "…-abstains" assumed no page exists; one now exists and binds |
| canvas-template | `no_match` | unchanged: route miss, the "no registered capability" text | FAIL | real: routing, unchanged |
| HAZ-1003 | `drawn` | `drawn` | FAIL: row accepts `task_requested` | **unmeasured on the live path:** the worker's `_seal_haz1003_acceptance.py` exits 2 without `HITL_POSTGRES_DSN` ("NOT a pass"). I did not fetch that credential. |

- `markdown_content` is still "No content available." on all three, which is the transition
  placeholder cortex asked for. **cortex-ui draws `pages`, so on screen these are answers.** That is
  not verified by eye tonight.
- **The census is not mine to re-key tonight.** Its `KNOWLEDGE_DOCUMENT → sections` key may be right
  for other producers, so this is a per-producer question, and the roll-a-service row is a sheet
  decision. The following are routed as findings, not fixed:
  - the two instrument rows;
  - the stale abstain row;
  - HAZ-1003's live disposition.

## Open, owned by Lane 1, and not done tonight

**cortex-ui's packet made four asks. Item 1 above answers the first; the other three are unstarted:**
- **Platform marker.** Mark platform domains in the entitlements payload, e.g. `kind: "platform"` on
  MESH / DOCS. Cortex hides them BY NAME today (`src/lib/platformDomains.ts`) and will switch to the
  marker once it exists.
- **Lot 3 `rate_vintage` menu is empty on rev 158.** `options: []`, `option_source: "none"`,
  `free_text_reason: "no_referent"`, where the census row expects 2 option chips
  (`docs/measurements/walk-census.yaml:91-96`). It is either a regression of the OPTION_SOURCES re-key,
  or the source is not registered on this fleet. Unmeasured by me. Separately, **the EAC row no longer
  refuses** (COMPETING_MEASURES, no ELICITATION). If that is intended, the census row is stale.
- **program_finance seed 409.** It is unconditional (`gateway.py` `_unbound = sorted(_consumed)`, nothing
  subtracted), and `CanvasSeedRequest` has no binding field.
  - Behind it is a 501 ("Only 'portfolio' seeds").
  - Slot `program` vs kwarg `program_id`.
  - Cortex asks for a binding field, the subtraction, a seeder, and one slot name. That is feature
    work, not a fix.

**Chart item: the substrate hook's object-store images.**
- The pre-upgrade hook needs an object-store client image that no longer pulls anonymously from either
  registry, so every upgrade blocks on the hook.
- Rolls #7 and #8 fire with `--no-hooks`, justified per roll by a values diff that touches nothing the
  hook creates.
- The fix is a mirrored image or a pull secret in the chart. It is not raised as a branch yet.
- Until it lands, **any roll whose diff adds a bucket or other hook-created substrate cannot use
  `--no-hooks`.**

---

# (earlier, 2026-09-29) Roll #7 status, and the docs census on revision 157 — 2026-09-29

## Done
- **Frontend bump LANDED.** Revision 157 `deployed` (`--no-hooks`, from master @17bb2064; first attempt died on a transient
  `tls: bad record MAC` at helm's query stage, leaving no revision; retry EXIT=0). The single cortex-ui pod's imageID is
  `sha256:6f27766587108f5dc7fc9af623b7eae4ecac4a67fd218e7efbd3524918b1d1b4`, ready=true. Watcher v2 had exited on its
  transition arm (`status=failed`, read ok), closing the caveat left open.
- **PR #4 opened, unmerged:** https://github.com/edgy-solutions/invincible-agent/pull/4
- **Cortex digest for roll #7 derived:** tag `f5c85ada8c36e36dad8e8288cb60a036e59769ff` →
  `sha256:4d49ca704ff6cd12ad3a25491ac2adbdb15cec62d7e3323ea3f47a8489ef4d6c`, OCI index with linux/arm64. Controls: the
  abbreviated tag answers `not found`; `5b559765…` still resolves to the running `6f277665`; `fc96c9b` at full sha has no image.
- **Full-suite baseline at 17bb2064:** 45 failed / 4910 passed / 199 skipped / 2 xfailed, 28m39s (junit: `suite_pre.xml`).

## Blocked — roll #7
- "The worker's merged commits" are **not merged**: `lane/74` (d246987d, 10 commits) is ahead of master, and lane 74's
  report to ia-01 hands the merge to Lane 1. Trial merge: one conflict in `agent_fleet/ontology_service/main.py:2968`,
  mechanical (lane 74 only stripped whitespace; take master's `cold_start_fallback_domains` block).
- **Merging into master was denied by the auto-mode classifier (Modify Shared Resources).** Not retried. Roll #7 not armed
  or fired: its ordered composition includes those commits.
- Also owed with roll #7: `release-helm-charts.yml` has failed on the last four helm/** commits (incl. my 3809d5ab) because
  Chart.yaml stayed 0.4.10. The roll #7 values commit should bump it to 0.4.11.

## The docs census — the measurement did not need roll #7
MESH scope (fadda10f), the pool fix (d4a00598/bfb33b89) and the lineage split (d3944da8) are all ancestors of `ec055c49`,
which all 19 engine deployments run. Three fires, `repo=17bb2064 fleet=ec055c4`, same five rows and runner as the morning report:

| row | fires 1–3 |
| --- | --- |
| safety-haz-1003-risk-assessment | `drawn`, row accepts `task_requested` — **identical ×3**, still owner 74 |
| docs-how-do-i-add-an-engine | `slot_required` + archetype ELICITATION lacks KNOWLEDGE_DOCUMENT — ×3 |
| docs-what-is-an-archetype | 0 rows under `sections`, floor 1 — ×3 |
| docs-how-do-i-add-a-canvas-template | `slot_required` + ELICITATION — ×3 |
| docs-how-do-i-roll-a-service-abstains | `drawn`, row accepts `slot_required` — ×3 |

Aggregate `0 pass, 5 fail` as before — **but this time the causes are stable per row.** The morning report's route miss
(`verb UNKNOWN`, `no_match`) and its `infra_error` did not recur in three fires. Three fires cannot show the
nondeterminism is gone, only that it did not appear; both route-miss rows now fail on the ELICITATION archetype.

Resolve probes (byte-identical to pre7_*): MAINTENANCE → Equipment from {Equipment, Procedure} ×3; DOCS → `mesh:DocPage` ×3.
Unchanged from the pre-roll reading, as expected with unchanged engines.

## The five census causes, named before roll #7 (read-only diagnosis on rev 157)

Measured from the dagster-user-code supervisor log (routing_decision / slots_filled / slot_resolution
lines for runs 6cfcc06e, 2df11033, 8c8c7e15), and from direct probes of engine-docs `/explain` and
engine-o `/page_for_subject`.

**Not one thing. There are four independent layers, and every docs row is blocked by at least one
that roll #7 does not touch.**

| # | row(s) | cause | owner |
|---|---|---|---|
| 1 | add-an-engine, add-a-canvas-template | Routed via `mesh:explain` (current registration). Slot resolution refuses the free-text subject: `slot_resolution … outcome=empty spoken='engine' candidates=0`. The ELICITATION is issued at extraction and engine-docs is never called. Nothing in the referent pool is named *engine* / *canvas template*. | engine-docs / corpus coverage — ia-5f/lane/5f |
| 2 | what-is-an-archetype, roll-a-service | Routed via a **stale second registration** `http://invincible-agent/mesh#explain` (the pre-fix spelling that `docs_agent/main.py:95-104` documents; both forms appear in `candidates=[…]`). That path fills slots as raw text (`{'subject': 'archetype'}`, `{'subject': 'service'}`) and dispatches, but `page_for_subject` keys on an IRI. Probe: `"engine"` gives 0 pages, while `mesh#Archetype` gives 1 page. So engine-docs abstains. Which of the two registrations wins is an LLM pick. | stale graph row = bootstrap-state (registrar); needs a HUMAN-executed delete of the old verb row |
| 3 | same two | The abstain body is then lost at presentation: `unrenderable` / "no typed contract for KNOWLEDGE_DOCUMENT; and output_uri matched no capability". Nothing binds `docs:DocExplanation`, so the card reads "No content available." | presentation binding for engine-docs — ia-5f/lane/5f |
| 4 | **all four**, even once 1–3 are fixed | engine-docs' body store reads `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`S3_ENDPOINT_URL\|MINIO_URL` (`body_store.py:61-63`). The deployment supplies only `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`/`MINIO_ENDPOINT_URL` (iagent-config); only the prime job maps one onto the other. Direct probe with a correctly resolved IRI: `502 … Unable to locate credentials`. **No docs page can currently be served at all.** It is a three-line fallback; the precedent is `agent_fleet/utils/artifact_provenance.py:93-97`. | ia-5f/lane/5f (`a3e31616`) |
| 5 | HAZ-1003 | `drawn` vs expected `task_requested`; the runner does not check `row_in_human_tasks`. | ia-74/lane/74 |

**None is small AND Lane 1's, so none rides roll #7.** Cause 4 is small, but it is lane 5f's file. Cause 2
is a live graph write, so a human executes it.

**What roll #7 can still measure for docs:** only roll-a-service. Post-merge its expected disposition is
`abstained`, and engine-docs does answer `abstained: true`, so `engine_abstain` may now score that row
correctly. The other three docs rows are predicted unchanged. If they change, that is a finding, not a
confirmation.

## The lane/74 merge fails its gate: 12 NEW reds, 0 fixed (junit node ids, baseline 17bb2064 vs staged merge)

pre=45 post=57 common=45 NEW=12 FIXED=0. **Every one of the 12 is red when its file runs alone**, so
none is order-dependence. Five causes:

| # | tests | cause | whose |
|---|---|---|---|
| a | `routing/test_the_pool_reaches_the_universal_referent` ×7 (master's file, untouched by the merge) | `for s, p, o in rows:` raises `too many values to unpack`. The merge changed the shape of the rows that master's universal-referent path consumes. | semantic conflict: lane/74 code vs master's leg-3 test |
| b | `test_the_migrated_route_returns_the_same_rows` ×2 (lane/74's file) | The flag-OFF arm now sends `contains_any domain [PRODUCTION_COST, MESH]` (master's MESH scope, fadda10f) and the flag-ON migrated arm sends `equal domain PRODUCTION_COST`. **The migrated route drops MESH scope.** That is a real behaviour difference. It is not live, because the flag defaults to OFF. | lane/74: the migrated route must carry MESH scope |
| c | `test_the_person_reaches_the_migrated_route` ×1 (lane/74's file) | It seals the set of `Initiator` mints in `ontology_service/main.py` at two, but master's `_POOL_READ_INITIATOR` (module level, :5074) is a third. | semantic conflict: the seal predates master's mint |
| d | `test_the_flag_default_is_off_and_every_claim_about_it_agrees` ×1 | `docs/measurements/route-migration-pilot-predicate-pool-2026-09-28.md:149` is parsed `undecided`. | lane/74 doc vs its own seal |
| e | `test_the_person_guard_is_an_allowlist_everywhere` ×1 | The file walk descends into the **untracked** `agent_fleet/docs_agent/.venv/` and flags the SDK's `interfaces.py:119`. That is this box's environment, not shipped code, but the test's population is wrong: it must skip venvs. | lane/74's test (environment-dependent) |

**The merge is uncommitted and staged in the master tree, where it sits across every other lane's
work.** Committing it would land 12 known reds on master, and (b) is a real routing difference.
