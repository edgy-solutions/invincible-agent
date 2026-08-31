---
id:         the-specificity-gate-strips-content-words
status:     open
owner:      agent (elicitation lane) — RULED AND IMPLEMENTED 2026-08-30
blocked-on:
repo:       invincible-agent
code-site:  agent_fleet/ontology_service/instance_resolution.py (_ENV_SUFFIXES, candidate_asset_name, identifier_name_and_qualifiers, passes_segment_specificity)
summary:    RULED AND FIXED 2026-08-30 — and the three readings turned out NOT to be alternatives. Measured through the FULL gate (fallback branch included), SYMMETRY ALONE IS A REGRESSION: stripping the identifier side empties "Test" to nothing and a nameless identifier is refused, so the reading called safest breaks a case that works today. PATH-SCOPING ALONE IS INCOMPLETE: `publog.p_cage.prod` still yields `prod` against `p_cage`. Only BOTH give self-match for every case, and they also keep the terminal name a CONTENT word (`test`) rather than the stopword (`and`) symmetry alone produces. Reading 3 (terminal-name for English phrases) untouched and still open. IMPLEMENTED by restoring the information `_segments` discarded — the SEPARATOR KIND — and the discriminator is WHITESPACE, not a list of punctuation: the first draft enumerated `[./\:]` and a real DataHub URN refused it, because its env qualifier is COMMA-separated, breaking six of the gate's own seal cases. A separator run containing whitespace joins WORDS OF A PHRASE; pure punctuation joins COMPONENTS OF AN IDENTIFIER. The strict xfail flipped to green; 175 routing tests pass. ORIGINAL FINDING: `passes_segment_specificity(x, x)` returns FALSE — a name cannot match itself — for any space-separated label whose final word is one of prod|dev|test|stage|staging|qa|uat. "Integration and Test" yields name `test` on the IDENTIFIER side and asset name `and` on the CANDIDATE side, because only the candidate side strips env suffixes. The two halves of the comparison are computed by different functions with different rules. Blast radius is human LABELS, not catalog ids: `my_dataset_prod` is one segment and passes. This is why every one of engine-fin's tied cases returns `not_specific` — the decision table never reaches the tie, and fixing engine-fin's field names is necessary but NOT sufficient for the ADR-0033 disambiguation case.
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

## Why the elicitation lane is the consumer whose input this needs

Their ADR-0033 fourth consumer — the subject-class ambiguity case — is scoped entirely around
IPMDAR name reuse: one phrase, several classes, and the class determines the *verb*. That is
the `mixed` outcome, and **`mixed` is unreachable for those names while this gate stands.**

So their item's stated blocker is incomplete. It reads as *"blocked on engine-fin's contract
mismatch"*; it is blocked on **two** things, and the second is this. Fixing
`identity`/`text` makes the fan-out reach the decision table, and the decision table then
answers `not_specific`.

**Which reading wins is partly their call**, because the three differ in what they let through:

* **symmetry** — every name matches itself; the most conservative, and it leaves multi-word
  labels still reduced to their last word (so *"Integration and Test"* and *"Qualification
  Test Campaign"* both resolve on their terminal word, which may or may not be what a speaker
  meant);
* **scope the suffix list to id-shaped text** — the same, plus spaced labels keep their whole
  terminal word, which is the population their consumer cares about;
* **rethink terminal-name for labels** — changes which word is the name at all, and is the
  only reading that would let *"Integration"* match *"Integration Lab Standup"* on a head word.

**The self-match property is pinned regardless**, as a strict xfail at
`tests/routing/test_instance_resolution_decision.py::test_a_name_matches_ITSELF`. It goes red
the moment the gate is fixed, which tells whoever fixes it to flip the marker rather than
leave a silently-passing xfail behind.


---

## ⚖ RULED AND IMPLEMENTED 2026-08-30 — and readings 1 and 2 are two halves, not two options

The packet laid out three readings and asked which wins. **Measured, the first two are not
alternatives: neither alone achieves the self-match property this packet says must hold.**

Measured through the **full** gate — including the segment-membership fallback the first probe
forgot, which is what makes `Test` interesting:

| self-match | current | (1) symmetry | (2) path-scoped | **both** |
|---|---|---|---|---|
| `Integration and Test` | FAIL | OK | OK | **OK** |
| `Acceptance Test` | FAIL | OK | OK | **OK** |
| `Wave 1 Test` | FAIL | OK | OK | **OK** |
| `publog.p_cage.prod` | FAIL | OK | **FAIL** | **OK** |
| `Test` | OK | **FAIL** | OK | **OK** |

* **Reading (1) alone is a REGRESSION, not merely imperfect.** Stripping the identifier side
  empties `"Test"` to nothing, and a nameless identifier is refused — so the reading the packet
  called "safest" breaks a case that works today. It also degrades the terminal name to a
  stopword: `Integration and Test` → `and`.
* **Reading (2) alone is incomplete.** `publog.p_cage.prod` still yields `prod` on the
  identifier side against `p_cage` on the candidate side.
* **Together:** every case self-matches, and the name stays a content word (`test`).

**Reading (3) — whether "the last word is the name" suits English phrases at all — is untouched
and still open.** It is the larger question the packet said it was, and this change does not
prejudge it. Note it also owns a pre-existing behaviour this fix does *not* introduce:
`"Qualification Test Campaign"` and `"Marketing Test Campaign"` both reduce to `campaign` and
pass the gate against each other **today**. Terminal-name collisions on spaced labels are
reading (3)'s territory; the gate is a *specificity* check, not a *uniqueness* one, and
discriminating between two candidates is the scoring layer's job.

### The implementation: restore the information `_segments` threw away

The root cause is one line older than the bug. `_segments()` splits on `.`/`/`/`,`/`:`/whitespace
and **keeps none of it**, so afterwards nothing can tell *"the next component of an id"* from
*"the next word of a phrase"* — and a rule written for the first silently applied to the second.
`_kinded_segments()` returns `(segment, joined_structurally)` and the env-suffix strip fires only
on a structurally-joined segment, never on a spoken word, and never on the last one remaining.

> ### ⛔ AND THE FIRST DRAFT OF THAT DISCRIMINATOR WAS WRONG — caught by the gate's own seals
>
> It enumerated the structural separators as `[./\\:]`. **A real DataHub URN refused it:**
>
> ```
> urn:li:dataset:(urn:li:dataPlatform:s3,iagent-minio.publog-lake/publog/p_cage,PROD)
> ```
>
> its env qualifier is **comma-separated**, so `prod` was not stripped and `candidate_asset_name`
> returned `prod` instead of `p_cage` — **six of the gate's own seal cases went red.**
>
> My ad-hoc probe had passed, because it used hand-made inputs (`publog/p_cage`) and never a real
> URN. `[[a-green-check-proves-only-its-scope]]`: the probe's scope was three invented pairs, the
> suite's was the shape the gate actually meets.
>
> **Enumerating the punctuation is the losing side of that bet** — there is one whitespace class
> and an open-ended set of punctuation. So the rule is written the way the set is bounded:
> **a separator run containing whitespace joins WORDS OF A PHRASE; a run of pure punctuation
> joins COMPONENTS OF AN IDENTIFIER.**

### Acceptance

* **`test_a_name_matches_ITSELF` — strict xfail FLIPPED to green.** The marker's reason is
  preserved as a comment rather than deleted: it is the clearest statement of what was broken,
  and being strict is what made it go red the moment the gate was fixed instead of rotting into
  a silently-passing xfail.
* **The regression guard holds**, and it was checked against the suite rather than my own probe:
  `cage`→`p_cage`, `publog`→a table inside it, and `p_caeg`→`p_cage` are all still refused, and
  `p_cage`→`publog.p_cage.prod` still passes.
* **175 routing tests pass, 0 failures.**

### What this unblocks

`mixed` is now reachable for IPMDAR-shaped names, so **ADR-0033's trigger #3 (ambiguous subject
class) can fire** once `[[engine-fin-is-registered-but-cannot-participate]]`'s contract mismatch
is repaired. This packet's own framing — *"blocked on two things, and the second is this"* — is
now blocked on one.
