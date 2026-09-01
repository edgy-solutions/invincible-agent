# Engine F — end-to-end routing, v1

**PRE-REGISTERED 2026-08-31, BEFORE THE CORPUS RAN.** Results appended below; nothing above
the results line is edited afterwards. An expectation quietly revised to match its outcome is
not a measurement.

**Why this exists.** `engine-f-verb-exercise-v1.md` closed with a stated limit: *"routing was
not tested. A green result means the verbs are correct and their registration data is coherent.
It does not mean a spoken question reaches them."* This is that missing half — the one thing
Engine F has never had.

---

## The chain under test

```
/resolve   (phrase + alice's entitlement key)  ->  an OntologyClass      [GROUNDING]
/find_tool (that class + a verb label)         ->  an endpoint_url       [ROUTING]
```

Both hops are **read-only** and neither edits Lane 1's surfaces.

**Grounding is domain-scoped to the caller's cells**, so hop 1 is simultaneously the first
proof that alice's `PROGRAM_FINANCE_ANALYST · PROGRAM_FINANCE` cell — written to Topaz tonight,
readback-gated `checked=24 failures=0` — actually reaches the class pool. Before it, the
fourteen `fin:` classes were scoped out of every caller's pool.

---

## Pre-registered expectations

### Hop 1 — grounding

20 phrasings across the six verbs, each an analyst's natural wording rather than a formal
label. **Expected: a clear majority ground to a `fin:` class at all** — that is the cell
working — and a **lower** rate ground to the *exactly right* class, because four of the six
verbs share two subjects (`Program` ×2, `PerformanceMeasurementBaseline` ×2) and the resolver
cannot know which of a shared subject's verbs was meant. That is hop 2's job, not hop 1's.

**A grounding rate near zero means the cell did not take**, not that the phrasings are poor —
and the two are distinguishable, which is why "grounded to ANY `fin:` class" is reported
separately from "grounded to the right one".

### Hop 2 — routing

Tested twice, deliberately:

* **by raw phrase** — the honest end-to-end case. Expected to be the **weaker** number:
  `/find_tool` matches a verb label or a registered synonym, and a whole sentence is neither.
* **by registered synonym** — the fair test of the synonym lists I wrote. **Expected near
  perfect.** A miss here is a defect in Engine F's registration, which is mine; a miss on the
  raw phrase is a statement about the matcher, which is not.

Reporting only the first would understate the registration; reporting only the second would
overstate the system. Both, with the distinction named.

### The IPMDAR collision, through the real resolver

The night sweep measured **16.2% of realistic partial phrasings** producing a tied-at-top
mixed-class candidate set in Engine F's own provider. That was measured at the provider.
**This is the first look at what the ROUTER does with it** — whether a tie abstains, or whether
a top-scoring exact match carries it through anyway. Five collision phrasings are probed.

**No expectation is registered for this**, deliberately: the decision table is Lane 1's code
and I have not read it. An expectation invented here would be a guess wearing a prediction's
clothes. The measurement is the deliverable, and it is the evidence ADR-0033's fourth consumer
was scoped without.

---

## What a failure here would and would not mean

| result | reading |
|---|---|
| grounding ~0 | the Topaz cell did not reach `/resolve` — an entitlement problem, not a phrasing one |
| grounding high, right-class low | expected; shared subjects, hop 2 disambiguates |
| synonym routing < 100% | **Engine F's registration is wrong** — mine to fix |
| phrase routing low | the matcher is lexical; a finding about the chain, not about Engine F |
| collision ties resolve anyway | the fourth-consumer case is latent rather than live |

---

*Results appended below this line. Nothing above is edited.*

---

# RESULTS — 2026-08-31, after the prime and the Topaz seed

**Nothing above this line was edited after execution.**

## Headline

| measurement | result | pre-registered as |
|---|---|---|
| grounded to **any** `fin:` class | **8 / 20** | the cell working |
| grounded to the **right** `fin:` class | **7 / 20** | expected lower than the above |
| routed by **registered synonym** | **7 / 7** | *"expected near perfect; a miss is MY defect"* |
| routed by **raw phrase** | **3 / 20** | *"expected the weaker number"* |

**The discriminator the pre-registration named came out clean. `7/7` on synonyms means Engine
F's registration — verb labels, synonyms, subjects, endpoints — is correct end to end.** Every
one lands on the right verb at the right FQDN endpoint:

```
Program                        + "EAC"                  -> finEacCalculation
Program                        + "variance analysis"    -> finVarianceAnalysis
PerformanceMeasurementBaseline + "CPI"                  -> finPerformanceIndices
PerformanceMeasurementBaseline + "burn rate"            -> finBurnRate
ControlAccount                 + "variance drivers"     -> finVarianceDrivers
FundingLine                    + "funding status"       -> finFundingStatus
```

**`3/20` by raw phrase is not a defect and the pre-registration said so before seeing it.**
`/find_tool` matches a verb label, IRI, or registered synonym; a whole sentence is none of
those. The three that hit did so because a synonym happens to be a contiguous substring.

## The real finding: grounding, not routing

**Alice's cell works** — 8 of 20 phrasings reach a `fin:` class, which was zero before tonight.
That is the Topaz write, `/resolve`'s domain scope, and the 14 seeded classes all functioning.

**But only `fin:Program` competes.** Broken down by intended subject:

| subject | grounded | note |
|---|---|---|
| `fin:Program` | **7 / 8** | "Meridian", "program", "overrun" are distinctive |
| `fin:PerformanceMeasurementBaseline` | **0 / 6** | lost to `DescriptiveDataModule`, `ProcedureDataModule`, BFO/IOF classes |
| `fin:ControlAccount` | **0 / 3** | lost to IOF `Procedure`, `Agent`, `ProcessCharacteristic` |
| `fin:FundingLine` | **0 / 3** | lost to `DescriptiveDataModule`, IOF `Agreement` |

**The cause is pool width, not definition quality alone.** Alice holds **seven** cells —
AVIATION, DEFENSE, ENTERPRISE, DATA_ENGINEERING, MAINTENANCE, PORTFOLIO_PLANNING and now
PROGRAM_FINANCE — so domain-scoping narrows the candidate pool to *everything she can see*,
which is most of the graph. The finance classes compete against MRO, IOF and BFO vocabularies
for phrases like *"how fast are we spending"*, and lose.

That is a genuine consequence of the fixture posture recorded in `users.yaml`: alice is a
power user *"wearing"* many entitlements, and every added cell widens her pool. **A real
finance analyst holding one cell would see a far narrower pool** — so this number is a floor,
not a ceiling, and it should not be read as "finance grounding is 40%".

**Not fixed tonight, deliberately.** The lever is `rdfs:comment` — the recall signal — and I
have already rewritten those definitions once today (moving sibling contrasts out). Churning
them again without a measurement designed for it would be tuning against a single corpus, and
every change costs another 46-minute prime. Filed with the evidence instead.

## The IPMDAR collision, through the real resolver — first look

| phrase | grounded to |
|---|---|
| `variance on Test` | **`fin:ControlAccount`** |
| `variance on Integration and Test` | **`fin:ControlAccount`** |
| `how is Software doing` | `FaultIsolationDataModule` |
| `Program Management costs` | IOF `BusinessFunction` |
| `Engineering overrun` | BFO_0000144 |

**The two collision cases that reach finance resolve cleanly to `ControlAccount` rather than
abstaining.** No expectation was registered here — the decision table is Lane 1's — and the
observation is that at the CLASS-grounding layer the tie does not surface as an abstain; a
winner is picked. The tie the night sweep measured (16.2% of partial phrasings, four classes at
0.75) lives in Engine F's *instance* provider, one layer below this.

**So the fourth-consumer case is LATENT rather than live at this layer**, which is new
information and the opposite of what the packet assumed was worth scoping urgently. The other
three collision phrasings never reach finance at all — they lose the grounding contest first,
which means the collision cannot even be reached for them.

## Instrument failures, mine, caught

**Third and fourth instances of one error class in two days.**

1. **`/find_tool`'s response nests under `step`.** I read `b.get('verb')` at the top level and
   got **0/20 and 0/7** — with HTTP 200 on every call. The tell was the uniform extreme
   result: `"EAC"` and `"burn rate"` are registered synonyms and cannot all miss. Corrected to
   `step.verb_type` / `step.endpoint`; the true numbers are 3/20 and **7/7**.
2. **`SUBCLASS_OF` is spelled `subClassOf`.** My post-condition query reported `parent=none`
   for all three new archetype classes. They are all `subClassOf mesh:Archetype`.
3. **`grep -c '[SUCCESS] '` counted a non-ingest line** (`[SUCCESS] All canonical TTLs
   uploaded.`), reporting 17/17 when `mesh_system` — the ingest carrying the three new classes
   — was still running. Nearly declared the prime finished one ingest early.

All three are the same shape: **a query or count that returns something plausible while
measuring the wrong thing.** In every case the tell was a value too uniform or too round to be
real. This is now the standing signature, and it has fired four times in two days.

---

# CORRECTION 2026-09-01 — the grounding number above measured MAINTENANCE, not alice

**The results section above is left standing and its CAUSE is retracted.** An expectation or an
explanation quietly edited to match later evidence is not a measurement, so the error stays
visible and the correction sits beneath it.

**What was wrong.** `/resolve`'s model is `domain: str = "MAINTENANCE"` with
`domains: list[str] = []` superseding it **only when non-empty**. The corpus run passed
`user_email` and **neither domain field**, so the candidate pool was scoped to **MAINTENANCE**.
The write-up attributed 8/20 to *"alice holds seven cells so the pool is wide"*. That
explanation was invented, not measured — and the losers it cited (`DescriptiveDataModule`,
`ProcedureDataModule`, IOF `Procedure`) are maintenance vocabulary, which should have been the
tell.

**The control proves it.** Re-run with no `domains`, twice, on two different primes:
**7/20 right, 8/20 any-fin — exactly reproducing the original.**

| arm | right | any `fin:` |
|---|---|---|
| **C** no `domains` → `MAINTENANCE` | 7/20 | 8/20 |
| **B** alice's seven domains | 12/20 | 19/20 |
| **A** one cell, `PROGRAM_FINANCE` | **12/20** | **19/20** |

**Passing the scoping field at all is what matters: any-`fin:` grounding goes 8 → 19 of 20.**

**And the second hypothesis is refuted too.** A and B are identical, so **pool width was never
the cause** — a one-cell analyst does no better than a seven-cell power user, and the
improvement predicted for the narrow arm did not occur.

**The real cause is that a verb's OUTPUT shape competes with its own INPUT subject** for the
question that invokes it, and grounding to an output is a hard dead end. Full analysis, the
definition rewrite it prompted (+1, `11 → 12`), and the structural fix that prose cannot reach:
`[[response-classes-compete-for-grounding]]`.

**Standing correction to the routing summary above:** `7/7` synonym routing and `3/20` phrase
routing are unaffected — those hops never took a domain argument. Only the grounding numbers
and their explanation are restated here.
