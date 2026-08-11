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

## Acceptance

- Coverage line reads *N of N indexed*, or every exception is a packet with a stated reason.
- No fabricated `id`, `status`, `owner` or `closed-by` anywhere in the sweep.
- The decided-but-unindexed rules are filed where they belong (ADR amendments, `AGENTS.md`, or
  their own packets) rather than listed in a migration report nobody re-reads.

## Owner

Empty — genuinely unassigned. It is a large, mostly-mechanical sweep with two judgement calls in
it, and assigning it to make the field non-empty would be the schema-satisfaction refusal this
repo makes everywhere else.
