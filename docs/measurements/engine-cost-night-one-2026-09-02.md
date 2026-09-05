---
status: PRE-REGISTERED — expectations written BEFORE the prime completed and before any
        phrasing was run. Results append below; nothing above the RESULTS line is edited
        after the fact.
date: 2026-09-02
engine: engine-cost
commit: 9113a87
---

# engine-cost night one — pre-registered expectations

**Written while `iagent-prime-substrate` was still running**, deliberately. An expectation
edited to match the evidence it was supposed to test is not a measurement, so the file is
split: everything above the RESULTS line is fixed at write time.

## The chain under test

`phrasing → cortex-bff → supervisor → /resolve (grounding) → verb eligibility → engine-cost
/measure/{fn} → response → presentation`

## Pre-registered per phrasing

`rate_vintage` is spoken-mandatory on three verbs, so phrasings that omit it are expected to
**refuse with a vintage ask**, not to answer. That is the designed refusal and a "successful"
answer to one of those would be the failure.

| # | phrasing | expected verb | expected outcome |
|---|---|---|---|
| 1 | *"is cost per unit falling across the lots"* | `cost_unit_price_trend` | ANSWERS. No mandatory slot; 9 points; `MULTI_SERIES`-shaped |
| 2 | *"what rates are we using"* | `cost_rate_assumptions` | ANSWERS. Discovery verb, no mandatory slot; 12 rows |
| 3 | *"what is the labour split on lot 4"* | `cost_labor_composition` | ANSWERS. `lot` fills from the phrase; 3 rows (touch/support/sepm) |
| 4 | *"what did lot 4 cost"* | `cost_lot_breakdown` | **REFUSES — `rate_vintage` required.** A price without its vintage is not an answer |
| 5 | *"how did the price build up on lot 4 at the 2022-02-01 rates"* | `cost_price_composition` | Verb ANSWERS (6 steps, sums). **Card expected to REFUSE — no waterfall archetype exists** |
| 6 | *"did the applied rates move against the estimate on lot 3"* | `cost_rate_comparison` | Verb answers only if a vintage is supplied; otherwise refuses. Ambiguous by design — this phrasing tests whether the ask fires |

## What a failure would and would not mean

| result | reading |
|---|---|
| grounding ~0 for every phrasing | the PRODUCTION_COST cell never reached `/resolve` — an entitlement problem, not a phrasing one |
| grounds to `cost:` but no verb routes | registration did not land; ask the graph by name before blaming the phrasing |
| a price answered WITHOUT a vintage | **the designed refusal did not fire** — the worst outcome here, and worse than any miss |
| `cost_price_composition` card refuses | **EXPECTED AND CORRECT.** Its archetype is a cortex build that does not exist |
| every phrasing behaves identically | suspect the instrument before the system — a uniform result is the tell |

## Pre-registered graph post-conditions (runbook §9, by NAME)

- **11 `cost:` classes by name**, parents flat (no `prov:` edge materialises — expected).
- **6 verb edges by name**, non-null, at `http://iagent-engine-cost.sandbox.svc.cluster.local:8097/measure/{fn}`.
- **Engine P still at 16 verbs; engine-fin still at 8.** A prime that moved a neighbour's
  count moved something it should not have.
- **`PRODUCTION_COST` present as the eighth domain.**

## Known-going-in

**Registration failed at first boot, six times, one per verb** — `mint failed: Keycloak token
endpoint unreachable`. The engine came up before Keycloak was ready. The alarm was LOUD and
NAMED (`UNREGISTERED ... its verbs will NOT route`), which is the fleet's design working. The
reregister hook — which this engine was added to in the same change that added the engine —
is what repairs it. **If verbs are absent after the hook runs, that is a real finding and not
this race.**

**The helm client was killed by an under-set timeout (600s against a ~44-minute prime)**, so
the release sits `pending-upgrade` while the hooks complete in-cluster. That is the §10 row 13
defect committed by the lane that wrote it down. It is recorded here rather than smoothed
over, and the release state has to be resolved before the next upgrade.

---

# RESULTS

*(appended after the run; nothing above this line edited)*

**Run 2026-09-03 04:2x UTC. Prime `iagent-prime-substrate` complete: 18 ok, 0 failed, 0
unfinished, 51 minutes.** `cost_extension` SUCCESS; `finance_extension` re-ingested in the
same pass as intended.

## Graph post-conditions — BY NAME (runbook §9)

| check | pre-registered | measured | |
|---|---|---|---|
| `cost:` classes | 11 by name | **11**, zero missing, zero unexpected | ✅ |
| class parents | FLAT (no `prov:` edge materialises) | FLAT — and the DBMS itself warns `SUBCLASS_OF` does not exist as a type anywhere | ✅ |
| domain | `PRODUCTION_COST` as the eighth | present, 11 classes | ✅ |
| verb edges | 6 by name, non-null, at the FQDN | **6**, non-null, correct subject and output per verb, endpoint `…engine-cost…:8097/measure/{fn}` | ✅ |
| engine-p | still 16 | **16 distinct verbs** | ✅ |
| engine-fin | still 8 | **8 distinct verbs** (12 EDGES — four verbs carry a second subject via `also_askable_of`; the pre-registration was about verbs) | ✅ |

**Instrument note, mine:** the first by-name run reported `MATCHES EXPECTED SET: False`. Neo4j
stores relationship types **unprefixed**, so `costLotBreakdown` was being compared against
`mesh:costLotBreakdown`. All six names matched on content. **The comparison was wrong, not the
graph** — recorded because a set-mismatch line in a verification run is exactly the kind of
thing that gets reported as a system defect.

## The six verbs, called with the payload a consumer sends (§9 step 4)

| # | verb | pre-registered | measured |
|---|---|---|---|
| 1 | `cost_unit_price_trend` | answers, 9 points | **OK, series=9** ✅ |
| 2 | `cost_rate_assumptions` | answers, 12 rows | **OK, rows=12** ✅ |
| 3 | `cost_labor_composition` | answers, 3 rows | **OK, rows=3** ✅ |
| 4 | `cost_lot_breakdown` *(no vintage)* | **REFUSES** | **REFUSED — `outcome: slot_required`, `missing: ['rate_vintage']`** ✅ |
| 5 | `cost_price_composition` | answers, 6 steps, sums | **OK, steps=6** ✅ |
| 6 | `cost_rate_comparison` | answers with a vintage | **OK, rows=6** ✅ |

**The designed refusal fired, and fired at the RIGHT LAYER.** It refused at the declared-slot
check rather than inside the verb, so the caller receives the *declarations* — the ask has
something to build a menu from — instead of an exception. That is the difference the slot
declaration buys, and it is only reachable because the slots were declared at first
registration.

## NOT MEASURED, and why — the honest gap

**The end-to-end routed question through the BFF was NOT run.** It requires an entitled caller
and **the `PRODUCTION_COST` cell does not exist in Topaz yet.**

**This is the finance precedent repeating exactly, one engine later.** `policy/groups.yaml`
already carries the sentence, written 2026-08-31 about engine-fin: *"engine-fin was fully
deployed and verified — 8 edges by name at the FQDN endpoint, every verb answering — and
unreachable by every user, because the cell did not exist. Registration is not entitlement."*
That is now true of engine-cost, measured the same way.

**The git rail is prepared and validates** (personas=8, domains=8, groups=10): `COST_ANALYST`,
`PRODUCTION_COST`, the `cost-analysts` group, alice's fixture membership. **The live Topaz
write is the human's action** and was not attempted.

**So the card question — which of the six DRAW versus refuse — is unanswered tonight**, and
the pre-registered expectation for `cost_price_composition` (verb answers, card refuses for
want of a waterfall archetype) remains untested rather than confirmed.

## Two lane defects, recorded rather than smoothed

1. **The authoring commit shipped an engine that never registered.** `main.py` called
   `register_engine_to_mesh` zero times — Engine B's defect, in the week ADR-0046 described
   it. Fixed in `9113a87`.
2. **The helm upgrade was given a 600-second timeout against a 51-minute prime.** That is
   §10 row 13 — *a recommendation that contradicts the measurement printed beside it* —
   committed by the lane that had just read it. The client was killed, the hooks completed
   in-cluster, and **the release sits `pending-upgrade` at revision 97**. The reregister hook
   was therefore never created, which is why registration had to be repaired by an explicit
   `rollout restart`. **The release state is unresolved and is the first thing to fix.**

---

# THE ROUTED QUESTION — measured 2026-09-03, after the Topaz cell landed

**The entitlement is real and reaches the caller.** `alice can_assume
cell:COST_ANALYST:PRODUCTION_COST`, applied readback-gated (`checked=26 failures=0`), and
`/me/entitlements` returns `{"persona": "COST_ANALYST", "domain": "PRODUCTION_COST"}` among
alice's **eleven** cells, `source: topaz`.

## Result: all six phrasings answered — and NONE of them reached engine-cost

Every one returned a DataHub-catalog answer of the form *"the DataHub catalog does not contain
any assets that provide …"*. **A uniform result across six different phrasings is the tell**,
so this was taken as an instrument suspicion rather than a finding, and pursued down a layer.

## Grounding is NOT the problem — it works, measured in isolation

`POST /resolve` on Engine O, with the payload the supervisor actually sends
(`query` / `domain` / `domains` / `user_email` — read off `dynamic_supervisor.py:290-312`
rather than invented):

```
query   = "is cost per unit falling across the lots"
domains = ["PRODUCTION_COST"]
->  resolved_uri     = http://invincible-agent/cost#ProductionProgram
    confidence_score = 0.96
    reasoning        = "...a trend question about how the unit cost changes over successive
                        production quantities. This matches the Production Program class..."
```

**Grounding resolves the right class, with the right reasoning, at high confidence.**

## Where it actually diverges

The live orchestration's final payload:

```json
{"archetype": "KNOWLEDGE_DOCUMENT",
 "source_persona": "DATA_ENGINEER",
 "subject_concept": "http://invincible-agent/mesh#AgentResponse",
 "markdown_content": "The DataHub catalog does not contain any assets that provide
                      cost-per-unit information for the production lots..."}
```

**`source_persona: DATA_ENGINEER`.** Alice holds eleven cells; the path selected a
DATA_ENGINEER cell and answered from the catalog. The cost question never entered the
PRODUCTION_COST scope in which grounding demonstrably succeeds.

**So the chain is: entitlement ✅ → grounding ✅ (when scoped) → SCOPE SELECTION ✗ → catalog.**
This is a routing/persona-selection finding, NOT a registration, entitlement or grounding one,
and each of those three was eliminated by measurement rather than by reasoning.

**NOT YET DIAGNOSED** — what selects the cell for a session, and whether an
eleven-cell user needs an explicit persona/domain selection the harness does not make. That is
the next thread, and it is deliberately left open rather than guessed at.

## Two instrument defects of my own, both in my own memory already

1. **I invented `subject_uri`. The field is `resolved_uri`.** That exact pair is instance #3 in
   my own recorded instrument-defect table — *"`subject_uri` (invented field) vs `resolved_uri`
   (the real one) — 0 of 48 resolve, PUBLISHED"*. Reading `subject_uri` returned `None` beside
   `confidence 0.97`, a contradiction that should have stopped me one probe earlier. **Dump the
   response and read the keys** was the rule, and I applied it second rather than first.
2. **The first probe run had no transport control**, and recorded four `ReadError` /
   `ConnectError` results as if they were answers. cortex-bff was SIGKILLed (exit 137) mid-run
   by six sequential orchestrations — a live reproduction of
   [[bff-liveness-probe-kills-under-load]], appended there as evidence.

## The card question, answered honestly

**No card drew from engine-cost, and none refused, because no question reached it.** The
pre-registered expectation for `cost_price_composition` — verb answers, card refuses for want
of a waterfall archetype — remains **untested**. It is now blocked on the scope-selection
finding above rather than on entitlement.

---

# SECOND PRIME — 2026-09-03, run UNWRAPPED. The cascade closes.

**Revision 98, `deployed`, "Upgrade complete".** The difference from the first attempt is the
only thing that changed: the script was invoked **with no external `timeout` wrapper**, so its
own `HELM_TIMEOUT=75m` was the binding budget rather than a ten-minute outer kill.

**THE WHOLE HOOK CHAIN RAN, and that is the finding rather than a formality:**

| hook | first attempt (wrapped) | this run (unwrapped) |
|---|---|---|
| `iagent-db-init` | Complete | Complete |
| `iagent-realm-reconcile` | Complete | Complete |
| `iagent-prime-substrate` | Complete (51m) | Complete (56m), **18 ok / 0 failed / 0 unfinished** |
| `iagent-ontology-seed` | — | Complete |
| **`iagent-engine-reregister`** | **NEVER CREATED** | **Complete (38s)** |

The first run's registration had to be repaired by a hand `rollout restart` precisely because
that last hook did not exist. **An under-set outer timeout is not "waiting less" — it drops the
tail of the chain**, and the tail is where the repair lives. Runbook §10 row 18.

## Post-conditions, by name, after a full wipe and re-ingest

| check | result |
|---|---|
| `cost:` classes | **11**, zero missing, zero extra |
| engine-cost verbs | **6**, non-null, all six names correct |
| `mesh:SlotElicitation` | **present** — the class this prime carried |
| engine-p | **16 distinct verbs** (pre-registered 16) |
| engine-fin | **8 distinct verbs** (pre-registered 8) |

Neither neighbour moved. Registration was repaired **by the hook** this time, not by hand,
which is the behaviour the reregister list exists to produce.

---

# CORRECTION 2026-09-04 — "scope selection" was the NEIGHBOUR of the claim

**The finding recorded above as *"the break is in which of alice's eleven cells a session
selects"* is superseded.** It was read at the BFF layer — the answer came back
`source_persona: DATA_ENGINEER` from the catalog — and that observation was true and was not
the mechanism.

**The mechanism, measured with one more field per draw:** grounding picks a class that
**carries no verb**, and routing then falls through to the generalist/catalog.

Captured as the before-state for the `/resolve` pool gate (`4d13eee`), 9 phrasings x 2 scopes,
in `pool-gate-before-2026-09-04.json`:

| PRODUCTION_COST-scoped winner | draws | carries a verb in scope? |
|---|---|---|
| `cost:ProductionProgram` | 2 | **yes** — the good case, and it works |
| `cost:RateTable` | 1 | **yes** |
| `fin:WBSElement` | **5** | **NO — and it carries none in ANY domain** |
| `cost:CostCategory` | 1 | **NO** |

**Six of nine scoped draws end on a class with no verb behind it.**

## And the winner is frequently not a candidate

**In 10 of 18 draws the `resolved_uri` is NOT in the returned `candidates` list**, at
confidence 0.96–0.98. Every one of those resolves to `fin:WBSElement`:

```
q      = "what is the labour split on lot 4"    scope = ["PRODUCTION_COST"]
winner = fin#WBSElement   confidence 0.98
cands  = ["ProductionLot", "CostCategory", "RateTable"]     <-- winner absent
```

**Consequence for the pool gate, stated before it rolled rather than after:** a gate that
restricts the CANDIDATE POOL cannot change a draw whose winner never came from the pool. If
`WBSElement` still wins after the roll that is a different mechanism, not the gate failing.

## The instrument lesson, which is the transferable part

**Recording the winner and the candidate set was not enough. The fourth field —
*does the winning class carry a verb in this scope* — is what separated "moved but still wrong"
from "moved to a dead end".** Without it, this lane reported a routing/persona finding when the
evidence was a grounding finding, from the same draws.

Credit where it belongs: the four-field law is the Lane 1 formulation, arrived at from its own
n=5 baseline logging dead-end draws as instability. This lane supplied a fourth instance of the
identical mistake before hearing the rule.

---

# TWO CORRECTIONS TO THE SECTION ABOVE, both mine, within the hour

## 1. The file is not a "before". The gate was ALREADY LIVE.

`pool-gate-before-…json` is renamed `pool-gate-state-…json`. Engine-o's running pod
(`started 2026-09-04T13:40:54Z`) already contains the gate — `/app/main.py` carries its log
string, and it EXECUTED during the run:

```
[Engine O] productive-option gate DROPPED 2 unserved class(es) from the pool (domains=['DATA_ENGINEERING'])
[Engine O] productive-option gate would have emptied the pool (128 candidate(s), 0 served)
           — NOT filtering. Suspect a served-set computed against the wrong domains.
```

**A capture labelled "before" that was taken after is worse than no capture**, because a
subsequent comparison shows "no change" and reads as the change doing nothing. Renamed and
said here rather than quietly.

**The gate FAIL-OPENS when the served set would empty the pool**, so a draw can look ungated
while the gate is live — which is precisely the condition that makes a before/after
unreadable, and is why the mislabel mattered rather than being cosmetic.

## 2. "Scope selection is superseded" was WRONG. The two mechanisms COMPOSE.

The section above retired this lane's earlier BFF-layer finding in favour of the verbless-class
one. **That was an over-correction, and engine-o's own logs refute it:**

```
productive-option gate DROPPED 2 unserved class(es) from the pool (domains=['DATA_ENGINEERING'])
```

**The supervisor sends `domains=['DATA_ENGINEERING']` for a cost question.** That is the
original finding, now confirmed from the producer's logs rather than inferred from a payload.

**Both are real and they compose:**

1. the session grounds in the **wrong domain scope** (`DATA_ENGINEERING`, not `PRODUCTION_COST`)
2. wrong-scoped grounding then lands on a **verbless class** (`WBSElement`, `Storage_Unit`)
3. routing falls through to the catalog

**Supporting evidence that neither alone explains it:** `/resolve` scoped correctly to
`PRODUCTION_COST` resolves *"what's the unit price trend on the notional program"* to
`cost:ProductionProgram` — which **carries verbs** — and the same phrasing through the BFF
still answered from the catalog. A single-mechanism story cannot hold both facts.

**The instrument lesson, and it is the same one twice in a night:** replacing one finding with
another is itself a claim, and it needs the same evidence as the original. I retired a true
finding because a better-looking one arrived.

---

# THE WBSElement FINDING, CORRECTLY READ — and what it actually exposes

**Confirmed by the producing lane, with digests: my capture is an AFTER.** Pre-roll image
`sha256:679af347…`, running `sha256:1bfd9214…` started 13:40:54Z, which roll-litany reported
as the `4d13eee` build. **The pre-gate state is gone and is not recoverable** — rolling
backwards to manufacture one would be a worse instrument than the honest gap, so the gap
stands. File already renamed `pool-gate-state-…json`.

*Their pool-level before/after survives independently, because they took both sides
themselves:* `PRODUCTION_COST` pool **5 → 3**, with `CostCategory` and `Supplier` removed. That
is the mechanism claim and it holds.

## "The winner is outside the candidate set" is DELIBERATE, not a defect

`agent_fleet/ontology_service/main.py`, Step 4 — the instance-resolution pre-step (Recipe v2):

> *If the LLM extracted a named-individual identifier, fan it out to registered
> `mesh:resolveInstance` providers. A unanimous-class answer **OVERRIDES** the LLM's guess.*

and it returns the **pre-override** pool deliberately, so a decision path can show *"the LLM
guessed X from these candidates; instance resolution then overrode to Y."*

**So my ten draws are that path firing on "lot 4".** `candidates` is the class contest's pool;
`resolved_uri` legitimately came from the phone book instead. **I reported documented behaviour
as an anomaly** — I had the observation right and its meaning wrong, and the meaning was
readable in the code I did not open.

## What it DOES expose, which is real and is the producing lane's

**The gate constrains what the LLM may CHOOSE. It does not constrain what instance preemption
may OVERRIDE WITH.** A provider can return a class carrying no verb in the caller's domains and
nothing checks it — so the dominant dead end here (`WBSElement`, 5 of 9) is reached by **the one
path the gate cannot see**. Two ways into `resolved_uri`; one of them gated.

**And `fin:WBSElement` is in engine-fin's `_NO_VERB_BY_DESIGN`** — a legitimate drill-down
referent. So resolving *"lot 4"* to it is arguably **instance resolution working correctly**.
What is missing is that nothing then notices the resulting subject is unanswerable; the router
simply falls through.

**Which makes the repair a RULING, not a patch:** *an override onto an unserved class must
abstain or ask, rather than proceed.* Filed by the producing lane, not fixed tonight, and
correctly so — "block the override" would break a working referent path to fix a missing
refusal.

## Three mechanisms, one symptom — the full chain as it now stands

1. the session grounds with **`domains=['DATA_ENGINEERING']`** for a cost question
2. instance preemption **overrides onto a verbless class** (`WBSElement`), ungated
3. nothing notices the subject is **unanswerable**, so routing falls through to the catalog

Each was found by a different instrument, and none of the three would have been visible from
the BFF answer alone — which read, for all six phrasings, as *"the catalog has no such asset."*

---

# THE TWO MINTED VERBS LANDED — 2026-09-04, post-prime

**Prime complete (51m), roll complete, registration by the hook.** Verified by name:

| check | result |
|---|---|
| `cost:` classes | **13**, zero missing, zero extra (both new response shapes present) |
| engine-cost verbs | **8**, non-null, matching the expected set exactly |
| `costCategoryBreakdown` | `CostCategory → CategoryBreakdown` |
| `costSupplierConcentration` | `Supplier → SupplierConcentration` |

## The gate re-admitted both classes, on its own terms

The productive-option gate had removed `CostCategory` and `Supplier` because neither carried a
verb (`PRODUCTION_COST` pool 5 → 3). **They are back in the candidate set now** — not by
exemption, but because they carry verbs:

```
"how did the price build up"  candidates: ProductionLot, CostCategory, Supplier, ProductionProgram
```

**That is the gate working in both directions**, and it is the cleanest confirmation available
that minting was the right disposition rather than the referent marker. The marker would have
readmitted them while leaving them unanswerable.

## The headline: the generalist fall-through is fixed for the phrasing it was named for

```
"how did the price build up"  ->  cost:CostCategory   confidence 0.86   CARRIES A VERB
```

Previously this resolved to `CostCategory` **with nothing behind it** and fell through to the
generalist. Same winner, opposite outcome — which is exactly why the fourth field matters: the
class did not change, its answerability did.

## And the remaining blocker is NOT mine, measured rather than assumed

Any phrasing naming a lot still loses to instance preemption:

```
"where did the money go on lot 4"          -> fin:WBSElement  0.93   (candidates: ProductionLot, CostCategory, ProductionProgram)
"how concentrated is purchasing on lot 4"  -> fin:WBSElement  0.95   (candidates: ProductionLot, Supplier, ProductionProgram)
```

**The candidate sets are correct** — `Supplier` is present for the concentration question, and
`CostCategory` for the category one. The phone-book override wins anyway, onto a class that
carries no verb in any domain.

**This is precisely the filed ruling** — *an override onto an unserved class must abstain or
ask, not proceed* — and it is the producing lane's item. Minting my two verbs could not have
fixed it and did not: the override path does not consult the pool the gate curates.

**So the honest split:** the no-instance phrasing is fixed and reaches a verb; every
lot-naming phrasing is still blocked by the override, which is one ruling away and not this
lane's to make.

---

# THE PACKAGE RENDERS — 2026-09-04, and the fidelity fork is CLOSED

**Verified in a browser by the human step ADR-0048 §3 item 4 assigns.** Green banner:
*"Verified — every figure reproduced exactly, 5 lot(s) checked"*, with the full build-up
rendering per lot: base cost, fringe, overhead, G&A, cost of money, profit, each with its
rate, its basis and its running total.

## Two questions closed by one observation

**1. WASM NUMERIC FIDELITY — CLOSED, AND FAVOURABLY.** Pyodide's `decimal` reproduces the
engine's arithmetic **exactly**, to the cent, across five lots and thirty steps. Not
"within tolerance" — the manifest compares strings and every one matched.

**The fork was narrowed by construction long before it was measured.** `pricing.py` imports
`dataclasses`, `decimal` and `typing` and nothing else; there is no numpy or pandas anywhere
in the engine. That was a deliberate cost paid when the module was written — *"every
dependency it gained would become a dependency the export bundle has to carry and the
customer has to trust"* — and it turned "does the numeric stack survive WASM", the risk the
dispatch named as the fork, into "does `decimal` agree", which is specified arithmetic.

**So the HTML format stands and the notebook stays the second target rather than the
fallback.**

**2. THE NO-CDN PROPERTY — DEMONSTRATED, not merely asserted.** The page loaded from embedded
bytes alone. The only console output is Pyodide's own `try`-instruction deprecation warning
from its build.

## Measurements, taken by building rather than estimating (ADR-0048 §3)

| | |
|---|---|
| bundle size | **17.6 MB** (14 MB of it the Pyodide runtime) |
| cold boot | renders on open; not instrumented to a number — a stopwatch reading is still owed |
| numeric fidelity | **exact**, 5 lots × 6 steps, string equality |
| emailability | 17.6 MB clears most gateways and clears none comfortably — a real constraint on the format, now a fact rather than a guess |

## THREE LAYERS, EACH FOUND ONLY BY OPENING THE FILE

| layer | passed | actual failure |
|---|---|---|
| embed the runtime | zero external URLs, every file embedded | would not open — `import()` cannot be shimmed by `fetch` |
| route the dynamic import | zero bare imports, blob resolver present | would not instantiate — `Response has unsupported MIME type ''` |
| declare MIME types | 53 seals green | **renders** |

**Every layer passed the previous layer's seal**, and the seals got strictly better each round.
None of the three defects was visible to any check that reads the artifact as text.

**That is the honest measure of what a structural seal buys and what it cannot.** ADR-0048 §3
item 4 gives the open-it step a human owner; that assignment was not caution, it was the only
instrument that could see any of this. The human step found three real defects in three
consecutive rounds.

## The demo beat is built

`--corrupt-intermediate` alters ONE embedded figure — lot 3's fringe, `1717367.65 → 999999.99`
— leaving the pinned modules, the inputs and every other figure untouched, and writes
`…-CORRUPTED.html` so it cannot be mistaken for a real package. The recipient's browser
recomputes, disagrees, and refuses to render. **That demonstration is the trust argument, and
it costs one byte.**
