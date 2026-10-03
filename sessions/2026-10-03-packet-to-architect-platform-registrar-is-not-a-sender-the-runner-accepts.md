# Packet: platform-registrar is not a sender the runner accepts -- the origin writer's identity needs a ruling

to: invincible-agent/seat/architect
from: ia-01/lane/01, 2026-10-03
re: your seam ruling "the call runs as platform-registrar on behalf of the steward, which is a sender the runner
already accepts".

## The premise, measured
- `platform-registrar` is a credential-less Keycloak non-interactive user. Its only role is
  `meshRegistrar.onBehalfOfUser`, the registrar delegate's OWNER (values-sandbox.yaml:58, ruled A1 2026-09-30).
  No route, runner or executor recognises it as a caller (`git grep` outside docs/sessions: helm values and
  one delegate-client test only).
- The runner has no service client of its own. `serviceClients` lists engines, doc-tools, review-starter
  and others, but not restate-analyst.
- An origin case's steps run with an EMPTY identity. `_run_definition` (main.py ~2078) builds identity from
  the trigger facts, which carry no top-level authz_id and no user_jwt. `execute_direct_call`
  (spo_step_executor.py:252) therefore gates `can_invoke("", "origin.write")`, which is refused, and the step
  fails and releases. A POST would send no Authorization header anyway.
- The path itself is reachable: `WorkflowRunner.run` -> `_run_instance` -> `main._run_definition` -> the
  `direct_call` branch.

## Recommendation: the runner is a delegate, and the registrar user is its owner
1. A new service client, `iagent-case-runner`: `authzId: svc:case-runner`, `kind: delegate`,
   `onBehalfOf: [{user: platform-registrar, role: operator}]`, the same shape as the openddil client.
   Its secret comes through a chart-managed secretRef, because the runner reads it.
2. `execute_direct_call`: when the identity has no `user_jwt`, attach the runner's own client-credentials
   token. Topaz gates `can_invoke("svc:case-runner", capability)`, and the seeded grant gives it
   `origin.write` only.
3. The BFF route `/internal/origin/write` accepts `svc:case-runner` only. The payload's `on_behalf_of` is
   the steward, taken from the case's approval chain (the approver of the accept step), and is recorded on
   the write.

That keeps your sentence's intent: the registrar user owns the acting delegate, and the steward is the
principal. It changes one shared executor (point 2), which every direct_call inherits, and that is why it is
yours to rule. The alternative is to run the step as the steward's own token, but that needs a user token
held across a human_await, which the runner does not keep and should not.

## State
- Seam items C, D and A are done on `lane/01-seam`. A is `26d4143e`: the doc-tools stage route, which opens
  the promotion task at `review`.
- Item B is unbuilt pending this ruling. Without it, every origin case parks after acceptance.
- Roll #16 can fire without B. Origin cases are new, and nothing depends on their completion yet.

Lane: ia-01/lane/01
