---
id:         board-migration
status:     open
owner:
blocked-on:
closed-by:
code-site:  scripts/generate_board.py, tests/test_board_drift.py
repo:       invincible-agent
summary:    Retrofit ADR-0040 headers onto the unheadered packets; the board's first tracked item is its own completion.
---

# Board migration — retrofit headers onto the remaining packets

The board's coverage line states the gap in the artifact itself. This packet is the work that
closes it, and it is **the first thing the board tracks about itself** — which is the property
worth having: the pattern's completion is on the board, not in a conversation about the board.

It was deliberately absent until now. A board line without a packet fails the orphan test, and
papering it in to make the first instance look complete would have been the worst available
trade. It becomes legal the moment this packet exists.

## The work

Every `docs/plans/*.md` gets the ADR-0040 header. Two populations, different difficulty:

**Unheadered packets** — most of the corpus. Mechanical: derive `id` from the filename, read the
body for status, name an owner or leave it empty.

**Legacy-frontmatter packets** — two, carrying a June convention (`status`/`date`/`authors`/
`gates`) with prose statuses and no `id`. These are the hard ones and they are **not** mechanical:
their prose encodes nuance the five-value vocabulary deliberately flattens
(*"Plan (LOCKED — Decision 3 RESOLVED… ALL gates 1-6 closed)"*). ADR-0040 says the migrator must
accept that trade **consciously rather than discover it mid-sweep**.

## The trap this migration must not fall into

A test asserting conformance over these packets will propose a repair: invent an `id`, flatten a
prose status you are *interpreting*, fabricate a `closed-by` sha you do not have. All three are
defects in this repo's own catalogue, and the third is worse than it looks — a fabricated sha
would then **pass the attribution seal**, laundering a guess into something that reads as
evidenced.

**Do not migrate a packet whose status you cannot establish from a committed artifact.** Leave it
unheadered and let the coverage line keep counting it. An honest gap outranks a fabricated entry.

## PHASE 2 — the larger half: arcs with NO packet at all

**Added 2026-08-10, and it is the finding under the finding.** The coverage line counts
*packets*. Phase 1 indexes them. **Neither surfaces work that was never written down** — and
roughly as many live arcs have no artifact at all as there are unheadered packets.

So phase 1 completing would make the board read *N of N indexed* while missing the larger half.
The coverage line would be honest about packets and silent about arcs, which is the
omission-lying shape one level up from the one it was built to fix.

### Method

Sweep for arcs with no artifact — conversation-held work, in-flight threads, decisions with
consequences nobody filed. **Each candidate gated by a verifying grep before it gets a line**,
because reconstruction is exactly what this board exists to replace.

**Expect attrition, and treat it as the method working.** Of five candidate items swept this
way on 2026-08-10, two were killed by one grep each: an approver-provenance fork already closed
(`acted_by` first-class in the payload and the projection schema), and "three payload-drop bugs
live" already sealed by a passthrough test deriving from the producer. Three July-era candidates
were likewise refused — a range-type defect already fixed with a comment explaining why, a
punch-list citing a survey file that does not exist, and a probe result unverifiable from the
repo.

**Five of ten candidates died on contact with a grep.** A phase-2 sweep that files everything it
remembers would put closed defects on the board as live, which sends readers hunting bugs that
someone already fixed — the board lying in its most expensive direction.

## Sub-task — sweep for decided-but-never-indexed rules

While reading 45+ packets and the ADR set, collect **rules and triggers that were decided and
never indexed anywhere**. The July bank-rule (*every banked item gets a named trigger or deadline
at bank-time*) sat unindexed for six weeks; it applied directly to ADR-0040 and neither agent
reached for it until prompted. It is now `trigger:` in the schema.

**Rules already decided and never indexed are the most expensive things to re-derive** — they are
re-argued from scratch, often to a different conclusion, by people who would have agreed with the
original. That sweep is the migration's highest-value by-product and should not be left implicit.

## RULED 2026-08-11 — `closed-by` must become repo-aware, and the tripwire on that field just fired

**Filed by ruling, not by discovery.** ADR-0040 gave packets a `repo:` field, so a packet can
describe work in another repository — but `closed-by` is validated with `git cat-file -t` in
**this** repo (`scripts/generate_board.py:113`). **A packet with `repo: cortex-ui` structurally
cannot cite the commit that closed it.**

First live instance: `cortex-ui-transport-idiom`. The work landed as `cortex-ui@2c3b8a9`; the
board can only resolve `d1184b3`, the invincible-agent commit that *records* it. The escape hatch
(`closed-by-note:`) was used, and was the correct use — but that is precisely the problem.

### Why this is urgent rather than cosmetic

**Every cross-repo closure will burn the escape hatch, and an escape hatch used routinely stops
signalling anything.** `closed-by-note` exists to mark the *unusual* closure whose commit touches
neither the packet nor its code-site. If it also becomes the standard way to close any packet
with a foreign `repo:`, a reader can no longer tell *"this closure is odd, read the note"* from
*"this closure is ordinary, the schema just cannot express it."*

This is the **explaining-or-excusing tripwire** set on that field when it was designed, arriving
on schedule and from the direction the design anticipated: a field that permits a stated reason
degrades into a field that *collects* stated reasons, at which point the reasons are noise.

### The fix

1. **Accept a repo-qualified sha: `closed-by: cortex-ui@2c3b8a9`.** Bare shas keep meaning
   "this repo", so every existing row is untouched — the change is additive.
2. **Resolve against the named repo when it is available, and apply the SAME attribution check
   there**: the commit must touch the packet's declared `code-site`. Attribution is the whole
   value of the field — *a resolving sha is not a correct sha*, which is the lesson the seed
   board already paid for. A cross-repo sha that resolves but touches nothing is that same defect
   wearing a different repo name.
3. **When the sibling repo is not on disk, fall back to `closed-by-note` — but record the reason
   as STRUCTURAL, not exceptional.** Distinct vocabulary, so the two cases stay separable:
   *"the checkout is unavailable here"* is a fact about the environment; *"this closure
   legitimately touched neither target"* is a fact about the work. Collapsing them is exactly
   what makes the hatch stop signalling.
4. **Seal it break-on-purpose in both directions:** a repo-qualified sha that does not resolve
   must go RED, **and** one that resolves but touches nothing must go RED. A seal that only
   proves the happy path would let the second through silently — and the second is the one the
   seed board actually shipped.

### Scope note

**The in-repo path is unaffected and its coverage is real.** This is one expressiveness gap in
one field, not a defect in the board's validation — which kept biting throughout: it caught an
invalid `status: done` and then an unresolvable sha within a minute of each other, while this
very item was being closed. Stated so the fix is not over-scoped into "the board checks are wrong."

## CENSUS 2026-08-15 — the 46 are not 46 items, and the coverage line is overstating the gap ~5×

**Read before starting phase 1, because it changes what phase 1 IS.** All 46 unheadered files
were enumerated with their title, any self-declared status line, and their add/last-touch commits.
They are not one population. They are four, and only one of them is board work:

| species | n | what it is | migration disposition |
|---|---|---|---|
| **witness / exhibit / run-card** | ~16 | a record of work already done and proven — `pcn-*-exhibit` (8), `engine-d-durability-*` (2), `phase-1-3-*-witness` (2), `b2-probe-run-card`, `analyst-loop-red-baseline`, `m2-m3-overnight-progress`, `m31-citation-ratification` (self-marked *DISPOSED*) | `closed`, and the sha that ADDED the witness is the honest `closed-by` — it touches the packet, so attribution passes for the right reason rather than by luck |
| **handoff log** | 5 | a point-in-time state dump, superseded by the next one — the four August handoffs plus `notice-a-dispatch-failure` | **not a work item in any status.** Dated, immutable, and already correctly named by their filenames |
| **design / posture / reference** | ~17 | `slice-1..5`, `standards-posture`, `identity-mint-contract`, `refusal-routing-design`, `m2-cutover-plan`/`-runbook`, `work-demo-runbook`, `cross-repo-string-contracts`, `telemetry-standard-buildplan`, `m3-grouped-review-definition-design`, `pcn-dashboard-payload-schema`, `git-rails-topaz-structural-summary`, `adr0034-trust-lifecycle-build-directive` | **the five-value vocabulary does not apply.** These are not open or closed; they are *true* or *superseded* |
| **live board work** | ~8 | `fingerprint-input-normalization` (its own title reads *BOARD ITEM*), `triage-card-archetype` (RULED, not built), `pcn-extraction-sort` (decided, waiting for its window — needs a `trigger:`), `unminted-caller-enumeration` (self-declares 5 of 5 swept → closed), `sdk-transport-auth-handoff` (*complete and green*), `phase-1-3-consumer-derive-packet` (superseded by its own witness), `pcn-can-act-topaz-binding`, `pcn-pdn-bulk-resolve` | **this is phase 1's actual scope** |

**So the coverage line is honest about the number and misleading about the meaning.** *"46 are
unheadered"* reads as *"46 items are missing from the board"*; roughly **8** are. The rest is
the archive, and an archive being unindexed is not a gap.

### The judgement call this surfaces, which is bigger than the two legacy-frontmatter packets

`docs/plans/` holds at least three species and ADR-0040's `status:` axis fits exactly one of
them. Forcing a status onto `standards-posture.md` is the schema-satisfaction refusal this repo
makes everywhere else, in the one place the migration would make it feel mandatory.

Three ways out, and this needs a ruling before the sweep rather than a decision discovered
mid-sweep — the same failure mode the legacy-frontmatter section already warns about, one level
up:

1. **A `kind:` field** (`work` | `record` | `reference`), with `status:` required only for
   `kind: work`. Most expressive; an ADR-0040 amendment.
2. **Move the archive** to `docs/plans/archive/` and scope the generator to `docs/plans/*.md`.
   Cheapest, and the coverage line becomes true by construction rather than by exception.
3. **Index everything as `closed`.** Rejected — it flattens *"this design is still the standing
   position"* into *"this is finished"*, and `standards-posture` is cited live by three ADRs.

Option 2 was the recommendation. **RULED 2026-08-15, and the ruling is a refinement of it —
see the next section.** Option 2's single `archive/` was one cut too few: it would have shelved
live-cited reference material as history.

## RULED 2026-08-15 — the cut is BY NATURE and it is THREE-WAY, and moves come BEFORE the sweep

**The split is not headered/unheadered.** That is a symptom. The split is *what kind of document
this is*, and the census above found four species where the directory name claims one.

> **A directory is a claim about what its contents are.** `docs/plans/` currently claims four
> things at once, which is precisely why its index cannot be honest. This is the same one-home
> discipline the board itself enforces — status lives in exactly one place — applied to the
> filesystem instead of to a field.

That principle is the ruling's actual content; the three destinations below are its application.

| destination | n | species | why here |
|---|---|---|---|
| **`docs/plans/`** (stays) | ~8 unheadered + 33 already headered | live work items | the ONLY species ADR-0040's `status:` axis fits. Once the rest leave, *N of N indexed* is reachable |
| **`docs/plans/archive/`** | ~21 | witness records, exhibits, run cards, handoff logs | not work items in any status — they are *what happened*. Forcing them into open/closed is a category error, and headering them would pass attribution for the wrong reason. Archive keeps them greppable without pretending they are tracked |
| **`docs/reference/`** | ~17 | design + posture docs | **the sharper problem.** `standards-posture` is cited live by ADR-0029 and two packets. Not open, not closed, not archived — **reference material with current authority.** A live-cited standard sitting in a directory called "plans" is mis-shelved regardless of headers |

**Execution order is part of the ruling: rule the taxonomy → move → sweep the ~8 that remain.**
Retrofitting headers onto 46 files and then discovering 38 should not have them is the wrong
order, and it is the same mistake this packet already warns about one level down.

### The inbound-citation census — RUN 2026-08-15, before any `git mv`

Caution: moving files breaks citations, and this repo has already had line-anchored citations
rot. So the census was run first rather than promised.

**39 inbound reference sites across 20 of the 46 files.** The breakdown is what matters:

| citing surface | sites | on move |
|---|---|---|
| intra-`plans/` cross-references | 26 | mostly *within the same destination* (handoffs cite handoffs, pcn exhibits cite each other) — but still path-shaped, so still break |
| `tests/` + a test fixture | 7 | **break SILENTLY — see below** |
| ADRs (0029, 0032, 0034) | 3 | authority-bearing |
| `AGENTS.md` | 2 | authority-bearing |
| `docs/principles/` | 1 | authority-bearing |

**Every authority-bearing citation is path-shaped** — `docs/plans/<name>.md` in backticks, or
`[...](../plans/<name>.md)`. None are name-shaped `[[wikilinks]]`. So none survive a move and
all six must be updated in the same commit.

**`docs/BOARD.md` needs nothing.** `generate_board.py` emits `docs/plans/{name}` from the file it
parsed, and live items are the species that STAYS — so the generated links are correct by
construction. A point in the ruling's favour: no generator change, no schema change.

### THE ONE THAT MATTERS — the code citations rot SILENTLY

All 7 code sites are **docstrings and assertion messages**, not file loads:

```
tests/test_dispatch_driver.py:378   f"(docs/plans/archive/2026-08-04-notice-a-dispatch-failure.md)"
tests/test_cross_repo_contracts.py:3    """... see docs/reference/cross-repo-string-contracts.md ..."""
tests/test_sustainment_instance_match.py:3  """... (docs/reference/pcn-pdn-bulk-resolve.md §6a) ..."""
tests/fixtures/failure_path/cropfail_review.py:16   """... docs/reference/refusal-routing-design.md ..."""
```

**A move breaks all four and no test fails.** That is this repo's most-tracked failure class
arriving through the migration meant to clean it up.

The first one is the worst: the path is inside an **assertion failure message**, so the dead link
surfaces only when the test fails — to someone already debugging, who then follows it nowhere.

**So the acceptance is a sealed check, not a careful commit.** A one-time grep protects this move
and nothing after it; a dangling-`docs/plans/` check in the suite protects every future one, and
it must scan **code as well as docs**, since code is where the rot is silent.

**The baseline is clean TODAY** — every path-shaped `docs/plans/…` citation in `docs/adr/`,
`docs/architecture/`, `docs/principles/`, `AGENTS.md`, `README.md` and `docs/plans/` itself
currently resolves to an existing file. **That is what makes the check assertable now**: it goes
in green, which means the first thing it ever catches is a real regression rather than a backlog.
Seal it break-on-purpose — rename a cited packet, watch it go red.

## EXECUTED 2026-08-15 — the move is done, and the seal caught two phantoms on its first run

**40 files moved, 37 files rewritten, one sealed check added.** Final classification, which
refines the census's estimate (~21/~17/~8) after reading each file against the ruling's test —
*does anything consult this to decide something today?*

| destination | n | notes on the judgement calls |
|---|---|---|
| `docs/plans/` (stayed) | 6 unheadered + 42 headered = **48** | the sweep's real scope is these 6 |
| `docs/plans/archive/` | **24** | includes the two executed build plans (`adr0034-trust-lifecycle-build-directive`, `telemetry-standard-buildplan`) and the one-time `m2-cutover-*` pair — a directive that has been executed is history, not authority |
| `docs/reference/` | **16** | includes `analyst-loop-red-baseline` (ADR-0032 measures its design against it — a live yardstick, not a record) and `pcn-pdn-bulk-resolve` (a test pins a decision recorded in its §6a) |

**Coverage line now reads `40 of 48` instead of `40 of 88`.** The denominator is reachable for
the first time; the migration's remaining scope is 6 files plus the 2 legacy-frontmatter packets.

### THE CENSUS WAS UNDERSTATED, and the correction matters more than the number

The census reported **39 inbound sites** over `docs/`, `scripts/`, `tests/`, `AGENTS.md`,
`README.md`. **That scope was wrong.** The real citing surface also includes `agent_fleet/`
(10 sites in `restate_analyst` alone), `src/iagent/`, `policy/`, `helm/…/values.yaml`, `sql/`,
`setup/`, and a `.baml` contract — roughly double what was reported, and the rewrite touched 37
files rather than the ~20 implied.

**And a generated mirror nearly took a dangling link to production.** `baml_client/inlinedbaml.py`
inlines the `.baml` source; rewriting the source alone left the generated copy pointing at a
moved file. Caught by the seal, not by review. **A generated artifact is a citing surface** —
skipping it because "it's generated" is exactly how the two drift apart.

### THE SEAL'S FIRST CATCH — a species the ruling had not named

Anchoring the check at `docs/` rather than `docs/plans/` surfaced two dead citations **that
predate this move by months**:

| cited path | citing site | verdict |
|---|---|---|
| `docs/adr/namespace-prefixes.md` | `ADR-0005:169` | **never created** (citation added `191cb63`) |
| `docs/routing/recipe_v2_instance_resolution.md` | `tests/routing/test_classify_route.py:232` | **never created**, `docs/routing/` has never existed (citation added `d454a64`) |

So there are **two species, and only one is rot**:

- **ROT** — the file existed and a move broke the link. Repairable, and what the seal fails on.
- **PHANTOM** — the file *never existed*. The citation was aspirational when written and has
  read as a statement of fact ever since. Nothing to restore.

The second is the worse shape and the harder one to see. The test one is **load-bearing**: a
deliberately-RED suite tells the reader *"See `docs/routing/recipe_v2_instance_resolution.md`"*
to understand why the rows are red — and that spec has never existed. Anyone asking the obvious
question is sent nowhere, by a comment that reads like an answer.

**Both are now phase-2 candidates, found mechanically.** That is the phase-2 method working
exactly as specified — an arc with no artifact, surfaced by a grep rather than by memory — and
it suggests the citation seal is a *phase-2 discovery instrument*, not only a regression guard.

### THE SEAL THEN MADE THE SAME MISTAKE IT WAS WRITTEN TO CATCH

The first seal matched **absolute** `docs/…` strings. A markdown link whose *target* is
relative — `](../adr/<name>.md)`, `](<sibling>.md)` — was invisible to it. And the move broke four
of those at once, by a mechanism the absolute check structurally cannot see:

> **`docs/plans/archive/` is one level DEEPER than `docs/plans/`.** Every relative link out of a
> moved file (`](../adr/…)`) needed re-basing to `](../../adr/…)`. `docs/reference/` sits at the
> same depth as `docs/plans/`, which is why only the archive tranche broke — and why a spot-check
> of the reference moves would have found nothing and read as proof.

The absolute-path seal was green throughout. So a second check now resolves relative link
targets, and between them they cover both shapes.

**That is four instances of one defect, two of them on the same day and both of them this
migration's own.** PROMOTED out of this packet — the rule applies to every guard this project
has built, not to the migration that happened to surface it:

> [[a-green-check-proves-only-its-scope]] — *the question to ask of a new guard is not "does it
> pass?" but "what is outside its scope, and how would I know?"*

The instance table and the two sub-species (excluded population vs. included non-population) live
there. Kept here only because this migration supplied the sharpest evidence: **the absolute-path
seal had been proven to bite** — renaming `standards-posture.md` went red naming `ADR-0029:157` —
**while being blind to four broken relative links in the same commit.** Proven-to-bite is
necessary and not sufficient.

**What the relative-link check found on ITS first run:** two more phantoms
(`ADR-0006-datahub-proposal-inbox`, `ADR-0016-memory-boundary-revised` — both linked as ADRs by
ADR-0019/0021, **neither ever created**), and one pre-existing broken link in
`tests/routing/STATE_GATEWAY_V02.md:417`, whose link target was written as the repo-root-relative
`docs/demo-script.md` and therefore resolved against its own directory. **It has been broken
since `3e92493` and was never valid.**

*(Note the three failures this section itself caused: prose quoting a link SHAPE is
indistinguishable from a link. The `<name>` placeholder convention above is the fix, and it is
why the scanner skips any target containing angle brackets — a seal that cannot be written about
is a seal nobody documents.)*

### And a correction to the move-day claim

*"The baseline is clean today"* was asserted in `0d1dae7`. **It was true for `docs/plans/` paths
and had never been checked for `docs/` generally**, which is where both phantoms live. The
narrower claim was accurate; the broader one was never tested. Recorded because the shape of the
error is the interesting part — **the check's own scope was the thing that made the gap
invisible**, which is the same defect as `legacy-dns-guard-phantom-scope` wearing different
clothes.

The allowlist is therefore narrow and **proves its own precondition**: an entry is legal only if
`git log --diff-filter=A` shows the path was never added, asserted per-entry, so the hatch cannot
be used to hide a real deletion. A second test deletes entries that stop being cited. Both exist
because this repo has already watched `closed-by-note` degrade from *unusual* to *routine*.

### And the coverage line should count what it can act on — RESOLVED, and it needed no code

`coverage_line()` counted every file in `docs/plans/` as a packet owing a header, so a
denominator including the archive could never reach *N of N*.

**The three-way move fixed it with no generator change.** `PLANS.glob("*.md")` is
non-recursive, so `docs/plans/archive/` is invisible to it and `docs/reference/` is outside the
tree entirely. The denominator became the live population by construction rather than by a
special case — which is why the move was ruled to precede the sweep, and is the strongest
evidence the taxonomy was the real fix and the header gap was the symptom.

## OWED 2026-08-17 — the ADR index is the third hand-maintained index found drifted, and it has headers

**Named as owed, not scheduled.** Not urgent and not part of phase 1 — filed so it is not
*discovered again in October* as if it were new.

`docs/adr/README.md` was found holding an index that stopped at 0011, resumed at 0023, and ended
at 0036: **fifteen of forty-one ADRs unrouted**, 37% of the corpus. Backfilled by hand on
2026-08-17 (`00a0ba1`), which closes the instance and leaves the defect.

That is the **third hand-maintained index found drifted this month**, and the three fail
identically — the artifact grows, the index is a separate write, and nothing goes red when the
two disagree:

| index | how it drifted | disposal |
|---|---|---|
| `BOARD.md` | reconstructed from conversation context because no index existed | **generated** from packet headers + drift test (ADR-0040) |
| the endpoint table | routes added without a row | manifest-driven |
| `docs/adr/README.md` | fifteen ADRs added without a row, tail kept growing so nobody looked | **hand-backfilled 2026-08-17 — repair still owed** |

**The repair is known and already built once.** Every ADR carries its own `# ADR-NNNN — title`
and `**Status:**` in its header — the same property that made `generate_board.py` possible. So
the ADR index is the identical shape one corpus over: generate from the artifacts' own headers,
seal with a drift test, and the index stops being a write anyone can forget.

Two things a future implementer should know before starting, both learned from the board:

- **Summaries are NOT derivable from headers.** The index rows carry each decision's load-bearing
  clause, which is editorial and worth keeping. So this is `BOARD.md`'s shape, not its scope — the
  generator owns number, link, title and status; the summary stays authored, in the ADR or beside
  it. A generator that also invents summaries would flatten the most valuable column.
- **The status field is prose here, deliberately** (*"Phase 1 Accepted; Phase 2 deferred"*,
  *"Accepted (r2); r1 withdrawn"*, *"Proposed — decision deferred"*). ADR-0040's five-value
  vocabulary would flatten it, and this corpus is where that nuance is load-bearing. Copy the
  prose through verbatim; do not vocabularise it. Same conscious trade the legacy-frontmatter
  packets forced, ruled the other way for a different reason.

**And the disposal that comes with it:** `AGENTS.md` carried a *second* index of the same corpus,
stopped at 0013 — two-homes, with the abandoned home actively lying (a reader trusting it concludes
28 ADRs do not exist). Retired to a pointer in the same arc. **One corpus, one index**; when this
item is built, that pointer is what keeps it true.

## Acceptance

- ~~The three-way move is done and every inbound citation site is updated in the SAME commit~~
  **DONE 2026-08-15.** 40 moved, 37 rewritten, one commit. Note the site count in the original
  census was understated — see the correction above.
- ~~A dangling-citation check is in the suite, scanning code as well as docs, sealed
  break-on-purpose~~ **DONE** — `tests/test_citation_paths.py`, anchored at `docs/` rather than
  `docs/plans/` (which is what caught the two phantoms). Break-on-purpose verified: renaming
  `standards-posture.md` fails the seal naming `ADR-0029:157` as the citing site.
- **REMAINING — retrofit headers onto the 6 packets still in `docs/plans/`** plus the 2
  legacy-frontmatter ones. This is now the whole of phase 1.
- **REMAINING — dispose of the two phantoms** (`namespace-prefixes`, `recipe_v2_instance_resolution`):
  write the artifact, or repair the citing site to stop asserting one exists. They are
  allowlisted, not fixed, and the allowlist is debt with a stated reason.
- Coverage line reads *N of N indexed*, or every exception is a packet with a stated reason.
- No fabricated `id`, `status`, `owner` or `closed-by` anywhere in the sweep.
- `closed-by` accepts `repo@sha`, resolves and attributes against that repo when present, and
  distinguishes a *structural* fallback from an *exceptional* one — sealed both directions.
- The decided-but-unindexed rules are filed where they belong (ADR amendments, `AGENTS.md`, or
  their own packets) rather than listed in a migration report nobody re-reads.

## Owner

Empty — genuinely unassigned. It is a large, mostly-mechanical sweep with two judgement calls in
it, and assigning it to make the field non-empty would be the schema-satisfaction refusal this
repo makes everywhere else.
