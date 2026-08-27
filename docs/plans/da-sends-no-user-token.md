---
id:         da-sends-no-user-token
status:     open
owner:      human
blocked-on: 
closed-by:  
code-site:  agent_fleet/data_analyst/main.py:256
repo:       invincible-agent
summary:    COUPLING — Engine DA passes jwt_token=None to CortexDataClient and rides entirely on the X-Originator-Email header. So the obviously-correct fix in [[dag-tools-gateway-unverified-subject]] — stop preferring the header over a verified token — TAKES DA'S DATA ACCESS DOWN. Neither item mentions the other. This exists so nobody does the right thing to the gateway and discovers the coupling in production.
---

# Killing the gateway's header override breaks Engine DA, and neither item says so

**Found 2026-08-26**, while answering an unrelated question about notebook authentication.
Not a defect in DA on its own terms — DA works. It is a **cross-repo coupling** between two
open items that each look independently safe to fix.

## The coupling in three lines

`agent_fleet/data_analyst/main.py:256`:

```python
user_jwt = None
```

Never reassigned. It is passed straight through at `:447`:

```python
client = CortexDataClient(
    broker_url=broker_url,
    jwt_token=user_jwt,          # <- always None
    originator_sub=originator_sub,
    originator_email=originator_email,
)
```

So DA sends **no user token at all**. `CortexDataClient` falls through
`None or os.getenv("MESH_DEV_TOKEN")` to whatever transport identity that pod has, and the
authorization subject arrives entirely as `X-Originator-Email`.

`[[dag-tools-gateway-unverified-subject]]`'s step 2 is *"gateway stops preferring
`X-Originator-Email` over a verified user token."* Applied today, DA has no verified user
token to fall back to, and its M2M token carries a hardcoded `svc:data-analyst` in the
entitlement claim. **Every DA read denies.**

## Why it is `None` — the reason is recorded, and it is reasonable

From the comment above the line:

> The central-gateway already enforces authz on the data path; engine-side authz can be
> re-added once the decorator is rewritten to be Restate-compatible.

An authz decorator's `*args, **kwargs` wrapper blinded Restate's inspect-based handler-arg
detection, so it was removed and the user JWT went with it. There is vestigial plumbing at
`:770` that sets `payload["user_jwt"] = auth_header`, but the handler never reads it — and
it holds the raw `Authorization` header (`"Bearer eyJ..."`), not a bare token, so it would
not have been usable as one.

## The circularity worth naming

DA defers authorization to the gateway. The gateway takes its authorization subject from
the header DA sends it. **Each defers to the other**, and the composed path is trusted by
neither end — the same
security-assumed-at-a-boundary-the-component-does-not-control shape as the
`MESH_DEV_TOKEN` docstring, except both ends are doing it simultaneously.

That is also why DA's transport identity is currently unfalsifiable: whether the pod
authenticates with a leftover `MESH_DEV_TOKEN` or with `svc:data-analyst`, the reads behave
identically, because neither is the subject. A misconfiguration there is not merely
unnoticed — it is **unnoticeable**, with no observable difference to notice.

## What has to happen, and in what order

| # | step | why this position |
|---|---|---|
| 1 | thread the end user's JWT into the DA handler and pass it as `jwt_token` | the gateway change has something to verify |
| 2 | witness DA reading with a user token, header still present and agreeing | the gauge already reports `agreement=agreeing`; make it true by construction |
| 3 | gateway stops preferring the header — `[[dag-tools-gateway-unverified-subject]]` step 2 | safe only after 1 and 2 |

Step 1 must resolve the Restate-compatibility problem the comment names, or thread the token
as request data rather than through a decorator. The `:770` plumbing is a starting point; it
needs to carry a bare token, and the handler needs to read it.

## The gauge already has the number for step 3

The subject-source gauge reports `source=` / `agreement=` on every live authorize. A sample
observed 2026-08-26 read `source=header-override agreement=agreeing token_subject_present=True`.
**Tallying `agreement=` across a window is what tells you whether removing the override is a
config change or a migration** — and this item is the reason a "100% agreeing" reading would
still not make it safe: DA agrees because it *sends* both, not because its token is verified.

## Acceptance

- DA reads data while sending a user JWT, with the gateway verifying it.
- With the header override removed, DA still reads.
- A DA request whose header disagrees with its token is refused rather than served.

## The ADR-shaped sentence underneath

> **A component that defers authorization to another must send that other something it can
> verify. Deferring while sending only an assertion makes the pair trusted by neither.**
