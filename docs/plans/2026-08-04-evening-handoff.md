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

> **SUPERSEDED 2026-08-05 — this block was stale within 25 minutes of being written.** An ADR-0038
> langfuse-v4 telemetry train landed on `master` between 19:08 and 22:31 the same evening
> (`cb16a59`…`15f5cd7`, 14 commits). `f8a3dc2` is still an ancestor, so nothing here was reverted,
> but any "current state" read from this block is wrong. A handoff's STATE section has a shelf life
> measured in commits, not in days — re-derive it from `git log`, never quote it.

**Baseline provenance (addition 4).** The 788/6/1 numbers and the adjudication *"none in this diff's
blast radius"* come from `0c222c3`'s commit message, which enumerates the six by name. **Not**
`5fb2b15` — that commit is the orphaned-audience probe (`tests/sandbox_e2e/_probe_orphaned_audiences.py`),
which is a different instrument and is cited separately below. The adjudication method was: run the
full offline suite, diff the failure SET against the previous run's, and confirm each survivor's
module is outside the diff's touched files. A successor inheriting the claim should re-run that
comparison rather than trust the count — the count alone cannot distinguish "same six" from "six".

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

## 0. FOUND 2026-08-05 — `procurement` is live-only and the next sync DELETES it

Discovered while reading preconditions for item 2, before writing any code. Live Topaz
`task_audience`/`actor` versus `policy/task_grants.yaml`:

```
disposition_review:SUSTAINMENT   git ✓   live ✓
qualification                    git ✓   live ✓
procurement                      git ✗   live ✓     <-- last night's fix, UNCOMMITTED
promotion:DATA_ENGINEERING       git ✓   live ✗
access_grant:DATA_ENGINEERING    git ✓   live ✗
```

`task_grant_sync` **prunes** `task_audience` actor relations not asserted in git. So the grant that
closed notice A's *second* defect — `procurement` resolving non-empty — is one sync run away from
being revoked, which would restore the exact defect that was just closed, silently, under a green
`synced: +N, -1 revoked` line.

This is the same drift-closure the `disposition_review:SUSTAINMENT` comment block already documents
("live in sandbox Topaz from M1 but never committed"). Second instance; the shape is now a class:
**a grant applied by hand to fix an incident is unfinished until it is asserted in the file its own
sync prunes from.**

Ordering is forced, and it is the reason this is item 0: **commit `procurement` FIRST, then sync.**
Item 2's new audience also lands through that same sync, so running it before this is committed
would take `procurement` down as collateral of the fix for its sibling defect.

The other direction (`promotion:` / `access_grant:` git-asserted but absent live) is a SEPARATE
question and is NOT resolved by the same edit — it means the sync has not been run in some time, and
`promotion:DATA_ENGINEERING` resolving to nobody is the very orphan this packet already cites as a
cautionary tale. Confirm with `_probe_orphaned_audiences.py` before assuming it is benign.

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

### The seal's STOP CONDITION (addition 2) — read before trying to make it red

`0c222c3` already landed mint-at-use, so **an expired *user* token no longer reaches the dispatch
path at all** — the field was deleted from the journaled payload. Do not spend the night trying to
manufacture the original defect through its original door; that door is bricked up, and failing to
open it is the fix working, not the seal failing.

The staleness must be re-introduced at **the point where a credential is still consumed**, which
today is the service mint itself (`utils.service_identity.mint_service_token`, bound at module
scope in `dispatch_driver` precisely so a test can reach it). Stub it to return a token that is
expired at use, and drive the real register call.

**If the red turns out to be unreachable, that is a FINDING, not a failure to build the seal.** It
would mean the fix closed the class rather than the instance, and the seal's claim changes
accordingly: it becomes a guard against *regression to a journaled credential*, anchored to the
payload shape rather than to token expiry. Write the finding down and re-anchor. What must not
happen is a seal that is quietly weakened until it goes green, or a night spent at 3am asking "why
can't I make this go red."

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

#### ARCHITECT'S LEAN (addition 1) — (b), and here is why the other two are already excluded

The fork was written neutrally, but the arc's own rulings already argue a position, and leaving it
fully open invites the next session to relitigate settled reasoning.

The workflow-1 dispatch-gate ruling established: *the reviewer's job ends at the decision; effect
execution is the pipeline's own responsibility under its own identity.* By that light —

- **(c) is out.** It routes an *operational* failure to a person selected by *decision* provenance,
  and per-user routing is a new pattern nobody ordered.
- **(a) has the same conflation one notch softer.** alice cannot fix a 401 or an ungranted audience;
  handing her the failure converts "did my decision execute?" anxiety into a task she can only
  escalate.

That leaves **(b)**, whose stated risk — an ungranted audience routes to NOBODY — is *exactly the
class this incident just taught us to handle*. So it is handled by construction:

> **Lean: (b) `dispatch_failure:<compartment>`, grant-in-the-same-commit, non-empty verified before
> the first emission. If the session finds a reason to deviate, the reason gets written down BEFORE
> the deviation.**

The grant lands through the rails in the **same commit** as the emission code, and non-empty
resolution is the definition of done — not a follow-up. This preserves a fresh head's veto while
sparing it the re-derivation.

#### Post-roll freshness is a STEP, not a war story (addition 3)

Item 2 modifies the executor and rolls engine-a again. Tonight's corpse-grep earns promotion out of
the operational-notes footer and into this item's protocol:

> **After any roll: the pod-identity check is `digest` + `Running`, never `kubectl rollout status`
> alone.** List all pods for the selector and check for `Terminating`; a `-First 1` handed back a
> corpse. Then read the digest off the *running* pod and compare it to the one you pushed.

Executed, not remembered.

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
