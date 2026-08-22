---
id:         bff-liveness-probe-kills-under-load
status:     open
owner:      unassigned
blocked-on:
closed-by:
code-site:  helm/invincible-agent/values.yaml, src/iagent/gateway.py
repo:       invincible-agent
summary:    ⚠️ DEMO RISK, classified 2026-08-22. cortex-bff was SIGKILLed (exit 137) under ordinary traffic — not OOM, a LIVENESS PROBE KILL. The probe allows `/health` `timeoutSeconds: 1` with `failureThreshold: 3`; kubelet recorded "Liveness probe failed x4 over 105m" and "Readiness probe failed x6" with `context deadline exceeded`. A single-threaded FastAPI event loop busy with an Electric shape proxy or a graph query cannot always answer within one second, so the BFF is killed for being busy. In a demo this is every answer failing at once with nothing in the log to point at — the container dies without writing a reason.
---

# The BFF is killed for being busy, and it dies without saying so

Found while chasing why a registration's logs were missing: the pod had restarted, and the
logs were in the *previous* container.

## Classified, not guessed

```
Last State:  Terminated    Reason: Error    Exit Code: 137
Started:  11:03:05   Finished:  11:03:04 (prev)   Restart Count: 1
Limits:   cpu 500m   memory 512Mi

Events:
  Warning  Unhealthy  Readiness probe failed (x6 over 105m): context deadline exceeded
  Warning  Unhealthy  Liveness  probe failed (x4 over 105m): context deadline exceeded

livenessProbe: { path: /health, timeoutSeconds: 1, periodSeconds: 10, failureThreshold: 3 }
```

Exit 137 is SIGKILL. **It is not OOM** — an OOM kill reports `Reason: OOMKilled`, and memory
never appears in the events. The kubelet killed it because `/health` did not answer within one
second, three polls running.

## Why one second is the wrong budget here

`/health` is served by the same single-threaded event loop that proxies Electric shapes,
serves review batches, and issues graph queries. A slow upstream or a burst of shape traffic
blocks the loop, and a blocked loop cannot answer a health check no matter how trivial the
handler is. **The probe is measuring event-loop availability and calling it liveness.**

The readiness failures (x6) are the same cause showing up earlier and more often — the service
was flapping out of the Service's endpoint list before it was ever killed.

## Why this matters more than its size

In a demo the BFF is on the path of every answer. A restart is ~seconds of total failure, and
the container **writes nothing about why** — the last lines before death are ordinary 200s.
Someone debugging live sees answers stop and a healthy-looking log. The reason exists only in
`kubectl describe`, which is not where anyone looks first.

This is also why a registration's rejection log went missing for twenty minutes of
investigation today: the evidence was in the previous container, and nothing in the current
one hinted that a previous container existed.

## Disposal

1. **Raise `timeoutSeconds` to 5 and `failureThreshold` to 3–5.** Smallest change; matches what
   the endpoint actually is. A genuinely wedged service still dies, just not a busy one.
2. **Give `/health` its own budget** — keep it dependency-free and never let it await an
   upstream, so it measures the process rather than its neighbours.
3. **Consider `startupProbe`** so `initialDelaySeconds: 30` stops doing double duty.

Do NOT simply remove the probe: a wedged BFF that stays in the endpoint list is worse than one
that restarts.

## Acceptance

An hour of ordinary sandbox traffic with zero `Unhealthy` events on the deployment, confirmed
by `kubectl describe`. Restart count stable, checked twice with a gap — a single reading of a
restart counter says nothing about whether it is still climbing.
