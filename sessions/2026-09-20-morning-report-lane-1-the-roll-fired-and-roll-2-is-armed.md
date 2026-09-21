# Morning report — Lane 1, 2026-09-20 early: the roll fired, roll #2 is armed, three seals are red

to: ia-01/lane/01
cc: Chris (this is the one file the overnight order asked for), the architect
from: session working `C:\Users\cnogr\git\invincible-agent` :: `master` and `ia-01` :: `lane/01`
read-by:

**Read §1 and §2 only if you read nothing else. §1 is what needs you; §2 is what is armed.**

Every number below was measured by me tonight unless it says otherwise. Where I took something on
another lane's word, it says so. Two of my own published claims were WRONG tonight and both
corrections are in §6 rather than quietly fixed.

---

## 1. WHAT NEEDS CHRIS

1. **Cortex's new frontend digest.** Roll #2 is armed and verified *except* for this. The frontend
   line is NOT in roll #2's diff — it stays on `sha256:c8d6553f…`, so as it stands roll #2 carries
   no frontend change at all. When cortex reports, the digest goes into
   `helm/invincible-agent/values-roll-frontend-digest.yaml`, then I re-run the dry run and the
   full-manifest diff before any go.

2. **A red seal whose missing half is cortex's.** `test_the_two_MIRRORS_agree_FLEET_WIDE` fails on
   `('cost#LotCostingReview', 'mesh#SourceLedger')`: the backend advertises the pair, the frontend
   does not bind it. Checked in the sibling repo, not assumed — cortex-ui ships `SourceLedger.tsx`,
   its contract and its registry entry, but the string `LotCostingReview` appears **nowhere** in
   `cortex-ui/src`. Either cortex binds it, or somebody who owns the staging adds a
   `_MIRROR_GAPS_AT_RATIFICATION` entry. **I did not add one**: that register declares deliberate
   intent and "only ever shrinks", which is not a thing to invent overnight to quiet a seal.

3. **The inbox seal is red on NINE files, and it is the lane-less-addressee gap — TWO OF THEM ARE
   MINE.** This is the architect's own open item ("the inbox seal has no word for a seat") with a
   count attached. Six are tracked handoffs addressed to lane-less seats, and **I added two of them
   tonight** by committing the architect's evening handoff (`bcea1ab`) and 5f's (`4811312`) exactly
   as ordered — so following that order made this seal worse, and neither the order nor I noticed.
   The other three are ca packets that landed untracked in the shared checkout *during* my suite
   run; I did not commit those, because the complaint is that they name no lane, so committing them
   as-is keeps the seal red and adding a `to:` line to another lane's packet puts words in their
   mouth. **The fix is the vocabulary, not the nine files.** One of the ca packets matters a lot —
   see §6.2.

4. **A walk, when you are up.** Lot 4's re-walk is the after-picture, and per the walk sheet it will
   still show the bound missing until cortex's half lands. That is expected, not a regression.

5. **The suite was run on Windows, not WSL.** 4552 passed / 4 failed / 239 skipped, and AGENTS.md is
   explicit that a Windows green is real but **is not a CI signal** (3.11 vs CI's 3.12). I did not
   run WSL concurrently on purpose — two full suites contending for one machine is a documented way
   to manufacture a red with an empty stderr. Say the word and I will run it.

## 2. ROLL #2 — ARMED, NOT FIRED

    ROLL SHA   8952b114d9f5e4361a32cbee532b313fb5b8bbb5   (master, pushed)

**`60b512e2f353…` WAS ARMED FIRST AND IS SUPERSEDED — do not run it.** I verified that sha, then
kept working: the `.venv.wsl` seal fix, the lane/91+32 merge and this report all landed after it, and
one of them is lane/32's SOURCE_LEDGER projector row. A roll that omits work already merged to master
is not the roll anybody wants, so the whole arming was re-run at the real head: **17/17 images
present with arm64 at `8952b114…`, control absent, CI run `35487603467` green, and the dry run
re-diffed.** Both armings produced the identical shape, so nothing below changed except the sha.

**The general lesson, since it nearly shipped a wrong command:** an armed sha goes stale the moment
you commit again, and the artefact that carries it is a command someone will copy and paste.

**Verified tonight:**

* **17/17 images present at `8952b114…` with `linux/arm64`**, bogus-sha negative control ABSENT on
  all seventeen, so the probe discriminates. CI run `35487603467` green. (The first arming's run,
  `35486224214`, was green too, at the superseded sha.)
* **Dry run clean.** Full-manifest diff against deployed revision 147: **84 lines** — 38 `image`,
  2 `checksum/broker-code`, 2 `IAGENT_IMAGE_TAG`. 5883 lines each side, so **nothing is added or
  removed**.
* **A narrower blast radius than roll #1**, and this is the part worth knowing: there is **no
  chart-label change**, so the five sibling `:latest` deployments do not appear in the diff at all.
  They will not restart and will not re-pull. Roll #1 restarted them because the chart label sits
  inside every pod template.
* **Sibling digests re-checked** and unchanged: `c05e0131…` / `70092098…` / `ed93f7b1…`.

```
cd C:\Users\cnogr\git\invincible-agent
helm --kube-context edge upgrade iagent helm/invincible-agent -n sandbox \
  --reuse-values \
  -f helm/invincible-agent/values-roll-frontend-digest.yaml \
  --set global.imageTag=8952b114d9f5e4361a32cbee532b313fb5b8bbb5 \
  --no-hooks
```

## 3. WHAT MOVED — ROLL #1 FIRED AND LANDED

`helm upgrade` → **revision 147**, roll sha `c0005142a610…`, exit 0. Every `iagent` pod Running /
Ready / 0 restarts at settle, `engine-lg` included (it crash-looped on the previous roll).

* **Frontend is on the pin:** running digest `sha256:c8d6553f142e…`, `/version.json` reports
  `git_sha 8a13dd63f5bf…` built 18:20:11Z. Before: `df702ca5…` / `70a0eead…`.
* **The five sibling deployments pulled nothing new** — all three `:latest` digests identical before
  and after. The drift everyone was braced for did not happen, and that is now measured rather than
  hoped: Lane 1's earlier "they have drifted" was explicitly a GUESS and it was **wrong**.
* **The consumer is live on `iagent-engine-a`**, confirmed by IMPORT and not by `ls`:
  `load_table()` True, `select('Medium')` → `safety_acceptance_direct`, `select('High')` →
  `safety_concurrence`, lowercase `'medium'` correctly refused. Same import in
  `iagent-data-analyst` → `ModuleNotFoundError`. That pair is what makes it a check; check 3 reads
  TRUE on two pods with no consumer in them.

**Merged to master and pushed:** `lane/74` at `930a14e` (verified by content), `lane/01`,
`lane/91`, `lane/32`, plus 5f's handoff by name. **ADR-0055 needed nothing — it was already on
master at `73547e8`, byte-identical.**

**Shipped by me tonight:** the projector `threshold`/`threshold_defaulted` row with three seals
(`988e2a4`), `scripts/retrievability_census.py`, `scripts/explain_cosine_probe.py`, the walk-sheet
record, and a one-word fix to a seal that was walking into `.venv.wsl` (`20abccf`).

## 4. THE MEASUREMENTS, AND WHAT THEY MEAN

### Predicate is in the backfill's scope

Measured three times at settle, stable, and matching 74's independent dry-run reading:

    total 133 | named 89 | legacy 44 | NO VECTOR AT ALL 0 | partition sums to 133 of 133

`legacy > 0`, so **Predicate is in scope**. The third bucket is zero and that is *asserted*, not read
off an absent line — the partition is checked to sum to the total, because "bucket empty" and "a row
escaped the partition" look identical in a counts dict. So `aitool_linker.py`'s vector-clearing path
has not fired on Predicate in this window.

**The 44 legacy rows are 43 cortex `mesh:rendersAs` bindings + exactly ONE verb.** The architect
guessed 3 + 41; it is 43 + 1. The 43 **cannot cost a route**: their only consumer reads them with a
plain `{Get{Predicate(limit:500){…}}}` — no vector, no filter — and sorts in Python, with a
truncation guard already in place at 500 against 133 rows.

**The five missing rows (138 → 133) are NOT nameable** and I did not hunt, per the ruling. Neither
74 nor I ever held a listing. **That is now fixed forward:** the probe emits all 133 rows with uuid,
slot and retrievability on every run, committed beside the census, so the next time a total moves it
is a diff. My listing independently corroborates 74's bound — 19 rows at or below
`1a5adb7b…`, 114 above.

### The pool leg's number

`mesh:explain`'s subject is `mesh#DocPage`, **read off the live Predicate row** and cross-checked
against the source rather than hardcoded. Ranked against all 24,924 OntologyClass rows carrying a
readable vector:

| question | rank | cosine |
|---|---|---|
| what is an archetype | **7** | 0.5573 |
| how do I add a canvas template | **19** | 0.4731 |
| how do I add an engine | **85** | 0.4743 |
| how do I roll a service | **139** | 0.4480 |

**Only one of four lands in a plausible top-10.** And the `DOCS`-domain subset is **EMPTY** — zero
OntologyClass rows carry `domain == "DOCS"` — so the domain filter that would rescue recall by
shrinking the pool has nothing to shrink to. 74's caveat rides in the probe's own output: hand-scored
over stored vectors, no BM25 half, no filter, no top-k. A good number would not have proven routing
works; **these are bad-to-marginal, and that direction does carry.**

OntologyClass is confirmed untouched: `legacy=24,924, none=1,315, named=0` — the 1,315 matching 74's
16 + 1,299 exactly.

### The census: the totals matched by coincidence

8 pass / 12 fail / 0 blocked, identical to the lexical baseline. **Two rows moved in opposite
directions and cancelled.** A totals comparison would have said "no change".

    finance-performance-indices   FAIL -> PASS
    finance-variance-drivers      PASS -> FAIL

The baseline's advance partition predicted "(b)'s two rows move, nothing in (a) or (c)". **All three
halves are wrong:** neither (b) row moved, one (c) row did, and (a) held.

**The finding of the run:** `safety-haz-1003` still reports disposition `drawn` wanting
`task_requested`. The roll carries the fix, 74 verified the consumer live by import, and the census
drove a real gateway turn through the row. So **"the consumer is importable" and "the dispatch opens
an acceptance" are measurably different facts** — the one link 74 marked unmeasured, still
unsatisfied. It is the first thing to chase after the walks.

**Attribution, and one of my claims needs replacing — see §6.2.** Ruled out by measurement: the 43
bindings becoming vector-visible (a probe run immediately after the census read the same
133/89/44/0, and no page load occurred). Not the cause: the `infra_error` the census printed, which
did not reproduce on a single-row re-run — the row fails on its merits, misrouting to the sibling
`fin_variance_analysis`, with all three `fin*` rows named and reachable.

## 5. MASTER IS RED ON THREE SEALS

| seal | cause | owner |
|---|---|---|
| `test_the_two_MIRRORS_agree_FLEET_WIDE` | **introduced by tonight's lane/32 merge.** Backend advertises `LotCostingReview→SourceLedger`; cortex-ui does not bind it | cortex, or whoever owns the staging |
| `test_THE_REPO_INBOX_IS_FULLY_ADDRESSED` | **9 files naming no lane** — the lane-less-addressee gap. 6 tracked handoffs to lane-less seats (**2 committed by me tonight, as ordered**), 3 untracked ca packets | the architect (it is their open vocabulary item) |
| `test_EVERY_CITED_ANCHOR_NAMES_A_HEADING_THAT_EXISTS` | a literal placeholder anchor with slug `r-0NN--slug` — written here **without its leading hash**, because the seal greps every tracked file for that literal and the first version of this line reproduced the defect it was reporting, giving the seal a second site in my own report — at `sessions/2026-09-19-handoff-architecture-seat-no-lane.md:42` | the architect seat |

**Two were fixed tonight.** `SOURCE_LEDGER` having no projector path — my overdue item, gated behind
a prime — was built by **lane/32**, and their merge turns that seal green. And the writer seal was
going red on two *dependencies* because its exclusion list named `.venv` but not `.venv.wsl`, the
second venv AGENTS.md documents; fixed by prefix, and the walk is still non-vacuous (702 repo files
kept, 65,393 venv files dropped, none kept inside a venv).

**Why I kept lane/32's merge rather than reverting it**, since it is a judgement call: master was
**already** red on the SOURCE_LEDGER projector path, so the choice was between two reds, not between
red and green. The merge trades a missing projector row on a runbook site for a declaration gap that
has a named owner and a sanctioned interim.

**A hazard worth carrying from lane/32's own comment:** the graph threads the initiator's bearer
token through state and returns it at `identity.authorization`, measured against the rolled fleet on
a live NP-MERIDIAN response. Their projector copies named fields only, so it cannot reach a browser
today, and their seal asserts that — because the way it *would* reach one is somebody widening that
tuple in good faith.

## 6. WHAT I GOT WRONG, AND WHAT CAUGHT IT

1. **I published a wrong cause for the docs rows.** I wrote that they fail "consistent with
   `mesh:explain` being the one verb row in the legacy slot". There are **two** rows for that verb:
   the live `mesh:explain` is NAMED and reachable (updated 02:08:10Z, one second before engine-docs
   logged `RECOVERED`), and the legacy one is a **stale duplicate** under a full-URI spelling whose
   `verb_local` is `//invincible-agent/mesh#explain` — what you get splitting an `http://` IRI on
   its first colon. Corrected in the file with the wrong sentence left visible. **Caught by actually
   reading engine-docs' log instead of inferring from the slot**, which the architect had ordered.
   It also means the architect's either/or ("never re-registered, or skips `upsert_predicate_row`")
   has a third answer: it re-registered and the write was correct.

2. **My "what would settle it" was wrong, and ca and eo settled it the other way.** I said the
   census attribution could be confirmed by observing a search report `mode='hybrid'`. ca's packet
   (built on eo's in-pod measurement) shows **`mode` only reports whether the embed call raised**:
   Weaviate refuses a pure vector search against an unreachable space and **silently drops the
   vector half of a hybrid one**, so `mode` says `hybrid` in both states and the hybrid result is
   the BM25 result row for row. My proposed confirmation could never have discriminated. **The real
   discriminator is eo's:** force the bm25 arm and compare row-for-row against hybrid for
   *Predicate*, where 89 rows are now genuinely reachable. Not run. It is the next measurement.

3. **I reported two lanes as "docs only" in a commit message and it was false.** True when I read
   the branches; lane/32 pushed its night's work in the interval. Amended before pushing. **A branch
   inspection from forty minutes ago describes a branch that may not exist.**

4. **I ran a naive digest comparison and nearly reported drift that was not there.** Comparing a
   pod's `imageID` to `docker manifest inspect -v` output compares different digest kinds. A positive
   control on a provably-immutable tag showed MISMATCH where a match was certain, which killed the
   method; `buildx imagetools inspect` reproduces the control exactly.

5. **Three broken matchers returned zero tonight and zero reads as a finding every time:** an
   `awk -F:` reassembly that destroyed the lines it classified; a name match that found a Service
   where I wanted a Deployment; and `git show` on a merge commit, which prints nothing by default.
   Each was caught only by asking for a positive control or the raw text.

6. **I searched for a mechanism by name and matched prose about it.** All 29 "hybrid" hits in
   engine-o's 10,626-line log are a prompt string, "verb matching is done by hybrid vector".

## 7. STANDING, AND WHAT I DID NOT DO

* **No store write, no prime, no re-sync, no backfill.** Cluster reads only, plus the one roll Chris
  authorized. The backfill did not run.
* **No roll #2.** Armed and reported; the command is in §2 and it is not fired.
* **I did not add a `_MIRROR_GAPS_AT_RATIFICATION` entry** (§1.2), commit ca's three packets (§1.3),
  or touch the `walk_census.py:54` default that still points at the stray stub — that stub is **still
  live**, still answering `git_sha deadbeef…` and still 500ing every token POST on port 18083. Held
  until the walks draw.
* **IOF_Core stays held, with its mechanism recorded:** the second manifest entry re-writes the same
  `generate_uuid5(uri)` rows by batch replace, so a failed embed strips the vector from every shared
  row — 74 found 12 of the 13 BFO and IOF Core rows vectorless. First fleet-writer item after the
  walks. Nothing built.
* **Tonight's two projector edits are HAND EDITS to the table that ADR-0055 §3 replaces** — mine and
  lane/32's, in the same tuple table in `presentation_agent/main.py`. Both will need revisiting when
  that ADR's mechanism lands; they are not the shape it describes.

Lane: ia-01/lane/01
