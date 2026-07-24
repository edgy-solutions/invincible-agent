# can_act / disposition_item — the Topaz binding, decided on paper (live session reads this)

The `can_act` seam is the ONE piece of the PCN loop that cannot be sealed offline (it needs the live
authz layer). But "can't be sealed offline" ≠ "undesigned": an authz question answered at the console
under demo momentum becomes the entitlement model by accident. So the SHAPE is decided here; the live
session BINDS and OBSERVES, it does not decide.

**The type (born generic per AGENTS.md):** Topaz resource type `disposition_item`, a workflow-model
noun. The domain is a Topaz **attribute** (`domain: SUSTAINMENT`), never baked into the type name — a
`pcn_disposition` type would write the domain into the entitlement contract, the hardest layer to walk
back and where the flip-checklist seals live. Action: the approver's disposition act (e.g. `act`).

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

**3. The three-caller discrimination seal (pcn edition) — the LIVE acceptance, watched not inferred.**
Same shape as the ADR-0025 flip-checklist `can_view` seal (entitled / empty / wrong-domain), applied to
`can_act`. When the binding lands, OBSERVE in-session (status = the menu-growth assertion: watched, not
"nothing errored"):
- an **entitled** SUSTAINMENT approver SEES their batch (non-empty);
- an **unentitled** approver does NOT (their batch is empty → `NO_ENTITLED_ACTION`, per decision 2);
- the **domain attribute actually discriminates** — a hypothetical other-domain approver cannot act on
  a SUSTAINMENT `disposition_item`, proving the born-generic type's *attribute* does the work the
  domain-named type used to. That third leg is the whole point of `disposition_item` + attribute; if it
  doesn't discriminate, the attribute is cosmetic and the type is domain-named in disguise.

> **THIRD-LEG FIXTURE (acceptance — the seal MUST run all three legs).** Everything live on sandbox is
> SUSTAINMENT, so the other-domain `disposition_item` the attribute must reject **does not exist** — the
> third leg requires WRITING a synthetic other-domain item into the authz/graph surface, running the
> reject, and **DELETING it after** (same clean-after discipline as the state-write test — a fixture,
> not residue). Name it in the run card so the seal does not quietly shrink to two legs when someone
> notices there's nothing other-domain to test against — "can't test it, skip it" is exactly how the
> attribute stays cosmetic — and so the fixture does not outlive its test.

## The example (replicate at work) — Topaz artifacts, mirroring the sealed ontology can_view gate

Sandbox `ENABLE_AGENTIC_AUTH` is OFF (all gates dark; the terminal flip is staged + irreversible). So
can_act gets its OWN dark-launch toggle `ENABLE_DISPOSITION_AUTHZ` — NOT the terminal flip. Entitled
subject for the test = `alice`; swap the real approver identity at work.

**1. Manifest type** (add to the Topaz `manifest.yaml` — type is GENERIC, domain is the instance key):
```yaml
  disposition_item:
    relations: { actor: user }
    permissions: { can_act: actor }
```

**2. Policy** `invincible_agent.disposition.can_act` (mirrors `ontology.can_view` — `ds.check`, subject
in `resource_context.user_id`, fail-closed):
```rego
package invincible_agent.disposition.can_act
import future.keywords.if
default allowed := false
allowed if {
    ds.check({
        "object_type": "disposition_item",
        "object_id": input.resource.domain,     # domain = the instance key (attribute); type stays generic
        "relation": "can_act",
        "subject_type": "user",
        "subject_id": input.resource.user_id,
    })
}
```

**3. Grant** (directory relation — the entitlement), stated SYMBOLICALLY because this doc is the
copy-paste vector across environments and identity FORMAT differs per deployment (see Identity
invariant below): `user:<subject in your deployment's id format> --actor--> disposition_item:SUSTAINMENT`
(written via the directory writer / a `disposition_grants.yaml` + sync, mirroring `policy/asset_grants.yaml`).
Seed grants in the ENVIRONMENT's format — sandbox=email (`alice`/`bob`), **work=employee-id** (e.g.
`E123456`). Do NOT paste `alice@…` literals into work's seed. At work: grant the real approver `actor`
on their domain's `disposition_item`.

**Identity invariant (born-generic on the identity plane — pin, don't infer).** Subject identity enters
from ONE claim and is carried OPAQUELY: nothing in the policy repo, manifest, or any consumer parses,
validates, or assumes the format — no email regexes, no `@`-splitting, no "looks like an ID" checks.
The rego's `subject_id: input.resource.user_id` is already format-agnostic (good); keep it so. Identity
is a string that matches or doesn't; the FORMAT is deployment CONTENT, not mechanism. The seam — WHICH
claim populates `user_id` — is config-per-environment (sandbox maps its IdP's email; work maps the
employee-id claim, per the already-filed `central_gateway` `preferred_username` fix in
[[project_work_deploy_runbook]] — same seam, same invariant, one gateway layer down). A grant seeded in
`email` denies-everyone against an `employee-id` caller — fail-closed presenting as "the flip broke
everything," the ADR-0025 first-symptom class; and it hides because STRUCTURE diffs clean (shape
identical, only values differ). So it is a named knob, not a buried assumption.

**4. Wire-up** (BUILT, `pcn_review_starter.can_act_via_topaz`): POSTs `/api/v2/authz/is` with
`policy_context.path = invincible_agent.disposition.can_act`, subject in `resource_context.user_id`,
domain in `resource_context.domain`. Toggle `ENABLE_DISPOSITION_AUTHZ=true` on engine-a (off → no-op True).

**5. Discrimination seal — the three legs:**
- `alice` (actor of `disposition_item:SUSTAINMENT`) → ALLOW → sees the batch.
- `bob` (no relation) → DENY → unentitled → `NO_ENTITLED_ACTION` (not a silent empty).
- `alice` on `disposition_item:AVIATION` (no relation) → DENY → the domain attribute DISCRIMINATES.
  The AVIATION item is the synthetic other-domain fixture: written, rejected, then DELETED (fixture,
  not residue).

## DEFERRED: the discrimination seal runs on the git-deployment RAILS, not hand-surgery (decided 2026-07-24)

Hand-editing sandbox Topaz (kubectl edits to the manifest/policy) would MANUFACTURE the sandbox/work
disparity it's meant to avoid: every future seal would prove something about an 11pm hand-build, not
the deployment path work uses. Work's Topaz is git-overlay + cronjob-sync; sandbox must be stood up the
SAME way — one producer path, both clusters derive, no second hand-maintained truth (the graph-convention
lesson on the entitlement plane). So `can_act` ships tonight WIRED + verified-DARK + example-committed;
the discrimination seal runs later against config that arrived by the deployment MECHANISM (which makes
it a stronger exhibit — it proves the rails too). The flip checklist re-runs it at work regardless.

**The two open unknowns are FACTS ABOUT THE CURRENT (hand-built) SANDBOX TOPAZ — filed unresolved as
"what we're replacing" notes for whoever does the git-rails sync:**
- **Policy load = explicit volume-items, not whole-dir.** OPA `local_bundles.paths: ["/policies"]`
  loads the dir, BUT the topaz *deployment* mounts the configmap with an explicit `items:` list — a new
  rego needs a DEPLOYMENT volume-items change, not just a configmap key. The git-rails path replaces
  this with the overlay's documented mount.
- **Manifest load path unconfirmed (configmap-file vs PVC-persisted).** `manifest.yaml` is mounted in
  `/policies`, but a `topaz-seed-cronjob` (default-DISABLED) syncs data, and the schema may be
  DB-persisted in the PVC — so a configmap edit might not "take" without a re-seed. Directory manifest
  API didn't answer on probed ports (9393/8383). The git+cronjob path is the ANSWER to "how does a
  manifest change take effect" — it's already proven at work; nobody reverse-engineers the hand-built
  mount.

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
