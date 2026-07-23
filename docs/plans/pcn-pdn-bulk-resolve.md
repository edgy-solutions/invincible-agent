# PCN/PDN bulk-resolve — the one substrate extension (grouped review: 1 approval resolves N items)

The PCN/PDN part-obsolescence workflow (ADR-0029 Case-2 exemplar, `2b5615f`) needs **zero new
workflow-model step kinds** — the five slices are the whole model. Its net cost is **one narrow
substrate extension**: a HumanTask that a single approval resolves across N items (a grouped
review), keyed so execution stays per-item. This doc + `workflow_bulk_resolve.py` is the pure core
of that extension, in the same rhythm as the slice cores.

## 0. The dual of the Slice-5 join

Slice 5's `evaluate_join`: **N approvals gate 1 step** (fan-IN of approvals onto one grant).
Bulk-resolve: **1 approval resolves N items** (fan-OUT of one human action onto many promises).
They are mirror images and sit side by side — both are HumanTask lifecycle cores, both pure, both
take the authz/relevance decisions as INPUT.

## 1. Governing ruling — approval grain ≠ execution grain (banked)

**Approval grain is a UI decision the backend must serve; execution grain is per-item.** One human
action resolves N promises (the approver clicks once), but each item executes independently —
idempotent on `notice_fingerprint × mpn`, over its own resolved subject, retryable in isolation. So
the core produces **N per-item resolutions from one decision**, each carrying its own idempotency
key. (The idempotency *substrate* — VirtualObject-on-composite-key vs a Postgres dedup table — is
the one open architect call; it gates the dispatcher, not this core. Lean: VirtualObject-on-composite,
one consistency domain.)

## 2. The funnel — stack of reducers, each measured by removal (instrument it)

A notice fans out to N part-items; most die before any human sees them. The stack:

```
items ──filter(relevance)──▶ ──auto-dispose(FYI lane)──▶ ──group(residue → approver)──▶ resolve
```

- **filter**: below a relevance floor → dropped (not affected). Not a disposition.
- **auto-dispose**: relevant + low-stakes + system-confident → an FYI lane, no human.
- **residue**: what a human must actually decide.

**Seal 1 — honest funnel (auto-archived items stay COUNTABLE).** Nothing vanishes: the counts at
every stage sum to the input (`filtered + auto_disposed + residue == input`). Auto-disposed items
are inspectable, not hidden — silent shrinkage at business scale is the funnel telling a comforting
lie. `run_funnel` returns every bucket, not just the residue.

## 3. needs_review is `resolved_via` for the data layer — weak extraction cannot take an automated path

doc-tools' PCN/PDN extraction (`../doc-tools`, `ce168fb`) flags `needs_review: true` when a part's
MPN extraction is uncertain (the vision/OCR read is shaky). That flag is **provenance strength for
the disposition** — the exact analogue of Slice-4's weak-provenance seam one layer down. A
disposition taken over a part whose MPN we're not sure we read is **weak provenance seeding durable
action** — Slice-4 laundering wearing a part number.

Two structural rules (both sealed):
- **A needs_review item may NOT take an automated lane** — never filtered, never auto-disposed. You
  cannot trust an automated relevance/disposition decision on an MPN you're unsure you read
  correctly, so it is forced into human residue. (`run_funnel` routes it to residue regardless.)
- **A resolution CARRIES the needs_review flag forward, visibly** — the human approves an INFORMED
  disposition, and the durable `ItemResolution` (and the effect it dispatches) records that the
  underlying extraction was uncertain. A disposition approval never silently launders an unverified
  extraction.

## 4. Grouped review is per-approver-filtered (existence-oracle at batch scale) — Seal 2

The batch a given approver reviews = `residue ∩ {items this approver can see and act on}`. Two
approvers on the SAME notice get **different-sized batches**, correctly. An item an approver cannot
act on is not in their batch and does not leak observer-facing. This reuses Slice-3's
`observer_view` / `audit_record` split: the approver sees their batch (`observer_view`); the
withheld items are the `audit_record` (countable for audit, never surfaced to this approver). The
discriminating seal: approver A and approver B over one notice see batches that differ, each
excluding what the other exclusively owns — proven on the same input, both sides.

## 5. Accept-all-with-exceptions + capture-why is structural (ruling #5)

The review UI is a default-with-exceptions grid: accept the system-proposed disposition for every
row unless overridden. An override MUST carry a reason — enforced by the **type** (`Override` has no
default reason), so capture-why cannot be skipped. An item with no proposed disposition and no
override cannot be resolved (you can't dispatch an effect with no disposition — refuse honestly).

## 6. The pure core — `workflow_bulk_resolve.py`

- `run_funnel(items, *, relevance_floor, auto_dispose_when) -> FunnelResult` (§2, §3-rule-1; Seal 1).
- `grouped_review(residue, approver, *, can_act) -> ReviewBatch` (§4; Seal 2).
- `resolve_batch(batch, decision, *, notice_fingerprint) -> list[ItemResolution]` (§1 execution
  grain, §3-rule-2 carry-forward, §5 capture-why).

Pure — no Restate, no Topaz. `can_act` (Topaz), relevance scores + `needs_review` (doc-tools), and
the system-proposed disposition are all INPUTS. The enforceable innovations are the four seals.

## 7. Driver + seals (spec — deploy-gated)

`_run_definition` registers the grouped HumanTask; the dispatcher (per-item, idempotent, OUTSIDE
the workflow graph) emits N invocations on resolve. Composed-path seals, red-first: the funnel
conservation (Seal 1), the per-approver discrimination (Seal 2), the needs_review lane-block +
carry-forward (§3), and capture-why (§5). Depends on: the pcn class vocabulary + registered verbs
(the disposition effects as mesh verbs with endpoints), and the idempotency-substrate ruling.
