# Evening handoff — notice A closed; the effect-failure surfacing is next

Extends `2026-08-04-m32-handoff.md` (the morning train). That packet's carried items are all
resolved or re-owned below; read this one first.

## The epitaph, for anyone reading this directory cold

**The first human-driven approval found the one bug no machine-latency witness could reach — and
fixing it unmasked a second defect behind it.** That is why the suite now needs *manufactured*
staleness, and why *serial failures mask* is a filed rule.

## State

`master` @ `f8a3dc2`, pushed. engine-a rolled onto `sha256:7fa91164…` with the mint-at-use fix
verified IN the running image (including a live mint returning a real token). cortex-bff on
`5c664b4f8d`. Branch gate green; offline suite 788 passed / 6 failed / 1 error — the six are the
long-standing baseline (entitlement-source ×2, endpoint-gating ×3, llm_utils, mem0 error), none in
any of today's blast radii.

## The train, in order (evening half)

- `02209da` M3.1 row-split corrected — 2 triage rows were witness fixtures, not real refusals
- `c059bcc` seed endpoint de-pcn'd; **seed scripts are MECHANISM** (scan widened, proven to bite)
- `13d98b3` notice A root cause filed — mint-at-use, **not** a longer-lived credential
- `0c222c3` **the fix** — mint at use; credential removed from the journaled payload
- `84f5b1a` rules — a durable journal is a TIME MACHINE; a guard's anchor is part of its claim
- `f8a3dc2` notice A closed two-of-two; serial-failures-mask; the disclosure framing

## Notice A — CLOSED, two-of-two

```
completion  M32-A-WITNESS:NSR01L30NXT5G    success   (was failure)
            M32-A-WITNESS:MPN-NEEDSREVIEW  success   (was failure)
projection  grouped_review   disposition_review:SUSTAINMENT  approved  alice
            NSR01L30NXT5G    qualification                   pending   bob
            MPN-NEEDSREVIEW  procurement                     pending   bob
```

Both `dispatched` markers present. Sequence: roll → **digest changed** (`7fa91164` ≠ `b21c7d47`) →
fix + live mint verified in the RUNNING image → **purge the spent failures, never mint a new key** →
re-fire under the SAME identity key, both parts.

Three defects on one notice: the stale credential, the empty `procurement` audience it was masking,
and the `DISPATCHED` status lie.

---

# NEXT SESSION — in this order

## 1. The expired-token seal FIRST (red-first, and it is the regression gate for item 2)

Build it **before** the triage-mint, because it is the gate for the very path item 2 modifies, and
because it must be shown RED against the *current* code — proving it catches the original defect —
before anything is landed behind it.

- Inject a deliberately expired / near-expiry token and resolve a review with it. **Manufacture the
  staleness; do not wait ninety minutes for it** (the kill-seal move).
- The suite's blind spot this closes: every automated witness resolves at MACHINE latency, so a
  defect whose trigger is ELAPSED TIME is structurally invisible to it. Twelve M3.2 seals passed
  green over notice A's bug.
- Note the mint is now stubbed in three suites (`test_dispatch_driver`, `test_grouped_review_workflow`,
  `test_promise_name_seal`) — this seal is the one place that must NOT stub it away.

## 2. The triage-mint + the status rename

**A review can currently read `approved` while its effects died silently.** That is the most
consequential dual-surface lie the arc has produced: a human believes their decision executed and
nothing anywhere disagrees.

- **Emit**, don't only detect: a dispatch that terminally fails AFTER an approval mints a triage row.
  The `extraction_refusal` shape exists and is proven — *"approved but effects failed"* is a refusal
  one stage later.
- **Rename in the same commit:** `DISPATCHED` → `RESOLVED` with `dispatch_enqueued: N`.
  `ctx.object_send` is fire-and-forget, so the workflow *cannot* know delivery. A stronger claim
  requires awaiting outcomes — a design change nobody has ordered.

### THE OPEN FORK — decide this FIRST, it is the item's opening question
**Which audience does the minted triage row belong to?** "Who owns effect-failures" is a policy
question with the same shape as every audience decision this arc has made deliberately — and
deciding it at the end of a long day is exactly how `promotion:DATA_ENGINEERING` got seeded to
nobody and sat unactionable for three weeks.

- **(a) The original review's audience** (`disposition_review:<compartment>`) — the people who made
  the decision learn it did not take effect. Zero new policy surface. Risk: conflates *deciding* with
  *operating*, and a reviewer may be unable to fix an infrastructure failure.
- **(b) A new operator audience** (e.g. `dispatch_failure:<compartment>`) — correct by ownership;
  costs a new audience + actors, and an ungranted one routes to NOBODY (the failure mode this very
  incident produced twice).
- **(c) The approver specifically** (`acted_by`) — most precise recipient, but per-user routing is
  not how any audience works today and would be a new pattern.

Whichever wins: **verify the audience resolves non-empty BEFORE the first emission**, not by watching
it fail. That is the serial-failures-mask rule applied to its own fix.

## 3. Carol — OPTIONAL AND PRICED, no ruling needed

A third dispatch persona would strengthen the multiplayer moment (alice reviews → two distinct
dispatch faces). **Cost: a seeded user in `users.yaml` PLUS its persona/domain cell.** Not taken
tonight because the entitlement model is policy, and policy does not grow to make demos prettier.
Take it only when a demo script actually wants three faces.

## Also carried (unchanged owners)

- **Workflow 2 ceremony** — `mesh:dispatchDispositions` granted to the pipeline identity, landed
  TOGETHER with the trust-table promotion as ONE governed decision. Note: the capability is declared
  in **no** policy file today; nothing has been granted.
- **The cross-surface probe** — detection sibling of item 2's emission. Positive condition: *any
  settlement that did not transit `/act`*, and now its twin: *any approval whose effects never landed*.
- **Registry startup invariant** and **Restate retry policy** — from the morning packet, unchanged.
- **Declared provenance** (`origin: live|witness|synthetic`) replacing the unenforced `witness_*` path
  convention.

## Rules filed today (AGENTS.md)

A probe's OUTPUT is part of its claim · a ruling made in CONVERSATION is unshipped until committed ·
projection and journal are two surfaces of one state · code renames orphan JOURNALS · provenance
comes from provenance-bearing fields, never classification fields · a RED result lies more
dangerously than a green one · a stored authz value re-checked at action time is a migration surface ·
a durable journal is a TIME MACHINE · a guard's ANCHOR is part of its claim · a status field asserts
what its author WITNESSED · seals resolve at MACHINE latency · **serial failures mask**.

## Operational notes that live nowhere else

`kubectl rollout status` reporting success does **not** mean your pod selector found the new pod —
list all pods and check for `Terminating`; a `-First 1` handed back a corpse tonight. PowerShell's
`Set-Content -Encoding utf8` writes a BOM that breaks `json.load` — use
`[System.IO.File]::WriteAllText` with `UTF8Encoding($false)`, or read with `utf-8-sig`. Commit
messages go through `git commit -F <file>`; here-strings mangle. `restate invocations list` shows
LIVE invocations only — completed and failed ones are in `sys_invocation_status`, and payloads in
`sys_journal.entry_json`.
