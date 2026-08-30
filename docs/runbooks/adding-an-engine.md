# Runbook — adding an engine

**Written 2026-08-29, while building Engine F (finance) per ADR-0045.** Every step below is one
I actually took. Where a step is marked **DISCOVERED**, it was not written down anywhere and I
found it by reading source, inspecting a running pod, or hitting an error. That is the whole
reason this file exists: the last engine's additions were lost, and the lane after it paid again.

> ## THE RULE THIS RUNBOOK IS BUILT ON
>
> **Every instrument that failed in this fleet reported success at the resolution of "I ran",
> not "I did the thing."** Three of them in one night, each hiding the next
> (`docs/plans/prime-preregistration-canvas-seed-classes.md`). So every verification step below
> asks the GRAPH, by NAME. None of them asks a component about itself.

**Scope.** This covers a *deterministic, typed, mesh-registered* engine — the template ADR-0045
Decision 6 names: **domain ontology extension + typed deterministic verbs + existing archetypes
+ mesh reads**. Engine P proved it, Engine F copied it, sprint planning is next.

**Order of work.** Authoring (§1–§4) needs no cluster and no seed window. Deployment (§5–§9)
does. Do all the authoring first; it is where the expensive mistakes are cheap.

---

## §0 — Before you write a line: claim the name

**DISCOVERED, and it cost the first hour.** ADR-0045 calls the finance engine "Engine F". The
component name `engine-f` was **already taken** — it is the presentation agent (UX proxy):

| where | what it says |
|---|---|
| `helm/invincible-agent/values.yaml:435` | `engineF:` → image `presentation-agent`, port 8087 |
| `helm/.../templates/configmap.yaml:74` | `PRESENTATION_AGENT_SVC_URL: ...-engine-f...` |
| `helm/.../templates/NOTES.txt:53` | `Engine F (UX Proxy)` |
| `agent_fleet/presentation_agent/main.py:167` | `_announce_transport_auth(component="engine-f")` |
| `tests/test_engine_names.py:26` | `("http://iagent-engine-f:8087/render_ui", "Engine F")` |
| `values.yaml:1025` | `engine-f` in `primeSubstrate.reregisterEngines.deployments` |
| `scripts/roll-litany.sh:44` | `iagent-engine-f) echo "POST /render_ui"` |

**An ADR names an engine in prose. It does not allocate a component name.** Reusing `engine-f`
would have pointed `PRESENTATION_AGENT_SVC_URL` at a finance engine and taken `/render_ui` down
fleet-wide — and the first symptom would have been cards failing to draw, three layers away from
the change.

### The check, before you pick anything

```bash
# Every place a component name can already be spoken for. Run it for YOUR candidate.
grep -rn "engine-x\|engineX\|ENGINE_X" \
  --include=*.yaml --include=*.py --include=*.tpl --include=*.txt --include=*.sh \
  helm/ agent_fleet/ src/ scripts/ tests/
```

Four distinct namespaces have to be free, and they are **not** the same string:

| namespace | Engine P's value | Engine F's value | set where |
|---|---|---|---|
| helm values key | `enginePlanning` | `engineFinance` | `values.yaml` |
| component / service / deployment | `engine-p` | `engine-fin` | `templates/engines.yaml` `$engines` list |
| image name | `planning-agent` | `finance-agent` | `values.yaml` `image.name` |
| Keycloak client id | `iagent-planning-agent` | `iagent-finance-agent` | `keycloak.serviceClients` |

**These four differing is normal, not a smell** — but it is why one engine's wiring gets missed
three times. `secrets.yaml` says it outright for Engine P: the values key is
`planningAgentClientSecret` (after the **image**) while the env var is `ENGINE_P_CLIENT_SECRET`
(after the **service**), so *"grepping either name finds only half the wiring."* Write your four
names down before you start, and grep all four when you think you are done.

**Engine F's ruling:** the deployment is **`engine-fin`**, values key **`engineFinance`**, image
**`finance-agent`**. "Engine F" survives as the prose name in the ADR and the docs. Prose names
and component names are different registries.

---

## §1 — The ontology extension

**File:** `setup/ontologies/<domain>_extension.ttl` (Engine F: `finance_extension.ttl`).
**Pattern to copy:** `setup/ontologies/portfolio_planning_extension.ttl`.

### What has to be in it

**BOTH ENDS OF CONTRACT D.** ADR-0019's Contract D requires `input_uri` **and** `output_uri` to
resolve to real `:OntologyClass` nodes in Neo4j before the registrar will accept a verb.

> **The failure this prevents, measured 2026-08-22:** the planning extension authored only the
> **input** end; the output end lived in `mesh_system.ttl`. Only one of the two was ever written,
> so **twelve registrations earned twelve 422s** naming five URIs — *while the engine served
> `/health` normally throughout.*

Engine F's file therefore carries all fourteen classes — 8 subject nouns + 6 response shapes — in
one file, so there is one thing to seed and one thing to verify.

### Namespace for your response shapes

Engine P's outputs are `mesh:*` because they were authored into `mesh_system.ttl`. **Do not copy
that.** A domain extension writing into the platform namespace is a domain file claiming platform
terms, and practically it is an edit to a shared file that other lanes are queued on. Engine F
declares `fin:VarianceDecomposition` and friends in its own namespace, in its own file, still
rooted at `mesh:Response`. **Contract D checks that the URI resolves to an `:OntologyClass` node;
it does not care which namespace supplied it.**

### The three conventions that are not stylistic

Inherited from `idp_extension.ttl`, and each has a measured cost behind it:

1. **`rdfs:comment` ONLY — never `skos:definition`.** The Jena→Weaviate sync UNIONs the two and
   *the last row wins*, so a `skos:definition` silently clobbers the comment. `rdfs:comment` is
   what lands in `Weaviate.OntologyClass.definition`.
2. **The definition IS the recall signal**, written for the CLASS, never for a query.
3. **No sibling-name bleed.** A definition naming a neighbouring class competes for that class's
   traffic — measured on `idp:Pipeline`, which ranked top for a question squarely about
   `idp:Dataset` purely because it said "datasets" twice.

**DISCOVERED — convention 3 is hardest for a standards-derived vocabulary.** IPMDAR defines
control account, work package and WBS element *by reference to each other*; transcribing the
standard's own wording would have every definition naming its two neighbours. The way through:
**define each class by its DISTINGUISHING QUESTION, not by its position in the hierarchy.**
`fin:WBSElement` says "organises the effort by WHAT IS BEING BUILT"; `fin:OBSElement` says
"organises the effort by WHO IS DOING IT". Neither names the other.

### Standard vocabularies: reference, do not redeclare

**DISCOVERED.** ADR-0045 says use FIBO for money primitives. The naive read is "add FIBO's classes
to the TTL". Do not — `setup/prime_databases.py` records why PROV-O itself is *deliberately not
ingested*: W3C-quality generic definitions **vector-outcompete domain classes with weaker
definitions** in the routable pool ("a user asking *who authorized this?* would route to
`prov:Bundle` before `AuthorizationDecision`"), and the meta-ontology filter in
`doc_tools/assets/ontology_assets.py` (`_META_ONTOLOGY_IRI_PREFIXES`) drops every one of them
anyway — which once made `sync_jena_ontologies_to_neo4j` fail with a confusing "zero classes
extracted".

So the FIBO binding is an **`owl:ObjectProperty` whose `rdfs:range` points out of the file**:

```turtle
fin:hasMonetaryAmount a owl:ObjectProperty ;
    rdfs:range <https://spec.edmcouncil.org/fibo/ontology/FND/Accounting/CurrencyAmount/MonetaryAmount> .
```

Costs nothing at routing time, states the mapping for anyone reading the model, adds no class to
the pool.

### `prov:Entity` parents will NOT appear as graph edges — this is expected

ADR-0045 carries the implementer's note and it is worth repeating here because it looks exactly
like a broken ingest: **the ingest does not materialise a `subClassOf` edge to a `prov:` target.**
No such edge exists anywhere in the graph today, including under `mesh:Archetype` and
`mesh:Response`. Your domain classes will be **flat** in Neo4j, precisely as the planning classes
are. Do not "fix" it, and do not verify a parent that is a `prov:` term.

### Verify the file before it goes anywhere near a cluster

```bash
.venv/Scripts/python.exe -c "
import rdflib
from rdflib.namespace import RDF, OWL, RDFS
g = rdflib.Graph(); g.parse('setup/ontologies/finance_extension.ttl', format='turtle')
cs = sorted(str(s) for s in g.subjects(RDF.type, OWL.Class))
print('classes:', len(cs))
for c in cs: print(' ', c)
bad = []
for c in g.subjects(RDF.type, OWL.Class):
    if len(list(g.objects(c, RDFS.comment))) != 1: bad.append(('comment', str(c)))
    if len(list(g.objects(c, RDFS.label)))   != 1: bad.append(('label', str(c)))
    if len(list(g.objects(c, RDFS.subClassOf))) != 1: bad.append(('parent', str(c)))
print('defects:', bad)"
```

**DISCOVERED — `python` is not on PATH in this repo's shell.** Use `.venv/Scripts/python.exe`;
the bare `py` launcher resolves to an interpreter without `rdflib`.

**This is a pre-flight check on the FILE.** It is not a post-condition on the graph — see §8.

---

## §2 — Register the TTL with the prime

The ontology-seed hook (`templates/ontology-seed-job.yaml`) is **not** a generic seeder:
`command: ["python", "scripts/seed_mro_extension_runtime.py"]`. It seeds exactly the MRO
extension. **Your TTL rides the PRIME ingest instead**, and the manifest is a Python list:

`setup/prime_databases.py` → `ONTOLOGIES`, one dict per file:

```python
{
    "domain":  "PROGRAM_FINANCE",
    "name":    "finance_extension",
    "s3_key":  "finance/finance_extension.ttl",
    "path":    "ontologies/finance_extension.ttl",
},
```

**`domain` must match what your verbs register under.** Not cosmetic — the resolver queries by
semantic domain name, and a class whose domain does not match what the resolver asks for gives a
**silent UNKNOWN cascade**. The planning entry carries this warning in-line; it is repeated here
because the symptom is nothing at all.

**Adding to this list is an edit to a SHARED file.** If another lane is queued on the same prime
window, coordinate rather than requesting your own run — the prime ingests every TTL in the list
together, so all the affected files ride the same window whether or not you asked.

---

## §3 — The verbs

**Files:** `agent_fleet/<engine>_agent/{entities,measures,seed,slots,main}.py`.
**Pattern:** `agent_fleet/planning_agent/`.

### The catalogue is ONE table, read twice

`VERBS` in `main.py` is read by the routes and by the registration, so the mesh and the
served surface cannot disagree about which verbs exist. `measures.OUTPUT_URI` is the other
half — one verb, one fixed output type (ADR-0030).

### Descriptions are the routing signal, and the not-clauses are load-bearing

The same rules as the ontology definitions: written for the VERB, never for a query, and no
sibling-name bleed. Say what the verb **OWNS** and what it is **NOT**.

**DISCOVERED — this is harder for a second engine than for the first.** Engine P's twelve
verbs span money, schedule, capability and process. Engine F's six are all about money, and
the words "variance", "spend" and "cost" appear in the natural phrasing of at least four of
them. Every Engine F description therefore carries explicit not-clauses *and* an
`anti_synonyms` list — a field the registration surface already accepts and which nothing in
the planning engine populates.

### Refuse, don't guess — and name the alternative

Three refusals, all of which return an ANSWER rather than an empty set:

| condition | shape | why not the alternative |
|---|---|---|
| subject absent from the model | `422 {"not_in_model": ...}` | an empty row set renders as "none found", a false statement about something that does not exist |
| a mandatory slot missing | `422 {"needs_slots": [...], "question": ...}` | `400 bad params` tells the asker they were wrong without telling them what would be right |
| a ratio with a zero denominator | `None` | `1.0` and `0.0` are both assertions about performance nobody made, and both get charted as real points |

**Build the missing-slot question FROM THE DECLARATION**, never from a typed string —
`slots.refusal_for()` reads the enum values out of the `Literal`, so a fourth EAC formula
appears in the refusal on the same edit that adds it.

---

## §4 — Slot declarations, from day one

**File:** `agent_fleet/<engine>_agent/slots.py`. **Pattern:** `planning_agent/slots.py`
(Lane 1).

A registration has always declared what a verb is ABOUT (`input_uri`) and what it PRODUCES
(`output_uri`) and never what it TAKES. Without declarations the router cannot know a slot is
*missing* — only that nothing cleared threshold — which is why a slot-shaped question surfaces
as `NO_VERB_CLASSIFIED`, an **information** gap wearing a **threshold** gap's clothes.

**DERIVE FROM `inspect.signature`. Never hand-transcribe.** Enum values read out of a
`Literal` cannot drift from it.

### The four kinds, and declaring the ones you don't use

`("spoken-mandatory", "spoken-optional", "handle", "ceremony")`. Engine F uses two.
**Declare `HANDLE_SLOTS = {}` and `CEREMONY_VERBS = set()` explicitly** rather than omitting
them: a reader who finds two of four kinds used cannot otherwise tell whether the other two
were considered or forgotten. Engine F has neither because ADR-0045 Decision 1 makes it
governed *reading* — no scenario handle to inject, no ceremony to supply.

### Three details that each cost somebody a measured failure

1. **`eval_str=True` on `inspect.signature`.** With `from __future__ import annotations`
   every annotation is a STRING, and `Literal["CPI", ...]` arrives as the literal text
   `"Literal['CPI', ...]"` — the enum values reduced to prose.
2. **Unwrap `Optional[X]`, but STOP at a real container.** Lane 1's first rule unwrapped
   `Optional[list[str]]` twice and declared a multi-valued slot a scalar. A router then sent
   the bare string, the measure iterated it, and the engine refused with
   `422 unknown fiscal period(s): F, Y, 2, 6, -, Q, 4` — a message naming CHARACTERS and
   blaming the engine for the declaration's lie.
3. **Declare a `referent` class URI on every spoken `*_id` slot.** Without it the filler
   emits the NAME into an id slot — `site_id="Aurora"` at 0.92 confidence, answered
   `422 unknown site 'Aurora'`, the largest single failure class in the planning corpus.
   The value is the **class URI**, not a kind name, so a consumer compares
   `class_uri == referent` and needs no second map.

### Vocabularies that are DATA, not code

`window` takes fiscal periods, which come from the loaded model. Keep `slots_for` a pure
signature derivation and attach data vocabularies in a separate `with_live_vocabularies()`
that registration calls — registration is the moment both are in hand.

> **FILED, NOT FIXED:** Engine F's `slots.py` is a **second implementation** of Lane 1's
> derivation. The extraction target is `agent_fleet/utils/slot_declarations.py`, imported by
> both under the flat/packaged idiom. It was not done here because `utils/` is shared code
> another lane is in, and because a cross-engine import does not survive containerisation
> (see §5). **A third engine is where this stops being a cost and becomes the defect.**

---

## §5 — The flat/packaged import idiom, and why it is not optional

In the built image **`/app` IS the engine directory**. `agent_fleet` does not exist there;
`utils` is a sibling *top-level* module. In the repo it is the opposite. So every
intra-engine and utils import is written twice, flat first:

```python
try:      # flat in the image (/app)
    import measures
    from slots import slots_for
except ImportError:   # packaged in the repo
    from agent_fleet.finance_agent import measures
    from agent_fleet.finance_agent.slots import slots_for
```

**Getting the order backwards cost Engine P a full roll:** the import failed, the
registration helper became `None`, and **twelve registrations were skipped while the engine
reported perfectly healthy.** `tests/test_agent_modules_survive_flat_layout.py` seals it.

**Check it before you build the image**, because CI will not:

```bash
cd agent_fleet/<engine>_agent && PYTHONPATH= python -c "import main; print(len(main.VERBS))"
```

---

## §6 — Keycloak: the identity, and the law that costs a silent 401

**Realm:** `invincible-agent` (`keycloak.realm`). **You never run `kcadm`.** Adding a service
identity is an edit to `keycloak.serviceClients` in `values.yaml`, in **every** environment —
that ONE list drives both the first-boot realm import (`keycloak-configmap.yaml`) *and* the
realm-reconcile job that runs on every upgrade (a realm import applies at **first boot only**;
before the reconcile job existed, a client added after a realm was imported existed in git and
not in the running Keycloak).

### Three edits, and the third is the one that gets missed

```yaml
# 1. values.yaml -- keycloak.serviceClients
- clientId: "iagent-finance-agent"     # after the IMAGE
  authzId: "svc:finance-agent"         # the entitlement subject
  secretRef: "financeAgentClientSecret"

# 2. values.yaml -- the secret value itself (placeholder in the tracked file)
financeAgentClientSecret: "sandbox-finance-agent-secret"

# 3. templates/secrets.yaml -- PROJECT IT TO AN ENV VAR   <-- MISSED TWICE BEFORE
#    (hasKey-guarded, so a deployment can override without editing the chart)
ENGINE_FIN_CLIENT_SECRET: {{ .Values.keycloak.financeAgentClientSecret | quote }}
```

> **Step 3 has been omitted twice, for engine-a and then for engine-p, with the identical
> shape both times:** the client existed in the realm, was reconciled on every upgrade, and
> was **unusable by the only workload that needed it**, because the secret reached no env
> var. *Nothing fails at deploy time* — minting is lazy and OBSERVE tolerates a token-less
> caller — so the first symptom is a 401 at registration, or a registration that silently
> never happens while `/health` stays green.

### THE LAW: identity is an ARGUMENT, never derived from the component name

```python
_mint = engine_mint(client_id="iagent-finance-agent",
                    secret_env="ENGINE_FIN_CLIENT_SECRET")
```

Both the client id and the env var are named **by the caller, at the caller's own site**.

**What deriving it costs.** Engine P's provider registration was first written with the
DEPLOYMENT name copied from a neighbour's block; minting failed **401 silently** while the
fourteen verb registrations beside it succeeded — a half-registered engine whose verbs route
and whose resolver does not. The general form of the same mistake is `mint_service_token()`
reading `REVIEW_STARTER_CLIENT_ID`, which made the **supervisor dispatch as the review
starter**: a general name over specific behaviour.

**Hoist the mint to ONE variable per engine** so there is one place to be wrong rather than
five.

### Registration is routing authority — hence per-engine, not one shared credential

The manifest names the endpoint URL a verb resolves to. Under a shared credential the
registrar learns only that *some* legitimate mesh component called, while *which engine* stays
an unauthenticated payload claim. Sharper: the payload `name=` is **verb-scoped**, so a shared
credential leaves the registrar checking a self-asserted string *finer-grained than any
identity it could verify*.

**Give the identity even when the engine is default-off.** A service that appears later
without one is a service that flips `REQUIRE_TRANSPORT_AUTH` from working to broken.

### Transport auth is a birth rule

```python
_announce_transport_auth(component="engine-fin")
app = FastAPI(**_docs_kwargs(), dependencies=[Depends(_transport_auth("engine-fin"))], ...)
```

Validate what arrives, log the caller posture, **refuse nothing** until
`REQUIRE_TRANSPORT_AUTH` flips. The **announcement string is load-bearing** — the fresh-deploy
gauge reads it, so an engine that takes the dependency but drops the announcement has a real
posture nothing can observe. `_docs_kwargs()` turns `/docs`, `/redoc` and `/openapi.json` off
in deployment (the Starlette-bypass class).

---

## §7 — Environment variables

Everything reaches the pod through **`envFrom`** — the shared ConfigMap and the shared Secret.
The per-engine `env:` map in `values.yaml` is for exceptions only.

### A container's `env:` OVERRIDES `envFrom` — leave it `{}`

A URL literal in a per-engine `env:` block does not *reinforce* the ConfigMap's templated
FQDN, it **REPLACES** it with whatever you typed. Measured on the live sandbox 2026-08-27:

```
ConfigMap : http://iagent-engine-w.sandbox.svc.cluster.local:8088/query_knowledge
pod env   : http://iagent-engine-w:8088/query_knowledge          <- the literal won
```

The intent was "make the deployment's intent explicit so drift surfaces at review time"; the
effect was silently disabling the `svcDomain` protection for **every engine that had one**.
The ConfigMap is the single source; change the suffix via `global.clusterDomain`.

*(Also watch for a duplicate `env: {}` **after** a populated `env:` in the same block — in
YAML the later key wins, and Engine P's `ENGINE_P_PUBLIC_URL` was silently discarded that
way.)*

### Engine F's full variable list

| variable | source | required? | degraded behaviour if absent |
|---|---|---|---|
| `ENGINE_FIN_PUBLIC_URL` | ConfigMap (templated FQDN) | **effectively required** | falls back to `http://iagent-engine-fin:8096` — a **BARE NAME**, which registers a non-FQDN endpoint into the mesh. Works in-namespace, breaks across, and is invisible until a cross-namespace caller fails |
| `ENGINE_FIN_CLIENT_SECRET` | Secret (§6 step 3) | **required to register** | `engine_mint` raises `KeyError` per attempt → **every verb unregistered, engine healthy** |
| `MESH_REGISTER_ON_STARTUP` | ConfigMap | **required to register** | default `"false"` → registration **skipped entirely**, with one log line. Serving is unaffected, so nothing else notices |
| `MESH_REGISTRAR_URL` | ConfigMap | no | unset → falls back to the **legacy direct-to-DataHub** path. Historically that path reached a RETIRED materialiser — 11 URNs, 0 rows. Prefer the gateway |
| `DATAHUB_GMS_URL` / `DATAHUB_TOKEN` | ConfigMap / Secret | only on the legacy path | unset → registration logs a warning and returns |
| `REQUIRE_TRANSPORT_AUTH` | ConfigMap | no | unset → **OBSERVE**: inbound callers logged, none refused. This is the intended posture today |
| `CENTRAL_GATEWAY_URL` | ConfigMap | only for governed reads | unset → `mesh_ticketed_read` raises `KeyError`. It is **not** consulted on the notional path |
| `NEO4J_*` | ConfigMap / Secret | **not read by this engine** | listed so the next reader does not add a driver it does not need |

### The degraded-default law

> `LLM_BASE_URL` was unset for **67 days** and degraded **silently**. The A/B afterwards
> showed it cost zero accuracy — *by luck*, because retrieval was over-provisioned against a
> 27-row pool. The lesson is not "degraded defaults are fine".

**Every degraded default in the table above SAYS SO IN A LOG LINE**, and the two that must
never degrade — the caller's identity on a governed read, and the registration credential —
**raise instead**. A data read that degrades to "unscoped" costs more than an LLM that
degrades to "unused". There is nowhere in `main.py` a standing secret could be read from, so
the degraded mode cannot silently become the privileged one.

---

## §8 — Registration, Contract D, and the ontology seed

### The call

One `register_engine_to_mesh(...)` per verb — the helper takes a single verb, and eight calls
is the honest shape. Plus, for any engine with instance-kind slots, **two provider
registrations**:

* **`mesh:resolveInstance`** — a speaker says "Meridian", not `NP-MERIDIAN`. Without a
  provider the filler emits the name into the id slot.
* **`mesh:enumerateInstances`** — `resolveInstance` scores against something the speaker
  *said*. A slot the phrase never filled has no such string, so **no number of resolve
  providers builds a menu for it.**

### CONTRACT D: both ends must PRE-EXIST, and rejection is ATOMIC

The registrar validates that `input_uri` **and** `output_uri` resolve to real
`:OntologyClass` nodes in Neo4j. **A 422 is PERMANENT — the transport does not retry it**,
because the ontology has to be fixed first.

> **The batch is refused WHOLE.** When `mesh#DecisionArtifact` was missing, **all fourteen of
> Engine P's verbs were refused together — and the engine kept serving, healthy, while none
> of its verbs routed.** That failure is invisible to `kubectl get pods` and looks exactly
> like a working cluster until someone asks a question.

The provider registrations need `mesh:InstanceClass`, `mesh:InstanceEnumeration`,
`mesh:InstanceIdentifier` and `mesh:InstanceResolution` to exist too.

**Check before you deploy** — this is what `tests/finance/test_engine_f_contracts.py`'s
`test_every_verb_has_both_ends_of_contract_d_declared_in_the_ttl` does, and it is the only
check available before a prime runs.

### The seed window

Hook order is **`prime(10) → ontologySeed(15) → reregister(20)`**.

```bash
helm upgrade iagent ./helm/invincible-agent \
  --namespace sandbox \
  -f helm/invincible-agent/values-sandbox.yaml \
  --set primeSubstrate.enabled=true \
  --set primeSubstrate.wipe=false \
  --set primeSubstrate.triggerIngest=true \
  --timeout 90m
```

> ### PRECONDITION — the chart AND the image must both carry your change
>
> The prime job runs from the **`dagster-control-plane` image, which bakes the repo**, so your
> TTL and its `ONTOLOGIES` manifest entry ride the IMAGE. Your deployment, secret and
> reregister entry ride the **CHART**. They are two different artifacts on two different
> workflows and **they fail independently**:
>
> ```bash
> gh run list --limit 5   # BOTH must read `completed success` for your commit:
>                         #   Build & Push Container Images   -> the image the prime runs from
>                         #   Release Helm Charts             -> the chart the upgrade installs
> ```
>
> **Engine F's first push had a green image build and a RED chart release** (no `Chart.yaml`
> bump, §10 row 11). Priming on that state would have ingested the finance classes from the
> image while the engine itself was never deployed — the ontology half landing and the runtime
> half silently absent, which is the same split that cost the planning engine twelve 422s,
> arriving from the other direction.

Five things about this command, every one of which has bitten someone:

1. **`--timeout 90m`. NOT 40m — AND 40m IS THE TRAP, not 15m.**

   Dagster's `QueuedRunCoordinator` caps at **2 concurrent runs**, so the wall-clock scales
   with the manifest. **Engine F's run: 17 ingests, Job duration 44 MINUTES.**

   > ⛔ **The inherited advice was "use `--timeout 40m`" — and its own measurement in the
   > same paragraph was 43 minutes.** The recommendation contradicted its evidence and sat
   > uncorrected in the prime playbook and in the first draft of this runbook. **40m sits
   > INSIDE the range that times out.** Adding one TTL to the manifest made it worse: 16
   > ingests → 17.

   **What under-waiting costs:** helm times out, the Kubernetes Job **keeps running and
   finishes**, and the release is left `failed` with the **hook chain CUT** — so
   `reregister(20)` never fires. Concretely, on this run that would have meant: engine-fin
   never registered, engine-p stuck at 15 with its `enumerateInstances` still refused, and
   **helm reporting failure over a prime that had actually succeeded.** Two lanes blocked by a
   timeout, with the substrate half-applied and every component healthy.

   **Over-waiting costs nothing** — helm simply returns when the chain completes. Set it high.
   `90m` leaves headroom for a manifest that grows again, which it will: every new engine adds
   an ingest.
2. **Fast path when the ontology is already ingested:**
   `--set primeSubstrate.triggerIngest=false` → the prime completes in ~40 **seconds** and
   reregister still fires.
3. **`primeSubstrate.enabled=false` DOES NOT "skip the prime and keep the chain".** The
   reregister hook renders under
   `{{ if and .Values.primeSubstrate.enabled .Values.primeSubstrate.reregisterEngines.enabled }}`
   — turning the prime off removes **the tree the hook hangs from**, and helm exits **0
   having done nothing**. To fire reregister you need `enabled=TRUE` with
   `triggerIngest=false`.
4. **`--reuse-values` cannot deliver a chart-default DELETION.** It reuses the last release's
   *merged* values, so a key you DELETE is carried forward and re-applied. Measured cost: a
   fix removing three shadowing `ENGINE_*_PUBLIC_URL` literals was committed, built and
   deployed **three times with zero effect** — the ConfigMap showed the new FQDN, the pod env
   showed the old bare name, every signal said the fix had landed. Either drop
   `--reuse-values` and re-supply the values files (done above), or null the KEY explicitly
   (`--set engineFinance.env.ENGINE_FIN_PUBLIC_URL=null`). **Null the key, never the block** —
   sibling blocks carry other env.
5. **`wipe=false` is load-bearing** and is the default. The wipe path clears Neo4j
   `OntologyClass`, every Weaviate collection, the Jena graphs and the MinIO TTLs. Adding an
   engine is additive and needs none of it. Flip `primeSubstrate.enabled` back to `false`
   afterwards so a later unrelated upgrade does not re-run it.

**Add your deployment to `primeSubstrate.reregisterEngines.deployments`** in the same change
that adds the engine. It was omitted for data-analyst and then again for engine-p, and both
times a wipe+reprime left the engine present and unrouted while **every hook reported
success — the only visible evidence was the pod name not changing.**

### B4a GATE — reregister RESTARTS the engines it covers

Engine P's `PlanStore` is in-memory: a restart destroys every scenario **silently**. Engine F
holds no session state, so it is safe — but the gate is about the whole list, not your entry.
Verify Engine P is empty (`0 scenarios, baseline v0`) before any reregister that covers it,
because "should be empty" and "is empty" are different claims.

### Networking: the endpoint URL is BAKED AT REGISTRATION TIME

`endpoint_url` is written into the mesh as the address a verb resolves to. **A ConfigMap
change is INERT until the engine re-registers.** Use the FQDN via the `svcDomain` helper,
never a bare service name: a bare name resolves differently depending on where the reader
stands, and an endpoint — like a ticket — is consumed somewhere else. The same defect appeared
on the data plane, where a ticket relayed a namespace-local `aws_endpoint_url` resolvable only
where the producer ran.

---

## §9 — Verification: the sequence that actually proves an engine is live

> ### DO NOT VERIFY REGISTRATION BY ASKING THE ENGINE ABOUT ITSELF
>
> `/health`'s `verbs` count reads the engine's **own in-process table**. It returns the full
> number when the mesh holds bare endpoints, when the engine never re-registered at all, and
> when the reregister job was never created — **all three measured.** It would green-light
> exactly the failure it looks like it detects. Engine P's `verbs: 14` was written into a prep
> doc as "the signature that matters most" and struck out the next day for precisely this.
> Engine F's `/health` carries the warning in its own payload.
>
> **DO NOT VERIFY BY COUNTING CLASSES EITHER.** The graph holds every seeded TTL, so a file's
> class count is a pre-flight check on the EDIT, never a post-condition on the GRAPH. And a
> count cannot see misclassification: the right names under the wrong parents counts
> identically and is wrong — which Contract D also cannot see, because it checks existence,
> not classification.

### 1. Verb edges in the graph, BY HOST — is it registered at all, and at the right address?

```bash
kubectl --context edge exec -n sandbox deploy/iagent-engine-e -- python -c "
import os
from neo4j import GraphDatabase
drv = GraphDatabase.driver(os.environ.get('NEO4J_URI','bolt://iagent-neo4j:7687'),
                           auth=(os.environ.get('NEO4J_USER','neo4j'), os.environ['NEO4J_PASSWORD']))
q='''MATCH ()-[e]->() WHERE e.endpoint_url IS NOT NULL AND e.endpoint_url CONTAINS 'iagent-'
RETURN DISTINCT split(split(e.endpoint_url,'//')[1],'/')[0] AS host, count(*) AS edges ORDER BY host'''
with drv.session() as s:
    for r in s.run(q): print(' ', r['host'], 'edges=', r['edges'])
drv.close()"
```

Engine F must show **8 edges** (6 verbs + 2 providers) at the **FQDN** host
`iagent-engine-fin.sandbox.svc.cluster.local:8096`. A **bare** host means it registered before
the URL fix reached it; a **missing** host means it did not register. The credentials are the
pod's own, read from its env by the code it runs — **do not fetch the secret yourself.**

### 2. The verbs BY NAME — Contract D refuses atomically, so a partial set is the shape to watch

```bash
kubectl --context edge exec -n sandbox deploy/iagent-engine-e -- python -c "
import os
from neo4j import GraphDatabase
drv = GraphDatabase.driver(os.environ.get('NEO4J_URI','bolt://iagent-neo4j:7687'),
                           auth=(os.environ.get('NEO4J_USER','neo4j'), os.environ['NEO4J_PASSWORD']))
q='''MATCH ()-[e]->() WHERE e.endpoint_url CONTAINS 'engine-fin'
RETURN e.verb AS verb, e.endpoint_url AS url ORDER BY verb'''
with drv.session() as s:
    for r in s.run(q): print(' ', r['verb'], '->', r['url'])
drv.close()"
```

> ### ⛔ THE VERB IS THE RELATIONSHIP **TYPE**, NOT A PROPERTY — and getting this wrong
> ### produces a by-COUNT check wearing a by-NAME check's clothes
>
> **Measured on this run.** The first version of this query selected `e.verb`. There is no such
> property; the verb name is `type(e)`. Neo4j returned a warning and **eight rows of `None`**:
>
> ```
> count = 8
>   None   None   None   None   None   None   None   None
> ```
>
> **The count was right.** A check that asserted only "eight rows returned" would have passed
> — while verifying nothing about which verbs those were, which is the entire thing the
> by-name rule exists to establish. It was caught only because the `None`s printed; a summary
> line would have hidden it completely.
>
> **THE ASSERTION SHAPE, and it generalises past this query:** a by-name check must assert the
> **names are non-null and match an expected set**, never that rows came back. Rows returning
> is liveness; names matching is identity, and the whole discipline in this section is that
> the two are different claims.
>
> ```cypher
> MATCH (a)-[e]->(b) WHERE e.endpoint_url CONTAINS 'engine-fin'
> RETURN type(e) AS verb, e._input_uri AS input, e._output_uri AS output, e.slots AS slots
> ORDER BY verb
> ```
>
> `_input_uri` / `_output_uri` are underscore-prefixed; `slots` is a JSON string (a Neo4j
> property holds primitives or arrays of primitives, never maps).

**Verified live 2026-08-30** — Engine F's eight, each with both Contract D ends and its
declared slot count:

```
enumerateInstances     InstanceClass                  -> InstanceEnumeration     slots=0
finBurnRate            PerformanceMeasurementBaseline -> BurnRateSeries          slots=2
finEacCalculation      Program                        -> EstimateAtCompletion    slots=3
finFundingStatus       FundingLine                    -> FundingStatusGrid       slots=2
finPerformanceIndices  PerformanceMeasurementBaseline -> PerformanceIndexSeries  slots=3
finVarianceAnalysis    Program                        -> VarianceDecomposition   slots=5
finVarianceDrivers     ControlAccount                 -> VarianceDriverRanking   slots=5
resolveInstance        InstanceIdentifier             -> InstanceResolution      slots=0
```

**Fewer than eight means the batch was refused; go read the registrar's 422.** A `slots=0` on
a *finance* verb would mean the declarations never reached the mesh — the engine would route
and never elicit.

**The providers' `slots=0` is CORRECT and not a gap:** they take a typed request body rather
than declared slots.

### 3. The classes BY NAME AND PARENT — never by count

```cypher
MATCH (c:OntologyClass) WHERE c.uri STARTS WITH 'http://invincible-agent/fin#'
OPTIONAL MATCH (c)-[:SUBCLASS_OF]->(p:OntologyClass)
RETURN c.uri, c.label, p.uri ORDER BY c.uri
```

Fourteen `fin:` classes. **The `prov:Entity` parents will be ABSENT and that is expected** —
no `subClassOf` edge to a `prov:` target materialises anywhere in this graph (ADR-0045's
implementer note). Verify the **names**; verify a parent only where the parent is a `mesh:`
term.

### 4. Declarations spot-checked against signatures — no cluster needed

```bash
curl -s http://localhost:8096/verbs | python -m json.tool | head -60
```

Confirm `method` on `fin_eac_calculation` is `spoken-mandatory`, has three `values`, and has
**no `default`**. This endpoint is *only* good for this; it is not a registration check.

### 5. A routed question, end to end — the only check that covers the whole chain

Ask through the front door, not the engine:

* **"what's the EAC on Meridian"** → must **REFUSE**, naming CPI / CPI_SPI /
  REMAINING_AT_BUDGET. *(This is the demo beat. A number here is a FAILURE.)*
* **"what's the EAC on Meridian using CPI"** → 14,152,381 USD.
* **"why are we over budget on Meridian"** → a decomposition reaching WP-3101.
* **"funding status for Meridian"** → a three-state grid.

### 6. THE PAGE LOAD — presentation bindings do not reach the graph from a deploy

**A named step, because skipping it produces a symptom that looks exactly like a binding bug.**

Verb edges reach the graph when an **engine** starts. `output_uri → archetype` bindings do not:
they are posted by **cortex-ui**, from `assembleCapabilities()`, through a `useEffect` **gated
on `auth.isAuthenticated`** (`cortex-ui src/App.tsx:103` via `src/api/client.ts:635`) — so they
land on an **authenticated browser page load, once per load**, and never from a helm upgrade, a
pod restart, or the reregister hook.

> **Measured, and it is `docs/principles/a-registration-is-not-a-reachable-call.md` row 3:**
> `CANVAS_SEED` shipped in the bundle and sat **registered-in-source and unregistered-in-fact
> for days**, because *nobody had loaded the page.* Every deploy signal was green.

**So: after a correct cortex ship, LOAD THE PAGE AS AN AUTHENTICATED USER BEFORE CONCLUDING
ANYTHING.** A finance card that does not draw is this until proven otherwise.

```bash
# The binding rows, AFTER an authenticated page load. Absent before it, by design.
kubectl --context edge exec -n sandbox deploy/iagent-engine-e -- python -c "
import os
from neo4j import GraphDatabase
drv = GraphDatabase.driver(os.environ.get('NEO4J_URI','bolt://iagent-neo4j:7687'),
                           auth=(os.environ.get('NEO4J_USER','neo4j'), os.environ['NEO4J_PASSWORD']))
q='''MATCH (o)-[r]->(a) WHERE type(r) CONTAINS 'RENDERS' OR r.predicate CONTAINS 'rendersAs'
RETURN o.uri AS output, a.uri AS archetype ORDER BY output'''
with drv.session() as s:
    for x in s.run(q): print(' ', x['output'], '->', x['archetype'])
drv.close()"
```

**The ordering trap, stated because it is the one that wastes an afternoon:** a browser reload
is the trigger, and the BFF log carries the admitted/rejected split from `capability_admission`.
An archetype the backend has no name for is **refused at the door** — so a new archetype must be
in `KNOWN_ARCHETYPES` *before* the frontend advertises it, not after. Four live-view archetypes
were refused on their first registration for exactly that, and that registry was the one nobody
enumerated.

**For Engine F specifically:** only two of six verbs are binding rows today
(`fin:BurnRateSeries → PERIOD_SERIES`, `fin:FundingStatusGrid → SHORTFALL_GRID`); three need
cortex builds and one carries an open question. Until those land, finance answers **route and
return rows correctly and do not draw as their intended cards** — which is a known state, not a
regression. See `[[engine-f-archetype-bindings]]`.

### 7. The pod name across a reregister

> **The one check that has caught something twice.** `values.yaml`'s `reregisterEngines`
> comment records a run where *"every hook reported success; the only visible evidence was
> the pod name not changing"* — and it caught the same thing again five days later. **Read
> that comment before running.** It is the shortest true thing written about this hook.

### On any failure: PASTE, DO NOT RETRY

A blind second run cannot distinguish "transient" from "the thing is wrong", and it destroys
the first run's evidence. On a refused binding the recovery is **not** another prime — read
the rejection: `capability_admission` names the row, the archetype and the reason,
per-capability rather than per-batch.

---

## §10 — Errors hit while building Engine F, and what each one teaches

Recorded because the next engine will meet most of them.

| # | what happened | the general lesson |
|---|---|---|
| 1 | **`engine-f` was already the presentation agent.** Reusing it would have taken `/render_ui` down fleet-wide. | An ADR names an engine in prose; it does not allocate a component name. **§0.** |
| 2 | **`python` is not on PATH** in this repo's shell; the bare `py` launcher has no `rdflib`. | Use `.venv/Scripts/python.exe`. |
| 3 | **The seed's own roundness guard refused 36 rows of a perfectly round seed** — it asserted `% 50_000`, transcribed from the phrase "round multiple of $50,000" in the docstring above it. $75,000 and $80,000 are round and are not multiples of fifty thousand. | **The DATA was right and the ASSERTION was wrong.** A guard transcribed from prose inherits the prose's imprecision. |
| 4 | **Every period returned CPI 0.8367, identical to four decimals, six times** — constant seed factors cannot produce a trend, and the series verb exists *because* the trend is the question. | **A uniform extreme result is the tell.** A flat line is also what a broken instrument returns, so a demo over that data would have been indistinguishable from a bug. Fixed in the SEED, not the verb. |
| 5 | **`resolve_instance("Integration and Test")` returned two exact matches in different classes** — the seed gave one name to a control account, a WBS element and an OBS element. The router abstains on mixed-class ties. | A duplicate label makes a question **unroutable while every component reports healthy**. Now refused by `check_consistency`. |
| 6 | **`fin:FundingLine` — the `input_uri` of a registered verb — answered `unsupported` to enumeration.** | The enumerable set must be **DERIVED FROM WHAT THE ENGINE ROUTES ON**, not from what looked worth listing. `unsupported` is a *legitimate-looking* answer, so an ask falls back to free text believing a provider considered the question. Now asserted at boot from `VERBS`. |
| 7 | **Widening a seed table from 5 columns to 7 moved the BAC out from under `a[4]`.** It raised only because summing a string onto an int throws; two numeric columns would have made the program's budget quietly wrong. | Destructure from the END (`for *_, bac in ...`) or by name. |
| 8 | **`#` is not a comment inside a Go template action.** A per-entry note inside `{{- $engines := list ... }}` breaks the parse. | Notes go in a `{{/* */}}` block above the action. |
| 9 | **`helm template` against bare `values.yaml` fails** on an unrelated pre-existing nil (`dagster.daemon.image.registry`). | Always render with `-f values-sandbox.yaml`. Not your bug; don't chase it. |
| 10 | **A test assertion compared a string to a list and asserted nothing** while passing as "checked". | **Assert on the claim, not its neighbour.** The fix was to hoist `DOMAINS` to a constant so the test compares the registration's own value against the prime manifest, instead of a literal typed twice. |
| 13 | **The inherited `--timeout 40m` was below the measured runtime it cited.** Its own paragraph said the job took 43 minutes. This run took **44** over 17 ingests. | **A recommendation that contradicts the measurement printed beside it survives because nobody re-reads the paragraph.** Under-waiting cuts the hook chain and leaves the substrate half-applied with everything reporting healthy; over-waiting costs nothing. Now 90m. |
| 14 | **A verification query selected `e.verb`, which does not exist** — the verb is `type(e)`. It returned **8 rows of `None`**, and the COUNT was right. | **A by-name check must assert the names are non-null and match an expected set**, not that rows returned. Otherwise it is a by-count check wearing a by-name check's clothes — the exact instrument class this whole runbook is written against, produced by the person writing the section that warns about it. |
| 12 | **The engine image failed to build: no `uv.lock`.** `Dockerfile.agent` runs `uv sync --locked`, which refuses to generate one. Every other matrix job — including `dagster-control-plane`, the prime's image — went green, so the prime could have run against a correct ontology while the engine image did not exist. | **A new engine directory needs the lockfile, not just the manifest.** And note the shape: ONE red job in a 16-job matrix, with the workflow's overall status the only summary. Read WHICH job failed, not whether the run did. |
| 11 | **Pushed a `helm/**` change without bumping `Chart.yaml`.** `Release Helm Charts` failed in 10 seconds; the container build was unaffected and green, so a reader watching only the build would have proceeded. | **A chart change that does not move the version publishes NOTHING and reports success at the resolution of "I ran".** The seal exists because this exact omission once shipped engines with no client secret. Watch BOTH workflows on a push, not just the image build. |

---

## Appendix — the complete Engine F change list

Copy this shape. The count is the point: **seventeen** places, of which the four outside the
engine's own directory are the ones that get forgotten.

**New files**

1. `setup/ontologies/finance_extension.ttl` — 14 classes, both Contract D ends
2. `agent_fleet/finance_agent/entities.py` — model + refusal types
3. `agent_fleet/finance_agent/seed.py` — notional data + `check_consistency`
4. `agent_fleet/finance_agent/measures.py` — 6 verbs + `OUTPUT_URI` / `VALUE_UNIT` / `VALUE_LABEL`
5. `agent_fleet/finance_agent/slots.py` — declarations + the declaration-built refusal
6. `agent_fleet/finance_agent/main.py` — app, catalogue, registration, 2 providers
7. `agent_fleet/finance_agent/{Procfile,pyproject.toml,project.toml}` — port 8096 in all three
7b. **`agent_fleet/<engine>_agent/uv.lock` — GENERATE IT, or the image will not build.**
    `Dockerfile.agent` runs `uv sync --locked`, which **requires** a lockfile and refuses to
    create one: *"Unable to find lockfile at `uv.lock`, but `--locked` was provided."* Copying
    a neighbour's `pyproject.toml` does not copy its lock. Run `uv lock` in the engine
    directory, and check the resolved SDK commit matches the other engines' — the pin exists
    so one SDK commit cannot change every engine's auth behaviour at rebuild, and
    `tests/test_lock_coherence.py` polices the drift:
    ```bash
    cd agent_fleet/<engine>_agent && uv lock
    grep -A2 '^name = "iagent-mesh"' agent_fleet/*/uv.lock | grep source   # all must match
    ```
8. `tests/finance/test_engine_f_contracts.py` — the seals
9. `docs/runbooks/adding-an-engine.md` — this file

**Edits to shared files** — 12, 13, 15 and 16 are the ones that get forgotten

10. `setup/prime_databases.py` — `ONTOLOGIES` manifest entry, domain `PROGRAM_FINANCE`
11. `helm/.../values.yaml` — the `engineFinance` block
12. `helm/.../values.yaml` — `keycloak.serviceClients` + `financeAgentClientSecret`
13. `helm/.../values.yaml` — `primeSubstrate.reregisterEngines.deployments`
14. `helm/.../templates/engines.yaml` — the `$engines` list
15. `helm/.../templates/configmap.yaml` — `ENGINE_FIN_PUBLIC_URL` (FQDN via `svcDomain`)
16. `helm/.../templates/secrets.yaml` — `ENGINE_FIN_CLIENT_SECRET` projection
17. `helm/.../templates/NOTES.txt`, `values-sandbox.yaml`, `.github/workflows/build-containers.yml`
18. **`helm/invincible-agent/Chart.yaml` — BUMP THE VERSION.** Missed on Engine F's first
    push and caught by the release workflow, which fails loudly on exactly this. **Any change
    under `helm/**` needs it**, and the reason is in Chart.yaml's own comment: eight
    chart-changing commits once landed on 0.3.36 without a bump, `skip_existing: true`
    published none of them **while reporting green**, and a deployment installing "the latest
    chart" got frozen contents with **no `ENGINE_*_CLIENT_SECRET` — so every engine died on
    `KeyError` at mint and registered zero verbs.** An engine addition adds exactly that kind
    of secret, so this is the same failure mode, not a neighbouring one. Check the tag is free
    (`git tag -l "invincible-agent-0.3.*"`) — a bump to an already-published version fails the
    same gate.

**Known gap, FILED not fixed:** the `output_uri → archetype` bindings (`DERIVED_BINDINGS`)
live in the **cortex-ui** repo, outside this one, and land on an authenticated page load (§9
step 6) rather than from a deploy.

> ⛔ **CORRECTED 2026-08-29.** This paragraph originally said Engine F's rows satisfy the
> `PERIOD_SERIES` / `SHORTFALL_GRID` / `INSTANCES_BY_PROPERTY` contracts *"so each binding is a
> one-line addition there."* **That was asserted, not demonstrated, and doing the demonstration
> disproved it for half the engine.** Only **two** of six are binding rows
> (`fin:BurnRateSeries → PERIOD_SERIES`, `fin:FundingStatusGrid → SHORTFALL_GRID`). One fits at
> a cost, and **three are cortex BUILDS**: a tree with no flat archetype, a single measure whose
> method no archetype carries, and a ranking assigned to `INSTANCES_BY_PROPERTY` — an archetype
> that is **not in the projection arm at all** and is semantically a *filtered instance table*.
> The full field-by-field table is `[[engine-f-archetype-bindings]]`.
>
> **The lesson generalises, which is why the error is kept rather than edited away:** an
> archetype's NAME sounding right is not a fit. Read the arm (`_PLANNING_ARCHETYPES`) for
> whether a projection exists at all, then read the contract's fields against your payload's.
> Both checks are ten minutes and one of them is the difference between a binding row and a
> quarter of frontend work.

`fin:VarianceDecomposition`'s archetype is deliberately unchosen — ADR-0045 defers it pending a
payload read, and that read is now done: it confirms the deferral.
