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
owner:      agent | human | <thread-name>
blocked-on: <what, or empty>
closed-by:  <commit sha, or empty>
repo:       <repo name>
---
```

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

- **Vocabulary test:** every `status:` value is one of the five. A sixth value is a merge failure, not a convention drifting.
- **Marker test:** for items declaring a code site, the marker is present at that site — the `MIGRATION_MARKER` shape, where absence fails rather than merely being noticed.

## Explicitly out of scope

- **Retrofitting headers onto all 55 packets** is the migration, not the decision. It should be its own scheduled item — and it is the first item the board will carry.
- **Automating status transitions** (e.g. flipping to `closed` when a referenced sha lands). Tempting and deferred: a generator that infers status is a second decider, and the packet's own header should remain the single authority.

## Verification note

Every count and quotation above was read on 2026-08-10 from this repo: 55 files in `docs/plans/`, 11 containing a status line, the eight verbatim status shapes, the absence of `sessions/` and `docs/BOARD.md`, and the `MIGRATION_MARKER` precedent at `tests/test_cross_repo_contracts.py:98,142`. **Unverified:** the equivalent state in the other four repos — this ADR proposes a per-repo board and a canonical platform board without having read what tracking artifacts those repos already carry, and that read should precede the migration item rather than the decision.
