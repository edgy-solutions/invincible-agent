# iagent-mesh-mcp

Creates (post-install/upgrade hook) the confidential Keycloak resource-server client `iagent-mesh`
with RFC 8693 standard token exchange, and two audience mappers: one so tokens minted for it carry
`aud` containing `iagent-mesh`, one so the exchange may request `client.exchangeAudience`. The hook
refuses Keycloak older than 26.2. An optional server Deployment/Service (off by default, digest
pinned) renders when `deployment.enabled`.

## Hand step: two Secrets, created by hand

Create with `kubectl create secret generic`, never `apply`, never in a values file:

- the Keycloak admin credential (`keycloak.adminSecret`: name, `userKey`, `passwordKey`);
- the client credential (`client.credentialSecret`: name, `key`).

Both reach the Job only as `secretKeyRef` env; nothing is echoed or written to disk.

## Findings

- `helm/invincible-agent` passes the Keycloak admin password as a plaintext chart value
  (`keycloak.auth.adminPassword` -> `value:` env in `realm-reconcile-job.yaml` and `keycloak.yaml`).
  That is why this chart cannot reuse it and needs its own admin Secret.
- Which client the BFF's audience is, is open (spec section 3 item 6): `client.exchangeAudience`
  has no default; set it per deployment.
- The `audience-self` mapper covers tokens minted *for* `iagent-mesh`. A user token an MCP client
  presents carries `aud` containing `iagent-mesh` only if the client that minted it maps that
  audience. That mapper belongs to the MCP client's own registration, not to this chart.
