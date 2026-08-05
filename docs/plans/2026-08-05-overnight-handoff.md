# Overnight handoff — the effect-failure surfacing is CLOSED, live; a provenance fork is open

Extends `2026-08-04-evening-handoff.md`. That packet's items 0, 1 and 2 are all executed and
witnessed on the cluster; read this one first.

## The epitaph

**The fix worked on the first live drive, and the live drive immediately found a second defect the
offline seals could not see — because every offline seal supplied its own provenance and therefore
agreed with itself.** The triage row appeared exactly as designed, in the right queue, and told the
operator that a *service* had approved the disposition.

## State

`master` @ `c2f33b2`, pushed. engine-a rolled onto `sha256:aca9e5a9…`, ONE pod Running, the
labelling code verified in the running image (`review_started_by` ×1, `approved_by` ×0). cortex-bff
unchanged (`8674c9c64c`) — nothing in this arc touched it. Topaz synced: 6 audiences, readback 6/6.

**Do not read a State block that is more than a few commits old** — the previous packet's was stale
within 25 minutes. Re-derive from `git log`.

## The train

- `38baf6f` the four packet additions + item 0, found reading item 2's own preconditions
- `9c2173c` `procurement` git-asserted; the whole disposition→queue map probed
- `5800458` **the seal that can AGE** + **emit, don't only detect** + `RESOLVED` not `DISPATCHED`
- `07fbe46` the effect-failure row said a SERVICE approved it — labelled truthfully
- `c2f33b2` the seal's verdict line must state what it actually measures

## What is now true, and how it was witnessed

### Item 0 — three defects where one had been reported

Notice A's "second defect" (an empty `procurement` audience) was never one bug. Reading the live
Topaz directory against `policy/task_grants.yaml` **before writing any code** found three:

```
procurement    granted LIVE, absent from git  -> one sync run from revocation
sourcing       granted NOWHERE at all         -> latent, waiting for a reviewer
promotion:DATA_ENGINEERING / access_grant:DATA_ENGINEERING
               asserted in git, absent LIVE   -> resolving to nobody right now
```

`task_grant_sync` PRUNES what git does not assert, so the fix that closed notice A was one routine
sync from being silently revoked under a green `+N, -1 revoked` line. **The ordering proved itself:**
`procurement` was committed first, and the sync then reported **`+3 relations, -0 revoked`**. That
zero is the whole argument — sync-before-commit would have read `-1`.

`_probe_disposition_audiences.py` closes the class structurally: it enumerates from the CODE's
declared `_DISPOSITION_QUEUE` (imported, never copied) rather than from live rows, because a queue
nobody has picked yet has no rows and is invisible to the row-walking probe. It reported 2 granted
and 1 empty **in the same run** — both directions witnessed at once, so no break-on-purpose was
needed to trust the green half.

### Item 1 — a harness that can AGE

`tests/test_expired_token_seal.py`. Time is a variable the file controls; ninety minutes is
manufactured, never waited for. The fake register **adjudicates expiry itself** from the presented
token and the clock, so the same token yields 200 at t=0 and 401 at t=90min and both arms are
witnessed before any later green is believed.

The stop condition bound exactly as written: mint-at-use had bricked up the original door, so the
staleness was re-introduced at the service mint. **Break-on-purpose then reproduced notice A's own
production error in 0.45 seconds** — `access denied (401) registering pcn dispatch task
'M32-A-WITNESS:NSR01L30NXT5G' … failing (state released)` — and the source was restored
byte-identical.

**The break also caught a defect in a guard, which is the entire argument for doing it.**
`test_no_credential_rides_the_journaled_payload` stayed GREEN while a credential rode the payload:
it checked only the TOP level, and the regression put the token where it would really go — nested
under `human_task`. The sibling assertion in `test_dispatch_driver` was top-level too. Both now walk
the whole structure and match a family of credential-shaped names.

### Item 2 — emit, don't only detect (WITNESSED LIVE, GREEN)

A dispatch that fails TERMINALLY after an approval files a triage row before re-raising. The fork
was resolved as ruled — **(b)**, `dispatch_failure:<compartment>`, granted in the same commit,
verified non-empty with negative controls **before** the first emission:

```
dispatch_failure:SUSTAINMENT -> ['bob@example.com']
dispatch_failure:            -> []
dispatch_failure:NOSUCH      -> []
```

The live drive used a **genuine** latent defect rather than an injected one: `dispatchAltSourcing`
routes to `sourcing`, which grants nobody, so the register answers 422 and the dispatch dies
terminally. `EFFECTFAIL03`, all six legs GREEN, with the surviving two parts landing in bob's
qualification queue as the positive control:

```
task_id  : dispatch-failure:EFFECTFAIL03:NSR01L30NXT5G
audience : dispatch_failure:SUSTAINMENT      recipient: bob@example.com   status: pending
reason   : DISPATCH_FAILED_AFTER_APPROVAL
cause    : cortex-bff register … rejected (422) — failing TERMINALLY (release), not retry-park
```

`DISPATCHED` → `RESOLVED` + `dispatch_enqueued`, observed on the wire, not inferred from the diff.

---

# NEXT SESSION — in this order

## 1. ~~THE OPEN FORK~~ — RULED AND BUILT (`90464e7`); LIVE RE-VERIFICATION PENDING A ROLL

**Ruling: thread the `/act` caller, with the field semantics settled first — because the fork as
framed below slightly misstated what was broken.** `requested_by` was never lying about its own
meaning; it faithfully records who STARTED the review. The lie was in what readers INFERRED, because
no field carried the decision's actor at row level. So nothing is renamed: **the actor starts
existing**, additively, and `requested_by` keeps its meaning as provenance-of-initiation. That is
(b)'s outcome with (a)'s safety — no field changes meaning, one field starts existing everywhere it
should have.

**The one open question was verified before any code: the resolution payload does NOT carry the
actor.** `/act` builds `decision = {"overrides": …}` and `submit_decision` resolves exactly that.
But the identity is present AND authorized right there — `check_can_act(audience,
current_user.authz_id)` runs immediately above — so this was a payload-schema addition, not an
authz change. `_build_bulk_decision` reads only `overrides`, so the new key rides through validation
untouched.

**Landed:** `/act` stamps `acted_by` from the authenticated identity (never the body) → the workflow
reads it off the resolved decision → the fan-out carries it → it lands on **ordinary dispatch rows
as well as triage rows**, because the misattribution was never triage-only (EFFECTFAIL02's two
surviving parts carried it too).

**Named `approved_by` on the row, NOT `acted_by`, and the difference is load-bearing.** The
projection already has an `acted_by` COLUMN meaning "who resolved THIS row", which must stay NULL on
a freshly-registered dispatch task until its assignee acts. Two meanings behind one identifier is
the collision this repo already documents for `pcn_disposition`. Rides in `payload` (pass-through
jsonb): additive, no migration.

**DEPLOY IS ORDER-INDEPENDENT — no dual-key interval needed.** engine-a first: `acted_by` is absent
from the decision and falls back to `approver` (the old, misattributing behaviour — degraded, not
broken). cortex-bff first: it sends a key engine-a's validator ignores. Both halves are safe alone,
which is why this did not need expand/contract despite touching two services.

**PENDING:** 49/49 offline, but the live re-drive needs BOTH services rolled onto `90464e7`. Not
done because engine-a was being actively rolled for unrelated ADR-0038 telemetry work at the time.
Re-run `_seal_effect_failure_surfacing.py` (fresh notice) and confirm `payload.approved_by ==
alice@example.com` on **both** the triage row and the surviving `pcn_disposition` rows.

<details><summary>The fork as originally framed (superseded, kept for the reasoning)</summary>

**Decide this before touching the code it governs.** It is stated here rather than settled at 4am
for the same reason the last packet stated its fork: that is how `promotion:DATA_ENGINEERING` got
seeded to nobody for three weeks.

**The defect, witnessed live.** `_run_grouped_human_await` fans out with `requested_by=approver`,
and `approver` is `request["approver"]`, which `start_review` stamps from **whoever STARTED the
review** — the sensor's service identity in the canonical flow. So on `EFFECTFAIL02`:

```
dispatch-failure row   requested_by: svc:review-starter   summary: "Approved by: svc:review-starter"
grouped review row     requested_by: svc:review-starter   acted_by:  alice@example.com
```

The approving human was recorded **one row away** the whole time. This **predates this arc** — the
ordinary `pcn_disposition` dispatch rows carry the same wrong value — and it makes the notice-A
fix's own claim ("requested_by still names the human") false in the auto-started flow.

**Already done:** the row no longer lies. `payload.approved_by` → `payload.review_started_by`, and
the summary names the initiator and tells the operator the approver is the grouped review's
`acted_by`. A lookup instead of a dead end.

**Still open — the options:**

- **(a) Thread the `/act` caller through `submit_decision` into the fan-out.** Mechanically small,
  and the trust model already permits it: cortex-bff stamps identity from the token and Restate
  trusts cortex-bff, which is exactly how `approver` reaches `start_review` today. Cost: it changes
  the MEANING of `requested_by` on every dispatch task, a field cortex-bff REQUIRES on register and
  other surfaces already read. That is a semantics migration across consumers, not an edit.
- **(b) Add a NEW field (`approved_by`) alongside `requested_by`,** leaving the existing field's
  meaning alone. No migration; costs a field whose absence on old rows must be handled honestly.
- **(c) Leave it as a read-side join** — the projection already has `acted_by` on the grouped row,
  keyed by notice. Zero write-path change; costs every consumer a join, and the effect-failure row
  is exactly the surface least able to perform one.

**Architect's lean, offered not imposed: (b).** It is the only option that makes the row TRUE
without a semantics migration on a field three surfaces already consume, and "add the honest field
rather than redefine the ambiguous one" is the same move that separated provenance from
authorization in the first place. Whichever wins, the rule that applied to the last fork applies
here: **verify the value is non-empty on a real auto-started review before trusting it**, because
the whole defect is that a plausible-looking identity was sitting in that field all along.

</details>

## 2. `sourcing` grants nobody — and it is now load-bearing for a test

Deliberately NOT granted (who buys alternate sourcing is a ruling, and policy does not grow to make
a demo path work — the same posture that priced Carol). Two consequences to hold together:

- A reviewer choosing alternate sourcing today gets a dispatch that reaches no one. It is now
  VISIBLE (a triage row) rather than silent, which is a strictly better failure but still a failure.
- **The live seal uses that gap as its fault injector — and the seal now says so itself.** Relying
  on the eventual fixer knowing this file exists was never a control, so **LEG 0 asserts its own
  precondition**: it resolves `sourcing` through the same directory registration uses and exits
  INCONCLUSIVE **with re-pointing instructions** the moment it is no longer empty. Granting
  `sourcing` therefore produces a self-announcing failure instead of a green that means nothing.
  Unreachable Topaz returns `None`, never `[]` — "nobody is granted" and "I could not find out" are
  different answers, and collapsing them would let an outage read as a healthy injector. Verified to
  discriminate before being trusted: `sourcing -> []`, `qualification -> ['bob@example.com']`, same
  call.

## 3. ~~`promotion:` / `access_grant:` resolve to NOBODY~~ — CHECKED AND CLEAN, no action

Both were asserted in git and absent from live Topaz; the sync added them (`+3 relations`). The
worry was stranded rows — the orphaned-audience class is exactly "visible but unactionable", and the
drift had been live for an unknown period. Checked rather than assumed:

```
dispatch_failure:SUSTAINMENT    kind=extraction_refusal   rows=2   actors=1
disposition_review:SUSTAINMENT  kind=grouped_review       rows=1   actors=1
procurement                     kind=pcn_disposition      rows=1   actors=1
qualification                   kind=pcn_disposition      rows=7   actors=1

CLEAN: 4 live audience(s), every one grants at least one actor.   (exit 0)
```

Nothing was ever queued against those two keys, so nothing was stranded. Closed. (The two
`dispatch_failure:SUSTAINMENT` rows are `EFFECTFAIL02`/`03` from the live drives, both routable —
the probe's own positive control that the new audience works end to end.)

## Also carried (unchanged owners)

- **Workflow 2 ceremony** — `mesh:dispatchDispositions` granted to the pipeline identity, landed
  TOGETHER with the trust-table promotion as ONE governed decision. Still declared in no policy file.
- **The cross-surface probe** — the detection sibling of item 2's emission, and now more valuable
  than before: the emission covers dispatches that fail TERMINALLY, and says nothing about one that
  never ran at all. Positive condition: *any approval whose effects never landed*.
- **Registry startup invariant**, **Restate retry policy**, **declared provenance
  (`origin: live|witness|synthetic`)** — unchanged.
- **Carol** — still optional and priced. Not taken.

## Rules filed today (AGENTS.md)

A hand-grant that clears an incident is a MITIGATION; the commit is the fix (check BOTH drift
directions) · coverage over the audiences that EXIST is not coverage over the audiences code can
PRODUCE.

Earned tonight but not yet written up, because each wants its own sentence rather than a paragraph
in a packet:
- **A guard that never failed has not been shown to guard anything** — the top-level `user_jwt`
  check passed for a year over a payload it could not see into.
- **A seal that supplies its own provenance agrees with itself.** Every offline test passed
  `requested_by` in; only the live drive asked the system what it actually had.
- **A test asserting the wrong claim is worse than a missing test** — LEG 6 went RED against a
  system that could not have satisfied it, and the fix was to the seal, not the code.

## Operational notes

Everything in the previous packet still holds. Additions:

`kubectl rollout restart` leaves BOTH pods Running for a while, and the old one still serves —
driving a test in that window can hit either image and the result is ambiguous, not wrong-looking.
Wait for the pod COUNT to return to one, then check digest + Running + grep the code in the image.
Git Bash mangles POSIX paths in `kubectl cp` / `exec` args (`/app/...` becomes
`C:/Program Files/Git/app/...`) — use PowerShell for kubectl, or `MSYS_NO_PATHCONV=1`. `kubectl cp`
also rejects a Windows absolute source path in the same argument position; `cd` to the directory
first. PowerShell here-strings mangle multi-line SQL/Python into `kubectl exec` — write the script
to a file and `kubectl cp` it. And `Select-Object -Last 30` on a pytest run **silently truncates the
failure list** — it cost a bogus 44-vs-41 comparison until the runs were redone with full capture.

## Verification ledger

- Affected offline suites: **35/35** (dispatch_driver, expired_token_seal, grouped_review_workflow)
  and **47/47** including promise_name_seal + review_identity_from_artifact.
- Full-suite adjudication, before/after by NAME (not by count):
  - BEFORE (clean worktree @ `9c2173c`): 41 failed / 912 passed / 1 error
  - AFTER (main repo, all changes): 44 failed / 921 passed / 1 error
  - Delta: **exactly 3, all `OSError [WinError 1920]`** traversing
    `agent_fleet/restate_analyst/.venv.wsl/lib64` — a broken WSL symlink present in the main tree
    and absent from a fresh worktree. Not a content finding. **Zero regressions in the blast
    radius.** The +9 passed are this arc's new seals.
  - The baseline six + 1 error are all present and named (entitlement-source ×2, endpoint-gating ×3,
    llm_utils, mem0 error). The other ~35 are `routing/*`, which the historical "788/6/1" invocation
    did not collect — that number is NOT comparable to a `pytest tests/` run, and treating it as a
    baseline is how tonight's first comparison went wrong.
- Live: `EFFECTFAIL03` all six legs GREEN, on `sha256:aca9e5a9…`, single pod, code verified in image.
