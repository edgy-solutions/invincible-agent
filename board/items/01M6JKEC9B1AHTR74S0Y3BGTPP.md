---
title: Wire the Keycloak token exchange that #229 only ever ran against a double
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: now
blocked_on: []
pr: []
ruling_ref: architect 2026-11-04: exchange configured before any work install
updated: 2026-11-04
---

`IDENTITY_EXCHANGE_TOKEN_URL`, `_CLIENT_ID` and `_CLIENT_SECRET` are set by no values file, so a token near expiry goes straight to `awaiting_reauth`.

What it would need, from reading the chart, not run: a client row; per-client attributes in the realm reconcile, which has none today; an audience mapper on the subject tokens; the `authz-id` mapper on the new client; a new secret in Chris's overlay; and a live check with a person's token from Chris.

Ruled 2026-11-04: 0.4.78 rolls on the sandbox with `awaiting_reauth` observable, and the exchange is configured before any work install. That makes this item the gate for a work install. The live check still needs a person's token from Chris.
