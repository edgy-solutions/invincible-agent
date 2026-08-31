---
id:         enumerate-probe-2026-08-30
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
code-site:  agent_fleet/planning_agent/main.py (/enumerate_instances), src/iagent_pure/slot_disposition.py
summary:    THE PROBE NOBODY HAD RUN. All four spoken-mandatory slots' classes enumerated live against engine-p, and the prediction made before the fan-out was built holds exactly: BusinessProcess -> members n=2, Technology -> members n=5, Capability -> too_many n=9, Project -> too_many n=14, against bound 8. So TWO OF FOUR mandatory slots produce a real menu today and two legitimately do not — which is the enumerate capability's whole design working, not a gap. Neither of the two that CAN produce a menu has a corpus case, so this is capability confirmed rather than behaviour measured, and it is reported as such. The probe was cheap and had never been done: the classes that would work were the ones nobody asked about, because the corpus was written around the cases that were failing.
---

# Enumerating the four mandatory-slot classes — the probe nobody had run

**Run 2026-08-30**, live against `iagent-engine-p` in the sandbox
(`kubectl port-forward svc/iagent-engine-p 8095`), one POST per class to
`/enumerate_instances`.

## Why it had never been run

Every spoken-mandatory slot in the system is instance-kind, and the two the corpus exercises —
`capability_id` (`H06`) and `project_id` (`E05`) — are the two whose classes are **over** the menu
bound. So the reasoning ran *"the ask trigger is free and every menu it could build is blocked"*,
which is true of the cases in the record and **false of the capability**.

**The classes that would work were the ones nobody asked about, because the corpus was written
around the cases that were failing.** That is a corpus fact wearing a capability fact's clothes —
the same species the slot arc opened with.

## The result — the prediction holds exactly

| slot | class | outcome | n | menu? |
|---|---|---|---|---|
| `process_id` | `idp#BusinessProcess` | **`members`** | **2** | **yes** — BP1 *Order to Cash*, BP2 *Plan to Produce* |
| `tech_id` | `idp#Technology` | **`members`** | **5** | **yes** — T1…T5 |
| `capability_id` | `idp#Capability` | `too_many` | 9 | no — bound is 8 |
| `project_id` | `idp#Project` | `too_many` | 14 | no — bound is 8 |

Raw, verbatim:

```
BusinessProcess  {"outcome":"members","count":2,"members":[{"instance_id":"BP1","label":"Order to Cash"},
                                                            {"instance_id":"BP2","label":"Plan to Produce"}]}
Technology       {"outcome":"members","count":5,"members":[{"instance_id":"T1","label":"Core ERP Platform"},…]}
Capability       {"outcome":"too_many","count":9,"bound":8,"members":[]}
Project          {"outcome":"too_many","count":14,"bound":8,"members":[]}
```

**Two of four mandatory slots produce a real menu. Two legitimately do not.** That split is the
enumerate capability's design working rather than a gap — a provider that can say *"the class is
real and larger than a menu"* is what makes ADR-0033's free-text boundary decidable instead of a
fudge.

**And `9` against a bound of `8` is worth noticing rather than smoothing.** The item that ruled
the bound used *"nine capabilities is a menu"* as its example of a menu, and then ruled 8 — so the
ruled number and its own example disagree by one, and `capability_id` falls to free text because
of it. The provider's comment already flags this as *"intended, or an off-by-one against the
example"*, unresolved. This probe is the measurement that would decide it, and the decision is
the architect's: **at 9 the menu is one line longer; at 8 the most-asked slot in the corpus never
gets one.**

## What this is NOT evidence of

**Capability, not behaviour.** Neither `plan_process_evolution` nor `plan_tech_footprint` has a
corpus case that leaves its mandatory slot absent — `H04` and `H05` both resolve cleanly now. So
the menu path is *confirmed reachable* and *unexercised by any measured question*. The end-to-end
test (`test_END_TO_END_a_real_menu_a_validated_pick_and_a_reroute`) composes this response with
the disposition, the card, a refused fabrication and a bound re-route — which proves the **path**,
not that a user has ever walked it.

**Not an end-to-end live run.** The router-side fan-out does not exist
(`[[enumerate-is-not-resolve]]`), so the supervisor still cannot reach this endpoint;
`ENUMERATE_INSTANCES_URL` is unset and the disposition reports `no_provider`. The probe went
**directly** to the provider, which is exactly the hop the supervisor is missing — and getting a
clean answer from it is the strongest available evidence that the only missing piece is the
dispatch.

## Consequence for the corpus

**Two cases worth authoring**, and they cost nothing to run once the fan-out lands:

* *"how has it evolved"* with no process named → `process_id` absent → a **2-option menu**
* *"what is the tech footprint"* with no technology named → `tech_id` absent → a **5-option menu**

Those are the first questions in this system that would produce a genuine
ask-menu-pick-answer round trip. They belong in the corpus as `mandatory-missing` cases beside
`H06`, whose class is the one that cannot produce a menu — which is why `H06` alone was never
enough to test the path.


---

## ADDENDUM — the bound was corrected to 10 after this probe, and two rows RE-CLASSIFY

**The measured values above are unchanged and are not rewritten.** The distinction matters:

* **the counts are substrate facts** — `Capability` holds 9 members, `Project` holds 14. Those
  were measured and they stand.
* **the outcomes are a JUDGMENT APPLIED to those facts** — `members` vs `too_many` is whatever
  the bound says it is, and the bound moved.

Rewriting the outcome column in place would have quietly turned a measurement into a
restatement of the current ruling. So the re-classification lives here instead:

| slot | class | n | at bound **8** (probed) | at bound **10** (ruled 2026-08-30) |
|---|---|---|---|---|
| `process_id` | `BusinessProcess` | 2 | `members` | `members` |
| `tech_id` | `Technology` | 5 | `members` | `members` |
| **`capability_id`** | **`Capability`** | **9** | `too_many` | **`members` — a real menu** |
| `project_id` | `Project` | 14 | `too_many` | `too_many` |

**The correction was caused by this probe**, which is the point of having run it: the bound had
been ruled at 8 while its own worked example was *"nine capabilities is a menu"*, and nothing
had measured whether that mattered. It did — it cost `capability_id`, the most-asked slot in the
corpus, its menu.

**So `H06` now gets a real menu**, and `E05` correctly does not. *"Both live ask cases fall to
free text"* was true for one day and is now false; corrected where it was asserted.

**And `Project` at 14 still answers `too_many` at the new bound**, which is the property worth
keeping: the outcome stays reachable at the DEFAULT, rather than only by lowering the bound
inside a test. An outcome a suite can reach only by changing the thing under test is one nobody
has really checked.
