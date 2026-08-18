---
id:         first-viewer-critical-path
status:     open
owner:      human
blocked-on: nothing — the scope sentence is ANSWERED (2026-08-15): Tier-3 row 8 IS in scope, so the path is three items in the order stated below. What remains is building them.
closed-by:
code-site:  docs/BOARD.md, docs/demo-script.md, docs/demo-day-runbook.md
repo:       invincible-agent
summary:    TRIAGE — of 27 live board items, THREE are load-bearing for "one other person can use this", in a stated order. The other 24 sort into demo-day operational risk (3, now a runbook not board work) and hygiene/posture/architecture (21). The goal is three items away, not thirty-nine, and this packet names which and why the other 24 are not.
---

# Which of the board is actually between here and one other person using this

**Written because the board answers "what is wrong" and was never asked "what is between us and
the goal".** Those are different questions over the same 27 rows, and the second one has a much
shorter answer.

## First, the population is smaller than it looks

The board says 39 items. That is 39 *indexed packets*, not 39 open questions:

| status | count | on the decision surface? |
|---|---|---|
| open | 26 | yes |
| blocked-on-human | 1 | yes |
| parked | 4 | no — parked with a stated trigger |
| closed | 8 | no |

**27 live, not 39.** And the 46 unheadered packets do not add 46 more — see
[[board-migration]], where a census puts roughly 8 of those 46 in scope and the rest in the
archive. So the honest live surface is ~35, and the count that has been reading as
overwhelming was inflated by about two and a half times by closed work and historical records.

That correction is worth having on its own. It is also the reason the triage below is short.

## The sort needs THREE buckets, not two

The question posed was *load-bearing vs infrastructure hygiene*. Sorting the 27 against it, a
third category separates cleanly and matters:

1. **Load-bearing** — a person sitting in front of this hits it. Fixing it changes what they see.
2. **Demo-day operational risk** — nothing to build; it decides whether the system is *up and
   correct* when you walk in. Runbook items, not board items, and they will not be fixed by
   working the board.
3. **Hygiene / posture / architecture** — real, mostly correct, and none of it is between here
   and one other person.

Collapsing 2 into 3 is the mistake this sort exists to avoid: those three items are the ones
that make a working system fail in the room, which reads exactly like a broken system.

---

## Bucket 1 — LOAD-BEARING (2, plus 1 conditional)

### 1. [[ui-renders-honest-failure-as-answer]] — the only item where the SCREEN is wrong

Everything else on the board is wrong somewhere a user cannot see. This one is wrong in the one
place they will look. Its own packet already states the case better than a triage can:

> *It is also the shape that makes every other fix unverifiable: with this in place, "did the
> data path work?" cannot be answered by looking at the UI, which is the only place most people
> will look.*

Three outcomes, one of which is correct, and the viewer cannot tell them apart:

| what happened | what they see |
|---|---|
| grounded, queried, rows returned | the answer |
| did not ground; `status: "success"` | a confident apology |
| pipeline crashed | a blank card |

**This packet's definition of done and the goal are the same sentence** — *a VALUE on the UI for
a query the data path can serve*. That is not a coincidence to note in passing; it means item 1
is the goal, already written down, with an owner and no blocker. It has been on the board since
2026-08-15 marked HIGH with `blocked-on: nothing`.

**Ranked first, and not only on severity:** it is the instrument. Items 2 and 3 cannot be shown
to be fixed while the UI cannot distinguish an answer from an apology, so doing them first buys
work you cannot verify.

### 2. [[instance-resolution-nondeterminism]] — the second person WILL ask twice

This is the difference between a demo and a tool. A demo is one question asked once by someone
who knows the phrasing. Handing it to another person means they ask their own question, get
nothing, ask it again, and get something — and the conclusion they draw is *the asset is not in
the catalog*, because run B is articulate about why it cannot help.

Two things about this one are better than the board line suggests:

**(a) It may be a deterministic misparse, not noise.** The packet's STRONG LEAD (2026-08-15):
every failing query ended in a trailing class noun (*"p_cage dataset"*, *"p_cage table"*), the
one that grounded was bare (*"publog's p_cage"*), and `ClassifyDomainIntent` emits the class and
the `instance_identifier` in ONE call — so the trailing noun tips a single decision toward "a
KIND of thing", selecting the specific-sounding class AND emitting no identifier. Two symptoms,
one cause, and a nameable trigger. If that holds, this is not a research project.

**(b) Its stated blocker may already be gone, and one check settles it.** The packet says the
discriminating read is pending "a rig that resembles work" — sandbox Engine O on
`ontology-service:latest`, last restarted 2026-08-10, five days behind. **`5f3b4e1` records the
sandbox being upgraded to chart 0.3.37 (rev 71) on 2026-08-15 and the 29-phrasing corpus running
29/29 clean against it.** That is the same rig.

Stated as a lead rather than a fact, deliberately: `5f3b4e1` is a docs-only commit, so the
upgrade is attested by an operational record, and it names `engine-a` restarting — not Engine O,
which is the pod this packet's gate is about. **The check is one command** (Engine O's image
digest and restart time on sandbox) and it decides whether item 2 is blocked or runnable today.

**RUN 2026-08-15 — the lead held. Engine O started `2026-08-15T04:18:07Z`** (after the 00:28Z
upgrade commit), `pullPolicy: Always`, digest `sha256:fe90b047…`. The packet's "last restarted
2026-08-10, five days behind" was stale and **item 2 is runnable today**. Full read in
[[instance-resolution-nondeterminism]], including the part it does *not* establish: the digest
pins what sandbox runs, not that it equals work's build.

The read itself is already specified in the packet and is cheap: ten runs each of the bare and
the trailing-noun phrasing, compare grounding rates. ~10/10 vs ~0/10 means deterministic and the
word is the trigger; ~50/50 both ways means sampling noise and the current title stands.

### 3. [[da-collects-before-filtering]] — CONFIRMED IN SCOPE 2026-08-15

This was filed as conditional on a scope question. **The scope question is answered: Tier-3
row 8 is in scope, and the reasoning is worth keeping rather than just the verdict** —

> *"Fetch rows from a real table" is not a stretch goal. A first viewing that shows catalog
> metadata and refuses to touch data is a demo of a catalog browser, not of this system.*

That is the right test and it retires the conditional permanently. It also reclassifies the
whole of Tier-3 from *nice-to-have* to *the reason anyone would care*, which is a judgement this
packet had no standing to make.

`SELECT cage_code FROM dataset LIMIT 2` reads the entire table into RAM and OOM-killed Engine DA
at work on 2026-08-14. Memory is a function of the dataset, never of the query, so a careful
`LIMIT 2` and a reckless `SELECT *` cost the same, and the next larger table kills the pod again
at any limit.

**Third, not first, and the ordering has a reason.** Its failure mode is the worst one available
— the pod dies, `execute_subtask` raises, `generate_ui_payload` never runs, and the viewer gets a
blank card. *It looks like nothing happened rather than like something broke*, which is the one
outcome from which a room draws no conclusion at all. But that rendering is item 1's third mode,
so **item 1 is what converts this from silent to legible**, and doing item 3 first would fix the
crash while leaving every other crash equally mute.

## The order, and why it is not severity order

1. **[[ui-renders-honest-failure-as-answer]]** — the instrument. Nothing after it is verifiable
   until it lands, and it turns items 2 and 3's failures from invisible into stated.
2. **[[instance-resolution-nondeterminism]]** — *but run the Engine O image-digest check first*,
   because its stated blocker may already be gone (below) and that check is a minute against a
   packet that otherwise reads as blocked.
3. **[[da-collects-before-filtering]]** — the highest-severity failure, deliberately last,
   because item 1 is what makes its failure mode visible.

---

## Explicitly NOT load-bearing, with the reasoning stated so it can be argued with

### [[archetype-chosen-before-data]] — demoted, and this is the call most likely to be wrong

It is on-screen, it is small, and it is mechanical, which makes it look like item 3. It is not,
**because the degradation half already shipped on 2026-08-15**: a list of CAGE codes now reaches
the honest fallback and the viewer sees `00000, 00001` instead of "CHART DATA NOT RENDERABLE".

So the residual defect is that the system *chooses wrong first and recovers*, rather than
choosing right. That is a correctness debt and a real one — but the viewer now sees the values
either way, and this triage is about what the viewer sees. **Demoted to hygiene on the strength
of the shipped fallback, not on the strength of the defect being small.** If the fallback turns
out to render poorly enough to embarrass the room, this comes straight back to bucket 1.

### ⚠ A ROW THIS PACKET CERTIFIED ✅ READY REGRESSED FOUR HOURS LATER

**Demo-script §2 row 5 — the Tier-1b trust-builder — is now ⚠, and the triage above should be
read with that correction.**

`2f617fd` (2026-08-15 11:16) rewrote the `idp:Column` / `idp:Pipeline` definitions to remove a
recall bias, correctly and with measurements. It also records its own cost:

> `misspell-01` (*"...publog's p_caeg"*, an asset that does not exist) previously abstained to
> UNKNOWN and now resolves to Column, stably 3/3.

**Honest abstention on a non-existent asset IS row 5.** The demo script's expected behaviour for
that row is `instance_resolved=false` → generalist, *no fabricated answer*, and the whole point
of the beat is stated there: *"a system that refuses to confabulate lands harder than any
success — everyone has been burned by a tool that confidently made something up."*

So the beat whose entire value is watching the system decline is the beat that just stopped
declining, on the exact input shape it is demonstrated with (a name that looks right and is not).

**This is not an argument against `2f617fd`** — it fixed two genuine class-contest defects, it
measured them, and it recorded the regression rather than burying it. The gap is that the cost
was recorded as a *resolver* fact and never connected to the *demo* row that depends on it.
That connection is the thing this packet exists to make.

**UPGRADED FROM ⚠ TO ⛔ 2026-08-15, and the 2026-08-17 re-read makes it MORE binding.** A
290-probe run measured `p_caeg` (an asset that does not exist) resolving **10/10** to the real
`publog/p_cage`,
because the extractor takes `cage` from the words *"cage values"* and the matcher accepts a
content word as a name. A second row does it from a bare *"values from cage"*.

Re-probed 2026-08-17 on the **same pod, no redeploy**: it abstains correctly **6/6**, with
nothing fixed — one candidate score moved 0.006 and flipped both the class and the extracted
identifier. **So the beat is not reliably broken, it is reliably UNSTABLE, which is worse for a
demo:** a row that always fails gets dropped from the script; a row that passes your morning
check and confabulates in the afternoon is the one you put in front of an audience *because* you
tested it. **Run it as a slide, not a live query**
([docs/demo-day-runbook.md](../demo-day-runbook.md) §A5).

**Consequence for the ordering:** none. Items 1–3 stand. But this is now a *content* problem with
the demo rather than a readiness check — the Tier-1b trust-builder currently demonstrates the
opposite of its thesis, and no amount of pre-flight verification fixes that. It is retired by
[[instance-resolution-nondeterminism]]'s identifier/content-word discrimination, and explicitly
**not** by the qualifier-stripping half alone, which would make it more reachable.

## Bucket 2 — DEMO-DAY OPERATIONAL RISK (3): now [docs/demo-day-runbook.md](../demo-day-runbook.md)

**These are not fixed before a viewing; they are SEQUENCED AROUND** — deploy the day before,
verify the verbs registered, confirm the URN resolves, then do not touch it. That makes them a
different artifact from this one: *"what do I check in the hour before"* is not *"what is
broken"*, and filing a checklist as a board item would make it read as work someone owes.

So they are written up as a runbook that lives **outside `docs/plans/`** — deliberately, so it
never enters the board's denominator as a 47th unheadered packet. Retained below only as the
pointer from the board to the checklist.

- **[[registration-boot-order-race]]** — an engine that boots before the ontology ingest lands
  takes a 422, never retries, and recovery at work was a hand restart. This is *"is the system
  actually up when you walk in"*. Repair 3 landed (`fbf7307`); repair 1 is still owed — which of
  three ways the re-register hook failed to fire — so a deploy still depends on a hook nobody
  has verified runs.
- **[[broker-endpoint-env-divergence]]** — the stuck `PUBLOG_S3_BUCKET_URL` was removed by hand
  and its source is still unfound (absent from `helm template`, absent from the image, present
  in the live Deployment). Unfound source means it can come back, and when it does every data
  read 404s while the routing table looks fully populated.
- **[[urn-reconciliation-guard]]** — blocked on a human POSTURE ruling. Its own line says every
  identity defect this week produced the same silent 404 and this one check would have caught
  all three *"at startup instead of at a demo"*. It does not add capability; it converts a
  demo-time failure into a boot-time one, which is the entire value.

### Bucket 3 — HYGIENE / POSTURE / ARCHITECTURE (21 of 27)

Not ranked, because the point is that none of them are on the path. The largest coherent group
is the **authz/transport arc** — [[transport-flip]], [[agentic-auth-flip]], [[undeclared-routes]],
[[dag-tools-broker-register-unauthenticated]], [[dag-tools-gateway-unverified-subject]],
[[supervisor-mint-missing-identity]], [[jupyter-user-token-data-access]] — seven items, all real,
and all of them are the price of a *shared* cluster with users who are not you. **Showing one
person over your shoulder does not touch any of it.**

The rest: [[board-migration]], [[endpoint-table-generation]], [[suite-signal]],
[[doctools-ci-silent-on-push]], [[legacy-dns-guard-phantom-scope]], [[dagster-loader-call]],
[[adr0039-deliverables]], [[retire-inline-task-loop]], [[seeder-manufactures-declarations]],
[[subject-resolution-at-composition]], [[agent-loop-infra-error-flail]],
[[da-schema-affordance]], [[deterministic-decisions-made-by-llm]], [[archetype-chosen-before-data]].

Two of those deserve a note rather than silent demotion:

- **[[deterministic-decisions-made-by-llm]]** is the architectural parent of items 2 and 3 and
  is correctly `owner: human, blocked-on: a design session`. **Do not promote it to unblock
  item 2.** The lead in item 2 is a specific, cheap, falsifiable read; the design session is the
  right answer to a question the read has not asked yet, and taking it first converts a
  ten-minute measurement into a week.
- **[[da-schema-affordance]]** burns 3 of 6 agent steps guessing column names. That is latency
  in the room, not wrongness. Genuinely a judgement call between bucket 2 and 3; filed as 3
  because a slow correct answer survives a demo and a wrong one does not.

---

## The prerequisite that is on NO board item — READ, and it is not a blocker

**"One other person" needs an identity and an entitlement.** Read 2026-08-15 rather than
assumed, and the answer is better than expected in one direction and worse in another.

**The identity already exists and the grant is already asserted in git.** `policy/users.yaml`
seeds three demo accounts present in sandbox Keycloak, and one of them is a deliberate
power-user: it holds `aviation-engineers`, `defense-engineers`, `enterprise-architects`,
`data-engineers` and `maintenance-mechanics`, which flattens to catalog, aviation, defense,
enterprise and maintenance cells. `get_entitlements` (`src/iagent/authz/topaz_client.py:179`)
walks member→group then group→cell, exactly as the standing finding describes. **So this is not
item 0 and it is not a human's Topaz write** — the rail is already populated. Delete the fear,
keep the three checks below.

### But WHICH identity they log in as decides whether the viewing works at all

`/resolve` **domain-scopes the OntologyClass pool to the caller's cells.** The other two seeded
accounts are deliberately NOT granted catalog access, and `users.yaml` is explicit that this is
an assertion rather than a gap — their honest "Not entitled" denial is described as a demo asset,
with a standing instruction not to add the group to make a denial go away.

**That is correct behaviour and it is also a way to lose the room.** Sit someone down on the
steward or mechanic account, have them ask a catalog question, and the system correctly refuses
— which is indistinguishable, to them, from the system not working. The power-user account is
the one to use, and its catalog grant is annotated in-file as a **FIXTURE** with a stated
removal condition (*"if the demo stops needing a catalog-entitled X, this line comes out"*). A
prerequisite resting on a line that is documented as removable is worth knowing before the day.

### Three checks, none of them long

1. **Does the live Topaz directory match `policy/`?** The rail is git→directory sync, and drift
   has precedent *in this very file*: the maintenance cell carries a note that it files a grant
   "already written to the sandbox directory" so that git and the directory agree — i.e. the
   directory was ahead once. `policy/sync/` is the tool; confirm it has run against sandbox.
2. **Does `USER_ENTITLEMENT_CLAIM` line up with the email the IdP actually issues?** It defaults
   to `email`, and `users.yaml` warns in its own header that a domain mismatch between the
   seeded ids and the issued claim **silently blanks the user's matrix**. Silently. Combined
   with item 1, a blanked matrix would present as the system having no answer — the exact
   failure this whole packet is about, arriving through the login screen.
3. **Log in as the second identity and ask one Tier-1 question, before anyone is watching.**
   Settles 1 and 2 together and costs a minute.

**These three are the TOP of [docs/demo-day-runbook.md](../demo-day-runbook.md), above the
infrastructure checks** — because they are two independent ways for a viewing to fail *while the
system is functioning perfectly*, and neither produces an error anywhere. A denied account and a
blanked matrix are both correct behaviour; to the person in the chair they are indistinguishable
from a broken system. Everything else in that runbook fails loudly. These do not.

## Acceptance

- One named non-author person asks a question they chose, in the interface, and gets a value.
- Asking it a second time returns the same thing.
- When it cannot answer, the interface says so — no apology wearing `status: "success"`, no
  blank card.

That is items 1 and 2 and nothing else, which is the claim this packet is making.

## Related

- [[board-migration]] — the census that shrinks the other half of the count.
- [docs/demo-script.md](../demo-script.md) — the tier definitions the Tier-3 scope question refers to.
