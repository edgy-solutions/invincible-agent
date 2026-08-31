---
id:         the-specificity-gate-strips-content-words
status:     open
owner:
blocked-on:
repo:       invincible-agent
code-site:  agent_fleet/ontology_service/instance_resolution.py (_ENV_SUFFIXES, candidate_asset_name, identifier_name_and_qualifiers, passes_segment_specificity)
summary:    MEASURED. `passes_segment_specificity(x, x)` returns FALSE — a name cannot match itself — for any space-separated label whose final word is one of prod|dev|test|stage|staging|qa|uat. "Integration and Test" yields name `test` on the IDENTIFIER side and asset name `and` on the CANDIDATE side, because only the candidate side strips env suffixes. The two halves of the comparison are computed by different functions with different rules. Blast radius is human LABELS, not catalog ids: `my_dataset_prod` is one segment and passes. This is why every one of engine-fin's tied cases returns `not_specific` — the decision table never reaches the tie, and fixing engine-fin's field names is necessary but NOT sufficient for the ADR-0033 disambiguation case.
---

# The specificity gate strips content words, and a name cannot match itself

## The tie check could not measure ties

Feeding engine-fin's tied-at-top cases through the real decision table:

| identifier | tied at top | `instance_match` |
|---|---|---|
| "Integration and Test" | 1 (score 1.00, exact label) | **`not_specific`** |
| "Integration" | 2 — `ControlAccount`, `WorkPackage` | **`not_specific`** |
| "Test" | 4 — four distinct classes | **`not_specific`** |

**None of these is a tie-breaking outcome.** `not_specific` fires *before* tie-breaking, in the
segment-specificity gate, so the decision table never reaches the `mixed` branch the
disambiguation case needs. The tie check's real answer is that ties are unreachable here.

## The mechanism — one string, two names

```
identifier 'Integration and Test'  -> name  'test'    (identifier side: no suffix stripping)
candidate  'Integration and Test'  -> asset 'and'     (candidate side: strips env suffixes)
'test' == 'and'  ->  False
```

`_ENV_SUFFIXES = {prod, dev, test, stage, staging, qa, uat}`. `candidate_asset_name()` pops
trailing env suffixes; `identifier_name_and_qualifiers()` does not. **The two sides of the
comparison are computed by different functions with different rules**, so the same text
produces two different names and cannot match itself:

```
passes_segment_specificity(x, x)
  FAILS   'Integration and Test'
  FAILS   'Acceptance Test'
  PASSES  'Site A — Aurora'
  PASSES  'Order to Cash'
  PASSES  'my_dataset_prod'      <- one segment: underscores are KEPT, so nothing is stripped
```

## Blast radius: human labels, not catalog ids

The rule is correct for what it was built for. `p_cage`, `publog.p_cage`, `my_dataset_prod` are
**single segments or dotted paths**, and `_segments()` deliberately keeps `_` and `-` inside a
name. An env suffix there really is an environment.

It breaks on **space-separated human labels ending in one of those words** — which is exactly
the population that label-based resolution introduced when engines began resolving names to
opaque ids. IPMDAR finance data is full of them: *Integration and Test*, *Qualification Test
Campaign*, *Test and Evaluation Directorate*.

Measured candidate names:

```
'Integration and Test'                      -> 'and'
'Qualification Test Campaign'               -> 'campaign'
'Research, Development, Test and Evaluation'-> 'evaluation'
'Test and Evaluation Directorate'           -> 'directorate'
```

Only the first is fatal (the stripped word was the terminal one); the others merely take a
different terminal word, which is a separate question about whether "the last word" is the
right name for a multi-word label at all.

## Why this matters beyond engine-fin

**Fixing engine-fin's `identity`/`text` field names is necessary but not sufficient.** Once the
contract mismatch in `[[engine-fin-is-registered-but-cannot-participate]]` is repaired, the
fan-out will reach the decision table and the table will answer `not_specific` for these names
anyway. The ADR-0033 disambiguation consumer — whose whole scoping case is IPMDAR name reuse —
would still never fire.

**Engine P is currently safe by luck of vocabulary.** *Aurora*, *Order to Cash*, *Wave 1
Cutover*, *Core ERP Platform* all pass. A seed entity named *"Wave 1 Test"* would not.

## Not fixed

The gate is deliberate, structural, and load-bearing — its own comment records the measured
defect it repairs (`cage` resolving to `p_cage`, and a nonexistent asset alternating between
abstention and a confident wrong answer as a score moved 0.006). **It should not be loosened by
a sweep.** The shape of a fix is a judgment about the rule, not a typo correction, and at least
three readings exist:

1. **Symmetry** — apply the same suffix stripping to both sides, so a name always matches
   itself. Smallest change; leaves "the last word is the name" intact for multi-word labels.
2. **Scope the suffix list to id-shaped text** — strip env suffixes only when the candidate
   looks like a catalog id (dotted/underscored), never on a spaced label. Targets the actual
   population.
3. **Reconsider terminal-name for labels** — "the last segment is the name" is right for
   `a/b/c` paths and questionable for English phrases, where the head word is often first.

(1) is the safest and (2) the most precise; (3) is a larger question. **Whoever rules it should
know the self-match property is the crispest test**: `passes_segment_specificity(x, x)` must be
true for every x, and that assertion is worth adding whichever way the rule goes.
