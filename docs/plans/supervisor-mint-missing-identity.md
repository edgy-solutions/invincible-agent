---
id:         supervisor-mint-missing-identity
status:     open
owner:      agent
blocked-on: nothing — one read settles it: `printenv` for SUPERVISOR_CLIENT_ID and SUPERVISOR_CLIENT_SECRET in the pod that runs the supervisor. KeyError does not say which.
closed-by:
code-site:  agent_fleet/utils/service_identity.py:57
repo:       invincible-agent
summary:    Every supervisor dispatch is unauthenticated at work — `mint_supervisor_token()` raises KeyError, so specialists record `caller: none`. Inert under OBSERVE, and it becomes a hard failure the moment REQUIRE_TRANSPORT_AUTH flips.
---

# The supervisor dispatches with no identity, and the engine logs the confession

Every specialist dispatch at work carries this:

```
caller: none (absent, claimed:mint-failed:KeyError) posture=OBSERVE path=/analyze_data
```

## First — this is NOT Engine DA's secret

It reads as a DA problem and is not. `X-Auth-Status` is a **caller-asserted** header that the
receiving engine logs verbatim (`iagent_mesh/transport_auth.py:358`, marked *"legal to LOG and
illegal to TRUST"*). The setter is the SUPERVISOR
(`src/iagent/defs/dynamic_supervisor.py:953`), when its own mint throws. DA merely recorded
what its caller admitted.

`mint_supervisor_token()` reads `os.environ["SUPERVISOR_CLIENT_ID"]` AND
`os.environ["SUPERVISOR_CLIENT_SECRET"]` (`service_identity.py:57-60`). The `KeyError` names
neither, and they arrive by different routes — the ID from the ConfigMap
(`configmap.yaml:167`), the secret from the Secret (`secrets.yaml:34`) — so a pod missing just
one is entirely possible.

Diagnosing this as `CORTEX_CLIENT_SECRET` would send the next person to the wrong pod and the
wrong variable. It was filed that way once already and corrected before landing.

## Why it is not urgent, and why it will be

The dispatch catches the exception and proceeds unauthenticated
(`dynamic_supervisor.py:943-958`), which is correct OBSERVE-phase behaviour: the gauge needs
the discriminant, so the cause travels as a diagnostic header rather than failing the request.
Nothing is broken today.

It becomes a hard failure at the transport flip. `svc:supervisor` exists as a declared
identity and is unusable by the only process that needs it — the same declared-but-unwired
class as `ENGINE_A_CLIENT_SECRET`, which was found by RENDERING the chart rather than trusting
the `serviceClients` list.

## The read

Both variables, in whichever pod runs the supervisor (a Dagster asset, so the user-code or run
pod, not an engine):

```
kubectl exec -n <ns> deploy/<pod> -- printenv | grep SUPERVISOR_
```

Both are wired in the chart and both are inside published 0.3.36 (tag = `3ac573d`, the commit
that introduced them), so a missing one means the pod does not mount what it should — not that
the chart lacks it. Which is itself the finding.

## Related

Work runs an EXTERNAL Keycloak (`keycloak.enabled: false`), so the realm-reconcile job never
renders and the `iagent-supervisor` client must exist in the corporate IdP by hand, with an
`authz-id-svc` mapper writing `svc:supervisor` into `preferred_username`. A present-but-wrong
secret fails as a Keycloak 401, not a KeyError — a different symptom worth distinguishing when
reading the fix.
