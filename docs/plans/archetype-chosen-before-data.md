---
id:         archetype-chosen-before-data
status:     open
owner:      agent
blocked-on: nothing — small and mechanical. The honest-degradation half shipped 2026-08-15; this is the half that stops forcing the wrong shape in the first place.
closed-by:
code-site:  agent_fleet/presentation_agent/main.py
repo:       invincible-agent
summary:    The UI archetype is selected from the verb's output_uri before anything looks at the rows, so every analyzeDataset result becomes a CHART_WIDGET — including a list of CAGE codes, which are identifiers and can never be plotted. The payload's shape should decide; output_uri is a hint, not a verdict.
---

# A capability map decides the shape, and the data is never consulted

```
render_ui: output_uri=http://invincible-agent/mesh#DatasetAnalysisReport
           matched capability archetype=CHART_WIDGET
```

`mesh#DatasetAnalysisReport` → `CHART_WIDGET`, always. The rows are not examined. So a query
returning `["00000", "00001"]` — two CAGE codes — is routed to a bar chart, and the BAML call
is then instructed to "fill in chart_type, chart_data … not to pick a different shape."

Identifiers are categories. There is no measure, so there is no chart, and no amount of
prompt-following produces one.

## What already shipped, and what it does not fix

2026-08-15 closed the **degradation** half: the normalizer now rejects non-numeric `value`
(it was accepting `{"name":"cage","value":"00000"}` as already-normalized and passing strings
to Recharts), and non-empty-but-unnormalizable payloads now reach the same honest fallback
that empty ones always did — so the user sees `00000, 00001` instead of "CHART DATA NOT
RENDERABLE".

That is correct and it is a fallback. The system still *chooses wrong first* and recovers.
A list of values should have been a table or a value list by decision, not a failed chart by
recovery.

## The repair

Let the payload's shape pick the archetype, with `output_uri` narrowing the candidates rather
than dictating the answer:

- rows with a category and a numeric measure → `CHART_WIDGET`
- rows of scalars / identifiers → a list or table archetype
- a single scalar → `ASSET_STATE_METRIC`
- prose → `KNOWLEDGE_DOCUMENT`

This is deterministic and testable on the payload alone — the same discipline the chart
normalizer already embodies (*"LLMs produce data, deterministic steps conform shape"*),
applied one level up to the shape CHOICE rather than only to shape conformance.

Note there may be no list/table archetype in the enum today
(`PROCESS_TOPOLOGY | HAZARD_DECLARATION | ASSET_STATE_METRIC | KNOWLEDGE_DOCUMENT |
CHART_WIDGET | DIGITAL_TWIN_3D`). If so, adding one is part of this — and until it exists,
`KNOWLEDGE_DOCUMENT` carrying the verbatim values is the honest stand-in, which is what the
fallback now does.

## Related

An instance of [[deterministic-decisions-made-by-llm]] — a decision that could follow the
data's declared structure is instead made by a static type mapping that cannot see it. Same
family as subject selection, different mechanism: there a model overrides the scores, here a
lookup table never consults the rows.
