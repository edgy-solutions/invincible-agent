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
# Fresh cluster (loads manifest THEN entitlements):
kubectl get cm iagent-topaz-config -n sandbox \
    -o jsonpath='{.data.manifest\.yaml}' \
    > /tmp/topaz-manifest.yaml
kubectl port-forward -n sandbox svc/topaz-svc 9393:9393 &
python policy/sync/topaz_sync.py \
    --topaz-url http://localhost:9393 \
    --policy-dir policy/ \
    --load-manifest /tmp/topaz-manifest.yaml

# Existing cluster (entitlement update only, manifest already loaded):
python policy/sync/topaz_sync.py \
    --topaz-url http://localhost:9393 \
    --policy-dir policy/
```

Idempotent — same input twice is a no-op. `--load-manifest` on a
cluster with an existing (identical) manifest is safe.

## History note — the retired `topaz.seed` values path

Chart 0.3.9 shipped an in-cluster `topaz-seed-job.yaml` that read
`Values.topaz.seed` and wrote objects/relations at helm-upgrade
time. That path retired in chart 0.3.10 per
`[[coupled-interim-mechanisms-retire-together]]`: two writers to
one authz substrate is the two-truths shape the ADR rejects
everywhere else. The sync tool here is now the single writer;
the seed Job template and the `topaz.seed` values block are
deleted from the chart.

Existing sandbox entitlements (alice/bob/carol) migrated verbatim
into `users.yaml` at the time of retirement — no re-seed needed
for clusters already populated. Fresh clusters run the sync tool
as documented above.

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
