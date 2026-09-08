# Seven engines have served UNREGISTERED since revision 102

**Captured 2026-09-08 before any roll**, because the evidence exists only in the current pods'
logs and a roll discards it. Nothing was rolled: the human declared a deploy freeze overnight.

## What happened

`helm upgrade` to revision 102 (chart 0.3.58, the Dagster CPU sizing) restarted the release.
Every engine came up inside an eleven-second window; Keycloak came up **47–58 seconds later**.
Registration is attempted **only at startup**, so every engine exhausted its retries against a
Keycloak that was not yet answering, and none of them ever tried again.

| pod | started | vs Keycloak |
|---|---|---|
| `iagent-engine-d` | 23:16:43Z | −58s |
| `iagent-engine-p` | 23:16:44Z | −57s |
| `iagent-engine-fin` | 23:16:46Z | −55s |
| `iagent-engine-cost` | 23:16:48Z | −53s |
| `iagent-engine-e` | 23:16:50Z | −51s |
| `iagent-engine-w` | 23:16:52Z | −49s |
| `iagent-data-analyst` | 23:16:54Z | −47s |
| **`iagent-keycloak-0`** | **23:17:41Z** | — |

All seven carry the identical alarm:

```
ERROR:mesh_registration:❌ mesh registration: UNREGISTERED
  (mint failed: ServiceTokenError: mint_token: Keycloak token endpoint unreachable ...)
  [Errno 111] Connection refused
```

**This was caused by my deploy.** Revision 102 was mine — the user-code CPU sizing. The change
itself was correct and stands; the collateral is that a full-release restart has no ordering
guarantee between the engines and their identity provider.

## The part that changes what this means

**Routing still works, and existing verbs still dispatch.** Proven, not assumed: at 03:28 on
2026-09-08 — four hours *after* the failed registrations — a pre-resolved pick routed to
`iagent-engine-p` and returned an answer, while engine-p was in this state.

The reason is that routing reads the **Neo4j compat-walk**, which holds the registration
written at some earlier, successful startup. The graph remembers.

**CORRECTED 2026-09-08 by `invincible-agent-91`, and the correction matters.** I wrote below
that this outage is why engine-cost cannot bind `cost:PriceComposition`. **It is not.** 91
queried Neo4j properly — a registration is a *relationship carrying `endpoint_url`*, not a
node — and **all nine cost verbs are registered right now**, with correct endpoints and
correct stored slot declarations, verified verb by verb rather than inferred from an alarm not
firing. That lane's loss set is **empty**.

So what is lost is narrower than I made it: *whatever a given engine would have changed at
this startup*, which must be checked per engine and per verb rather than read off the alarm.
For engine-cost the answer was nothing. The engine's *current*
process never re-asserted itself, but nothing invalidated what was already there.

So the alarm's own wording — *"its verbs will NOT route until a successful re-registration"* —
overstates it for verbs that were already registered. What is actually lost is anything this
startup would have **added or changed**: a newly declared verb, a changed endpoint, a changed
slot declaration — **per engine, checked, not assumed**: see the correction above, where
the answer for engine-cost turned out to be nothing. The real `PriceComposition` blocker
is that `mesh:StepLadder` and `mesh:NamedHole` are declared and unprimed — a different
problem that my original sentence would have masked.

**The failure is therefore latent rather than active, and that is worse for diagnosis, not
better.** The fleet looks healthy, answers correctly, and silently ignores every registration
change made since 23:16. Anyone who redeploys an engine expecting a new verb to appear will
watch it not appear, with a green pod and a passing probe.

## What to do, and what was deliberately not done

**A roll of the seven fixes it** — Keycloak answers from inside the engine pods now (verified
by `invincible-agent-91`, which probed the discovery endpoint from the container).

**Not done tonight**, for three reasons, one of which is decisive:

1. The human declared no shared-infra deploys until they are up. Seven deployments is not a
   component any lane exclusively owns, and no peer can grant that permission.
2. The evidence lives in these pods' logs and would be discarded by the roll. Now captured
   here, so the roll is cheap whenever it happens.
3. The sequencing question is real and outlives this incident (below).

## The durable question, which is the actual finding

Rolling seven pods fixes today. It does not fix that **registration is startup-only with a
bounded retry, against a dependency with no ordering guarantee.** The same race recurs on
every full-release upgrade, and its tell is silence.

Worth deciding, in rough order of cost:

- **A registration that retries for the life of the process**, not just at boot — an engine
  that cannot mint a token is not permanently unable to.
- **A readiness probe that fails while UNREGISTERED**, so the state is visible to Kubernetes
  instead of only to a log line nobody greps. This is the change that would have made tonight
  a red pod instead of a four-hour silence, and it keeps working when Keycloak restarts hours
  later — which ordering cannot touch.

  **It must fail on "gave up", never on "still trying"** (91's point, and the difference
  between a fix and a worse outage). A probe that goes red while an engine is still retrying
  turns a cold start behind a slow Keycloak into a crash-loop.
- **Ordering** — engines depending on Keycloak's readiness. Cheapest to express, weakest
  guarantee, since it does not help if Keycloak restarts later.

## How it was found, and the method note

`invincible-agent-91` found it on engine-cost and said plainly that it had *sampled a few pods
and not swept properly*. That sentence is why this document exists: the census over all 39
running pods found **seven**, and six of them nobody had looked at.

A defect report is a sample, not a census — and the neighbours that look fine are what hide the
class. The scan is one line and worth keeping:

```bash
for P in $(kubectl get pods -n sandbox --field-selector=status.phase=Running \
             -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'); do
  kubectl logs -n sandbox "$P" --tail=3000 2>/dev/null \
    | grep -q UNREGISTERED && echo "UNREGISTERED: $P"
done
```

Census: 39 pods scanned, 1 registered OK, **7 UNREGISTERED**, 31 with no registration line
(they do not register).
