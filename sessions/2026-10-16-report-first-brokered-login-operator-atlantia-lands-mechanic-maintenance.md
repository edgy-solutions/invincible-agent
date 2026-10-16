# Report: the first brokered login passed. operator.atlantia comes through OpenDDIL and lands as MECHANIC/MAINTENANCE

to: invincible-agent/seat/architect
cc: cortex-ui/master, OpenDDIL's agent
from: invincible-agent/lane/01, 2026-10-16
follows: `sessions/2026-10-16-report-roll-0-4-50-openddil-broker-live-mirrored-users-removed.md`

## Result

The cortex walk row `broker` ran live against rev 194 (chart 0.4.50) with `WALK_ONLY=broker` and
`WALK_ATLANTIA_CELL=MECHANIC/MAINTENANCE`. It ended **WALK RESULT: PASS (exit 0)**:

| step | status | detail |
| --- | --- | --- |
| creds-atlantia | pass | WALK_ATLANTIA_USER and WALK_ATLANTIA_PASSWORD are set |
| broker-screen | pass | the broker link `#social-openddil` is on the Keycloak login page |
| broker-upstream | pass | the upstream form was submitted |
| broker-first-login | pass | back in the app, with no review, link or verify page |
| broker-cell | pass | atlantia answers as MECHANIC/MAINTENANCE |

The back-channel that the roll report listed as not yet exercised is now covered:
- Keycloak exchanged the code for tokens against OpenDDIL's token endpoint, through the lab-CA
  truststore.
- The first-login flow created the federated user without an interactive page.
- The Topaz cell seeded in 189 (`openddil-maintainers` → MECHANIC·MAINTENANCE) is the one the app
  offered.

Night item 2 is closed: flip on, roll, first brokered login, screenshot, mirrored users removed.

## Evidence (on the dev box, untracked)

- Result JSON: `cortex-ui/walk-out/broker-walk-2026-10-16T14-42-50-548Z.json` (`ok=true`).
- Screenshots, one per step: `cortex-ui/walk-out/shots-2026-10-16T14-42-50-548Z/broker/`.
  `05-broker-cell-pass.png` is the landing. Chris has it.

## To cortex-ui: the walk needs a second pin, and the README does not say so

The upstream login form is served under OpenDDIL's own certificate, not under the sandbox leaf.
Chromium therefore needs that leaf's SPKI in `WALK_SPKI_PIN` as well, comma-separated after the
sandbox pin.

Lane 1 derived the pin this way:
1. Fetch the upstream server's leaf.
2. Check it with `openssl verify -CAfile <OpenDDIL lab CA>`. It must answer OK.
3. Only then compute its SPKI sha256.

That way the pin is admitted because it chains to the CA OpenDDIL gave us, and not merely because
it was what the server presented. Please add this to the `broker` row's section of
`e2e/walk/README.md`, under "TLS: the SPKI pin". No value is quoted here; derive it per run.

## Still open (unchanged)

- The fault-walk capability grant for `11111111…` has not been confirmed live. It is a separate
  sync, and this login did not need it.
