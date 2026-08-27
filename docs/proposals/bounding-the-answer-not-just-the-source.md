# Bounding the ANSWER, not just the source

**Date:** 2026-08-27 · **Raised by:** Lane 1, from a live work-cluster failure · **For:** architect ruling
**Status:** PROPOSAL. Nothing built. Three of the four findings are measured; one is hypothesis and is labelled.

## The one-line finding

> **`DA_MAX_SOURCE_CELLS` bounds the table we READ. Nothing bounds the answer we RETURN — and the
> answer is what goes into the model's prompt.**

`d06da52` closed the source side after Engine DA was OOMKilled on a publog question. The same
species of defect — an unbounded materialisation — is still open one stage later, and its failure
mode is worse than the OOM it followed.

## What happened at work, in order

| # | observation | status |
|---|---|---|
| 1 | `give me the distinct cage codes per company from publog's p_cage` OOMKilled at 2Gi | measured |
| 2 | memory raised to 16Gi — **no more OOM** | measured |
| 3 | the question then ran **12+ minutes**, last log line mid-way through printing the dataset | measured |
| 4 | the answer card came back **empty** while the Dagster run was still going | measured |
| 5 | the same large prompt appears to be re-issued repeatedly | **HYPOTHESIS — see §Retry** |
| 6 | a narrower question returns fine | measured |

**Raising memory did not fix the question. It converted a fast, loud failure into a slow, silent
one.** The code's own comment predicted the general case: *"raising the memory limit only MOVES
the cliff."* It was written about memory; step 2→3 is that sentence coming true across a
different axis.

## Why the existing gate does not catch this

`query_datahub_asset` ends:

```python
return result_df.write_json()     # unbounded
```

The gate above it measures `n_rows * n_cols` of the **source** and refuses over 40M cells. But the
question that failed is:

```sql
SELECT company, ARRAY_AGG(DISTINCT cage_code) FROM dataset GROUP BY company
```

That returns a few hundred rows — **each carrying a list of every cage code for its company.** The
row COUNT collapses; the DATA VOLUME does not. It is the source table redistributed into lists,
and it passes a row-and-column gate cleanly. The closed doc says as much at line 97: *"a question
whose answer is a few hundred rows still pays for every row of `p_cage`."*

So this is not a threshold that needs raising. **It is a dimension nobody is measuring.**

## THE UNIT IS THE INTERESTING DESIGN QUESTION

The source gate counts **cells**, correctly, because its constraint is RAM and memory is a
property of width × length.

The result gate's constraint is **not RAM**. The result is serialised to JSON, printed, and becomes
the CodeAgent's *observation* — which is then part of the next model prompt. Its binding constraint
is the model's **context window**, measured in tokens, approximated by bytes.

**Those are different ceilings and they do not convert into each other.** A 200-row result of long
`ARRAY_AGG` lists is small in cells and enormous in tokens. A 5M-row × 2-column result is the
reverse. Bounding the result in cells would repeat the current mistake in a new place.

**Recommendation: bound the SERIALISED RESULT IN BYTES**, since that is what actually enters the
prompt, and it needs no tokeniser.

## Refuse or truncate — and why refuse should win

The house doctrine is honest refusal and *absence stays representationally distinct from content*.
Truncation is tempting here because an agent can often reason from a sample. It is still wrong as a
default:

**A truncated aggregate is not a partial answer, it is a false one.** "The distinct cage codes per
company" cut off at 500KB is not "some of the distinct codes" — it is a list the reader will
believe is complete. Silently changing an answer's meaning is precisely what this codebase refuses
everywhere else (a never-assessed cell is ABSENT, never level 0).

**Refuse, and tell the agent the shape**, exactly as the source gate does — it already ends with
*"Do NOT retry the same query — narrow it first: select fewer columns, filter rows, or aggregate at
the source."* That text is doing real work: it lets the agent **self-correct into a bounded
question** rather than failing the turn. The result gate should say the same thing with the result's
own numbers.

If truncation is wanted later, it should be **opt-in per call** and the marker must ride in the
payload so no reader can mistake it for the whole.

## Four layers, and they are separable

A ruling could take any subset. They are listed in the order I would do them.

### 1. Bound the result — the direct cause

In `query_datahub_asset`, after `con.execute(...).pl()`: measure the serialised size and refuse
over `DA_MAX_RESULT_BYTES` with a message naming rows, columns and bytes. Same shape and same
wording discipline as the source gate. **Testable exactly like `test_da_source_size_gate.py`.**

### 2. Bound the step — so a slow answer fails as DATA

`agent.run` has no timeout. Wrap it so it fails as a *result* ("I could not analyse that in
time") before any infrastructure aborts it. The existing `except` block already models the
reasoning: *"an agent failure is a RESULT of this engine, not an infrastructure fault, and
re-raising would make Restate retry the whole LLM loop for a deterministic failure."* A timeout
belongs on that same side of the line.

### 3. THE GATE HAS A BYPASS — and it is silent by design

If the precheck itself throws, the code prints `DA_SIZE_PRECHECK_FAILED` and **proceeds ungated**,
saying so: *"an oversized table can still OOM this container."* That was an honest trade when the
gate was new. It means a store that behaves differently from sandbox MinIO — plausibly the work
cluster — gets **no gate at all**, and the only trace is one stdout line nobody greps.

**Ruling needed:** should a precheck that cannot run REFUSE rather than proceed? Refusing is
consistent with the rest of the model; proceeding was chosen so a working query would not be
failed by a broken guard. Both defensible; it should be a decision, not an inherited default.

### 4. Retry policy — HYPOTHESIS, not yet confirmed

**No Restate inactivity/abort timeout is configured anywhere in this repo** (verified by two
independent greps over `agent_fleet/`, `src/` and `helm/`), so framework defaults are in force —
on the order of a minute of inactivity before an invocation is considered stuck and retried.

A `ctx.run("run-agent", ...)` step that takes 12 minutes writes no journal entries while it runs.
If Restate aborts and retries it, the step re-executes from scratch — same prompt, same duration,
indefinitely, because nothing about the retry is cheaper than the original.

**This is unconfirmed.** The cheap confirmation is a count of `DA_AGENT_CONFIG`, which prints once
per attempt, outside the journaled step:

```bash
kubectl logs -n <ns> deploy/iagent-data-analyst --tail=2000 | grep -c "DA_AGENT_CONFIG"
```

One question should print one line. If it prints several, the retry loop is real.

**Note the ordering.** The retry storm, if real, is a CONSEQUENCE of the unbounded step. Raising
Restate's timeouts alone would make a broken question fail quietly instead of loudly — the same
trade as raising the memory limit, and the same mistake.

## What this is NOT

**Not a dag-tools problem.** `CortexDataClient.get_dataframe` is byte-identical between the pinned
SHA `61cbfa92` and dag-tools HEAD, and its body is `scan_parquet`/`scan_delta`/`scan_iceberg` — lazy
at both refs. Bumping the pin cannot change this behaviour. (The pin is 71 commits behind and
crosses a distribution rename; worth doing deliberately, but it is a separate piece of work and
should not be coupled to this.)

**Not a presentation problem.** `mesh:DatasetAnalysisReport → CHART_WIDGET` is *archetype-hardened*
(`await b.RenderAsChart(...)`), not *projected*. The six planning archetypes are the projected set.
The model call that is slow here is Engine DA's own `CodeAgent`, which is the engine, not the
renderer — so deterministic projection downstream does not help.

## The general principle, if the architect wants one

> **Every boundary where data crosses into a bounded resource needs its own measure, in that
> resource's own units.** Source → RAM, measured in cells. Result → context window, measured in
> bytes. Step → wall clock, measured in seconds. A gate on one of these says nothing about the
> others, and passing one is routinely mistaken for passing all three.

This is the third instance of the same species on one path: `.collect()` into RAM (closed),
`write_json()` into a prompt (open), and a step into a retry window (open, unconfirmed).
