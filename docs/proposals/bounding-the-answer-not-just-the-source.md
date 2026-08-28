# Bounding the ANSWER, not just the source

**Date:** 2026-08-27 · **Raised by:** Lane 1, from a live work-cluster failure · **For:** architect ruling
**Status:** RULED 2026-08-27. **Layers 1 and 2 BUILT** (`agent_fleet/data_analyst/main.py`,
`tests/test_da_result_size_gate.py`). Layer 3 is ruled but NOT built — it waits on a measurement
only a human at the work cluster can take. Layer 4 remains HYPOTHESIS, same reason.

**REPRODUCED ON SANDBOX the same day, against the real 86 MB `p_cage`** — including an OOMKill at
2Gi. That run CORRECTS this document in three places and breaks claim 1's proposed instrument.
**Read §SANDBOX REPRODUCTION at the foot before acting on anything above it**; where the two
disagree, the measured section wins.

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

---

# RULING — 2026-08-27

The architect ruled on all four layers. Two were built the same day; two are ruled but
**deliberately unbuilt**, because each depends on a number that cannot be taken from this machine.

## What was ruled

| layer | ruling | state |
|---|---|---|
| 1 · bound the result | **bytes, ratified.** The unit argument is the finding; cells would relocate the RAM mistake | **BUILT** |
| 2 · bound the step | **build it.** A timeout belongs on the same side of the line as the existing `except` | **BUILT** |
| 3 · the silent bypass | **fail closed.** A precheck that cannot run REFUSES, naming the precheck failure | ruled, NOT built — waits on claim 2 |
| 4 · retry policy | **confirm before building anything** | HYPOTHESIS — waits on claim 1 |

**Refuse over truncate was ratified and it SUPERSEDED the architect's own earlier lean** toward
declared truncation. The deciding argument: a truncated aggregate is not a partial answer, it is a
false one, and the refusal achieves the same self-correction without the false-completeness risk.
Truncation, if ever wanted, is opt-in per call with the marker riding in the payload.

## Claim 3 — MEASURED, and it is the sharper number

The reproduction the ruling asked for, run locally against duckdb + polars at the versions this repo
pins. The exact shape that failed at work, on a source that passes the shipped gate:

```
SOURCE  rows=500,000 cols=2 cells=1,000,000  limit=40,000,000 -> PASSES
RESULT  rows=200     cols=2 cells=400        -> PASSES on a CELL gate
RESULT  serialised bytes=4,007,401 (~4.0 MB, ~1,001,850 tokens at 4 B/token)
```

**The result is 0.04% of the source in CELLS and carries 4 MB into the prompt.** A cell gate on the
result side does not merely fail to catch this — it passes it by five orders of magnitude. The
dimension-nobody-measures claim is no longer an argument; it is a number, and it is pinned as
`test_the_cell_gates_BOTH_pass_while_the_payload_is_enormous`.

The companion arm `test_CELLS_and_BYTES_order_two_results_OPPOSITELY` executes the stronger claim:
two frames where A has more cells than B **and fewer bytes**. The orderings invert, so neither unit
can stand in for the other — which is why layer 1 did not simply reuse `_MAX_SOURCE_CELLS`.

## Claims 1 and 2 — NOT measurable here. This is the honest blocker.

Both require the **work cluster's** data-analyst logs. This machine's kubeconfig holds only
`edge` / `edge-rancher` (sandbox) and `docker-desktop`; the work cluster is not reachable from it,
and no sandbox reproduction substitutes, because both claims are about **what that specific
deployment did on that specific day**. Running them against sandbox would produce a number that
looks like an answer and is about the wrong cluster.

**Claim 1 — is the retry loop real?** ⚠️ **THE COMMAND BELOW IS WRONG — do not run it.** The
sandbox reproduction measured two `DA_AGENT_CONFIG` lines for one execution, because the line also
prints on a free replay. Use the `DA_FUMBLE_METRIC` form in §SANDBOX REPRODUCTION instead. Kept
here unedited so the defect stays legible rather than quietly patched:

`DA_AGENT_CONFIG` prints once per attempt, outside the
journaled step:

```bash
kubectl logs -n <ns> deploy/iagent-data-analyst --tail=2000 | grep -c "DA_AGENT_CONFIG"
```

One question should print **one** line. Several ⇒ layer 4 promotes from hypothesis to measured and
the retry storm explains the flood. Exactly one ⇒ **strike layer 4 from this document.**

**Claim 2 — is the gate running at work at all, or bypassed?**

```bash
kubectl logs -n <ns> deploy/iagent-data-analyst --tail=2000 | grep "DA_SIZE_PRECHECK_FAILED"
```

Any hit means the work cluster has been running **ungated** — layer 3 is then a live incident, not a
design preference, and the fail-closed change ships immediately. No hits means the precheck works
against that store and layer 3 is the ordinary hardening the ruling describes.

**Why layer 3 was not built anyway, given it is already ruled:** the ruling's own reasoning is that
refusing is fixable and a silent OOM is not — but flipping a guard to fail-closed against a store
whose behaviour is unmeasured could refuse every query at work on the first deploy. The measurement
is one command and it decides whether this is a hardening or an emergency. Building ahead of it
would be guessing which, and shipping the guess.

## What layers 1 and 2 actually are

**Layer 1** — `query_datahub_asset` serialises **once**, measures the UTF-8 byte length, and refuses
over `DA_MAX_RESULT_BYTES` (default 256,000 ≈ 64k tokens ≈ half a 128k window). The refusal names
rows, columns and bytes, and its remedy names the escape that actually applies to the failing
shape — `COUNT(DISTINCT x)` instead of `ARRAY_AGG(DISTINCT x)`. "Select fewer columns" would not
have fixed the publog question, and a remedy that does not apply to the motivating failure teaches
the agent nothing.

**Layer 2** — `agent.run` is wrapped in `asyncio.wait_for(..., DA_AGENT_TIMEOUT_S)`, default 300s:
above a normal multi-step run, well under the 12 minutes observed. A timeout returns the failure
**dict**, never re-raises, and carries its own `reason="agent_timeout"` and its own metric value
rather than being averaged into the fumble rate as an indistinguishable `agent_raised`.

**One honest limit, pinned by an executed test rather than promised in a comment:** `wait_for`
cancels the *await*, not the thread. Python cannot kill a running thread, so `agent.run` keeps
burning its worker and its tokens until it returns on its own. What layer 2 buys is a bounded
**response**, not bounded **work**. `test_wait_for_bounds_the_AWAIT_and_NOT_the_thread` samples the
worker at the instant the timeout fires — sampling after the loop exits would measure loop shutdown
joining the executor, which is a different fact and would read as a refutation of a claim it never
tested.

**Layer 2 also interacts with layer 4 and cannot be assumed to fire.** If Restate's inactivity
default aborts a long `ctx.run` first, a 300s timeout is never reached. That is a further reason
claim 1 is a measurement and not a formality.

## Still outstanding after this

- claims 1 and 2, above — **blocked on a human at the work cluster**
- **acceptance:** re-run the original publog question and confirm it now fails fast as a refusal
  naming its own numbers, rather than slowly as an empty card
- the **determinism track** for chart selection — a deterministic function of (declared chart slot,
  SQL shape, result schema), model reading SQL + schema and never rows, so presentation's context
  cost stops scaling with the dataset. First step is the rules table built standalone and scored
  against historical (SQL, schema, chosen chart) triples: the agreement rate says whether the
  ambiguous residual is 2% or 30%. **A measured number before code**, and separate from this
  document — layer 1 bounds the reasoning loop's observations; the rules table removes data from
  the presentation decision entirely. Two couplings, two remedies, and neither caps what the system
  can query.

---

# SANDBOX REPRODUCTION — 2026-08-27. It corrects this document in three places.

The edge cluster already carries the real table: `publog-lake/publog/p_cage/data_0.parquet`,
86 MB, seeded and untouched. So the question that failed at work was run against the same data
rather than a synthetic stand-in. Everything below is measured.

## The source table barely passes the gate that exists

```
rows 4,158,375 x cols 9 = 37,425,375 cells   vs DA_MAX_SOURCE_CELLS = 40,000,000
-> PASSES, at 93.6% of the limit
```

Note the headroom: 6.4%. One more column on `p_cage` and the source gate begins refusing questions
it answers today. Recorded, not acted on.

## CORRECTION 1 — the mechanism argued here is not the one this table exhibits

This document claims, at §"Why the existing gate does not catch this":

> *That returns a few hundred rows — each carrying a list of every cage code for its company. The
> row COUNT collapses; the DATA VOLUME does not.*

**The row count does not collapse. It barely moves.**

```
rows                4,158,375
distinct company    3,950,528   (95.0% of rows)
distinct cage_code  4,158,375   (100.0% — it is the primary key)

codes per company:  1 code   3,830,292 companies
                    2 codes     94,125
                    3 codes     14,430
busiest:            1,493 codes  THE SHERWIN-WILLIAMS COMPANY DBA THE SHERWIN WILLIAMS CO
```

A CAGE code is issued per company facility and the names are effectively unique, so `GROUP BY
company` aggregates almost nothing. The result is 3.95 MILLION rows, not a few hundred. The
list-inflation story is a plausible mechanism that this table does not have.

**The finding is unaffected and the numbers are worse than the ones argued for:**

| query | result | cells | CELL gate | serialised | BYTE gate |
|---|---|---|---|---|---|
| `ARRAY_AGG(DISTINCT cage_code) ... GROUP BY company` | 3,950,528 x 2 | 7,901,056 | **PASSES** | 251,191,404 | REFUSED, **981x** |
| `COUNT(DISTINCT cage_code) ... GROUP BY company` | 3,950,528 x 2 | 7,901,056 | **PASSES** | 202,124,187 | REFUSED, **789x** |

A cell gate on the result passes both by a factor of five. The unit argument now rests on
measurement rather than on the example that motivated it.

## CORRECTION 2 — it is the GROUPING KEY, not the aggregate. This explains all four work runs.

Observation 6 says *"a narrower question returns fine"*, and layer 1's first remedy said "count
instead of listing". Both are the wrong axis. Same aggregate, same table, four keys:

| grouping key | distinct values | result rows | serialised bytes | gate |
|---|---|---|---|---|
| `company` | 3,950,528 | 3,950,528 | 202,124,187 | REFUSED |
| `state_province` | 13,233 | 13,233 | 546,342 | REFUSED (2.1x) |
| `country` | **212** | 212 | **7,048** | passes |
| `cage_status` | 12 | 12 | 352 | passes |

**Five orders of magnitude, decided entirely by the key.** Mapped against what was actually run at
work:

| # | question run at work | key | outcome at work | predicted by the table above |
|---|---|---|---|---|
| 1 | cage codes **per company**, x5 | company | all 5 OOMKilled, until RAM was raised | 251 MB — yes |
| 2 | distinct cage code counts **per company**, x2 | company | both timed out | 202 MB — yes |
| 3 | cage code counts **per country**, x1 | country | **worked** | 7 kB — yes |

Run 3 did not work because it was "narrower" in phrasing or because it counted instead of listing —
it counted instead of listing in run 2 as well, and that OOMed. It worked because `country` has 212
distinct values. The refusal text was corrected accordingly: it now names *"aggregate on a column
with FEWER DISTINCT VALUES"* first, because count-don't-list alone would have sent the agent from a
251 MB answer to a 202 MB one and called it a remedy.

## CORRECTION 3 — the same question, twice, gave two different failures

`DataAnalystService/analyze_data`, alice@example.com, the URN above, the user's exact phrasing.

**Run 1 — HTTP 200 in 122.5s, correct answer, no restart.**

```
Step 2  ... "COUNT(DISTINCT cage_code) ... GROUP BY company ORDER BY ... DESC"
        -> Code execution exceeded the maximum execution time of 30 seconds
        [Step 2: Duration 40.78s | Input tokens: 5,209]
Step 3  ... same query + LIMIT 200  -> final_answer          <- SELF-CORRECTED
        [Step 3: Duration 58.61s | Input tokens: 22,547]
DA_FUMBLE_METRIC outcome=success steps=4 step_errors=1
```

**Run 2, five minutes later, identical request — container OOMKilled at 2Gi.**

```
Step 2  ... same unbounded query -> exceeded the maximum execution time of 30 seconds
        [Step 2: Duration 53.56s | Input tokens: 5,134]
Step 3  ... THE SAME UNBOUNDED QUERY AGAIN, no LIMIT       <- DID NOT self-correct
        lastState: terminated, reason "OOMKilled", exitCode 137
```

Nothing differed but the run. **The recovery in run 1 was the model choosing to add `LIMIT 200`,
and in run 2 it chose to retry the same query instead.** That is why work saw five OOMs in a row on
one phrasing and two timeouts on another: the protection is a coin flip, and the flip is the model's.

## What is protecting the engine today, and why it is not enough

smolagents 1.24 ships two defaults nobody in this repo chose:

* `MAX_EXECUTION_TIME_SECONDS = 30` — the per-step code-execution timeout seen firing above
* `DEFAULT_MAX_LEN_OUTPUT = 50_000` — printed observations truncated head+tail with an explicit
  `..._This content has been truncated..._` marker

**So the current protection is a TIME bound doing a SIZE bound's job, and the margin is seconds.**
Measured in-cluster on the same table:

```
ARRAY_AGG form   query 29.1s + serialise 5.5s = 34.6s   -> over 30s, killed
COUNT form       query 24.5s + serialise 3.7s = 28.2s   -> UNDER 30s
```

A 202 MB answer takes 28.2s to produce on a 3Gi tools pod. On a faster node, a warm page cache, or
a slightly smaller table it lands under 30s, the step does not time out, and only the
50,000-character truncation stands between it and the prompt. This is this document's thesis
observed rather than argued: **the bound that exists is in seconds, the hazard is in bytes, and a
second and a half of slack is the whole protection.** It also explains the work/sandbox divergence
without any difference in code — a time bound gives different outcomes on different hardware for
the same question. A byte bound does not.

**One point in the framework's favour, on truncation.** smolagents splices head and tail around a
marker, which for a JSON array yields visibly BROKEN json — no reader mistakes it for the whole.
That is not an argument for our gate truncating: a gate emitting well-formed but incomplete JSON
would produce exactly the false completeness the ruling refused. The framework is accidentally safe
because its truncation is ugly.

## CLAIM 1'S INSTRUMENT IS WRONG — caught before it was run at work

The verification plan at §4 says:

> *The cheap confirmation is a count of `DA_AGENT_CONFIG` ... One question should print one line.
> If it prints several, the retry loop is real.*

Measured, for ONE question, on sandbox:

```
00:34:08.950  DA_AGENT_CONFIG                                  <- handler entered
00:36:09.229  DA_FUMBLE_METRIC ... outcome=success steps=4     <- the work, completed ONCE
00:36:09.372  DA_AGENT_CONFIG                                  <- entered AGAIN, 143ms later
                                                                  no metric follows: no work done
```

**Two `DA_AGENT_CONFIG` lines, one execution.** The second entry is a replay: that line prints at
agent construction, OUTSIDE `ctx.run("run-agent", ...)`, while the journaled step returns its
memoized result without re-executing — exactly as the durability comment in `main.py` describes.
The replay costs nothing.

So `grep -c DA_AGENT_CONFIG` counts HANDLER ENTRIES, replays included. Run at work as written it
would have reported *"the retry loop is real"* for a question whose expensive work ran exactly once.
**The instrument measures something adjacent to the claim.**

**The corrected instrument.** `DA_FUMBLE_METRIC` is emitted INSIDE the journaled step, so it prints
once per actual execution and not at all on a replay:

```bash
# how many times did the LLM loop actually RUN for one question?
kubectl logs -n <ns> deploy/iagent-data-analyst --tail=2000 | grep -c "DA_FUMBLE_METRIC"

# and the diagnostic form — entries vs executions, in order:
kubectl logs -n <ns> deploy/iagent-data-analyst --timestamps \
  | grep -E "DA_AGENT_CONFIG|DA_FUMBLE_METRIC"
```

One `DA_FUMBLE_METRIC` per question ⇒ no retry storm, however many `DA_AGENT_CONFIG` lines appear.
Several ⇒ layer 4 is real and expensive.

**What this does NOT settle.** Sandbox ran 122s; the work failure ran 12+ minutes. A 122s
invocation is not a test of a retry policy triggered by minutes of inactivity, so this measures the
INSTRUMENT, not the hypothesis. Claim 1 still has to be taken at work — now with a command that
answers the question that was asked.

## Layer 1 changed as a result of this run

The gate as first built serialised and then measured, so it allocated the full 251 MB inside a 2Gi
container in order to discover the payload was too large — the guard's own cost reinstating the OOM
it exists to prevent. A cheap `estimated_size()` pre-check (45ms and frame metadata, versus 5.5s
and a 251 MB string) now refuses first. Both checks are load-bearing and neither subsumes the
other: the pre-check is conservative by construction, and a fixture packing to 202,000 bytes
serialises to 323,701 — under the pre-check, over the limit. The json/estimate ratio is deliberately
not relied on anywhere, having measured 1.24x, 1.34x, 1.46x and 3.13x across ordinary shapes.
