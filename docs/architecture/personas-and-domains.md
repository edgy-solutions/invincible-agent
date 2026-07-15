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

### Adding a domain (config, no recompile)
1. Add the label to `policy/domains.yaml` (mirror in ADR-0009 per the file's own
   discipline — a doc note; the BAML enum is `@@dynamic`, nothing to rebuild).
2. Ensure **ingestion tags data with the same label** (`prime_databases.py`
   `extra_metadata={"domain": "<SEMANTIC>"}` or S3 `x-amz-meta-domain`).
3. Grant it in `groups.yaml`/`users.yaml`, re-run `topaz_sync.py`.

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
| **`policy/personas.yaml`** | the entitlement enum: `DATA_STEWARD, DATA_ENGINEER, ARCHITECT, MECHANIC, ANALYST` | **source of truth for grants** |
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
- For **access**: `personas.yaml` + `groups.yaml` only (the enum the sync validates).
  No recompile (`PersonaTarget` is `@@dynamic`).
- To make it **own verbs** (frame answers in its voice): also set `owner_persona` at
  verb registration. Optional — unset = falls back to the caller.

---

## Granting yourself (recipe)

**Work vs sandbox key:** `authz_id` = **email** in sandbox, **employee-id** at
work-deploy. Every `id:` / `grant_to:` must be the value the JWT actually carries.
Confirm after login with `GET /me/entitlements`.

**1. `policy/domains.yaml`** — make the real domains grantable:
```yaml
domains:
  - AVIATION          # demo, no data
  - DEFENSE           # demo, no data
  - ENTERPRISE        # demo, no data
  - DATA_ENGINEERING
  - MAINTENANCE
  - SUSTAINMENT        # add (bulk of live data)
  - MESH               # add
  - MANUFACTURING      # add
  # - TRAINING         # add only when training data is ingested
```

**2. `policy/groups.yaml`** — a group granting a persona across every domain:
```yaml
  all-domains:
    grants:
      - {persona: DATA_ENGINEER, domain: AVIATION}
      - {persona: DATA_ENGINEER, domain: DEFENSE}
      - {persona: DATA_ENGINEER, domain: ENTERPRISE}
      - {persona: DATA_ENGINEER, domain: DATA_ENGINEERING}
      - {persona: DATA_ENGINEER, domain: MAINTENANCE}
      - {persona: DATA_ENGINEER, domain: SUSTAINMENT}
      - {persona: DATA_ENGINEER, domain: MESH}
      - {persona: DATA_ENGINEER, domain: MANUFACTURING}
```
(Entitlement is per `(persona, domain)` pair — add lines for other personas, e.g.
`ARCHITECT` / `DATA_STEWARD`, if you want their capabilities too.)

**3. `policy/users.yaml`**:
```yaml
  - id: <YOUR-AUTHZ-ID>          # employee-id at work, email in sandbox
    display_name: <Your Name>
    groups:
      - all-domains
    default:
      persona: DATA_ENGINEER
      domains: [SUSTAINMENT, MAINTENANCE, MESH, DATA_ENGINEERING, MANUFACTURING]
```

**4. Sync** (single writer; idempotent; diff-based deletion; readback-gated):
```bash
kubectl port-forward -n <ns> svc/topaz-svc 9393:9393 &
python policy/sync/topaz_sync.py --topaz-url http://localhost:9393 --policy-dir policy/
# fresh cluster only: --load-manifest /tmp/topaz-manifest.yaml   (see policy/README.md)
```

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
