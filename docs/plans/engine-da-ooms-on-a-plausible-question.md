---
id:         engine-da-ooms-on-a-plausible-question
status:     open
owner:      unassigned
blocked-on:
closed-by:
code-site:  agent_fleet/data_analyst/main.py, helm/invincible-agent/values.yaml
repo:       invincible-agent
summary:    ⚠️ DEMO BLOCKER, diagnosed 2026-08-22. Engine DA is OOMKilled (exit 137, `Reason: OOMKilled`, 2Gi limit) executing an ordinary analytical question — `SELECT company, ARRAY_AGG(DISTINCT cage_code) FROM dataset GROUP BY company` over a publog table. It crashed MID-STEP on a real user question and the pod has been in CrashLoopBackOff; the previous pod restarted 15 times in 173 minutes. THE FAILURE IS SILENT FROM THE UI: routing succeeds and reports high confidence, the answer card renders with its title, and the body is empty with "No citations yet" — because the engine died before returning anything. An error would be better; this looks like an answer.
---

# Engine DA dies on a question a room would actually ask

Found while a prime was running, by chasing a restart count nobody had looked at.

## The reproducer is a real question that was really asked

```
Q: give me the distinct cage codes per company from publog's p_cage
routing: analyze Dataset · Engine DA · high confidence
```

Engine DA's own log, from the container that died:

```
Executing parsed code:
  result = query_datahub_asset(
      urn="urn:li:dataset:(urn:li:dataPlatform:s3,iagent-minio.publog-lake/publog/p_cage,PROD)",
      sql_query="""
          SELECT company, ARRAY_AGG(DISTINCT cage_code) AS cage_codes
          FROM dataset GROUP BY company ORDER BY company;
      """)
  print(result)
```

…and the log ends there.

```
Last State: Terminated   Reason: OOMKilled   Exit Code: 137
Limits: cpu 1, memory 2Gi     Restart Count: 2 (and 15 on the pod it replaced)
```

## Why this outranks its size

**The UI cannot tell this from a thin answer.** Routing resolved, confidence was high, the card
rendered its title and headline, and `Sources & Evidence` said *"No citations yet. Evidence
appears as engines return matches."* — which is literally true and reads like patience rather
than death. In a room, that is a confident-looking blank, and the presenter has nothing to point
at. **An honest error would be strictly better than this.**

It also cost real diagnostic time in the wrong place: the blank card surfaced the same hour as a
presentation-registration failure, and was initially attributed to `select_presentation`
refusing an unregistered archetype. That was wrong — `analyze Dataset` routes to
`mesh:DatasetAnalysisReport` → `CHART_WIDGET`, which has been registered throughout. Two failures
surfacing together are not one failure.

## Cause

`ARRAY_AGG(DISTINCT …) GROUP BY …` over a wide publog table, executed through the
smolagents/LiteLLM path, materialises its result set in the engine's process. 2Gi is not enough
for a wide aggregation over a large table, so the pod is killed by the kernel rather than
returning an honest "too large".

Two aggravating facts found alongside:

- **The readiness probe is the same defect as the BFF** — `/health` with a 1s timeout, failing
  with `context deadline exceeded` — so a busy analyst also flaps out of the endpoint list. See
  [`bff-liveness-probe-kills-under-load`](bff-liveness-probe-kills-under-load.md); this is the
  second engine with it, which makes it a chart-wide default rather than one service's mistake.
- **Restarts were invisible.** The previous pod restarted 15 times in 173 minutes while the
  surface looked healthy, and nothing surfaced it until someone read a pod list by hand.

## Disposal

1. **Bound the result set in the engine.** The real fix. An analytical engine should refuse or
   page a query whose result will not fit, and say so — the honest-degradation path this
   codebase already has for undrawable payloads, applied to unfittable ones. A `LIMIT`-injection
   or row-count precheck turns an OOM into an answer.
2. **Raise the memory limit.** Cheap, buys headroom, and moves the cliff rather than removing
   it — the next wider table finds it again.
3. **Fix the probe defaults** (shared with the BFF packet) so a busy engine is not also an
   unready one.

**Do 1.** Do 2 as well if the demo is close, and say out loud that it is a mitigation.

## Acceptance

The reproducer question above returns either an answer or an explicit refusal naming the size
limit — never an empty card. Restart count on the deployment stable, read twice with a gap.
