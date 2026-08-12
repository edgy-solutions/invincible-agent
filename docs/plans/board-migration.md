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

## Acceptance

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
