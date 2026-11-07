# Packet: Q3 and Q4 get one candidate because of the subject, not the persona

to: invincible-agent/lane/saf
cc: invincible-agent/seat/architect
from: invincible-agent/lane/01, 2026-10-18
re: `2026-10-18-packet-to-lane-01-q3-q4-reach-the-classifier-with-one-candidate-explain.md`
relay: Chris

Placed, not committed. This packet carries no secret.

## What I read, and what I did not measure

This is a **reading of the code and the declarations** at `lane/01-196`, against the route
records you sent. I did not re-run your six runs or read their event logs. Treat the cause as
read, not measured. The check that would measure it is at the end.

## The candidate pool is keyed on the resolved subject

`dynamic_supervisor` builds the pool with `_find_compatible_verbs(subject_uri, entitled_domains)`.
That asks the ontology service for the verbs whose `input_uri` covers the **resolved subject**,
plus the verbs with a required slot whose referent covers it. Then the arity and argument-fit
gates run. `candidate_count` is the length of what survives.

Your route records name the subjects:

| prompt | `about` (the resolved subject) | the verb you expected | its `input_uri` |
| --- | --- | --- | --- |
| Q4 `what failed on this part` | `safety#FailureRecord` | `whatFailedOnThisPart` | `safety#SafetyCriticalItem`, and `pcn#Component` |
| Q3 `risk of deferring this work order` | `safety#RiskAssessment` | `assessDeferralRisk` | `mro#MaintenanceWorkOrderRecord` |

**No safety verb takes `FailureRecord` or `RiskAssessment` as input.** The six safety
`input_uri`s are:
- `Hazard`, twice
- `MaintenanceWorkOrderRecord`
- `SafetyCriticalItem`
- `pcn:Component`
- `Platform`

So on those two subjects the pool can only hold the generalist `mesh:explain`, which is the one
candidate you saw in all six runs.

**The resolver picks what the question is about, not what it is asked of.** "What *failed*"
resolves to the failure, and "*risk* of deferring" resolves to the risk. Each verb is declared on
the thing it is asked about ("this part", "this work order"). Both verbs carry these exact
phrasings as synonyms, but the classifier never sees a synonym of a verb that is not in the pool.

## Why I do not think it is the persona or domain

- **The persona/domain mismatch is real, but it is not in this filter.** The pool is filtered by
  `entitled_domains`, which is `[SUSTAINMENT]` on all six runs, and by the caller's identity,
  which is sent as `on_behalf_of` (bob). The persona is not sent to `_find_compatible_verbs` at
  all.
- **Your own walk is the control.** Q5, Q6 and the hazard prompts reach safety verbs under the
  same run config. Those prompts resolve to `Hazard` and to a part, which are declared inputs.
- **Q3 #2 fits the same reading.** There, `explain` was classified, and the subject slot then
  failed on "this work order". That is instance resolution, after the pool.

## The check that would measure it

Two checks, read-only. Either one confirms or refutes this reading.

1. **Read the route record's eligibility trace** for Q4 #1, run `02fe5689`. The supervisor
   carries `_eligibility_trace`, which says which rule admitted or dropped each verb. Neither
   safety verb should appear in it at all, because it was never fetched, not fetched and then
   dropped.
2. **Call `/find_compatible_verbs`** with `safety#FailureRecord` and `[SUSTAINMENT]`, then with
   `safety#SafetyCriticalItem`. The first should give `explain` only. The second should include
   `whatFailedOnThisPart`.

## What a fix would be, for the architect

This is not mine to choose. There are three shapes:
- **(a) Resolve the asked-of class.** Teach the resolver that "on this part" and "of this work
  order" name the subject.
- **(b) Widen the declarations.** Register each verb's output class as a referent, so `FailureRecord`
  pulls in `whatFailedOnThisPart`.
- **(c) Accept it.** The elicitation already names a way out, though `explain` is a poor one.

(b) risks the authority-ranking trap: a verb would then claim every question about its own output
class.
