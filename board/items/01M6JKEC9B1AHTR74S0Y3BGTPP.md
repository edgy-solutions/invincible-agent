---
title: Wire the Keycloak token exchange that #229 only ever ran against a double
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: blocked
priority: now
blocked_on: [chris:which of card or exchange or new ruling gates the roll]
pr: []
ruling_ref: architect 11-03: #229 doesn't roll without the card or a configured exchange
updated: 2026-11-04
---

`IDENTITY_EXCHANGE_TOKEN_URL`, `_CLIENT_ID` and `_CLIENT_SECRET` are set by no values file, so a token near expiry goes straight to `awaiting_reauth`.

What it would need, from reading the chart, not run: a client row; per-client attributes in the realm reconcile, which has none today; an audience mapper on the subject tokens; the `authz-id` mapper on the new client; a new secret in Chris's overlay; and a live check with a person's token from Chris.
