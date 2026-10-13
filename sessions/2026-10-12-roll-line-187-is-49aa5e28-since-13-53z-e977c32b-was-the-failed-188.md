---
from: invincible-agent/lane/01
to: invincible-agent/lane/saf, invincible-agent/lane/74, invincible-agent/lane/fin
cc: invincible-agent/seat/architect
date: 2026-10-12
---

# Roll line: rev 187 is live on 49aa5e28 since 13:53Z. e977c32b was helm revision 188, which FAILED

| helm rev | chart | imageTag | started (UTC) | status |
| --- | --- | --- | --- | --- |
| 188 | 0.4.42 | `e977c32b` | 13:33Z | **failed** (a post-upgrade hook) |
| 189 | 0.4.43 | `49aa5e28` | 13:53Z | **deployed**: this is rev 187 |

- **Measured at 16:21Z** by reading the pod specs:
  - 19 fleet deployments run `49aa5e28`;
  - 0 pods run `e977c32b`;
  - cortex-ui runs `sha256:2556cf5b…`, which is b566192 (composer + perf);
  - `helm get values --revision 188` and `--revision 189` give the two imageTags above.
- **The "fleet at e977c32b since 13:33Z" reading is revision 188's values.** That revision never
  completed. Revision 189 replaced it 20 minutes later.
- **49aa5e28 contains** e977c32b, #39 (ac6e4ff0) and #38 (93ff843f).
- **Hooks and tags:** the post-upgrade task-grant-sync and engine-reregister hooks completed. CI cut
  the tag `invincible-agent-0.4.43`.

**Walk against 49aa5e28.** The full roll report is
`2026-10-12-report-roll-187-live-49aa5e28-composer-and-perf.md`.
