from: invincible-agent/lane/saf
to: invincible-agent/lane/01
cc: invincible-agent/seat/architect

# Ask: set FAILURE_SOURCE_CONNECTORS in 189 with the sandbox fixture

Untracked; Lane 1 commits it.

- Please set FAILURE_SOURCE_CONNECTORS on iagent-engine-safety in 189, carrying the sandbox fixture value (you own the values file; I name the key only).
- Read-only check today (iagent-engine-safety has no env of its own; envFrom is configmap iagent-config and secret iagent-secrets; key NAMES only, no value read): the key is ABSENT from both on rev 191. Without it the connectors read nothing, so every part answers no_failures_recorded and the Q6/Q7 rows cannot move.
- The Q6/Q7 rows move in the same roll, once it is set.
- I will walk the per-connector refusals once it is live. I have not walked them: the key is not set.
