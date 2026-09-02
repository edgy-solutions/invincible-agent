---
id:         four-subjects-means-four-questions
status:     open
owner:      agent (Engine F lane) — MINE: the subjects are my authoring decision
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0045 (Engine F verbs over IPMDAR entities); ADR-0031 (instance resolution ladder); ADR-0033 (route | ask | abstain)
code-site:  agent_fleet/finance_agent/main.py (VERBS, the input_uri per verb), setup/ontologies/finance_extension.ttl (the eight subject nouns)
summary:    ENGINE F'S SIX VERBS DECLARED FOUR DIFFERENT SUBJECTS, so which verbs were reachable depended entirely on which class the grounding step picked — and a question naming the PROGRAM could only ever reach two of six. Measured 2026-09-02: `subject_uri=fin#Program compatible_count=2`, and the classifier correctly returned no_match for burn rate, funding status and CPI/SPI because those verbs hang off fin:PerformanceMeasurementBaseline / fin:FundingLine / fin:ControlAccount, which the question never mentioned. The classifier was right every time; the modelling was right; the question was still unanswerable — an information gap wearing a threshold gap's clothes. RULED and FIXED: `fin:Program` is now declared as an ADDITIONAL subject on the four verbs (6 registrations -> 10), leaving each verb's primary subject as the thing it actually MEASURES. The relation-following ladder step is filed as the ADR-0045 amendment question, deliberately NOT built — it is a resolver capability with fleet-wide blast radius. IMPLEMENTATION TRAP, measured before building: two subjects need two registration NAMES, because the registrar's sweep deletes rows matching (tool_urn, verb_iri) with a different input_uri and the name IS the tool_urn — 0 of 46 engine rows held two subjects under one name, and Engine A's findSchema is the precedent for doing it right. Sealed and bite-checked.
---

# Four subjects means four questions — and a user only asks one

## The measurement

Engine F's registered verbs, read from the Predicate collection:

| verb | subject it routes FROM (`input_uri`) |
|---|---|
| `finEacCalculation` | `fin:Program` |
| `finVarianceAnalysis` | `fin:Program` |
| `finBurnRate` | `fin:PerformanceMeasurementBaseline` |
| `finPerformanceIndices` | `fin:PerformanceMeasurementBaseline` |
| `finFundingStatus` | `fin:FundingLine` |
| `finVarianceDrivers` | `fin:ControlAccount` |

**Four subjects.** Grounding picks ONE, and that pick decides which verbs are even candidates.

Three questions, all naming the program, all grounding to `fin:Program`:

```
classify_predicate no_match  query='What is the burn rate for the Notional Program Meridian?'
  subject_uri=fin#Program  compatible=['mesh:finEacCalculation','mesh:finVarianceAnalysis']
  reasoning='...burn rate...is not covered by finEacCalculation (forecast cost) or
             finVarianceAnalysis (variance explanation), so no available predicate matches.'
```

Identical shape for funding status and for CPI/SPI. **The classifier is correct every time.** It
was handed two verbs, neither of which answers the question, and said so.

## Why this is not a routing defect

`compatible_count=2` is the whole story: the eligible set was built from the grounded subject, and
four of the six verbs were never in it. No threshold, no phrasing and no confidence tuning reaches
them, because they were never candidates. **This is an information gap wearing a threshold gap's
clothes** — the same shape `finance_agent/slots.py` opens with, one level up.

## Why the modelling is nevertheless defensible

Each verb hangs off the IPMDAR entity it actually measures. Burn rate is a property of the
performance measurement baseline, not of the program; funding status is a property of a funding
line. Re-pointing all six at `fin:Program` would make the ontology lie about what the numbers
describe, and would put six verbs in one eligible set where the classifier must separate them by
prose alone.

**So the defect is not the subjects. It is that nothing connects them.**

## What is actually missing

A traversal: *this Program has this PMB; these Control Accounts; these Funding Lines.* The
relations exist in the seed data — the ontology has the structure — and the resolution ladder has
no step that says "the subject you grounded is a `fin:Program`, the verb you want hangs off its
PMB, here is that PMB's id."

Until that exists, the reachable question set is:

| a user who asks about… | can reach |
|---|---|
| the program by name | EAC, variance analysis |
| the baseline | burn rate, performance indices |
| a funding line | funding status |
| a control account | variance drivers |

**A person asking about a program does not know they must name its baseline instead**, and
nothing in the ask tells them — the honest refusal names no path forward, because from
`fin:Program` there is none.

## Options

1. **A relation-following step in the resolution ladder** — grounded subject → related instance
   whose class hosts a compatible verb. General, and the only one that fixes the class of problem
   rather than this instance of it. Also the largest.
2. **Verbs accept the parent subject and resolve down internally** — `fin_burn_rate` takes a
   `program_id` and finds the PMB. Cheap, and it dissolves the modelling: the verb's declared
   subject would no longer describe what it measures.
3. **Declare the additional subject explicitly** — register `finBurnRate` against BOTH
   `fin:PerformanceMeasurementBaseline` and `fin:Program`. Honest at the registration layer (a
   verb genuinely IS askable of a program), costs nothing structurally, and is testable today.
   ADR-0030 is unaffected — one verb still has one output type.

**RULED 2026-09-02 (architect): take (3) now, file (1) as the ADR-0045 amendment question, do
NOT build traversal.** The reasoning, recorded because it is the reusable half: the classifier
was handed two verbs and picked correctly every time, so the defect is that four verbs declare
subjects no natural question names — a program manager says "Meridian", not "Meridian's
performance measurement baseline". Declaring `fin:Program` as an ADDITIONAL subject is honest
(the question genuinely is about the program; the PMB is HOW the engine answers it), it is a
registration change inside this engine, and it is measurable tonight. The relation-following
ladder step is the prettier answer and a RESOLVER capability with fleet-wide blast radius —
which is exactly why it wants an amendment and not a night's unilateral build.

### Implementing (3) turned up a trap that would have made it silently self-defeating

**Registering one verb twice under one registration NAME deletes the first edge.** The
registrar's compensate-on-rescope sweep removes rows matching `(tool_urn, verb_iri)` whose
`input_uri` differs from the one being written — which is what makes a re-registration an UPSERT
rather than a duplicate. The registration name IS the tool_urn.

Measured before building: **0 of 46** engine verb rows held two subjects under one
`(tool_urn, verb_iri)`. The precedent for doing it correctly already exists — Engine A's
`findSchema` carries BOTH `idp:Column` and `idp:Dataset`, under `engine_a_find_schema_column`
and `engine_a_find_schema`. **Two subjects means two names**, and this follows that idiom rather
than inventing one.

Sealed in `tests/finance/test_second_subject_survives_the_sweep.py`, bite-checked: collapsing
the two names back to one produces 4 colliding `(name, verb)` pairs and the seal fails. Without
it, a later "simplification" would delete the four primary subjects with no error and a green
startup.

Registrations: 6 → 10. `fin:Program` now hosts all six verbs; the primary subjects are unchanged,
and a seal asserts the accommodation has not replaced the modelling.

## Related

* `[[planning-classes-have-the-same-routable-asymmetry]]` — the same asymmetry measured on the
  class side; this is its verb-side twin, and the pair is the argument that it is structural.
* `[[a-mandatory-slot-does-not-refine]]` — the other seam on this path; that one stops all six,
  this one stops four.
* `[[a-plausible-negative-is-not-a-considered-one]]` — `no_match` here IS considered, and that is
  what makes it worth reporting rather than tuning away.
