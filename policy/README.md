# policy/ — authoritative entitlements

This directory holds the **asserted-in-git** source of truth for
persona/domain entitlements per ADR-0026. Every file here is a
named human's PR-reviewed claim about who is entitled to what.
No automated process converts directory/AD data into these files
without a human's approval on the PR — see ADR-0026 Alternative D
for why (confabulation-as-authorization is a security anti-pattern).

## Files

- **`personas.yaml`** — canonical persona enum (from ADR-0009).
- **`domains.yaml`** — canonical domain enum (from ADR-0009).
- **`groups.yaml`** — group taxonomy: each group grants entitlement
  to one or more (persona, domain) cells.
- **`users.yaml`** — user → group memberships + default cell.

## Sync

`sync/topaz_sync.py` reads all four files, validates the schema
(Pydantic), computes a diff against the target topaz's current
Directory state, and applies additions + removals via the topaz
Directory writer API. After apply it runs a readback
(`[[verification-must-fail]]` gate): every asserted (user, cell)
grant must return TRUE from a topaz permission check, and any
relation NOT in the YAML must NOT exist in the directory. Any
divergence fails the sync loudly.

Usage:

```bash
# Against a running sandbox (kubectl-reachable):
kubectl port-forward -n sandbox svc/topaz-svc 9393:9393 &
python policy/sync/topaz_sync.py \
    --topaz-url http://localhost:9393 \
    --policy-dir policy/

# Against a cluster you're already exec'd into:
python policy/sync/topaz_sync.py \
    --topaz-url http://topaz-svc:9393 \
    --policy-dir policy/
```

Idempotent — same input twice is a no-op.

## Relationship to `topaz.seed` Helm values

`values.yaml` has a `topaz.seed` block that the ADR-0026 step-1
seed Job consumes to insert relations at helm-upgrade time. That
block is a helm-native shortcut for operators who prefer to keep
their entitlements in the same file as the rest of their chart
overrides. It has the same shape as the YAML files here.

Two paths coexist:

- **Helm-native**: `topaz.seed` in values overlay → topaz-seed Job
  inserts on upgrade. Simple; opinionated on when the seed runs.
- **Git-managed**: `policy/` files → CI or manual `topaz_sync.py`
  run. Explicit; can run on any schedule.

Either works. Both write to the same topaz Directory and produce
the same runtime behavior.

## What NOT to do

- **Do not automate a directory (AD/LDAP) → users.yaml write.** AD
  membership is a *draft input* for a human PR, never the decision.
  A separate tool (`sync/draft_from_ad.py`, out of scope for step 2)
  can emit a proposed diff; a human reviews and merges.
- **Do not add a permissive "everyone gets DATA_ENGINEER" fallback
  cell.** ADR-0026 Alternative D — that's confabulation-as-authorization
  hiding in the policy store. Every entitlement is a specific human's
  asserted decision.
- **Do not skip the sync readback.** The readback is the
  `[[verification-must-fail]]` gate that catches "the writer said
  200 but the reader disagrees" — silent-drop failures across topaz
  transaction boundaries. If it never fires red, it's ceremonial.
