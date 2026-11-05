---
title: The BFF reads gateway_delegates.yaml from the merged policy view, and a row's for replaces DELEGATE_ON_BEHALF_OF
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: architect 11-04 on #224's three readings; architect via Chris 11-04 on #251's forks 1 and 3; Chris 11-04: lands in 0.4.80
updated: 2026-11-04
---

**A regression is open until this lands.** Since #251 (`758811d7`), the BFF reads `gateway_delegates.yaml` only from its own image (`/app/policy/`). The chart mounts no deployment policy on the BFF. Before #251, a deployment added a register service in a values overlay (`keycloak.taskRegisterServices`). Now it needs an image, which fails the 10-30 rule's third test.

It lands in 0.4.80 (Chris 11-04: no work install in 0.4.79, so 0.4.79 ships without it).

One PR carries both halves.

**Fork 1: the merged view.** The BFF mounts the policy overlay the way the other rails do: a ConfigMap or overlay dir layered over the image's `policy/`.
- The existing mechanism is `policyOverlay`, with the `cortex-bff` row that already delivers `canvases` (`templates/_helpers.tpl`, `docs/contracts/finance-overlays.md` section 4).
- `gateway_delegates.yaml` is read from the merged view: the image's seed rows plus the overlay's rows.

**Fork 3: `for:` on the row.** R-089's per-delegate list of people is a field on the delegate row, not chart config.
- `for: any` is the default. `for: [subject, …]` lists exactly who that service may act for.
- A `door: bff` row with `for:` replaces that service's `DELEGATE_ON_BEHALF_OF` entry.
- The chart key goes in the same PR. That's `DELEGATE_ON_BEHALF_OF`, rendered in `templates/configmap.yaml` from the `kind: delegate` clients' `onBehalfOf`.

**To settle in the spec, not guess:**
- how the BFF's `_delegate_principals()` consumers read a rail row (it has about fifteen call sites, and several use it only as "is a delegate");
- what a seed row may name in `for:`, given sandbox principals (users.yaml subjects and brokered subs);
- the merge rule when a seed row and an overlay row name the same (service, door).

Architect 11-04, reading 1: `policy/gateway_delegates.yaml` is the central gateway's list, and the BFF is the second internal door reading the same file. #251 built the first half: the `door` key, and the BFF reading the `door: bff` rows for `human_tasks.register`.
