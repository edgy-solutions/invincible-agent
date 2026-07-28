# can_act — the Topaz binding, RECONCILED onto `task_audience` (live session reads this)

> **RECONCILED 2026-07-24 — `disposition_item` RETIRED.** Reading work's git-rails policy repo
> (`C:\tmp\iagent-policy`) before building revealed that a grouped review IS a HITL task, and "who may
> act on a class of HITL tasks in a compartment" is EXACTLY the existing Topaz **`task_audience`** type
> (`task_grants.yaml` → `task_grant_sync.py`; manifest: `task_audience { relations: actor: user |
> group#member; permissions: can_act: actor }`). The bespoke `disposition_item` type + rego this doc
> originally proposed were REINVENTING it — a second mechanism answering "who may act" on the
> entitlement plane, the last place that should ever happen (single-authz-decider). It died as a diff,
> never deployed. Everything below is the `task_audience` form; the old `disposition_item` shape is gone,
> not half-retired.

> **SPLIT 2026-07-27 (`feat-review-starter-identity`) — INITIATE separated from REVIEW; `NO_ENTITLED_ACTION`
> retired.** The first non-human initiator (`svc:review-starter`, the extraction→review sensor) exposed a
> conflation baked into the design below: `start_review` gated its residue filter on the INITIATOR's
> `can_act` against this `pcn_disposition:<compartment>` audience — a coarse initiator check wearing a
> per-item costume (it checked a FIXED audience, ignoring the item), invisible while `approver == reviewer`
> (M1). Now split: this doc's `task_audience` binding is the **REVIEWER** gate ONLY, enforced downstream at
> the HITL task layer (`register_task` materializes one row per audience actor; `/act` re-checks). The
> **INITIATOR** is gated separately by a CAPABILITY — `can_invoke(mesh:startReview)` (`capability_grants.yaml`,
> ADR-0029 sixth namespace) — because starting a review INVOKES a verb, it does not ACT on a task; an
> audience-membership grant for the initiator would be a false statement in the fifth namespace (membership
> IS recipiency). **`NO_ENTITLED_ACTION` is GONE, split in two:** the initiator-plane deny is
> **`NOT_ENTITLED_TO_INITIATE`** (BFF → 403; the sensor surfaces it as a failed run); the reviewer-plane
> zero-entitled-actors case — which the audience gate below used to catch ONLY because approver==reviewer —
> is now **`NoEntitledRecipients`**: `register_task` refuses a zero-recipient task (BFF → terminal 422 →
> workflow fail-and-release, never park, the join-that-can-never-complete closed on the reviewer plane).
> Everything below reads as the M1 record + the audience-rule reasoning (still valid for the reviewer gate).

The `can_act` seam is the ONE piece of the PCN loop that cannot be sealed offline (it needs the live
authz layer). But "can't be sealed offline" ≠ "undesigned": an authz question answered at the console
under demo momentum becomes the entitlement model by accident. So the SHAPE is decided here; the live
session BINDS and OBSERVES against work's mechanism, it does not invent.

**The binding:** audience key `pcn_disposition:<compartment>` where the **compartment IS the domain**
(`pcn_disposition:SUSTAINMENT`) — `<task_kind>:<compartment>`, work's existing shape. A caller may act
iff they are an `actor` of that audience (granted directly OR via `group#member`), permission `can_act`.
`can_act_via_topaz` is a direct Topaz DIRECTORY check (`POST /api/v3/directory/check`), deny-by-default
(an ungranted audience is "object not found" → deny). Grants arrive by the git-rails seed CronJob
(`task_grants.yaml`), never hand-surgery. The domain is the compartment half of the key — pcn-ness lives
purely in the key VALUE, and the type covers every future grouped review of any kind (more generic than
the invented type, per the birth rule's deeper form).

## Three decisions (settled now)

**1. A `can_act` DENY excludes the item from the approver's batch (redaction), not visible-but-
unactionable.** Already the implemented behavior — `grouped_review` (Seal 2) computes
`residue ∩ {items this approver can act on}`; denied items go to `audit_withheld` (countable for
audit, NEVER surfaced to this approver). The grouped review IS an `observer_view` computed per-approver
— the Slice-3 finding, one level up. Two approvers on one notice correctly get different-sized batches.
Recorded so the "visible-but-greyed-out" answer (which looks reasonable at 11pm) is not adopted live.

**2. ZERO entitled approvers fails LOUDLY, never parks.** A residue that this approver can act on NONE
of must NOT mask as "nothing to review". BUILT + SEALED (`start_review`, 70a321c+): residue-empty →
`NO_RESIDUE` (honest); residue-nonempty-but-batch-empty → **`NO_ENTITLED_ACTION`** (loud, no workflow
started). This is the deny-for-everyone misconfig — the agentic-auth flip's first-symptom class — and
the join-that-can-never-complete in review clothes (Slice-5 suspend-vs-fail, one level up): fail at
build/registration, never register a review that suspends forever unseen. Proven-to-bite (defeat the
distinction → the deny-all case silently returns `NO_RESIDUE`, red).

> **AUDIENCE RULE (record before the BFF grows an approver path).** `NO_ENTITLED_ACTION` is an
> **initiator-plane** outcome — honest loud-fail for the operator/system that STARTS the review.
> On the **participant plane** (an approver asking about their OWN view) it is an EXISTENCE ORACLE:
> "items exist you're not entitled to act on" is exactly the fact Slice-3 redaction withholds (Seal 2
> puts it in `audit_withheld`, unsurfaced). So: **any participant-facing surface collapses
> `NO_ENTITLED_ACTION` to the same shape as nothing-to-review.** Today the only caller is the operator
> plane (`start_review` is initiator-invoked), so this costs nothing now — but the dashboard work is
> precisely where someone adds an approver-initiated path, and this is the line that stops the leak
> being wired in then. Marked at the point of use in `start_review`.

**3. The FOUR-leg discrimination seal — the LIVE acceptance, watched not inferred.** Same shape as the
ADR-0025 flip-checklist `can_view` seal, applied to `can_act` on `task_audience`. Under the reconciled
mechanism it also RE-PROVES work's rails as consumed by a new caller (upgrades the exhibit). OBSERVE
in-session (watched, not "nothing errored"), grants arriving BY THE SEED, not hand-written:
- **leg-0 — deny-BEFORE-grant:** `alice` with NO grant → deny → `NO_ENTITLED_ACTION`. The fail-closed
  property observed live before the grant exists (the leg the 3-caller seal doesn't cover; costs one call).
- **leg-1 — entitled:** `alice` actor of `pcn_disposition:SUSTAINMENT` (via `task_grants.yaml` seed) →
  SEES the batch (non-empty).
- **leg-2 — absent:** `bob` (no grant) → does NOT → `NO_ENTITLED_ACTION` (per decision 2).
- **leg-3 — wrong-compartment:** `alice` granted `pcn_disposition:AVIATION` ONLY must NOT see the
  SUSTAINMENT batch — the **compartment key does the discrimination**. If it doesn't, the key is cosmetic
  and the audience is domain-blind. AVIATION is the synthetic fixture: seeded, tested, then REVOKED **by
  removing it from `task_grants.yaml`** (the rails' own removal-sync IS the cleanup — observe the
  revocation take, the one mechanism nothing has exercised yet).

> **THIRD-LEG FIXTURE (acceptance — the seal MUST run all four legs).** Everything live on sandbox is
> SUSTAINMENT, so the wrong-compartment audience `pcn_disposition:AVIATION` the key must reject **does
> not exist** — leg-3 requires SEEDING a synthetic AVIATION grant (a `task_grants.yaml` audience entry),
> running the reject, and **REVOKING it after by removing the entry** (the rails' removal-sync IS the
> clean-after — a fixture, not residue). Name it in the run card so the seal does not quietly shrink when
> someone notices there's nothing other-compartment to test against — "can't test it, skip it" is exactly
> how the key stays cosmetic.

## The example (replicate at work) — a `task_grants.yaml` entry (NO new type, NO rego, NO manifest edit)

The whole point of reading work's rails: the artifact is a grant in the EXISTING mechanism, not new
surface. Sandbox `ENABLE_AGENTIC_AUTH` is OFF (content gates dark); can_act has its OWN toggle
`ENABLE_DISPOSITION_AUTHZ` (NOT the terminal flip). Entitled subject for the sandbox test = `alice` in
sandbox's id format; swap the real approver at work in work's format.

**The grant** — one entry in `policy/task_grants.yaml`, PR-reviewed, merged to `main`, applied by the
seed CronJob (merge = grant, removal = revoke). Audience key `<task_kind>:<compartment>` where the
compartment IS the domain:
```yaml
audiences:
  pcn_disposition:SUSTAINMENT:
    grant_to: ["<subject in YOUR deployment's id format>"]   # sandbox: alice@example.com · work: <employee-id>
    granted_by: "<accountable human's id>"
    reason: "PCN/PDN disposition review approvals — SUSTAINMENT"
```
- `grant_to` may be employee-ids/emails (direct) OR a group name (via `group#member`) — work grants a
  whole approver group. Identity FORMAT is deployment content (below); do NOT paste literals across envs.
- The check is a direct Topaz DIRECTORY check on `task_audience` (`can_act` permission) — no rego, no
  manifest edit (`task_audience` already ships in the chart manifest, `loadManifest: true`).
- The `can_act` seam (`can_act_via_topaz`) builds the audience key `pcn_disposition:<domain>` and checks
  membership; `ENABLE_DISPOSITION_AUTHZ=true` on the analyst engine arms it (off → no-op True).

**Identity invariant (born-generic on the identity plane — pin, don't infer).** Subject identity enters
from ONE claim and is carried OPAQUELY: nothing in the policy repo, manifest, or any consumer parses,
validates, or assumes the format — no email regexes, no `@`-splitting, no "looks like an ID" checks.
`can_act_via_topaz` passes the `approver` string straight through as the check `subject_id` — already
format-agnostic (good); keep it so. Identity is a string that matches or doesn't; the FORMAT is
deployment CONTENT, not mechanism. The seam — WHICH
claim populates `user_id` — is config-per-environment (sandbox maps its IdP's email; work maps the
employee-id claim, per the already-filed `central_gateway` `preferred_username` fix in
[[project_work_deploy_runbook]] — same seam, same invariant, one gateway layer down). A grant seeded in
`email` denies-everyone against an `employee-id` caller — fail-closed presenting as "the flip broke
everything," the ADR-0025 first-symptom class; and it hides because STRUCTURE diffs clean (shape
identical, only values differ). So it is a named knob, not a buried assumption.

**Wire-up** (BUILT, `pcn_review_starter.can_act_via_topaz`): direct Topaz DIRECTORY check `POST
/api/v3/directory/check {object_type: task_audience, object_id: "pcn_disposition:<domain>", relation:
can_act, subject_type: user, subject_id: <approver>}`; absent/not-found/error → deny (fail-closed).
Toggle `ENABLE_DISPOSITION_AUTHZ=true` on the analyst engine (off → no-op True). The four discrimination
legs are decision 3 above.

## DEFERRED: the discrimination seal runs on the git-deployment RAILS, not hand-surgery (decided 2026-07-24)

Hand-editing sandbox Topaz (kubectl edits to the manifest/policy) would MANUFACTURE the sandbox/work
disparity it's meant to avoid: every future seal would prove something about an 11pm hand-build, not
the deployment path work uses. Work's Topaz is git-overlay + cronjob-sync; sandbox must be stood up the
SAME way — one producer path, both clusters derive, no second hand-maintained truth (the graph-convention
lesson on the entitlement plane). So `can_act` ships tonight WIRED + verified-DARK + example-committed;
the discrimination seal runs later against config that arrived by the deployment MECHANISM (which makes
it a stronger exhibit — it proves the rails too). The flip checklist re-runs it at work regardless.

**The two open unknowns are FACTS ABOUT THE CURRENT (hand-built) SANDBOX TOPAZ — filed unresolved as
"what we're replacing" notes — BOTH now MOOT under the reconciliation (2026-07-24):**
- ~~Policy load = explicit volume-items~~ — **MOOT: no rego.** `task_audience` needs no custom rego (a
  direct directory check does it), so there is no `/policies` volume-items change at all. The unknown
  only existed for the abandoned `disposition_item` rego.
- ~~Manifest load path (configmap vs PVC)~~ — **RESOLVED: chart-shipped, `loadManifest: true`.** The
  seed loads the chart's ReBAC manifest idempotently every tick; `task_audience` already ships in it
  (verified live, chart 0.3.26). No manifest edit, no PVC question. The git+cronjob path WAS the answer.
  (Kept struck-through, not deleted, as the record of what reading the rails made unnecessary.)

## FOLLOW-UP TASK: stand sandbox Topaz up on work's rails (config work, not code)

Source-authority for STRUCTURE (not content): `C:\tmp\iagent-policy` — the local dir that bootstrapped
the work git policy repo. It carries work's SHAPE (overlay layout, manifest organization, rego bundle
arrangement, cronjob contract, naming) — which is exactly the parity target — WITHOUT work's current
content (real grants/policies, restricted). That restriction is the correct boundary landing for free:
sandbox gets work's MECHANISM with sandbox's CONTENT (alice/bob/AVIATION, the pcn additions). Build:
1. **Verify the dir's structural currency FIRST** ("created long ago" = stale-record flag). Produce a
   one-page STRUCTURAL SUMMARY (file tree, load path, cronjob contract, manifest schema version) → the
   human eyeball-diffs it against the real repo (the restriction respected; "assumed same shape" →
   "verified same shape"). Parity vs the appearance of parity.
2. **Deliverable = a repo + a deployment path, not applied config.** Build a sandbox policy repo seeded
   from the dir's structure; land `disposition_item` + the rego + test grants (alice/bob/AVIATION, in
   sandbox's EMAIL format) as COMMITS; wire sandbox Topaz to consume it the SAME way work does (overlay
   + cronjob) — resolving the two unknowns above by standing up the REAL load path, not reverse-
   engineering the hand-built one. Then the discrimination seal runs against config that ARRIVED by the
   mechanism.
3. **Divergence policy, one README paragraph at birth:** structure SYNCS (periodic human eyeball /
   structural checklist), content DIVERGES freely, and anything sandbox-proven that work needs (the pcn
   additions) travels as a DOCUMENTED change applied to the real repo (exactly this doc's "replicable
   example" workflow). Include the identity knob: "subject claim: sandbox=email, work=employee-id —
   grants seeded in the environment's format." Self-documenting, not tribal.

Ledger: the dir the agent created "long ago" as a bootstrap aid becomes the seed of the mechanism that
keeps two clusters honest — [[project_bootstrap_state_debt]] converting into reproducible-asset lineage,
item C's program running backwards through time.

## Live-session order (unchanged; this is its first act)

bind `disposition_item` + wire `can_act_via_topaz` against `core/authz.py` → run the three-caller
discrimination seal (observe all three legs) → then the settled sequence: build+roll `restate_analyst`
+ `engine-o` (one each) → journal-verified kill-seal → `IPCN25300X` batch vs its waiting diff, banked →
menu-growth observed → dashboard → five beats. The M1 close-out writes itself from three exhibits: the
banked batch diff, the kill-seal evidence, the menu-growth + discrimination observations.
