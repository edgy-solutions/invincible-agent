---
id:         jupyter-user-token-data-access
status:     open
owner:      human
blocked-on: gateway must verify bearers first — dag-tools-gateway-unverified-subject
closed-by:  
code-site:  dag_tools/cortex_data/client.py
repo:       dag-tools
summary:    Design + configuration for transparent per-user data access from notebooks — JupyterHub OIDC token reaching CortexDataClient. Blocked: without bearer verification the design LOOKS per-user and is not.
---

# Transparent per-user data access from notebooks

**Goal, in the user's words:** *ideally it would be transparent to the user — when they log into
Jupyter, things get set so that they can access data.*

That is achievable and it is standard practice. It has one hard requirement that decides
everything else:

> **The notebook must carry a token that names the user** — minted at login, refreshed, never
> shared. "Transparent" means the user does not *type* credentials. It must not mean the platform
> supplies **one identity for everyone**.

## READ THIS FIRST — the precondition that is currently missing

This design was scoped on the assumption that *"the gateway's existing verification does the
rest — same JWKS check, same Topaz scoping as a UI session."*

**There is no such verification.** `central_gateway` never verifies a bearer's signature
(`main.py:110`, `:269` — both `verify_signature: False`), has no JWKS client and no auth module,
and **prefers the `X-Originator-Email` header over any token claim** as the authz subject
(`main.py:121`). Full evidence: `[[dag-tools-gateway-unverified-subject]]`.

**Consequence for this plan:** passing the user's token is **necessary and not sufficient**. Build
only the Jupyter half and you get a system that *looks* per-user — alice's pod carries alice's
token — while any caller can still assert `X-Originator-Email: bob` and read bob's slice. The
per-user property would be **presentational**.

**Sequencing is therefore not a preference.** Gateway verification lands first or alongside; the
notebook work is what makes it *useful*, not what makes it *true*.

## The shape that gets you there

Four moving parts. Parts 1-2 are configuration; part 3 is the one with a real design decision;
part 4 is non-negotiable and cheap.

### 1. The hub authenticates against Keycloak (OIDC)

```python
# jupyterhub_config.py
from oauthenticator.generic import GenericOAuthenticator

c.JupyterHub.authenticator_class = GenericOAuthenticator

c.GenericOAuthenticator.client_id     = os.environ["KEYCLOAK_CLIENT_ID"]
c.GenericOAuthenticator.client_secret = os.environ["KEYCLOAK_CLIENT_SECRET"]
c.GenericOAuthenticator.authorize_url = f"{KC}/realms/{REALM}/protocol/openid-connect/auth"
c.GenericOAuthenticator.token_url     = f"{KC}/realms/{REALM}/protocol/openid-connect/token"
c.GenericOAuthenticator.userdata_url  = f"{KC}/realms/{REALM}/protocol/openid-connect/userinfo"

# `offline_access` is what yields a refresh token with a usable lifetime —
# see part 3, and read its cost before enabling it.
c.GenericOAuthenticator.scope = ["openid", "profile", "email", "offline_access"]

# REQUIRED for the tokens to be retrievable at spawn. Needs JUPYTERHUB_CRYPT_KEY
# (32 random bytes, hex) in the hub's environment — auth_state is encrypted at rest.
c.Authenticator.enable_auth_state = True
```

**The entitlement key must match what the gateway keys on.** Sandbox is email; work is
employee-id (`USER_ENTITLEMENT_CLAIM`). Whatever claim work uses, *that* is what has to reach
Topaz — do not assume `email` is populated in the work realm.

### 2. The spawn writes the user's tokens into their own pod

```python
def auth_state_hook(spawner, auth_state):
    if not auth_state:
        # Fail loudly. A silent skip here is exactly how every notebook
        # ends up on the shared service identity — see part 4.
        spawner.log.error("no auth_state at spawn — user token will NOT be available")
        return
    spawner.environment["CORTEX_USER_TOKEN"]    = auth_state["access_token"]
    spawner.environment["CORTEX_REFRESH_TOKEN"] = auth_state["refresh_token"]
    spawner.environment["CORTEX_USER_ID"]       = auth_state["oauth_user"]["email"]  # or employee-id

c.Spawner.auth_state_hook = auth_state_hook
```

**The load-bearing property is one user per pod.** The single-user server's environment is a
per-spawn secret; that is the entire reason this is a per-user credential and not a shared one.
Anything that co-locates users in one kernel breaks the model, not just the config.

### 3. Refresh at use, not capture at spawn — this is the whole problem

A Keycloak access token lives minutes. A notebook session lives hours or days — someone starts an
analysis, goes to lunch, comes back. **Capturing one access token at spawn is the stale-credential
class wearing a Jupyter costume**, and it fails in the most confusing way available: the notebook
worked this morning and 401s after lunch, with nothing naming why.

So the client holds the *refresh* token and mints an access token per request (or per short
window):

```python
class _UserTokenProvider:
    """Refresh-at-use. The identity is verified NOW, not at login."""
    def __init__(self, refresh_token: str, token_url: str, client_id: str):
        self._refresh, self._url, self._cid = refresh_token, token_url, client_id
        self._access, self._exp = None, 0.0

    def token(self) -> str:
        if self._access and time.time() < self._exp - 30:   # 30s skew margin
            return self._access
        resp = httpx.post(self._url, data={
            "grant_type": "refresh_token",
            "refresh_token": self._refresh,
            "client_id": self._cid,
        }, timeout=10.0)
        resp.raise_for_status()
        body = resp.json()
        self._access = body["access_token"]
        self._exp = time.time() + body.get("expires_in", 60)
        # Keycloak rotates refresh tokens by default — persist the new one
        # or the NEXT refresh fails with the confusing "invalid_grant".
        self._refresh = body.get("refresh_token", self._refresh)
        return self._access
```

`CortexDataClient` then calls `self._tokens.token()` at request time instead of reading
`self.jwt_token` captured in `__init__`.

**The cost to name:** a long-lived refresh token sitting in a pod environment is itself a
credential with real lifetime. It is per-user and per-pod, which is what makes it acceptable, but
"acceptable" is a ruling and should be made explicitly rather than inherited from this document.
The alternative — short refresh lifetime and re-login — trades transparency for containment.

### 4. The fallback must announce itself, or transparency becomes invisibility

Today `CortexDataClient` resolves `jwt_token` → `MESH_DEV_TOKEN` → M2M → `ValueError`, **logs
nothing**, and the gateway logs a subject only on *denial*. So a notebook silently running as the
service identity is indistinguishable from one running as the user — and it would hand every
analyst the service's entitlements.

Required, and it is three lines:

```
data access: user alice@example.com (user token, refreshed)
data access: MESH_DEV_TOKEN (DEV FALLBACK — not your identity)
data access: service account cortex-da (M2M — shared identity, NOT per-user)
```

**A dev fallback that says so is fine. A silent one is how a work cluster serves everyone the same
data while looking correct.** Same posture-line pattern as the rest of the fleet.

## Order of work

| # | step | why this position |
|---|---|---|
| 1 | Gateway **verifies bearers** (JWKS, `algorithms`/`audience`/`issuer` pinned) | without it every step below is presentational |
| 2 | Gateway stops preferring `X-Originator-Email` over a verified user token | else the header overrides the very token step 3 delivers |
| 3 | Hub OIDC + `enable_auth_state` + spawn hook (parts 1-2) | the transparent-login half |
| 4 | `CortexDataClient` refresh-at-use + announcement (parts 3-4) | makes it survive lunch, and makes it legible |
| 5 | Witness alice ≠ bob | the only step that proves any of it |

Steps 1-2 are `[[dag-tools-gateway-unverified-subject]]`. **They are not this item's work, and
this item cannot deliver its claim without them.**

## The read to run first, at work

Jupyter is at work, so this is answerable only there. Two questions, one session:

1. **Is the hub OIDC-authenticated against your Keycloak today?** If yes, most of part 1 exists and
   the gap is `enable_auth_state` + the spawn hook. If it authenticates some other way, the
   token-passing *is* the build.
2. **Does anything reach `CortexDataClient` as `jwt_token` today?** Given the resolution order, if
   the answer is no, then every notebook is on `MESH_DEV_TOKEN` or the M2M identity right now —
   and the entitlement question is live rather than theoretical.

## Acceptance

- **alice ≠ bob, witnessed** — the same notebook code, run by two users with different
  entitlements, returns different rows. This is the only acceptance that matters; every other
  check can pass while the system is per-service.
- A session announces which identity it is using, and the dev fallback announces itself as one.
- A token expiring mid-session is refreshed without the user noticing — witnessed by a read
  after the original access token's expiry.
- A forged bearer, and a mismatched `X-Originator-Email`, are both refused (inherited from
  `[[dag-tools-gateway-unverified-subject]]`).

## The ADR-shaped sentence underneath

> **Notebook data access is per-user by construction; service identity is transport-only and never
> the entitlement subject.**

Which is the sentence already written on `svc:data-analyst`, applied one seam further out.
