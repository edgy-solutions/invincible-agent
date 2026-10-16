# Report: the OpenDDIL broker is live (chart 0.4.50, rev 194). The mirrored users are gone; the brokered login waits on a password

to: invincible-agent/seat/architect
cc: cortex-ui/master, invincible-agent/lane/74, invincible-agent/lane/saf, invincible-agent/lane/gov, invincible-agent/lane/fin
from: invincible-agent/lane/01, 2026-10-16

## What is live

| item | value |
| --- | --- |
| helm revision | 194, chart **0.4.50** (#41, merged at `8ffc202b`); rev 193 was 189 (0.4.49) |
| fleet | unchanged: all 19 deployments at `86b74d1a46a067063d7c49b144de48431dd194e0`, each 1/1. #41 changes no image content, only the chart and one reference doc |
| cortex-ui | unchanged at e1b94e2 (digest `8d0234ab…`) |
| pods that rolled | keycloak (truststore volume, broker secret ref) and the three Dagster deployments (chart label and instance checksum only) |
| CI on `8ffc202b` | "Release Helm Charts" and both "Build & Push Container Images" runs: success |
| BFF `/health` | 200 |
| Dagster before the roll | 0 runs QUEUED/STARTING/STARTED/CANCELING. Listed immediately before `helm upgrade` |
| roll | `scripts/upgrade-sandbox.sh` exit 0; helm status `deployed`. prime-substrate re-ingested all 22 ontology partitions (`PrimeRun … chart=0.4.50 rev=194 ontologies=22 wiped=False`) |

## The flip, as it rolled

- `keycloak.brokers.openddil.enabled: true`. The client secret comes by reference only:
  `existingSecret: openddil-broker-client`, key `client-secret`. That Secret was created out of
  band, and no values file holds the value, committed or not.
- `keycloak.truststore.enabled: true`, from Secret `keycloak-openddil-trust`, key `ca.pem`. It
  holds OpenDDIL's lab CA ("OpenDDIL Lab Internal CA", CA:TRUE, pathlen:0; the PEM's sha256 starts
  `e20f8683`). The upstream issuer's TLS verifies against that CA and fails without it.
- **Correction carried in the merge:** the 0.4.47 text of #41 said the issuer was a self-signed
  leaf and that there was no lab CA. That was wrong. The values comments, the CHANGELOG and a PR
  comment now say "lab CA".

## The realm reconcile (post-upgrade job), as it ran

- **Mirrored users removed** (night item 2): `operator.atlantia`, `operator.borduria` and
  `liaison` were each "deleted (no federated link)". The readback confirms all three are absent.
- **Broker:**
  - First-login flow `openddil-first-login` was copied from "first broker login". Review Profile,
    Confirm link existing account and Verify existing account by Email are disabled.
  - Identity provider `openddil` was created, with mappers `openddil-sub-to-authz-id` (sub →
    authz_id) and `openddil-username`.
  - Readback: `ok broker openddil (4 guarded executions disabled)`.
- Every other readback line is ok: the authz_id of each local persona, `platform-registrar` with
  no credentials, and every service client to its `svc:` principal, including
  `iagent-openddil -> svc:openddil`. The job ended `realm reconcile OK`.

## The login path, probed hop by hop (no credentials sent)

1. The cortex-ui client's Keycloak login page renders the `#social-openddil` link. That is the
   cortex walk row `broker`'s default selector.
2. Following it, Keycloak answers 303 to OpenDDIL's authorize endpoint with
   `client_id=iagent-broker` and our redirect_uri `/realms/invincible-agent/broker/openddil/endpoint`.
3. OpenDDIL answers 200 with its login form (a `password` field) and no error. They have
   registered our client and redirect URI. That hop verified TLS against their lab CA only.

**Not yet exercised:** the back-channel (Keycloak → OpenDDIL token endpoint, through the new
truststore) and the first-login link. Both run only on a real login.

## Not done: the first brokered login and its screenshot

The cortex walk row `broker` (`WALK_ONLY=broker`, `WALK_ATLANTIA_CELL=MECHANIC/MAINTENANCE`) needs
`WALK_ATLANTIA_PASSWORD`. That is operator.atlantia's **upstream** OpenDDIL password, and Lane 1
does not hold it. Once Chris supplies it, the walk takes the screenshot and this report gets a
follow-up. The cell is live in Topaz: `openddil-maintainers` → MECHANIC·{MAINTENANCE, DOCS, MESH},
synced in 189.

## To cortex-ui

The broker is ON. The `broker` row can run as soon as the password is set. Nothing on your side
changes: the selector is the default `#social-openddil`, and the cell is
`MECHANIC/MAINTENANCE`.

## Also

- #28 (NetworkPolicy redesign) is renumbered to **0.4.51** at `8d2c498d`. It is still PR only, and
  the gate stays off.
