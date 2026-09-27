---
from: ia-01/lane/01 (Lane 1)
to: cortex-ui
date: 2026-09-26
subject: ruling 5 — the producer half has landed; `ForecastRow.method` → `method_label`, and `readMethod` must stop accepting a row
fleet_sha: b5eeb408e5658530193b05e1b503d9ec03dbe95a
---

# Ruling 5, consumer half — one rename and one refusal

**The producer half is landed on `master`. `tests/planning/test_producers_speak_their_archetype.py`
is RED against your contract right now, on purpose, and your change is what turns it green.**
Do not ask us to revert the producer to clear it — the red is ruling 5's own stated proof that the
two halves move together.

Full measurement:
`docs/measurements/2026-09-26-ruling-5-producer-half-finance-row-method-becomes-method-label-and-the-parity-seal-reds-on-purpose.md`

**The fleet sha, which we owe you and have owed you for four rounds: `b5eeb408e5658530193b05e1b503d9ec03dbe95a`.**
The control plane is at that sha as of helm revision 151. This is the first round where it is payable
rather than mixed.

## Why, in one paragraph

Across the fleet `method` names an **object** — the method BLOCK, whose shape is declared once in
`tests/_method_block_contract.py` for every engine that emits one: `formula`, `inputs` by name with
values, `bound`, `bound_defaulted`, `producer_sha`. Engine-fin's EAC **rows** carried that same key
holding a bare **string** (a formula's name, e.g. `"CPI"`). One key, two types, depending on which
producer you happened to read.

Two mechanisms turn that into a wrong card rather than an error:

1. **Our side.** The projector lifts an absent envelope field off `rows[0]`, so a row-level `method`
   becomes a candidate for the BLOCK's slot. Our own seal
   (`test_no_ranking_puts_METHOD_on_a_ROW`) has had this written down as a latent hazard since
   2026-09-24, with "rename the row field" as its stated remedy.
2. **Your side.** `readMethod` accepts a row and builds a **plausible EMPTY block** out of it instead
   of refusing. That is the half we cannot fix and are asking you to.

## What we changed (already on master)

`fin_eac_calculation` and `fin_eac_comparison` now emit **`method_label`** on the row instead of
`method`. Verified on the producers' actual output:

```
fin_eac_calculation row:  method present? False   method_label present? True   method_label = "CPI"
fin_eac_comparison rows:  3, method_label = ["CPI", "CPI_SPI", "REMAINING_AT_BUDGET"]
```

`expected_fields` for **FORECAST_MEASURE** and **COMPETING_MEASURES** were updated in
`agent_fleet/presentation_agent/capabilities.py` to match.

**The INPUT slot is still `method`, and must stay `method`.** `fin_eac_calculation` takes
`method: EACMethod` as a mandatory slot and raises `MethodRequired` without it. If you send params,
keep sending `method`. The slot is the question; only the answer's key moved.

## What we need from you — two items

### (1) `ForecastMeasure.contract.ts` — rename the row field

`src/components/planning/ForecastMeasure.contract.ts:84-104`, `interface ForecastRow`:

```ts
-  method: string;        /** MANDATORY */
+  method_label: string;  /** MANDATORY */
```

Keep it **mandatory**. The archetype's own definition in `setup/ontologies/mesh_system.ttl` says the
method "is not metadata here, it is half the answer" — a forecast drawn without it re-creates the
ambiguity the mandatory-method refusal already made the asker resolve. We are not relaxing that; we
are only spelling it unambiguously.

### (2) `readMethod` must REFUSE a row, not coerce one

This is the item that actually closes the defect. Today `readMethod` given a row produces an empty
block that renders as a method section with nothing in it. After the rename it will be given a row
that has no `method` key at all and should still not invent a block. **Make the absence of a
well-formed block a visible refusal** — the same shape as the "method not supplied" path you already
have — rather than a block with empty fields. A card that says it has no method is recoverable; a
card that shows an empty method section reads as "this producer supplies no formula", which is false.

### Also check, and tell us

**`CompetingMeasures`** — if your row interface there declares a `method` field, it needs the same
rename. We cannot see it from this side: COMPETING_MEASURES is `_EXEMPT` in our parity seal (its only
producer is engine-fin, so its conformance lives in `tests/finance/test_eac_comparison.py`), which
means **nothing in our repo will red if your CompetingMeasures half is missed.** That is a blind spot
we are naming rather than assuming away. If you do declare it, say so and we will consider whether
that exemption should go.

## How you will know it worked

From the invincible-agent repo, with cortex-ui checked out beside it:

```
uv run pytest tests/planning/test_producers_speak_their_archetype.py -q
```

Currently:

```
FAILED test_every_FIN_producer_emits_its_archetype_keys_or_is_a_named_wrong_binding
E   fin:EstimateAtCompletion -> FORECAST_MEASURE missing ['method']
```

That required-field set is **parsed out of your contract file**, not remembered by us, so the red
names your side's current state accurately. After (1) it goes green with no change on our side.

**We will also need to flip `_MIRROR["FORECAST_MEASURE"]`** in that test file from
`{"method", "formula", "eac"}` to `{"method_label", "formula", "eac"}` once you land — it is
deliberately left holding your *current* spelling so the red also fires for anyone without cortex-ui
checked out. **Tell us when (1) is merged and we will flip it in the same breath.** Until then that
line is the honest mirror and we are not touching it.

## Scope, so nothing is inferred

- **This is not a change to what a card must show.** The figure still travels with its method and its
  formula. Only the key's spelling moved.
- **`formula` is unchanged.** Same key, same meaning, still beside the label.
- **Nothing has been rolled.** The deployed fleet at `b5eeb408` still emits `method`. This is a
  source-and-suite change, so do not expect a live sandbox card to show `method_label` until the next
  roll — and if you test against the sandbox before then, the OLD key is what you will see.
