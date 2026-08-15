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

**Every authority-bearing citation is path-shaped** — `docs/plans/X.md` in backticks, or
`[...](../plans/X.md)`. None are name-shaped `[[wikilinks]]`. So none of them survive a move and
all six must be updated in the same commit.

**`docs/BOARD.md` needs nothing.** `generate_board.py` emits `docs/plans/{name}` from the file it
parsed, and live items are the species that STAYS — so the generated links are correct by
construction. A point in the ruling's favour: no generator change, no schema change.

### THE ONE THAT MATTERS — the code citations rot SILENTLY

All 7 code sites are **docstrings and assertion messages**, not file loads:

```
tests/test_dispatch_driver.py:378   f"(docs/plans/2026-08-04-notice-a-dispatch-failure.md)"
tests/test_cross_repo_contracts.py:3    """... see docs/plans/cross-repo-string-contracts.md ..."""
tests/test_sustainment_instance_match.py:3  """... (docs/plans/pcn-pdn-bulk-resolve.md §6a) ..."""
tests/fixtures/failure_path/cropfail_review.py:16   """... docs/plans/refusal-routing-design.md ..."""
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

### And the coverage line should count what it can act on

Whatever the ruling, `coverage_line()` currently counts every file in `docs/plans/` as a packet
owing a header. **A denominator that includes the archive can never reach *N of N*** — the
migration would be permanently incomplete by construction, which is the opposite of what a
self-disclosing coverage line is for.

## Acceptance

- **The three-way move is done and every one of the 39 inbound citation sites is updated in the
  SAME commit** — a moved file with dangling ADR references is worse than a mis-shelved one.
- **A dangling-`docs/plans/` citation check is in the suite, scanning code as well as docs, and
  sealed break-on-purpose.** It goes in green against today's clean baseline; the code sites are
  the reason it cannot be a one-time grep.
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
