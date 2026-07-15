# Personas & Domains — the entitlement vocabulary

**What this is:** how the `persona` and `domain` labels work across the mesh —
where they're defined, how they couple, and how to grant them. Written to
de-confuse the recurring "are these fixed by the ontology, and is there a
duplicate list?" question.

**Grounding:** code + live sandbox data as of **2026-07-14**. The live-data counts
are a point-in-time snapshot of the sandbox; re-query before relying on them.

---

## TL;DR

- **Both persona and domain are configurable *policy labels*, not fixed by the
  ontology.** The IOF/MIMOSA MRO ontology is domain-agnostic (Maintenance and
  Manufacturing share the same graph). The BAML `Domain` and `PersonaTarget` enums
  are `@@dynamic` (injected at runtime) — there is **no hardcoded enum to
  recompile**.
- **`policy/domains.yaml` and `policy/personas.yaml` are the source of truth for
  *grants*** (they're the enums `topaz_sync.py` validates against). But the same
  labels also live on other surfaces (ingested data, verb registrations, the JWT
  claim), and **all surfaces must spell the label identically** or entitlement
  silently won't match data.
- **The demo policy drifted from the real data.** The sandbox policy grants
  `AVIATION / DEFENSE / ENTERPRISE` (which have **zero** data); the actual ingested
  ontology is mostly `SUSTAINMENT` (which **isn't grantable** because it's not in
  `domains.yaml`). Align the policy with the data before granting.

---

## Domains

### Two different things both called "domain"
1. **Ontology subject matter** — the IOF/MIMOSA **MRO** graph (Maintenance / Repair
   / Overhaul = *sustainment*). Fixed *content* (classes/terms). Domain-agnostic:
   one graph serves multiple domains.
2. **The access/scope "domain"** — a **classification label** (`SUSTAINMENT`,
   `MAINTENANCE`, …) that tags data and gates who sees it. **Configurable policy.**

The confusion comes from (1) and (2) sharing names: `MAINTENANCE` and `MANUFACTURING`
both draw on the MRO ontology, but the *domain* is the access label, not the
ontology identity.

### Domain is no longer a routing key
`dynamic_supervisor.py` marks `domain` as *"legacy, no longer routes"*; ADR-0009:
*"Domain is not a routing key; the matched verb's owner is."* Its live job is
**entitlement scoping** — `entitled_domains` ∩ the data's tagged domains decides what
you can access.

### The consistency contract (a domain label must match across all of these)
| Surface | Where | Role |
|---|---|---|
| **Entitlement** | `policy/domains.yaml` + `groups.yaml` → Topaz | what you're *granted* |
| **Data tagging** | `mesh_domains` on verbs/tools (registration); `domain` on ontology classes (doc-tools ingest); DataHub domain | what domain the *data* belongs to |
| **Routing scope** | `entitled_domains` filters eligible verbs/subjects | grant ∩ data-domain |

Access = **your granted domains ∩ the data's tagged domains.** Granted `MAINTENANCE`
but the docs were ingested as `manufacturing` → you see nothing. Not "fixed" — the
labels just don't match.

### How the label gets set at ingest (doc-tools)
Explicit per TTL file, in precedence order (`ontology_assets.py:ingest_ontology_to_jena`):
1. `config.extra_metadata["domain"]` — explicit Dagster config (set by
   `setup/prime_databases.py`).
2. S3 object metadata `x-amz-meta-domain`.
3. **ERROR** — path-derivation as a silent fallback was deliberately removed (it
   produced "confidently-wrong" routing). A new ingestion that doesn't declare a
   domain fails loud.

### Live domain snapshot (Weaviate `OntologyClass`, 2026-07-14 sandbox)
| Domain | Live classes | In `policy/domains.yaml`? |
|---|---|---|
| **SUSTAINMENT** | **866** | ❌ not grantable |
| MAINTENANCE | 59 | ✅ |
| MESH | 22 | ❌ |
| DATA_ENGINEERING | 6 | ✅ |
| MANUFACTURING | 1 | ❌ |
| AVIATION / DEFENSE / ENTERPRISE | 0 each | ✅ (empty) |
| TRAINING | 0 (never ingested) | ❌ |

**Reading:** the policy's aviation/defense/enterprise are demo cruft with no data;
the data's biggest domain (`SUSTAINMENT`) can't be granted today. `SUSTAINMENT` and
`MAINTENANCE` are **distinct** live domains (866 vs 59) even though both use the MRO
ontology — `prime_databases.py` tags the MRO *extension* TTLs `MAINTENANCE` while the
bulk sustainment ontology came in as `SUSTAINMENT`.

### Adding a domain (config, no recompile — deployment-assertable)
The domain vocabulary is a deployment's CLASSIFICATION label set. Nothing in code
evaluates specific domain values structurally (the couplings are cosmetic: a
`"MAINTENANCE"` routing fallback and a DataHub schema-map convenience keyed to the
`DATA_ENGINEERING` label, both in `dynamic_supervisor.py`). What binds is
**label ↔ data-tagging consistency**, and the data tagging is deployment-side too.
Two paths:
- **Sandbox / in-image policy:** add the label to `policy/domains.yaml` (mirror in
  ADR-0009 per the file's own discipline; the BAML enum is `@@dynamic`, nothing to
  rebuild).
- **Private deployment (chart ≥ 0.3.11):** assert `domains.yaml` in YOUR overlay —
  `topazSeed.policySource.overlayEnums: [domains.yaml]` — and carry the file in the
  policy repo. The shipped set is sandbox demo labels (see the snapshot above:
  aviation/defense/enterprise have zero data), so a private deployment asserting its
  own is the EXPECTED move, not an exception.
Either way:
1. Ensure **ingestion tags data with the same label** (`prime_databases.py`
   `extra_metadata={"domain": "<SEMANTIC>"}` or S3 `x-amz-meta-domain`).
2. Grant it in the DATA overlay (`groups.yaml`/`users.yaml`) — in-image for sandbox, in
   your private policy repo for work (reconciled by the seed CronJob). See the recipe.

---

## Personas

### Three roles (the "persona split", ADR-0009 — never conflate them)
1. **Caller persona** (`user_persona`) — *who you are*, from your JWT → your
   `(persona · domain)` entitlement cell. Half the access gate; drives UI prefs.
2. **Answerer / owner persona** (`owner_persona` → `answerer_persona`) — *whose voice
   answers*. A verb *can* be registered (via `mesh_registrar`) with an
   `owner_persona`; when it matches, the answer is framed in that persona. **Persona-
   agnostic verb → falls back to the caller persona.**
3. **Target persona** (`target_persona`) — task decomposition tags each sub-task with
   the persona meant to handle it.

**Live reality (2026-07-14 sandbox):** no verb carries an `owner_persona` — verbs are
persona-agnostic, so the **answerer persona = your caller persona**. Practically your
persona does two things today: half your access cell, and the voice answers come back
in.

### Surfaces (no hardcoded dup enum, but the vocabulary is spread out)
| Surface | What it is | Coupling |
|---|---|---|
| **`policy/personas.yaml`** | the canonical enum: `DATA_STEWARD, DATA_ENGINEER, ARCHITECT, MECHANIC, ANALYST` | image-default; overlay-assertable via `overlayEnums` but **CODE-COUPLED** — `catalog_domain_view.rego` hardcodes this list (subset-safe; **adding** needs a product change) |
| BAML `enum PersonaTarget` | `@@dynamic` — injected at runtime | **not** a dup; nothing to edit |
| Verb `owner_persona` | set at verb registration (`mesh_registrar`) | must match the enum; empty in current data |
| JWT persona claim (Keycloak) | where the caller persona originates | must match the enum |
| BAML per-role response classes | `MechanicResponse`, `DataStewardResponse`, `AuthoringResponse`, `LogisticsResponse`, `AuditResponse`, `GraphExpertResponse` | output *shape* per role — names **don't 1:1 match** `personas.yaml` |

**Soft drift to know about:** the BAML response-class names (`Authoring`,
`Logistics`, `Audit`, `GraphExpert`) don't line up with the five entitlement
personas — they read more like output archetypes. `personas.yaml` governs *who's
granted what*; a persona's *behavior* (voice, owned verbs) is coupled in registration
+ BAML and isn't perfectly aligned.

### Adding a persona
- Unlike domains, the persona vocabulary is **genuinely code-coupled**:
  `catalog_domain_view.rego` (topaz-configmap) iterates a **hardcoded persona list**
  to derive "entitled to domain D = holds ANY (persona, D) cell". An overlay may
  assert `personas.yaml` (`overlayEnums: [personas.yaml]`) to run a **SUBSET** —
  iterating absent personas just checks empty cells, safe. But **ADDING** a persona
  in an overlay half-works: `/me/entitlements` and the `can_assume` gate are
  data-driven and grant it, while catalog domain-view silently misses its cells →
  wrong fail-closed denial. So a NEW persona label is a **product PR** (rego + image
  `personas.yaml`) until that rego is de-hardcoded. No recompile otherwise
  (`PersonaTarget` is `@@dynamic`).
- **Granting** it is the DATA overlay (`groups.yaml`/`users.yaml`) — in-image (sandbox)
  or your private policy repo (work). Entitlement is per `(persona, domain)` pair.
- To make it **own verbs** (frame answers in its voice): also set `owner_persona` at
  verb registration. Optional — unset = falls back to the caller.

---

## Granting yourself (recipe)

### Two layers: canonical VOCABULARY (image) vs grant DATA (overlay)
Since chart 0.3.11 (`topazSeed.policySource`), the entitlement files split in two — and
this changes *where* you make a change:

- **`personas.yaml` + `domains.yaml` = the VOCABULARY — image-default,
  deployment-ASSERTABLE** via `topazSeed.policySource.overlayEnums`. Asymmetric:
  - **`domains.yaml`: assert it.** It's your deployment's classification label set
    (the shipped one is sandbox demo labels); `overlayEnums: [domains.yaml]` and
    carry your own (e.g. `SUSTAINMENT`, `MESH`, `MANUFACTURING`) in the overlay repo.
    Labels must match your data tagging at ingest.
  - **`personas.yaml`: subset-only.** `catalog_domain_view.rego` hardcodes the
    persona list — an overlay may run FEWER personas, but ADDING one is still a
    product PR (rego + image enum) or catalog domain-view wrongly denies its cells.
  Guards are fail-loud both ways: an enum file asserted but missing from the overlay
  is FATAL; an enum file present in the overlay but NOT asserted is FATAL (two-truths).
- **The five DATA files** (`users.yaml`, `groups.yaml`, `asset_grants.yaml`,
  `task_grants.yaml`, `ontology_compartments.yaml`) = the GRANTS (who gets what). These
  come from the deployment's overlay, chosen by `topazSeed.policySource.type`:
  `image` (baked in — sandbox default), `configMap`, or **`git` (an initContainer
  clones a PRIVATE policy repo every run — GitOps for entitlements, the CronJob IS the
  reconcile loop, no extra controllers)**. A data file MISSING from an overlay **FAILS
  the run** (no silent fallback to the image's sandbox copy).

**Work vs sandbox key:** `authz_id` = **email** in sandbox, **employee-id** at
work-deploy. Every `id:` / `grant_to:` must be the value the JWT actually carries.
Confirm after login with `GET /me/entitlements`.

### The grant DATA (edit these — in-image for sandbox; in your policy repo for work)

**`groups.yaml`** — a group granting a persona across every domain:
```yaml
  all-domains:
    grants:
      - {persona: DATA_ENGINEER, domain: DATA_ENGINEERING}
      - {persona: DATA_ENGINEER, domain: MAINTENANCE}
      - {persona: DATA_ENGINEER, domain: SUSTAINMENT}
      - {persona: DATA_ENGINEER, domain: MESH}
      - {persona: DATA_ENGINEER, domain: MANUFACTURING}
      # AVIATION/DEFENSE/ENTERPRISE — demo labels, no data; add if you want them
```
> Every domain named here must exist in the EFFECTIVE `domains.yaml` — the image's,
> or YOURS if you asserted it (`overlayEnums: [domains.yaml]`, the normal work move).
> `SUSTAINMENT`/`MESH`/`MANUFACTURING` aren't in the shipped enum: either assert your
> own `domains.yaml` in the overlay (work) or land the product PR (sandbox).
> Entitlement is per `(persona, domain)` pair; add lines for other personas
> (`ARCHITECT`, `DATA_STEWARD`) for their capabilities too.

**`users.yaml`** — that's you:
```yaml
  - id: <YOUR-AUTHZ-ID>          # employee-id at work, email in sandbox
    display_name: <Your Name>
    groups:
      - all-domains
    default:
      persona: DATA_ENGINEER
      domains: [SUSTAINMENT, MAINTENANCE, MESH, DATA_ENGINEERING]
```

### Applying it — two deploy paths
- **Sandbox / dev (in-image policy):** manual, single writer, readback-gated:
  ```bash
  kubectl port-forward -n <ns> svc/topaz-svc 9393:9393 &
  python policy/sync/topaz_sync.py --topaz-url http://localhost:9393 --policy-dir policy/
  ```
  Or `topazSeed.enabled=true` with `policySource.type=image` — the CronJob runs the same
  sync on a schedule. `topazSeed.loadManifest:true` loads the ReBAC manifest every run,
  **retiring the old manual `--load-manifest` extract-and-port-forward step**.
- **Work / private (git overlay, reconciled):** set
  ```yaml
  topazSeed:
    enabled: true
    policySource:
      type: git
      overlayEnums: [domains.yaml]   # work's classification labels ≠ the demo set
      git: { repoUrl: "https://git.example.com/org/iagent-policy.git", ref: "main", path: "policy" }
  ```
  Put the five DATA files — plus any enum file you asserted in `overlayEnums` — in
  that PRIVATE repo (unasserted enums stay in the image; personas: subset-only, see
  above). **Merge to `ref` → the seed CronJob converges the cluster on the next tick —
  no manual sync.** Gate every change in that repo's PR CI with
  `policy/sync/validate_policy.py --policy-dir <overlay> --enums-from /app/policy
  --overlay-enums domains.yaml` (fail-closed, network-free) so a broken overlay never
  reaches a seed run.

### Gotchas
- **The `id` must match the JWT's authz_id claim exactly** — else the grant exists
  but never binds to you.
- **`default` must be one of your granted cells** — it's the picker default when you
  don't override in the UI.
- **Empty demo domains grant nothing useful** — `AVIATION/DEFENSE/ENTERPRISE` have no
  data; harmless to include but they light up empty.
- **Don't automate AD/LDAP → `users.yaml`** and **don't add a permissive fallback
  cell** — see `policy/README.md` (confabulation-as-authorization is the anti-pattern
  ADR-0026 rejects).

---

## Related
- `policy/README.md` — the sync tool + the "what not to do" rules.
- ADR-0009 — persona/domain enums + the persona split.
- ADR-0026 — persona/domain entitlement via Topaz (git-asserted, human-reviewed).
- `docs/principles/select-from-authorized-set.md` — the governing access tenet.
