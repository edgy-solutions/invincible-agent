---
id:         chart-type-is-a-model-call-over-the-rows
status:     open
owner:      unassigned
blocked-on: a few days of POST-GATE history at work. The ruled first step is a rules table scored against historical (SQL, schema, chosen chart) triples, and the pre-gate history cannot supply them — see §The corpus cannot be built from existing history.
closed-by:
code-site:  agent_fleet/presentation_agent/main.py:664
repo:       invincible-agent
summary:    RULED, NOTHING BUILT. `RenderAsChart(str_raw_data, persona)` infers chart_type from the ENTIRE serialised result set, so presentation's model context scales with the dataset — the same data-size coupling `bounding-the-answer-not-just-the-source` closed one stage upstream, at a different boundary. Ruled fix: chart selection becomes a deterministic function of (declared chart slot, SQL shape, result schema), any residual model call reading SQL + schema and never rows. First step is a rules table measured against historical triples, which is why this is blocked on clean post-gate history rather than on a design.
---

# The chart type is a model call, and its input is the whole answer

Verified at the call site, not inferred:

```python
# main.py:794
str_raw_data = json.dumps(request.raw_data)     # the ENTIRE result set
...
# main.py:664
ui = await b.RenderAsChart(str_raw_data, persona)
```

and the function's own docstring (`main.py:590`):

> *The LLM is still responsible for **chart_type inference** and sql_query pass-through — what
> it can't be trusted to do reliably is rename keys to match a hardcoded React contract.*

So the model's only inputs are **the serialised rows and the persona.** The SQL is not an
argument. The schema is not an argument. The one decision being made — which chart this is —
is made from the one input whose size is unbounded.

**This is the same defect species as the one closed upstream, at a different boundary.**
`bounding-the-answer-not-just-the-source` bounded what crosses into the REASONING loop's prompt.
Nothing bounds what crosses into the PRESENTATION model's prompt, and the remedy is not the same:
there the answer was a byte ceiling, here it is that the decision never needed the rows at all.

## The ruling

Chart selection becomes a deterministic function of **(declared chart slot, SQL shape, result
schema)**, in that precedence order.

1. **A declared slot wins outright.** "Show me a bar chart of X" is dispositive — an intent slot,
   the same mechanism as scope or window, editable in the interpretation strip. Visible and
   correctable rather than guessed.
2. **SQL shape decides most of the rest.** `GROUP BY` names the categorical axis; `ORDER BY` on a
   date column says time series; an aggregate over one group is a metric; `ORDER BY <agg> DESC`
   with `LIMIT` is a ranked bar. The query is the analyst's own declaration of what the data
   means, and it is a few hundred tokens.
3. **Result schema is the fallback** — dtype signature x cardinality bucket. Metadata, ~200 bytes,
   not 40 MB.

Any residual model call for the genuinely ambiguous case **reads the SQL and the schema, never the
rows.** That makes its context cost constant regardless of dataset size, which is the whole point:
the data-size limit exists because the model sees data at all, and none of the three signals
requires it to.

## TWO SEPARABLE HALVES. Do not conflate them.

Conflating these is the `archetype-hardened` vs `projected` confusion by another name — the
distinction that already cost one round of wrong reasoning about this path.

* **(a) chart-type SELECTION becomes rule-driven** — removes the model's *choice*. Ships alone,
  measurable alone, and is where the value is.
* **(b) component BUILDING becomes projection** — rows pass through verbatim, `CHART_WIDGET`
  joins `_PLANNING_ARCHETYPES`, removes the model's *call*.

**(a) first.** With the residual model constrained to SQL + schema it captures most of the value
and can be measured on its own. If the rules table's agreement rate comes back at 95%+, (b) is a
formality rather than a decision.

## THE CORPUS CANNOT BE BUILT FROM EXISTING HISTORY

The ruled first step is the rules table, standalone, scored against historical
`(SQL, schema, chosen chart)` triples: **how often does the deterministic rule agree with what got
chosen?** A measured number before any code touches the path — 2% ambiguous residual and this is
nearly free, 30% and the shape of the fix changes.

**"Just use the existing history" is the obvious shortcut, and it is wrong.** Measured, on
2026-08-27, running one real question against the sandbox engine twice:

| run | outcome | triple it yields |
|---|---|---|
| 1 | 30s step timeout, model self-corrected to `LIMIT 200`, answered | a triple whose ANSWER is a truncated top-list |
| 2 | 30s step timeout, model retried unbounded, **container OOMKilled at 2Gi** | no triple at all |

One question, two runs, five minutes apart, identical request. Neither produced a usable triple.

**Pre-gate history is a record of what an UNPROTECTED engine did under duress, not of what charts
fit what queries.** Scoring the rules table against it would measure the gate's absence and report
it as the rules' disagreement rate. The corpus has to start after the result gate lands, which is
what this packet is blocked on — not on a design session.

## Row one is already waiting

From run 1 above — the model's own self-correction, a real query from a real question:

```sql
SELECT company, COUNT(DISTINCT cage_code) AS distinct_cage_count
FROM dataset GROUP BY company ORDER BY distinct_cage_count DESC LIMIT 200
```

That is the ranked-bar signature complete: `GROUP BY` naming the categorical axis, `ORDER BY <agg>
DESC` with `LIMIT` naming the ranking. **Decided from a few hundred tokens of SQL, while the 202 MB
result never enters the decision.**

Note what it demonstrates beyond the rule firing correctly: **the model, left to itself, produced a
query whose SHAPE declares its chart.** The rules table is not imposing structure on the model's
output — it is reading structure the model already puts there. That is the strongest available
argument that the residual ambiguous case is small.

## Related

An instance of [[deterministic-decisions-made-by-llm]] — a decision that could follow the data's
declared structure is instead a model judgment. Distinct from [[archetype-chosen-before-data]]
(CLOSED): that packet's claim was which ARCHETYPE is selected, now false by construction since the
payload is validated against the published contract first. This packet is about the chart TYPE
chosen inside `CHART_WIDGET` once the archetype is settled, which that fix did not touch.

Upstream sibling: `docs/proposals/bounding-the-answer-not-just-the-source.md` — same coupling
(model context scaling with dataset size), different boundary, different remedy. Layer 1 there
bounds the reasoning loop's observations; this removes data from the presentation decision
entirely. **Neither caps what the system can QUERY — only what crosses into a context window.**

## What this packet does NOT cover, deliberately

The menu-scoped half — binding the decision to the CALLING CLIENT's capabilities — is filed as
[[render-request-carries-no-frontend-id]] and stays there. Holding a packet open past its own scope
to cover adjacent work is how a summary drifts from its header.
