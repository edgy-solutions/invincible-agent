---
date: 2026-09-26
from: invincible-agent/master (architecture seat's dispatch, finance/cost seal line)
to: Chris (architecture seat)
subject: cost_labor_composition is DECIDED; the opaque-spread allowance's final shape and the
         three declarations it is keyed on; the cortex-ui-ff dialogue is parked
---

# 0. What you asked for, and what this is

> *"Take `cost_labor_composition` next round, close it, and then park the dialogue with a packet to
> me stating the allowance's final shape and the three declarations it's keyed on. Reopen it when a
> new producer lands, not before."*

Both done. **No code changed this round** — the close is a derivation, not a patch, and §1 says why
that is the right outcome rather than a thin one. The allowance is described in §2–§3 as it now
stands in the tree; the reopen condition is §4. §5 is the one lesson I am keeping from the item
itself, and it is about the *dialogue*, not the code.

---

# 1. `cost_labor_composition` — DECIDED: `CONTRIBUTION_RANKING`

Four rounds of packets on both sides said *"UNDECIDED on both sides, neither of us established that
card's archetype, and I am not claiming it either way."* That was true as a statement about the two
of us. It was never true of the tree. The answer is declared, registered, produced, sealed and
measured, in five artifacts:

| # | the artifact | what it settles |
| --- | --- | --- |
| 1 | `agent_fleet/presentation_agent/capabilities.py:446-453` | the binding: `cost:LaborComposition` → `mesh:ContributionRanking`, `"archetype": "CONTRIBUTION_RANKING"`, advertising `rank, entity_id, entity_name, contribution, share_of_total, value_unit` |
| 2 | `setup/ontologies/cost_extension.ttl:126` | `cost:LaborComposition a owl:Class` — the class the 2026-09-08 CURIE saga failed on *is* registered, so the historical "OntologyClass missing" note in `mesh_registrar/main.py:876` is closed history, not a live gap |
| 3 | `agent_fleet/cost_agent/measures.py:579-612` | the producer emits all six advertised fields; five of the six exist **only** on rows, so they cannot be satisfied by the envelope |
| 4 | `tests/cost/test_cost_cards_conform.py`, two parametrised arms at `:156` and `:179` | `cost:LaborComposition` is **in the basis**, not excluded: `COST_BINDINGS` filters only through `_NOT_A_COST_MEASURE`, whose single member is `LotCostingReview` with a written reason. Both arms **PASS**, real exit 0 |
| 5 | `docs/measurements/2026-09-26-post-roll-walk-census-…:55` | `cost-labor-split-lot-4` — **stable PASS, 3 of 3 fires.** The card renders, repeatably, post-projector |

## The seal is live for this parameter — three mutants, each named, each with its fragment

A green arm is not evidence until it has been made to go red on the row you care about. Fired
against the real producer and the real binding, restored byte-exact (`git status` clean after each):

```
L1  producer drops `entity_name` (a key the CARD CONTRACT requires)
        -> RED at test_every_bound_cost_verb_emits_its_archetypes_axis_keys[cost:LaborComposition]
           fragment "missing ['entity_name']"                                      present
L2  producer drops `rank` (ADVERTISED by the binding, OPTIONAL in the contract)
        -> RED at test_the_expected_fields_on_the_row_are_ACTUALLY_EMITTED[cost:LaborComposition]
           fragment "advertises 'rank' and emits it nowhere"                       present
L3  the DECLARED ARCHETYPE changed to MULTI_SERIES, producer untouched
        -> RED at test_every_bound_cost_verb_emits_its_archetypes_axis_keys[cost:LaborComposition]
           fragment "missing ['period']"                                           present
```

L1 and L2 red at **different** arms, so the two are not one arm twice: one defends the contract's
required axis, the other the binding's own advertisement. L3 is the one that matters most for your
question — it shows the archetype string is **load-bearing**, not decoration sitting beside a
description that happens to say "CONTRIBUTION_RANKING" in prose.

## And the required set is parsed from the real card, not from a list in the test

`required_keys("CONTRIBUTION_RANKING")` takes the **parsed** branch, not the mirror fallback:

```
contract file exists: True   cortex-ui/src/components/planning/ContributionRanking.contract.ts
_parse_required(...) = ['contribution', 'entity_id', 'entity_name']
_MIRROR              = ['contribution', 'entity_id', 'entity_name']   (agrees; asserted, not assumed)
```

So the arm that reds in L1 and L3 is tied to the interface the card actually compiles against. I
checked which branch was live rather than trusting that the parse works, because a mirror fallback
that silently replaces a parse is the shape this file's own comment warns about.

## Why there is no patch

The card is bound, the producer conforms, the seal covers it and can fire, and the walk shows it
rendering three times out of three. **Writing a test here would be decoration around a branch that
is already defended** — the same discipline as deleting a redundant case with its measurement
recorded rather than adding one because a mutant was quiet. What was missing was a read, and the
read is now in this file at the anchors above.

## Two things I found and am deliberately NOT fixing

* **Six `CONTRIBUTION_RANKING` bindings in `capabilities.py` carry byte-identical
  `expected_fields` lists.** I found this because a mutation anchor I expected to be unique matched
  six times. It is duplication across six bindings owned by other seats, and nothing asserts the six
  agree with each other or with the contract's optional set. It is a smell, not a leak — the
  conformance arms read each binding independently, so a divergent copy would be caught for its own
  verb. **Routed to you, not widened by me.**
* **`test_the_expected_fields_…` accepts a field present in the envelope *or* in `rows[0]`.** That
  looks like the containment defect I spent round 12 on, and it is not: `expected_fields` genuinely
  mixes envelope and row names across bindings (`cost:UnitPriceTrend` advertises `rows` itself), so
  the disjunction is the declaration's real semantics. For this verb only `value_unit` is ambiguous;
  the other five are row-only. **I checked before filing it, and there is nothing to file.**

---

# 2. The allowance's FINAL SHAPE

The subject is the finance engine's envelope seal,
`tests/finance/test_the_wire_carries_what_the_engine_declares.py` (2142 lines, 29 arms, real exit 0).
The allowance exists for exactly one construct: the endpoint's `**` spread of a per-verb builder
table at `agent_fleet/finance_agent/main.py:651-652`, whose keys cannot be enumerated statically.
Every other envelope key is accounted for by name.

**What it now permits, stated as the property rather than as a list:** a `**` spread operand is
accepted only when the operand **is** a read of an allowed table — not when it merely *contains*
one. The anchor is found by peeling the expression's own spine (`Call.func`, `Subscript.value`,
repeatedly) and requiring what remains to be an attribute access on a `measures` alias, or a local
bound to one. **Arguments are deliberately not peeled**, because an argument is precisely where a
laundering wrapper hides: `**_fold(measures.SUMMARY[fn](rows))` has the allowed reference inside it
and is refused. The older reference condition is kept alongside — `refs <= allowance` — because the
two refuse different things: the anchor refuses a wrapper around a good read, the references refuse
a foreign table inside the arguments of a well-anchored one.

**What the allowance costs:** a table on it must have every one of its keys written down in a
members register **and** a producer object to compare that register against, so the "opaque" spread's
content is enumerated in the seal even though it cannot be enumerated in the endpoint. An entry on
the allowance without a register fails; a register that disagrees with its producer fails. There is
nothing that can be excused by being named.

**What it is not:** it is not an exemption list. Round 11 deleted the thing a name could be appended
to — the AST node-type whitelist — and replaced it with a literal-shape property. What remains is a
one-member set whose single member must earn its place in three separate ways.

---

# 3. The THREE DECLARATIONS it is keyed on

All three are in `tests/finance/test_the_wire_carries_what_the_engine_declares.py`. Each is held by
a property, and **each property is the same one**, applied three times — not three arms aimed at the
three instances I happened to think of:

| # | declaration | anchor | what holds it, and where |
| --- | --- | --- | --- |
| 1 | `_ACCOUNTED_OPAQUE_SPREAD_TABLES` — the allowance itself, `frozenset({"SUMMARY"})` | `:670` | must be **written as string literals**, via `_literal_string_set` (`:291`) in `test_the_SUMMARY_REGISTER_is_SPELLED_OUT_and_not_DERIVED` at `:875-878`; must be a **proper** subset of the declared tables (`:1965`); must equal `frozenset(_MEMBER_REGISTERS)` (`:1975`) |
| 2 | `_MEMBER_REGISTERS` — table → (its members register, its producer object) | `:709` | must be an **`ast.Dict` literal with literal string keys**, so a `DictComp` deriving it is refused (`:884-893`); its key set must match the object the other arms drive; non-vacuity asserted at `:778` and `:854` |
| 3 | `_SUMMARY_MEMBERS` — the spelled-out keys of `measures.SUMMARY` | `:681` | each entry must pass `_literal_string_set` and equal the register the producer comparison drives (`:896`); the comparison against the live producer is `test_the_SUMMARY_MEMBERS_REGISTER_and_the_PRODUCER_agree` at `:755`, iterated over every register at `:779` |

**Why all three and not just the allowance.** The equality at `:1975` is what makes the allowance
non-arbitrary — it cannot name a table that has no enumerated members. But an equality between two
objects is worth nothing if either side can be *derived* from the other: `ALLOWED =
frozenset(REGISTERS)`, or its inverse, satisfies it while asserting nothing. I had written that
hazard into this file's own comment one round earlier and measured **neither** direction; both were
QUIET. Hence the literal-shape property on all three declarations rather than a caution in prose.
That is the shape I would want re-checked first if any of this is ever revisited.

---

# 4. Reopen condition

**Parked.** The dialogue with `cortex-ui-ff` is closed at round 12; I have sent them a note saying so
and naming the same condition, so they are not waiting on a round 13.

**Reopen when a new producer lands** — concretely, when any of these becomes true:

1. a second `**`-spread builder table appears in `agent_fleet/finance_agent/main.py`'s envelope, or
   the existing one moves;
2. a table is proposed for `_ACCOUNTED_OPAQUE_SPREAD_TABLES` (which now requires a register and a
   producer, so it cannot be added quietly) — **and §8 gives the one measurement that must be run
   when that happens**;
3. a second engine emits `mesh:CompetingMeasures` — today `capabilities.py:401-402` is the only
   binding, and the one-producer premise several of these arms rest on would stop holding.

Not before. Your read is right that the mutants had begun to outnumber the defects: rounds 11 and 12
each found a real leak, but both were generations of one 2026-09-18 defect, and the cost per round
was rising.

---

# 5. The one lesson from the item itself — and it is about the dialogue

**An item both sides call UNDECIDED reads as a considered draw.** For four rounds two agents each
wrote, in good faith, "UNDECIDED on both sides — I am not claiming it either way." That sentence
reads as *we have both looked and cannot tell*. What it actually meant was *neither of us looked*.
The mutual non-claim is **more** authoritative than a one-sided one would have been, because
symmetry looks like corroboration — and that is exactly what kept either of us from spending the ten
minutes this took. A one-sided "I don't know" invites the other side to check; a two-sided one
closes the question.

Same family as a plausible negative reading as a considered one, and as an obstacle stated but never
checked. The rule I am keeping: **a question that has been open for more than one round with no new
evidence on either side is not contested — it is unexamined. Go and read the artifact.**

**And there was a second reason, which the peer named better than I did.** Releasing the item to me
they wrote that four rounds of UNDECIDED *"isn't a shortage of analysis, it's an absent owner"* — and
in their case a hard one: `agent_fleet/cost_agent/measures.py` is **read-only to their lane**, so they
could review a patch and never write one. Neither of us had said that out loud in four packets. Worth
a convention: **when a status line says undecided, say who cannot decide it and why.** "Undecided"
plus a reachability fact is an assignment; "undecided" alone is a shrug that both sides can sign.

---

# 6. What I did NOT review

* I did not read cortex's `readMethod`, so the overloaded-`method` finding stays theirs.
* I did not run the full suite — `tests/finance/` and `tests/cost/` only, which is where every
  consequence of this round lands: **564 passed, 13 skipped, real exit 0**, at this sha. The 13 skips
  are pre-existing and I did not open them, so they are unexamined rather than clean. Nothing outside
  those two trees changed; nothing changed at all except this file.
* I did not verify the walk census row `cost-labor-split-lot-4` myself this round; I am relying on
  the 2026-09-26 census, which is mine from earlier today. Its PASS is a judge verdict on the
  rendered card and does **not** independently assert the archetype string — the archetype claim in
  §1 rests on artifacts 1, 3 and 4, with the census as corroboration only.
* I did not check whether `test_every_envelope_field_a_verb_declares_survives_its_archetype_passthrough`
  seals the projector→contract direction as well as contract→projector. Still open, still unclaimed.

---

# 7. Still yours, unchanged from the last packet

* Whether a `dagster-server` image exists at the current head **before roll #3 is armed** — offered,
  still awaiting a yes. This is the one that blocks the two user-visible items.
* Ratifying absent-means-silent / DECLARED-NEVER-INFERRED.
* The producer half: should `measures.py:84` emit `all_methods_answered: false` rather than `None`.
* The MethodBlock / allowlist ruling, and whether `change_count`-style payload-key placement is
  governed at all.
* Threading a caller identity through `/find_compatible_verbs`.
* Whether I should touch another seat's false-red `test_IT_PARSES`.
* The six duplicated `CONTRIBUTION_RANKING` `expected_fields` lists from §1.

**Next from me, per your ordering:** the docs feature and bob's task, both of which are waiting on
roll #3 and the classify read. The fleet sha beside the payload is still owed to `cortex-ui-ff` on
the next roll fire, with its derivation named.

---

# 8. One measurement taken after §2 was written, because it was aimed at §2

`cortex-ui-ff`'s round 13 arrived while this packet was being written and named a hazard on **my**
side, so I fired it rather than filing it — a claim about the allowance's final shape is worth
exactly the run it has had. Their finding: *anywhere an allow-list subtracts from a population a
guard iterates, the subtraction is a second lever on that guard's reach* — and on their side a
positive control survived because **the guarded population and the judged population were not the
same population.** That is true of the shape of my file too: the operand rule's controls
(`_OPERANDS_ACCEPTED` / `_OPERANDS_REFUSED`) all run against **synthetic** builders, while the arm at
`:1003` judges the **real** one. Two populations, one control.

```
P1  the real summary spread DELETED from main.py's envelope -- the subject gone, not widened
      -> RED, 3 arms by name:  test_the_SUMMARY_table_reaches_the_wire_WITH_TYPED_VALUES
                               test_the_envelope_POPULATION_ONLY_GROWS
                               test_every_field_the_COMPETING_MEASURES_contract_reads_ARRIVES
P2  the judged population narrowed to nothing INSIDE the rule (`_spread_operands(builder)[:0]`)
      -> RED: test_the_OPERAND_RULE_accepts_only_the_shapes_it_recognises
```

**Refused in both directions, by different arms.** The emptying is caught on the real builder by the
population ratchet, and inside the rule by the synthetic controls — so neither arm is covering for
the other. `main.py` and the seal byte-identical after each pass. **§2 stands as written.**

**The residual, and it is the reason this belongs beside §4 rather than in a commit message.** All
three P1 reds are about the `SUMMARY` table *specifically* — one reads its typed values, one is the
COMPETING_MEASURES contract, one is the population ratchet. A **second** allowed table would arrive
with a register and a producer (§3 forces that) but **not** automatically with an arm that notices its
spread disappearing. So the reopen condition in §4 now carries its own check:

> **When a table is added to the allowance, delete its spread from the envelope and confirm that
> something reds BY NAME.** If nothing does, the new table has a register nobody would miss.

That is the same object as the rule I already hold — a population derived from a consumer is blind to
its subject being deleted, so it wants one measured ratchet — and this is the first time I have known
in advance *which* ratchet, and that it covers exactly one table.

**Reproduced independently, which is why it is stated as a condition and not as a worry.** I sent the
residual to `cortex-ui-ff` as a check to run, and it reproduced on their side in a different language
against a different seal: a fifth register added to their isolation file is correctly green, and the
same register **deleted again is also green**, because both places that name registers by name name
the same four. They report they would have filed it as *"the positive control covers it"* had the
check not been sent. Two codebases, same shape: **a per-member predicate is not a ratchet, and a floor
by name covers exactly the names in it.** Their own note is the one I would keep if only one survived
— a floor is not a completeness claim, so the thing to record is its *reach*, beside the floor rather
than in a session file.

They have parked symmetrically, with their own reopen conditions, and nothing is owed in either
direction except the fleet sha beside the payload on the next roll — four rounds owed, on their ledger
as well as mine, and parking does not clear it.
