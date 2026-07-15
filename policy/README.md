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

## Private deployments — the policy-overlay path (chart ≥ 0.3.11)

The files in THIS directory are the **sandbox** assertion. A private
deployment (an org with its own users, groups, and grants) must not
edit them here — its entitlements are its own PR-reviewed decision, in
its own repo, with its own approvers and git-blame. The split is:

- **Product-owned (this repo, ships in the image):** the `sync/`
  scripts and the Topaz manifest. These version together with the
  chart/image — never fork them into a deployment repo.
- **Deployment-owned (private policy repo):** the five DATA files —
  `users.yaml`, `groups.yaml`, `asset_grants.yaml`, `task_grants.yaml`,
  `ontology_compartments.yaml`.
- **Enums (`personas.yaml` / `domains.yaml`): image-default,
  deployment-ASSERTABLE** via `topazSeed.policySource.overlayEnums`.
  The two are not symmetric — see
  `docs/architecture/personas-and-domains.md`:
  - `domains.yaml` is a deployment's CLASSIFICATION vocabulary. Nothing
    in code evaluates specific domain values; the labels must match the
    deployment's data tagging at ingest. A private deployment
    overriding it is the NORMAL move (`overlayEnums: [domains.yaml]`).
  - `personas.yaml` is CODE-COUPLED: `catalog_domain_view.rego`
    (topaz-configmap) iterates a hardcoded persona list to derive
    domain entitlement. Overriding with a SUBSET is safe; ADDING a
    persona in an overlay half-works (entitlements grant it, catalog
    domain-view misses its cells → wrong fail-closed denial) — adding
    stays a product change until that rego is de-hardcoded.
  Both directions fail loud: asserted-but-missing is FATAL, and an
  overlay carrying an UNASSERTED enum file is FATAL too (two-truths
  guard).

The seed CronJob composes the two at run time
(`topazSeed.policySource`):

```yaml
# values overlay for a private cluster:
topazSeed:
  enabled: true
  schedule: "*/10 * * * *"       # merge-to-main converges within 10 min
  policySource:
    type: git
    git:
      repoUrl: "https://git.example.com/org/iagent-policy.git"
      ref: main
      path: policy
      authSecretName: iagent-policy-repo   # keys: username, password (PAT)
```

Every run clones the tracked ref, takes the enums from the image and
the five data files from the clone (a missing data file is FATAL — no
fallback to the sandbox copy), validates ALL five with
`sync/validate_policy.py` before any write, then runs the five syncs
readback-gated. Merge → next tick → cluster converged. Immediate
apply: `kubectl create job --from=cronjob/<release>-topaz-seed seed-now`.

The private repo's PR CI can validate without any cluster access by
running the validator from the product image:

```bash
docker run --rm -v "$PWD/policy:/overlay:ro" \
    <cortex-bff image ref> \
    python policy/sync/validate_policy.py \
    --policy-dir /overlay --enums-from /app/policy \
    --overlay-enums domains.yaml     # mirror your overlayEnums setting
```

`policySource.type: configMap` is the no-git-access-from-cluster
alternative: the policy repo's CI applies the five files as a
ConfigMap and triggers the one-off Job itself.

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
