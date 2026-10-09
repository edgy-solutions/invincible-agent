# Lane 1, 2026-09-26 — ruling 5, producer half: finance's row-level `method` → `method_label`

**Status: LANDED, with exactly one deliberate red, and that red is the ruling's own proof.** Both
finance EAC producers now emit `method_label`. `tests/planning/test_producers_speak_their_archetype.py`
reds against cortex-ui's unchanged `ForecastRow.method`, which is what ruling 5 means by *producer and
consumer change together, parity seal proves it*. Cortex's half is ordered in
`sessions/2026-09-26-order-to-cortex-ruling-5-forecastrow-method-becomes-method-label.md`.

## 1. The defect, stated as the type collision it is

Fleet-wide, `method` names an **object**: the method BLOCK whose shape is declared once in
`tests/_method_block_contract.py` for every engine that emits one (formula, inputs by name with
values, the bound and whether it was defaulted, producer sha). Finance's EAC rows carried the **same
key holding a bare string** — a formula's name. One key, two types, depending on which producer you
read.

**The producer-side mechanism is worse than the consumer-side one, and it was already written down.**
`tests/test_the_method_block_is_one_shape_across_engines.py::test_no_ranking_puts_METHOD_on_a_ROW`
records it: the projector **lifts an absent envelope field off `rows[0]`**, so a row-level `method`
is a candidate for the block's slot. Its failure message already named the remedy — "Rename the row
field" — and its docstring already named finance as the offender. This change is that remedy applied.

On the consumer side, cortex's `readMethod` accepts a row and produces a **plausible empty block**
rather than an error. Both halves fail silently; neither fails loudly.

## 2. What changed

| file | change |
|---|---|
| `agent_fleet/finance_agent/measures.py:805` | `fin_eac_calculation` row: `"method"` → `"method_label"` |
| `agent_fleet/finance_agent/measures.py:~928` | `fin_eac_comparison` row: same, per method |
| `agent_fleet/finance_agent/measures.py:283` | `_verdict_eac`'s read — **see §3, this is the one that matters** |
| `agent_fleet/presentation_agent/capabilities.py:403,413` | `expected_fields` for COMPETING_MEASURES and FORECAST_MEASURE |
| `scripts/extraction_equivalence.py:56` | `_LABEL_KEYS` — **see §4** |
| `tests/finance/test_eac_comparison.py` (7 sites), `test_the_eac_formulas_are_the_formulas.py:159`, `test_the_eac_measure_module.py:195,277` | row reads |
| `tests/planning/test_producers_speak_their_archetype.py:152` | **NOT renamed** — see §5 |
| `tests/test_the_method_block_is_one_shape_across_engines.py:253` | the docstring that named the now-fixed offender |

**The INPUT slot `method` is untouched, deliberately.** `fin_eac_calculation` takes `method: EACMethod`
as a mandatory slot and raises `MethodRequired` without it; `policy/canvases/program_finance.yaml:135`
passes `method: CPI`; five test kwargs tables spell it. The slot is the **question**, the row key was
the **answer**, and only the answer collided. Renaming the slot would have broken R-001's mandatory
refusal for nothing.

**Verified on the artifact, not on the tests passing:**

```
fin_eac_calculation row:  method present? False   method_label present? True   method_label = CPI
fin_eac_comparison rows:  3, labels ['CPI','CPI_SPI','REMAINING_AT_BUDGET'], bare `method` on any row? False
```

## 3. The consumer that a rename injures QUIETLY, and the arm it was owed

`_verdict_eac` (`measures.py:283`) reads the method **with a silent default**:
`row.get("method_label", "forecast")`.

Had that read been missed, **every existing arm would have stayed green.** The fallback returns
`"forecast"`, which is non-None (`test_a_verdict_is_ABSENT_when_there_is_nothing_to_say` passes), and
carries no banned judgement word (`test_no_verdict_makes_a_JUDGEMENT_about_acceptability` passes). The
verdict would have silently stopped naming CPI.

So the hazard got an arm rather than a comment —
`test_the_EAC_verdict_NAMES_the_method_and_does_not_fall_back_to_the_word_forecast` — **and the arm
got its mutant run:**

| | measured |
|---|---|
| baseline | 1 passed |
| mutant (`measures.py` read reverted to `row.get("method", "forecast")`) | **1 failed**, on `assert label in verdict` |
| the mutant's verdict text | **`'forecast: 2,152,381 USD above budget'`** |
| restored (the **inverse of the mutation**, not to HEAD) | 1 passed |

That string is the entire argument: grammatical, judgement-free, figure-leading, and naming no
method. Nothing else in the suite can tell it from the right answer.

**Which half catches what, stated because assertions short-circuit and only the first reported.**
`label in verdict` catches the read drifting off the key. `"forecast:" not in verdict` catches the
caption gaining the fallback word *while still interpolating the label*
(`f"forecast: {row.get('method_label')}…"`), which the first half would pass. The second half is
**unexercised by the mutant above** and is kept on that stated distinction, not on habit.

## 4. A consumer whose breakage would have had no exception either — row IDENTITY

`scripts/extraction_equivalence.py:56` `_LABEL_KEYS` is a row-identity tuple, **tried in order**:
`("period", "entity_id", "subject_id", "method", "program_id", "line_id")`.

`fin_eac_comparison` emits three rows carrying the **same `program_id`**, and `program_id` is *later*
in that tuple than the method key. So the method key is what distinguishes those three rows there.
Renaming the producer without renaming this would not have errored: all three rows would have fallen
through to `program_id`, **three distinct forecasts would have reported under one label**, and the
report would have looked complete while losing exactly the attributability the tuple's own comment
says it exists to provide. `method_label` therefore sits in `method`'s **old position**.

**Not re-measured, and recorded as not re-measured:** three finance test docstrings cite figures this
script produced (e.g. `test_the_eac_measure_module.py:12`, "54 shared-key values unchanged"). Those
figures compare two extractions of the *same* module, and both sides now emit `method_label`, so the
comparison is unaffected — that is an argument, not a re-run.

## 5. The one red, and why the mirror was left FALSE-looking on purpose

```
FAILED tests/planning/test_producers_speak_their_archetype.py::
       test_every_FIN_producer_emits_its_archetype_keys_or_is_a_named_wrong_binding
E   fin:EstimateAtCompletion -> FORECAST_MEASURE missing ['method']
```

`1 failed, 1151 passed, 30 skipped, 1 xfailed` across `tests/finance tests/planning tests/cost` and
the cross-engine method-block seal. **One red, and it is the predicted one.**

The required-field set comes from **cortex-ui's parsed contract** when the sibling repo is checked
out, and `ForecastMeasure.contract.ts:84-104` still declares `method: string;  /** MANDATORY */`. So
the seal is reporting a true fact: the producer no longer emits a field the consumer requires.

**`_MIRROR["FORECAST_MEASURE"]` was deliberately NOT renamed.** That table is a *mirror of cortex's
contract*, used when the sibling repo is absent. Writing `method_label` there would assert that
cortex has renamed it — false today — and would **hide the red in exactly the environment where
nothing else can catch it** (no cortex-ui checked out). A false claim that makes a suite green is the
worse of the two outcomes. The line carries the retirement condition instead.

**Why not `xfail`.** The failing arm covers **every** fin binding, not this one. Marking it xfail
would trade one owned, explained red for five unwatched greens. The red stands with its owner and
trigger written in three places (the mirror comment, this report, the order to cortex).

**Why not `_FIN_WRONG_ARCHETYPE`.** That table is a claim that a binding is **unsatisfiable**, and a
sibling arm proves each entry still fails. This binding is satisfiable the moment cortex renames.

## 6. What retires the red

Cortex renames `ForecastRow.method` → `method_label` **and** fixes `readMethod` so it stops accepting
a row as a method block. Then `_MIRROR["FORECAST_MEASURE"]` becomes `{"method_label", "formula",
"eac"}` and its comment is deleted. **Not** by reverting the producer.

## 7. What I did not verify

- **That a FORECAST_MEASURE card renders correctly after cortex's half lands.** Untestable from this
  side today; the producer half is verified against the contract text, not against a rendered card.
- **COMPETING_MEASURES against a parsed contract.** It is `_EXEMPT` in the parity seal (its only
  producer is engine-fin, so its conformance lives in `tests/finance/test_eac_comparison.py`), so its
  rename is checked by that file's arms and **not** against cortex's `CompetingMeasures` interface. If
  cortex declares a row-level `method` there too, nothing in this repo reds.
- **The live fleet.** This is a source-and-suite change; no engine was rolled and no card was drawn.
  The deployed `b5eeb408` still emits `method`.
- **`scripts/extraction_equivalence.py` re-run.** See §4 — argued, not measured.
- **Whether any consumer outside these two repos reads the row key.** Enumerated across tracked
  Python, non-Python tracked files, and the ontology TTL; not enumerated beyond the repos.

## 8. Addendum, 2026-10-08 — the consumer half has landed; the red is retired

cortex-ui d7d6593 (`feat(finance): rows read method_label ... no fallback to method`) renames the
row key in COMPETING_MEASURES and FORECAST_MEASURE, still MANDATORY, with no fallback to `method`;
bd782c5 is an unrelated test fix in the same push. Both are ancestors of cortex-ui `master`.
`_MIRROR["FORECAST_MEASURE"]` on this branch already reads `{"method_label", "formula", "eac"}`.
Measured with the sibling checked out: `tests/finance/test_eac_comparison.py` and the
FORECAST_MEASURE arms of `tests/planning/test_producers_speak_their_archetype.py` pass. The §7
gap on COMPETING_MEASURES stands: that archetype is `_EXEMPT` from the parity seal, so its
rename is still checked only by `test_eac_comparison.py`, not against cortex's interface.
Three OTHER reds appear against current cortex master and are not method_label (SHORTFALL_GRID
cell interface unparsed, ILLUSTRATION and WORKFLOW_CASE with no projector path, NoticePartSet
mirrored on one side only). The deployed engine still emits what it was last rolled with; no roll
was done.
