# Post-roll walk census, three fires — and the total that hid six changes

Dispatch item 4: *post-roll walk census, three fires; attribute every change; place the lot 4
CONTRIBUTION_RANKING capture in `cortex-ui/sessions/`.*

Fleet at `MIXED(03ee440,600c454,c000514)` in all three fires. Raw log kept out of the repo
(scratchpad `walk-3fires.log`); every figure below is derived from it by a command recorded here.

## 0. The headline is an instrument finding, not a fleet finding

The first fire read **8 pass, 12 fail, 0 blocked** over 20 rows. The last recorded baseline,
`docs/measurements/walk-census-run-2026-09-19-post-roll-147.txt`, also reads **8 pass, 12 fail,
0 blocked** over 20 rows.

Identical footers. **Six rows had changed disposition** — three each way, netting to zero. A
reader comparing footers would have concluded "no change since roll 147" and been wrong about six
rows, three of them regressions.

The footer is not a weak summary of the census; it is a summary that actively cancels. Three
regressions and three improvements produce the same two numbers as thirteen quiet rows. Nothing in
the footer can distinguish them, so **the census must be compared by row identity and never by its
own totals.**

## 1. The three fires

| fire | pass | fail | blocked | repo sha in header |
| --- | --- | --- | --- | --- |
| 1 | 8 | 12 | 0 | `1fb1a7a0` |
| 2 | 11 | 9 | 0 | `69397987` |
| 3 | 10 | 10 | 0 | `d26ee014` |

**The three totals disagree with each other.** Any one of them, reported alone, would have been a
"post-roll census result". Which one you got would have been decided by when you ran it.

**The differing repo shas are mine and are not the cause.** Three commits landed between fires
(`56b69ee0`, `69397987`, `d26ee014`). Each was checked for code or config content:

```
for c in 56b69ee0 69397987 d26ee014; do
  git show --stat --name-only --format='' $c \
    | grep -cE '\.(py|ts|tsx|yaml|yml|json|Dockerfile)$|^helm/|^scripts/'
done
# 0, 0, 0
```

All three are documentation and session files. The deployed fleet sha triple is byte-identical
across all three fires. So the variance below is live nondeterminism in the fleet, not a
difference in what was being measured — which is the one thing a moving repo sha would otherwise
have made unanswerable.

## 2. Every row, all three fires

| row | f1 | f2 | f3 | verdict |
| --- | --- | --- | --- | --- |
| `cost-labor-split-lot-4` | PASS | PASS | PASS | stable PASS |
| `cost-rate-comparison-lot-3-vintage` | PASS | PASS | PASS | stable PASS |
| `cost-rates-fy2021` | PASS | PASS | PASS | stable PASS |
| `finance-burn-rate` | PASS | PASS | PASS | stable PASS |
| `finance-eac-comparison` | PASS | PASS | PASS | stable PASS |
| `finance-np-meridian-brief` | PASS | PASS | PASS | stable PASS |
| `finance-variance-decomposition` | PASS | PASS | PASS | stable PASS |
| `safety-unattended-hazards` | PASS | PASS | PASS | stable PASS |
| `cost-rate-comparison-lot-3-refusal` | FAIL | FAIL | FAIL | stable FAIL, **reason varies** |
| `docs-how-do-i-add-a-canvas-template` | FAIL | FAIL | FAIL | stable FAIL |
| `docs-how-do-i-add-an-engine` | FAIL | FAIL | FAIL | stable FAIL |
| `docs-how-do-i-roll-a-service-abstains` | FAIL | FAIL | FAIL | stable FAIL |
| `docs-what-is-an-archetype` | FAIL | FAIL | FAIL | stable FAIL |
| `finance-eac-refusal` | FAIL | FAIL | FAIL | stable FAIL, **reason varies** |
| `finance-funding-status` | FAIL | FAIL | FAIL | stable FAIL |
| `safety-deferral-risk-refusal` | FAIL | FAIL | FAIL | stable FAIL |
| `safety-haz-1003-risk-assessment` | FAIL | FAIL | FAIL | stable FAIL |
| `cost-supplier-concentration-lot-4` | FAIL | PASS | PASS | **UNSTABLE** |
| `finance-performance-indices` | FAIL | PASS | PASS | **UNSTABLE** |
| `finance-variance-drivers` | FAIL | PASS | FAIL | **UNSTABLE** |

**Partition, summing to a separately-counted 20:**

| class | count |
| --- | --- |
| stable PASS | 8 |
| stable FAIL, same reason all three fires | 7 |
| stable FAIL, disposition stable but reason varies | 2 |
| unstable disposition | 3 |
| **total** | **20** |

The join was asserted to contain 20 rows before any of this was computed, and no row appears in
one fire and not another, so nothing is silently dropped.

## 3. Attributing every change

The dispatch says *attribute every change*. Against the roll-147 baseline:

| row | baseline (one fire) | now (three fires) | attribution |
| --- | --- | --- | --- |
| `finance-eac-comparison` | FAIL | stable PASS | **IMPROVED** |
| `finance-variance-decomposition` | FAIL | stable PASS | **IMPROVED** |
| `safety-unattended-hazards` | FAIL | stable PASS | **IMPROVED** |
| `finance-eac-refusal` | PASS | stable FAIL | **REGRESSED** |
| `cost-supplier-concentration-lot-4` | PASS | unstable | **UNATTRIBUTABLE** |
| `finance-performance-indices` | PASS | unstable | **UNATTRIBUTABLE** |
| `finance-variance-drivers` | FAIL | unstable | **UNATTRIBUTABLE** |
| (13 others) | — | unchanged | unchanged |

**13 unchanged + 3 improved + 1 regressed + 3 unattributable = 20.**

**Why three are unattributable rather than "changed".** The baseline is a *single* fire. A row I
now know to be unstable could have been caught by that single fire in either state, so the
baseline does not record what the fleet did at roll 147 — it records what the fleet did once. For
those three rows there is no fact to compare against, and calling them regressions or improvements
would be inventing one. The honest entry is that the comparison cannot be made, and it cannot be
made *for a reason that is a defect in the baseline's method, not in the fleet.*

Every future census row is worth three fires for exactly this reason: a one-fire baseline cannot
be repaired later.

**The one real regression** is `finance-eac-refusal`: stable FAIL across all three fires,
`disposition 'drawn'` where the row accepts `['slot_required']`. It should have elicited and
instead drew a card.

## 4. Two instrument defects found in my own comparison

**Disposition-only diffing was too coarse.** My first comparison keyed on PASS/FAIL per row. Two
rows kept FAIL across fires while changing *why*:

- `cost-rate-comparison-lot-3-refusal` — fires 1 and 3: an elicitation offering 0 options where
  the sheet expects 2. Fire 2: `route_status='infra_error'`, verb `UNKNOWN`. Two different
  defects wearing one FAIL.
- `finance-eac-refusal` — fire 1: verb `UNKNOWN`, `no_match`, `subject_unknown`. Fires 2 and 3:
  routed to a real verb, `fin_eac_comparison`, and failed on the wrong one.

So the count of moving rows is **5 of 20, not 3**. A FAIL is not an atom; a row can move without
its disposition moving, and a diff that reads only the verdict column reports the fleet as more
stable than it is.

**`grep -c` counts lines, not matches.** Scanning the capture for infra detail returned "1 hit".
One *line* held two matches — the cluster-domain suffix and its final label, both inside one URL,
so two alternatives of the same pattern fired on one line. With `-o` still added,
`-c` continued to count lines. The correct form pipes `-o` output to `wc -l`, or through
`sort | uniq -c` to see identities. This is the same defect as §0 one layer down: a count stood in
for a census and hid half of what it was counting.

**One artefact that is not a defect:** the log renders an em-dash in one census message as a
replacement character, because the run was captured to a file with a console encoding that could
not carry it. It affects the log's bytes, not the census's verdicts.

## 5. What the persistent failures are

The 9 stable failures fall into four groups, and the largest is coherent:

**Four `DATA_ENGINEER` docs rows, one cause.** `docs-how-do-i-add-an-engine`,
`docs-what-is-an-archetype`, `docs-how-do-i-add-a-canvas-template`,
`docs-how-do-i-roll-a-service-abstains` — every one: verb `UNKNOWN` lacking `mesh_explain`,
`route_status='no_match'`, `no_compatible_verbs`, and `0 row(s) under 'sections'` against a floor
of 1. `mesh_explain` is not routable at all. This is the same verb whose gate was measured
mis-specified in
`docs/measurements/2026-09-25-mesh-explains-remeasured-in-jena-and-the-gate-that-reds-on-six-correct-rows.md`;
whether the two share a cause is **not established here** and should not be assumed from the name
matching.

**Two rows that draw a card where the sheet expects an elicitation.**
`safety-haz-1003-risk-assessment` (`drawn`, accepts `['task_requested']`) and `finance-eac-refusal`
(`drawn`, accepts `['slot_required']`).

**One row routed to a neighbouring verb.** `finance-funding-status` resolves
`fin_program_brief` instead of `fin_funding_status`, and returns `KNOWLEDGE_DOCUMENT` where the
sheet expects `SHORTFALL_GRID`. Stable and identical in all three fires.

**Two more, each carrying an unrouted verb.** `safety-deferral-risk-refusal`
(`assess_deferral_risk`, `no_compatible_verbs`) and `cost-rate-comparison-lot-3-refusal`, whose
reason varies as above.

None of these are filed on the board by this document; it measures them.

## 6. The lot 4 capture

Placed at
`cortex-ui/sessions/2026-09-26-capture-from-lane-1-the-lot-4-contribution-ranking-card-real-and-post-projector.md`,
committed there as `59fb2cb`.

**Which row the dispatch meant was derived, not assumed.** Two census rows are lot 4 *and*
`CONTRIBUTION_RANKING`: `cost-supplier-concentration-lot-4` and `cost-labor-split-lot-4`. The
dispatch says *with threshold on the wire*, and `threshold` / `threshold_defaulted` are produced
only by `cost_supplier_concentration` in `agent_fleet/cost_agent/measures.py:788-789` and by
`supplier_view` in `agent_fleet/cost_agent/page.py:632-633`. `cost_labor_composition` has no
threshold anywhere. So the phrase identifies the supplier-concentration row.

The capture is real and post-projector: census `judge` returns **PASS**, `route_status: matched`,
verbs `['costSupplierConcentration', 'cost_supplier_concentration']`,
`presentation_provenance.presentation_source = 'registered'`, 15 events, and
`components[0].threshold = "0.25"` with per-row `above_threshold`.

**`threshold_defaulted` is `true`,** so the bound on the wire is the engine's default and not a
caller-supplied one. The capture therefore evidences the default case only; the caller-supplied
path is unmeasured, and that is written into the file rather than left for the consumer to find.

**The capture's own row is one of the three unstable ones** — it passed 2 of 3 fires. The file
says so, because a fixture presented as reliably reproducible would be a false claim about the
fleet, and a consumer whose local reproduction answers `no_match` would otherwise conclude they
had called it wrong.

One value is a placeholder: `handled_by.endpoint_url` carried an engine's cluster-internal
address. The key is kept so it still reads as a field the fleet sends. The same matcher was run in
both directions (1 match in the input, 0 in the output) and the key multiset is identical before
and after, so only that one value changed. No token, password or `Bearer` header is present,
asserted before writing with the scanner positive-controlled against a string that *is* present.

## 7. What I did not review

- **Why any row is unstable.** Measured that it is, three times, on an unchanged tree and fleet,
  in both directions. A cold-start explanation would fit fires 1→2 and is refuted by
  `cost-rate-comparison-lot-3-refusal`, which *degraded* from fire 1 to fire 2 — so no cause is
  offered here.
- **Whether `mesh_explain`'s absence from routing and the `mesh:explains` gate defect share a
  cause.** The names match; that is not evidence.
- **The third fleet sha.** `fleet=MIXED(03ee440,600c454,c000514)` names three, and only two are
  accounted for elsewhere. `600c454` is unexplained and was not investigated.
- **No cortex-ui code was read**, so the capture is not claimed to match what the app parses.
- **Whether the unstable rows correlate with load.** Three fires ran back to back, and nothing
  about substrate contention was measured.

## Method

Per-row dispositions were extracted with
`grep -oE '^  (PASS|FAIL|BLOCK[A-Z]*) +[a-z0-9][a-z0-9-]+'` and compared by `join` on row id, so
a row present in one run and absent from another shows up as an unmatched key rather than
vanishing. Reasons were extracted as the indented continuation lines under each row and compared
as whole strings. Both the disposition join and the reason join were checked to contain 20 rows.
The partition in §2 sums to 20 counted separately from the classes.

`min_rows`, personas, domains and expected verbs are the sheet's own declarations, read from
`docs/measurements/walk-census.yaml`; none is restated from memory.
