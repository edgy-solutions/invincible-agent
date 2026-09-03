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
