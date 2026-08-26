# Demo-day runbook — the hour before someone else drives this

**This is a checklist, not work.** It deliberately lives outside `docs/plans/` and carries no
ADR-0040 header, because nothing here is a board item: none of it gets *fixed* before a viewing,
all of it gets *sequenced around*. Filing it as a packet would make a checklist read as work
somebody owes, and would add a 47th unheadered file to a coverage line that is already
overstating its gap.

Companions: [demo-script.md](demo-script.md) is what you ask in the room;
[plans/first-viewer-critical-path.md](plans/first-viewer-critical-path.md) is what is being
built to make it work. **This is the third question — what do I check before anyone watches.**

---

## §A. THE IDENTITY CHECKS — do these FIRST, they fail silently

Everything in §B fails loudly: a CrashLoop, a 404, a named alarm. **§A fails silently, while the
system is functioning perfectly**, and both failures look to the person in the chair exactly like
a broken product. That is the only reason this section is first.

### A1. Confirm WHICH account the viewer drives — and that it holds the right cells

`/resolve` **domain-scopes the OntologyClass pool to the caller's cells.** Of the three demo
accounts seeded in `policy/users.yaml`, only the power-user profile holds a
`DATA_ENGINEERING` cell. The other two are **deliberately denied** catalog access, and
`users.yaml` says so in its own comments: their honest "Not entitled" denial is a demo asset,
with a standing instruction not to add the group to make a denial go away.

- ✅ Use the power-user account for any catalog or Tier-3 row.
- ⚠️ Its catalog grant is annotated in-file as a **FIXTURE**, with a stated removal condition.
  A prerequisite resting on a line documented as removable is worth re-reading on the day.
- ⚠️ If you deliberately want to *show* access control working, that is a good demo beat — but
  run it as its own beat, narrated, **not** as a catalog question that happens to be refused.

### A2. Confirm `USER_ENTITLEMENT_CLAIM` matches the claim the IdP actually issues

Defaults to `email`. `policy/users.yaml` warns in its own header that a mismatch between the
seeded ids and the issued claim **silently blanks the user's matrix** — no error, no denial
message, just an empty entitlement set that presents downstream as the system having nothing to
say.

Check the claim the IdP issues for the viewer's account against the `id:` values in
`policy/users.yaml`. A domain mismatch is the failure mode; it is silent; it is one comparison.

### A3. Confirm git and the Topaz directory agree

The rail is `policy/` → sync → Topaz directory, and `get_entitlements`
(`src/iagent/authz/topaz_client.py:179`) reads the **directory**, not the file. Drift has
precedent *in this very file*: the maintenance cell carries a note recording that it was filing
a grant already written to the sandbox directory by hand, so git could catch up.

Confirm `policy/sync/` has run against the target cluster. A grant that exists only in git
entitles nobody.

### A4. THE ONE THAT SETTLES A1–A3 — log in as the viewer and ask one Tier-1 question

Before anyone is watching. One question, one answer, from their account, on the machine they
will use. It costs a minute and it collapses three checks into an observation.

**Do not skip this because A1–A3 passed.** They are checks on the configuration; this is a check
on the system.

### A5. ⛔ DO NOT RUN THE FAILURE DEMO LIVE (§2 row 5) — measured UNSTABLE across runs

**This is a hard block, and the 2026-08-17 re-read makes it MORE binding, not less.**

Measured 2026-08-15 (290 probes): `p_caeg` — an asset that does not exist — resolved **10/10** to
the real `publog/p_cage`, because the extractor took `cage` from the words *"cage values"*.

Re-probed 2026-08-17 on the **same pod, no redeploy**: the identical query **abstains correctly
6/6**. Nothing was fixed. One candidate's similarity score moved by **0.006** and that flipped
both the class and the extracted identifier.

**So the beat is not reliably broken — it is reliably UNSTABLE, which is worse for a demo.** A
row that fails every time can be dropped from the script with confidence. A row that abstains
correctly all morning and confabulates in the afternoon, on an unchanged deployment, is the one
you put in front of an audience precisely because you tested it and it passed.

**Run it as a SLIDE.** Narrate the thesis, show the intended behaviour, do not issue the query.
That is the cardinal demo rule (§C) applied to a row that used to be safe.

**Delete this section when the identifier/content-word discrimination lands** — per §E, a step
that routes around a known defect cites what retires it. Retired by
[plans/instance-resolution-nondeterminism.md](plans/instance-resolution-nondeterminism.md), and
**not by the qualifier-stripping half alone**, which that packet records would make this worse.

---

## §B. THE INFRASTRUCTURE SEQUENCE — deploy the day BEFORE, then stop touching it

The governing rule: **deploy the day before, verify, then freeze.** Every item below is a
known-recurring failure whose recovery is a hand action, and a hand action during a viewing is
indistinguishable from the thing not working.

### B1. Deploy the day before — never the morning of

Rationale is B2: the boot-order failure is a *race*, so the mitigation is slack, not speed.

### B2. Verify the verbs actually registered

Board item: [plans/registration-boot-order-race.md](plans/registration-boot-order-race.md).

An engine that boots before the ontology ingest lands takes a **422 Contract D rejection and
never retries** — the ruling that 422 is permanent is right for a real contract violation and
wrong for "the graph is not populated yet". Witnessed at work 2026-08-14; recovery was a hand
restart.

Repair 3 landed (`fbf7307`). **Repair 1 is still owed** — which of three ways the re-register
hook failed to fire — so a deploy still depends on a hook nobody has verified runs. Until that
read is done, this check is not optional.

- Verify the verb count per class is what you expect (the live-coverage read from `5f3b4e1`:
  `idp#Dataset` → 9, `idp#Table` → 9, `idp#Column` → 4).
- A class showing **zero** verbs is this failure. Restart the engine and re-verify.

### B3. Confirm the URN resolves — before the demo, not during

Board item: [plans/urn-reconciliation-guard.md](plans/urn-reconciliation-guard.md), which is
blocked on a human POSTURE ruling and whose whole value is stated as catching this *"at startup
instead of at a demo"*. Until that guard exists, **you are the guard.**

Every identity defect in the 2026-08-14/15 week — platform, endpoint, bucket — produced the same
**silent 404** against a routing table that looked fully populated. Resolve the specific URNs
behind the §6 substitution table in [demo-script.md](demo-script.md) and confirm each returns an
entity.

### B4. Check the endpoint env has not drifted back

Board item: [plans/broker-endpoint-env-divergence.md](plans/broker-endpoint-env-divergence.md).

`PUBLOG_S3_BUCKET_URL` was stuck on the live Deployment — **absent from `helm template`, absent
from the image, present in the running pod.** It was removed by hand to unblock, and **its source
was never found.** An unfound source means it can return on any redeploy, and when it does every
data read 404s while everything upstream looks healthy.

Since B1 says you redeploy the day before, this check belongs immediately after that deploy:
diff the broker's live env against what the chart renders.

### B4a. ⛔ DO NOT ROLL `iagent-engine-p` BETWEEN REHEARSAL AND THE ROOM

**Plan state is IN-MEMORY this cycle.** `PlanStore` says so in its own docstring — it becomes
Postgres in Phase 4. The consequence is operational, not architectural:

> **A restart of `iagent-engine-p` destroys every scenario, and silently.** Baseline returns to
> the seed, which looks perfectly healthy — nothing errors, no pod is unready, and the cards all
> render. What is gone is any drag anyone has already made.

**What this costs you if it happens mid-demo:** the drag beat is performed against a scenario
forked on the first drag. Roll the pod and that scenario is gone; the next card refresh reads
baseline again, Site B falls back to 1.8, and the room watches a consequence *un-happen* with no
explanation available.

**The rule:** once the rehearsal drag is done, `iagent-engine-p` is frozen. That includes
"harmless" restarts — a `kubectl rollout restart` to pick up an unrelated config change, a node
drain, an eviction under memory pressure.

**If it does restart** — deliberately or otherwise — say so and re-do the drag rather than
explaining a number that moved on its own. Re-forking is one drag; recovering the room's trust
in the numbers is not.

**Check before the room** (should be `0` scenarios and baseline at version `0` before the
rehearsal, and whatever the rehearsal left after it):

```bash
kubectl --context edge exec -n sandbox deploy/iagent-engine-p -- \
  python -c "import urllib.request,json; \
  print(json.loads(urllib.request.urlopen('http://localhost:8095/scenario').read()))"
```

**What retires this:** ADR-0042 §3's Phase-4 move of `PlanStore` to Postgres. Until then the
freeze is the mitigation.

---

### B5. Engine O image digest — the Tier-3 and grounding prerequisite

Sandbox Engine O has run `ontology-service:latest`, and a `:latest` tag makes the version
unfalsifiable from outside — `/health` returns `{status, jena_reachable}` with **no build
identity**. `5f3b4e1` records a chart upgrade to 0.3.37 (rev 71) on 2026-08-15 with the
29-phrasing corpus running clean, but names `engine-a` restarting.

Read the image digest and restart time on the Engine O pod. This is the same check that decides
whether [plans/instance-resolution-nondeterminism.md](plans/instance-resolution-nondeterminism.md)
is blocked, so it earns its place twice.

---

## §C. IN THE ROOM

- **Never run a 🔭 ROADMAP row as a live query.** [demo-script.md](demo-script.md)'s cardinal
  rule: a query that falls through to the generalist reads as failure even when it is correct
  behaviour. Roadmap items are slides.
- **Name the thing when you want a guaranteed-clean moment.** Queries naming a specific
  identifier route through instance resolution *before* any class-vocabulary contest, so they
  are the most robust live rows. Describe the thing when you want to show semantic routing.
  Pick per row, on purpose.
- **Put the failure demo in** (Tier-1b, row 5). A system that refuses to confabulate lands harder
  with a technical audience than any success.
- **Ask each question ONCE.** Until
  [plans/instance-resolution-nondeterminism.md](plans/instance-resolution-nondeterminism.md)
  lands, a repeat is a coin flip — and the losing side is articulate about why it cannot help.
  This line is the runbook's own admission that item 2 is not yet built; **delete it when it is.**
- **Read [demo-seed-physics.md](demo-seed-physics.md) before driving the planning beats.** Four
  properties of the model a sharp person could notice and ask about — only Site B can cross, a
  drag is two ops, moving a project does not move its money, and a week's overlap lands a full
  quarter's impact. Each has its answer written, and in three of four the honest answer is a
  design statement that lands better than the question. It also carries the prepared response
  to *"what if I pull it further?"* — **do that one live**; the flag changes from `moved` to
  `constraint-violated` and you are demonstrating the constraint engine rather than improvising.

---

## §D. What this runbook does NOT cover, on purpose

The authz/transport arc — transport-flip, agentic-auth-flip, undeclared-routes, the two dag-tools
findings, supervisor-mint, jupyter tokens. Seven live board items, all real, and all of them the
price of a **shared** cluster with users who are not you. Showing one person over your shoulder
touches none of it, and pulling any of it into a demo-day checklist would be the fastest way to
make this checklist unusable.

---

## §E. THE RULE THIS RUNBOOK FOLLOWS — every workaround cites what retires it

**Any step that exists to route around a known defect must cite the packet that retires it, and
say that it is to be deleted when that packet closes.** §C's *"ask each question once"* is the
pattern instance: it makes the checklist honest today and self-correcting later, because the step
carries its own removal condition instead of hardening into folklore.

This is the same move as `UNMEASURED` in the trust table — **a field that names its own absence
rather than staying blank.** A blank is indistinguishable from "fine"; a named absence is a
standing question with an owner.

Applied here, it sorts this runbook into two kinds of step, and the distinction is worth keeping
visible:

- **Permanent operational discipline** — §A4 (ask a question as the viewer before anyone
  watches), §B1 (deploy the day before), §C's roadmap-rows-are-slides. These stay forever. They
  are not routing around anything; they are how you run a demo.
- **Workarounds with an expiry** — §B2, §B3, §B4, §B5, and §C's ask-once. Each one exists because
  a named packet is open, each cites it, and **each should shrink this document when that packet
  closes.** A runbook that only ever grows is a runbook accumulating defects it has stopped
  calling defects.

The test for a new step: *if I cannot name what would delete this, it belongs in the first
category — and if I am wrong about that, I have just written down folklore.*

---
