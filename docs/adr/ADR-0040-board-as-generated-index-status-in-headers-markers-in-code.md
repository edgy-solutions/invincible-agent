# ADR-0040 — Work tracking: the board is a generated index, status lives in the item's own header, and code-sited items carry a marker

**Status:** Proposed — decision recorded; the migration it implies is substantial and is scoped below rather than assumed away.
**Date:** 2026-08-10
**Deciders:** Platform team
**Related:**
  - [ADR-0036](ADR-0036-config-layering-seed-overlay-composition.md) — generated-not-hand-written, and the drift test that keeps a generated artifact honest. This ADR applies that discipline to the board.
  - [ADR-0039](ADR-0039-workflow-definition-authoring-schema-and-bpmn-export.md) — same shape one plane over: a schema generated from the model with a drift test, so two declarations cannot disagree.
  - `AGENTS.md` — the discoverability rule ("a record the entry path doesn't route to is unshipped") and the marker-at-the-site discipline this decision generalises.

## Context

State is spread across artifacts with **no index**. The symptom is diagnostic: *"where are we?"* has been answered repeatedly by an agent reconstructing the board from conversation context — which is the one place it cannot live, because it evaporates between sessions and is invisible to everyone else.

### What is actually there, read 2026-08-10

| artifact | count | state |
|---|---|---|
| `docs/adr/*.md` | 39 | decisions — healthy, indexed by number |
| `docs/plans/*.md` | **55** | packets — **44 carry no status line at all** |
| of those, with a status line | **11** | and **no two share a format** |
| `sessions/*.md` | **0** | **does not exist in this repo** |
| `docs/BOARD.md` | — | does not exist |

The eleven status lines are free prose, not a vocabulary — verbatim samples:

```
status: Spike report (build-session gate item #2 per projector-build-plan §3.6)
status: Plan (LOCKED — Decision 3 RESOLVED by spike fe14d67 + Option C ruling; ALL gates 1-6 closed…)
**Status:** approved, unscheduled. **Recommended owner:** the telemetry agent (queue clear).
**Status:** RULED, not built (2026-07-31). Punch list below; mostly reuse.
**Status:** BUILT 2026-07-30 (design filed 2026-07-29). Raised from live operation: three notices hit…
**Status: complete and green, not a description.** `iagent-mesh-sdk@68e28c0` (pushed) carries the…
```

Two syntaxes (`status:` and `**Status:**`), eight distinct shapes, none machine-readable. **This matters for the decision:** generation-from-headers is only as good as the headers, and today 80% of packets have none. The migration is the expensive part, and pretending otherwise would produce an ADR whose plan fails on contact.

*Correction to the framing this ADR was commissioned under:* state was described as spread across four artifacts including `sessions/*.md`. That directory does not exist here. The narrative half lives in conversation and in the packets themselves — which strengthens rather than weakens the case, since it means there is **one** durable written surface (`docs/plans/`) and it is unindexed.

### The precedent worth generalising

The most reliable cross-thread channel this project has produced is a **marker at the site**. `tests/test_cross_repo_contracts.py:98` declares `MIGRATION_MARKER = "EXPAND-PHASE-DUAL-KEY"`, and the guard at line 142 **fails if the marker is absent** while the dual-key state persists. That is not a comment — it is a marker whose absence breaks a test. When two threads collided on Engine D, board documents failed to cross and a sited marker did.

## Decision

**1. One board file per repo — `docs/BOARD.md` — that is an index and nothing else.**
Each item is at most three lines: what it is, status, where the detail lives. Status is a closed vocabulary: `open` · `in-flight` · `blocked-on-human` · `parked` · `closed`. Nothing else may appear in the status field; narrative belongs in the packet.

**2. Status lives in the item's own file; the board is generated from it.**
Every `docs/plans/*.md` carries a required machine-readable header:

```yaml
---
id:         <stable-slug>
status:     open | in-flight | blocked-on-human | parked | closed
owner:      agent | human | <thread-name> | <empty = unassigned>
blocked-on: <what, or empty>
closed-by:  <commit sha, or empty>
repo:       <repo name>
summary:    <one line — what the board displays for this item>
code-site:  <path[,path] the item lives at, or empty>
closed-by-note: <why closed-by touches neither packet nor code-site, or empty>
trigger:    <the condition that should un-park this item, or empty>
---
```

**AMENDED 2026-08-10 — three fields the original schema omitted while the design required them.**
`summary:` was load-bearing in the generator and absent from this schema: two declarations of one
schema, disagreeing, which is exactly the defect this ADR's fourth alternative rejects.
`code-site:` is what makes the marker seal implementable at all — §3 requires code-sited items to
carry a marker and acceptance tests for it, while the schema gave the test nothing to read. Both
are OPTIONAL: a packet with no natural code site declares none, and forcing a value would be
schema-satisfaction over truth. `closed-by-note:` is the attribution seal's honest escape hatch —
a real closure can legitimately touch neither packet nor code site, and a seal that produces false
failures on legitimate closures gets overridden, which kills it.

A script greps these and rewrites `BOARD.md`; a **drift test asserts the committed board matches what the headers produce.** Nobody maintains the board by hand, which is the only reason it will not rot. `closed-by:` being a commit sha matches the standing rule that a thing is closed when it is committed, not when someone says so — the sha *is* the evidence.

**3. Code-sited items carry a marker at the site.**
Any item with a natural code location gets a one-line marker naming its board id. The person touching the code must trip over it; that is a guarantee no document provides.

**4. Cross-repo items are named by an explicit `repo:` field, and the platform repo's board is canonical.**
This project has five repos and this month produced at least three genuinely cross-repo items. The alternative — a "foreign items" section per repo — was rejected: it is two homes for one item, which is the defect this codebase has retired twice.

**5. Multi-project scope: per-repo boards plus a small top-level index of projects and their current arc.**
Do not unify boards across projects. What is actually lost across projects is not items but *which arc a project is in and what it is blocked on* — three lines per project.

## Alternatives considered

**An issue tracker — rejected for this specific case, not in general.** State would live somewhere the work does not. Agents cannot read and write it in the same operation as the code; closure becomes a second act of bookkeeping rather than the commit itself; and it cannot be reviewed in the diff that closes it. The property that makes the filesystem board win here is that an agent editing code can update the board in the same change, and a reviewer sees both.

**A hand-maintained board — rejected.** Hand-maintained indexes rot, and a board that lies is worse than no board because it is trusted. Generation plus a drift test converts rot into a CI failure.

**A board per thread — rejected, with evidence.** This is what exists de facto today and it has already failed twice: each thread searched where its own board lived, and the only artifact that crossed was a marker in the code. Two boards are two homes.

**Status in the board rather than in the item — rejected.** It puts the authoritative value in the generated artifact, so the generator would have to preserve hand-edits, which is the two-writers shape. The item owns its own status; the board is a projection.

## Consequences

- *"Where are we"* becomes one file read, always current, maintained by nobody.
- Closure is a commit, and the sha in `closed-by:` is auditable after the fact.
- **The migration is real work and should be scheduled, not assumed:** 55 packets, 44 with no status, 11 with prose statuses in two syntaxes that must be normalised into a five-value vocabulary. Some of those eleven encode genuine nuance ("RULED, not built", "approved, unscheduled", "complete and green, not a description") that the closed vocabulary deliberately flattens — the nuance moves into the packet body, and whoever migrates must accept that trade consciously rather than discover it mid-sweep.
- A packet with no natural code site gets no marker, and that is fine — markers are for items someone will physically walk past.
- The first `BOARD.md` is generated from what is already in `docs/plans/`, which is most of this month's state, already written, merely unindexed.

## Acceptance — the seals this ADR commits to

- **Drift test:** the committed `BOARD.md` regenerates byte-identically from the packet headers. Broken-on-purpose to prove it bites.
- **Orphan test, both directions:** no packet in `docs/plans/` without a board line, and no board line without a packet. Either direction alone permits a lie; the pair is what makes the board an index rather than a list.
- **`closed-by:` shas must resolve in this repo.** The drift test only proves board-matches-headers; a packet marked `closed` with a fabricated, mistyped, or reverted sha passes every other seal while claiming evidence it does not have. This is the standing "committed is the evidence" rule applied to the field that carries the evidence — if the sha does not resolve, the claim of closure is unbacked and CI says so.
- **AMENDED 2026-08-10 — `closed-by:` must RESOLVE *and* be ATTRIBUTABLE.** The original seal
  required the sha to resolve. Its first real-world test found the hole: the seed board cited
  `116fff0` for `registration-wiring` — a sha that resolves cleanly and is **the wrong commit**
  (a follow-up litany fix; the closure was `9d93146`). It passed every seal while claiming
  evidence for a different change. **Existence is not attribution**, and this is the same species
  as grep-names-not-content and scan-vs-read: a check validating FORM where the claim is about
  CONTENT. The strengthened rule: the `closed-by` commit must touch the packet's own file or its
  declared code site. Imperfect — a commit can touch a file without closing the item — but it
  converts "a sha exists" into "a sha related to this item exists", which is where the lie lived.

- **A `?` in a committed board is a merge failure, absence-checked not presence-checked.** An
  unreconciled seed must be physically unable to land, rather than landing with honest-looking
  uncertainty that ages into apparent fact. The marker exists SOLELY TO BE CLEARED — it is never
  a permanent convention, and a board carrying one is unfinished by definition. Same design as
  `_KNOWN_UNPINNED` being empty by construction.

- **Vocabulary test:** every `status:` value is one of the five.

**AMENDED 2026-08-10 — a `parked` item requires `blocked-on:` OR `trigger:`.**
The July bank-rule — *every banked item gets a named trigger or deadline at bank-time* — was
decided six weeks ago, never indexed, and neither agent reached for it while writing this ADR.
It applies directly and its absence is why parked items rot.

`blocked-on:` and `trigger:` are **different things**: a blocked-on is a DEPENDENCY (something
else must finish), a trigger is a FIRING CONDITION (something must become true, possibly
nothing anyone is working on). `watch-dashboard` has a dependency. The range-type sloppiness
under ADR-0011 has a trigger — *fires when composition work begins* — and no dependency at all;
under a blocked-on-only schema it would be parked forever with an empty field, which is
indistinguishable from forgotten.

Enforced by the vocabulary test: a `parked` item with neither field fails. A sixth value is a merge failure, not a convention drifting.
- **Marker test:** for items declaring a code site, the marker is present at that site — the `MIGRATION_MARKER` shape, where absence fails rather than merely being noticed.

## KNOWN LIMITATION — the seals guarantee board-matches-HEADER, never header-matches-BODY

**Found 2026-08-10, by the limitation firing.** `retire-inline-task-loop`'s body was updated with
a completed security read (*outcome: cleanup, not a fix*, with the reachability evidence). Its
`summary:` header was not. So the board rendered the **pre-read** state — "the condition is now
met and nobody noticed" — and a reader summarising from the board reported an
undetermined-severity item that had in fact been determined hours earlier.

**Every seal passed.** Drift: the board matched the headers exactly. Vocabulary: `status: open`
is legal, and still correct. Attribution: no `closed-by` to check. The staleness lived in the one
place nothing compares — **between a packet's header and its own body.**

This is the board's own machinery exhibiting the failure the board exists to fix: *a record
updated by one hand does not propagate to another hand's working memory.* Third instance in one
evening, with the ceremony record reading "DID NOT COMPLETE" a day after completing, and the
gating manifest's cortex-bff clause.

**No automated fix is proposed here, and that is deliberate.** A generator that inferred `summary`
from the body would be a second decider — the thing §2's alternatives explicitly reject — and a
test asserting "the header reflects the body" would need to understand the body. The honest
repair is procedural and belongs at the point of edit: **whoever edits a packet's body checks
whether its header still describes it.** Recorded here so the limitation is a known property of
the design rather than a surprise the next reader rediscovers from a stale board line.

### AMENDMENT 2026-08-11 — the limitation's WORST case is a human ruling, and it has its own rule

> **A human ruling recorded in conversation is not recorded. The packet header is where it lands,
> and whichever agent ACTS on the ruling updates the header in the SAME COMMIT as the action.**

The limitation above was found on an agent-authored body. The sweep that followed found the
severe form: **four `blocked-on-human` lines describing decisions the human had already made.**

| item | header said | actually true |
|---|---|---|
| `work-deploy` | *blocked-on: your go — nothing technical* | the go was given; deployed in OBSERVE |
| `undeclared-routes` | *blocked-on: gate-class judgment per route* | ruled 2026-08-10 — the packet's OWN BODY contains the four dispositions |
| `transport-flip` | *11 stopping callers remediated + 4 repos unswept* | 11 remediated overnight; 3 of 5 repos swept |

**The asymmetry is the finding.** The board tracks agent work well, because an agent updates a
header in the commit that does the work. Human decisions arrive in **conversation**, get acted on
immediately, and nothing writes them back — so the column labelled "waiting on the human" silently
becomes *a list of things the human already did*. That is worse than a stale summary: it inverts
the board's most load-bearing signal, and it does so specifically for the reader who is trying to
find out what is owed to them.

`undeclared-routes` is the proof it is not a memory problem. Its body carries a section titled
**"RULED 2026-08-10 — the human's dispositions"** ending *"this item unblocks on the strength of
these four dispositions"*, and an agent had already **executed against that ruling** — filing
`dag-tools-broker-register-unauthenticated` into its integrity-write column and citing it as
inherited precedent. The ruling was received, believed, and acted on, and the header still said it
was awaited. **Acting on a ruling without landing it is the defect**, which is why the rule binds
the actor rather than the ruler: the human said it once, and that was their part.

**Operational consequence:** an agent that consumes a human ruling owes two writes, not one — the
work, and the header. And `blocked-on-human` items are swept periodically with a single question:
*has this actually been given?*

## Explicitly out of scope

- **Retrofitting headers onto all 55 packets** is the migration, not the decision. It should be its own scheduled item — and it is the first item the board will carry.
- **Automating status transitions** (e.g. flipping to `closed` when a referenced sha lands). Tempting and deferred: a generator that infers status is a second decider, and the packet's own header should remain the single authority.

## Verification note

Every count and quotation above was read on 2026-08-10 from this repo: 55 files in `docs/plans/`, 11 containing a status line, the eight verbatim status shapes, the absence of `sessions/` and `docs/BOARD.md`, and the `MIGRATION_MARKER` precedent at `tests/test_cross_repo_contracts.py:98,142`. **Unverified:** the equivalent state in the other four repos — this ADR proposes a per-repo board and a canonical platform board without having read what tracking artifacts those repos already carry, and that read should precede the migration item rather than the decision.
