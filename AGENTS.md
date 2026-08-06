# AGENTS.md — AI Agent Workflow & Safety Guide

## The fence — agent read/write boundaries (three clauses, no ambiguity)

1. **Agents read freely where they have reach.** Read-only inspection of any substrate an agent can
   reach (sandbox Fuseki/Neo4j/MinIO, repos, logs) needs no gate — verify by observation, don't ask.
2. **Writes serialize through the human, everywhere.** Any mutation — helm/kubectl apply, prime,
   image roll, a destructive substrate op — is the human's to authorize or run. The user serializes
   the agents; a write is never assumed from a read.
3. **Work-cluster anything is the human's until agents get read credentials there.** The agents'
   access is sandbox-side; the work cluster (e.g. its Dagster runs) is out of reach, so any probe or
   task against it is the human's regardless of the read-only-vs-mutating rule — the fence is literal,
   not a permission judgment. Revisit when agents get read creds on the work cluster.

**Post-grant status (2026-07-23):** the human granted **standing write authorization on the SANDBOX
cluster** (kube context `edge`) for the current PCN/PDN M1 wiring — "the cluster is yours." So sandbox
deploys/ingests/rolls no longer serialize per-action under clause 2; agents may write there directly,
with the destructive-op discipline still applying (predict-via-check before a destructive substrate op;
additive/partition paths preferred; verify the effect; a full DROP-first prime remains decision-bearing
and should still be surfaced, not run silently). **Kill-seal ruling (2026-07-23):** the PCN driver's
two-direction failure-injection seal KILLS a Restate process mid-write on `edge` — disruptive-by-intent
but resumable-by-design (data loss would mean the seal already failed), so it is within the standing
grant, NOT a per-action gate; the agent DRIVES it, ANNOUNCING each kill before it runs (surface-not-
silent) with a timestamp to correlate against the Restate journal + assertions. The kill window must be
JOURNAL-CONFIRMED (mint journaled, state-write not yet → kill landed between the writes), not assumed. Clause 2's per-action serialization now governs writes
**outside** this grant; **clause 3 is unchanged** — the work cluster is still the human's. Re-scope the
grant when the work changes, and keep this line current so the fence tracks reality, not the state it
was written in.

**Deploy-target resolution is EXACT-MATCH, not pattern-match (2026-07-25).** The standing grant covers
the NAMED M1 services; it does not license rolling whatever a substring happens to hit. Resolve a
`kubectl rollout restart` target by exact deployment name (`iagent-cortex-ui`, `iagent-cortex-bff`, …),
never by a grep/`grep -iE` over `kubectl get deploy` output — a "frontend"/"ui" pattern once matched and
rolled `datahub-datahub-frontend` by accident (harmless rolling restart, but the wrong service). The
grant makes the fleet writable at 2am; the fence is that name resolution is deliberate, not incidental.
Filed from that miss so the anecdote becomes a rule, not a repeat.

**Git branches are OWNED BY NAME — the serialization rule applied to version control (2026-07-27).**
Multiple agents share one working copy; a `git checkout`/branch-switch by one silently moves HEAD under
another mid-edit (seen live: a second agent branched `feat/user-deployment-grist-chart` off an active
branch and left HEAD there; caught only because the human flagged it). So each agent works ONLY on the
branch it created/owns for its task, and **verifies `git branch --show-current` immediately before every
`git add`/`commit`** — a wrong-branch result aborts the commit (never `git checkout` onto someone else's
branch to "fix" it). This is clause 2's write-serialization applied to git: a branch is a write surface,
and an unowned HEAD move is a collision, not a convenience. Per-commit verification is the floor; if
agents run concurrently often, isolate with a `git worktree` per agent. Filed from that collision.

**STAGE BY EXPLICIT PATH, never by pattern, in a shared tree (2026-08-05).** The same hazard one layer
down: `git add -u` stages every tracked modification, and `git add -A` every file — including work
someone else has in flight in the same working copy. Used `-u` while the human was mid-arc on an
unrelated feature; it happened to catch only the intended five files, which is **luck wearing
discipline's clothes** — the outcome was identical to the careful version and would have stayed
identical right up until the once it wasn't. A pattern-stage that has never swept a stranger's file
has not been shown to be safe, it has been shown to be untested (the guard-that-never-failed rule
applied to a command). Name the paths; `git status --short` before, and read it.

## Runbook: engine-o's SELECT path drops RDF term types — typed reads go CONSTRUCT→parse (2026-07-23)

`execute_sparql` returns `list[dict]` of `{var: string}` — it stringifies every RDF term (main.py
~L415, `v["value"]`), dropping the Literal/IRI/datatype distinction. So **any** consumer reading a
TYPED value through the SELECT path gets a string: a boolean `"false"` becomes truthy (`bool("false")
is True`), a number becomes text, a date loses its type. This was found by design while building
`/policy_rules` (a boolean rule condition would have silently mis-fired), not by debugging a wrong
answer in production — file it so the next consumer doesn't rediscover it the expensive way. **Rule:
for typed reads, run a CONSTRUCT and parse the Turtle into rdflib (types preserved); reserve the
SELECT path for string/label reads.** `/policy_rules` is the reference: engine-o CONSTRUCTs + serves
Turtle, the consumer parses. **Convention (until a second consumer forces it structural):** raw
`/policy_rules` Turtle is NOT a rules API — consumers go through the loader/validator
(`restate_analyst/policy_rules_client.py`); nothing consumes the raw triples, which is why the endpoint
honestly serving a possibly-invalid graph is safe. Same shape as "audit_record is audit-only."

## Runbook: test-env must == image-env — runtime imports are frozen deps, never `--with` overlays (2026-07-24)

Found live: `restate-analyst` 500'd with `No module named 'rdflib'` — the code imports rdflib at
runtime, but it was missing from the image; the offline suite ran `uv run --frozen --with rdflib`, so
the overlay supplied rdflib in TEST but not in the CONTAINER. That's **test-env/runtime-env drift** — the
same shape as fixture/live drift, one layer down: the tests passed in an environment the deployment
doesn't have. **Rule: a module's RUNTIME imports must be in the image's FROZEN deps (pyproject+lock),
never provided by a `--with` overlay.** `--with` is only for TEST-ONLY tools (pytest, pytest-asyncio).
Enforcement: run the suite against `--frozen` alone for anything that imports a runtime dep (the pcn
suite now passes `--frozen` with no rdflib overlay); if a `--with <runtime-lib>` is load-bearing for a
test, that library belongs in the image, not the overlay. Same class as the CONSTRUCT finding above —
"the test lied about the environment."

## The generic-at-birth rule (adopted 2026-07-23)

**No new engine route, endpoint, Topaz resource type, or registered capability may carry a domain
name. New surface is GENERIC at birth; the domain arrives as a parameter or as data.** The domain-ness
lives in the arguments the caller passes, never baked into the name of the mechanism.

**ALL REPOS, including the UI (extended 2026-07-24).** The rule was written for engine surface and
didn't enumerate `cortex-ui`, so the presentation layer became the place the discipline arrived last —
and the UI recapitulated the engines' pollution arc (domain-named `switch` branches, label maps) six
weeks faster. So it binds every repo now: **no new UI component, switch branch, label/icon/color/route
map may carry a domain name or value; domain display arrives as a payload field or a served declaration
(the `rendersAs` / M3 horizon).** A new task kind adds a ROW to the single `taskKindRegistry` (interim
scaffolding awaiting served hints), never a `kind === "pcn_…"` branch; everything else keys on the
ARCHETYPE (structural). Undeclared kind → honest default (UI-COMPONENT-NOT-FOUND for labels). See
`cortex-ui/AGENTS.md`. The deletion test now reads every repo: no domain-named surface in engines OR UI,
feature still runs.

Why now: the PCN/PDN M1 exemplar moved fast and let *mechanism* pick up domain names
(`PcnDispatchItem`, `/write_pcn_disposition_state`, a would-be `pcn_disposition` Topaz type) while the
*content* stayed correctly in data. Content was always in the right place; mechanism got domain names
because the exemplar sprinted. Left alone the exemplar becomes the precedent — "real processes get
coded and named, the interview is for demos" — which inverts the ADR-0029 thesis that processes are
data. This rule stops the bleeding without a big-bang refactor: it binds only NEW surface, and it is
*less* work than the domain-named version (no second endpoint/type when the next policy domain lands —
which is the whole test).

Concretely, it already decides open questions rather than deferring them:
- A rules-fetch endpoint is `POST /policy_rules` taking `{graph, ruleset_label}`, NOT
  `POST /pcn_disposition_rules`. "Fetch flat rule individuals from a named graph" knows nothing about
  PCN; the pcn-ness is the caller's arguments.
- The authz check reuses the EXISTING workflow-model type `task_audience` (key
  `disposition_review:<compartment>`), NOT a domain-named `pcn_disposition` type — Topaz types are contracts
  with the auth layer; a domain-named type writes the domain into the entitlement model, the hardest
  layer to walk back. (Historical note: this was first designed as a bespoke-but-generic `disposition_item`
  type; reading work's policy rails showed `task_audience` already covers it, so the reconciliation went
  one better than "invent the generic version once" — it **reused** the existing generic type and deleted
  the invention as a diff. The deeper rule: before inventing generic surface, check whether the existing
  generic surface already answers it — the entitlement plane especially must not grow a second decider.)
  (Second historical note, M3.1: the KEY was itself `pcn_disposition:<compartment>` until this rule was
  read back against its own example — a generic TYPE carrying a domain-named INSTANCE key is still the
  domain in the entitlement model, just one level down. Renamed to `disposition_review:<compartment>`.
  The task KIND string `pcn_disposition` deliberately survives: it is a cortex-ui render contract, not
  authz vocabulary, and it retires with `taskKindRegistry` in M3.3.)

Existing domain-named surface is NOT retroactively force-renamed (don't generalize from one example) —
it is sorted for the extraction milestone (`docs/plans/pcn-extraction-sort.md`): rename-and-promote /
plugin-residue / dissolve-to-data, acceptance = the deletion test (every `pcn_*.py` gone from the
engines, the process still runs via generic mechanism + plugin + data).

## Governing Architecture

A strictly decoupled, **Polyglot Microservice** architecture:

- **Cortex BFF (`iagent-cortex-bff`, port 8090)** — Synchronous gateway.
  Accepts user queries via `POST /orchestrate`, calls Engine O for intent
  routing, launches Dagster supervisor jobs, streams SSE back to the
  frontend.
- **Dagster Control Plane** — Ephemeral, lightweight pods. Uses
  `requests` (no `PipesK8sClient`). Per-query dynamic supervisor jobs
  fan out to engines selected by the predicate graph (ADR-0004).
- **Agent Fleet** — Multiple independent FastAPI pods, one per engine,
  each with its own isolated codebase and OCI image. Inter-service
  contracts are BAML-typed.

**Routing is predicate-graph driven (ADR-0004).** Engines self-register
their verbs into Weaviate at startup. The supervisor calls Engine O
`/search_predicates` per subtask to look up which engine handles which
verb, scoped to the caller's `entitled_domains` claim. The RDF ontology
is the *vocabulary layer* (subjects, concepts, verbs); Weaviate's
Predicate collection is the *router*.

**Tech stack constraints:** Dagster (orchestration), FastAPI (API
layer), BAML (contracts), Restate + smolagents (Engine A / DA / E / W),
LangGraph (Engine B), Swarms.ai (Engine C), dbt + DataHub (catalog),
Polars + CortexDataClient (data plane), Neo4j + Weaviate (graph +
semantic), Keycloak + Topaz (authn + authz).

## Project Overview

**Invincible Agent (iagent)** is a Dagster-orchestrated mesh that
dispatches work to Kubernetes agent pods via HTTP. Each engine
specializes: catalog search (D), knowledge retrieval (W), graph
queries (E), code-agent analysis (A), data-plane reads (DA),
synthesis (B), UI mapping (F).

## Repository Map

```
src/iagent/
  definitions.py            # Dagster entry point (auto-loads defs/)
  gateway.py                # Cortex BFF FastAPI app (port 8090)
  auth.py                   # Keycloak JWT verification + persona/domain claims
  defs/
    agent_routers.py        # Dagster @asset HTTP dispatchers
    data_layer.py           # @asset: dbt ↔ ontology ↔ DataHub sync
    dynamic_factory.py      # Dynamic BPMN factory (reads bpmn_catalog)
    dynamic_supervisor.py   # Per-query dynamic supervisor
agent_fleet/
  ontology_service/         # Engine O — port 8084
    main.py                 # FastAPI app
    iof_mro.ttl             # IOF/MIMOSA MRO ontology
  restate_analyst/          # Engine A — port 8081
    main.py                 # Restate + smolagents analyst
    orchestrator/discovery.py  # JIT tool binding via DataHub
  langgraph_support/        # Engine B — port 8082 (synthesis + memory)
  swarms_scraper/           # Engine C — port 8083
  datahub_wrapper/          # Engine D — port 8085
  data_analyst/             # Engine DA — port 8089
    service.py              # Restate handler
    main.py                 # FastAPI app
  neo4j_expert/             # Engine E — port 8086
  presentation_agent/       # Engine F — port 8087
  weaviate_expert/          # Engine W — port 8088
  utils/                    # mesh_registration, weaviate_utils
  core/                     # authz dependency, topaz client
  llm_utils.py              # Shared get_smolagent_model() + init_baml_client()
  models.py                 # SQLAlchemy ORM for bpmn_catalog
sql/
  create_bpmn_catalog.sql   # Schema + auto-update trigger
baml_shared/
  baml_src/contracts.baml   # SOURCE OF TRUTH for inter-service schemas
  baml_client/              # Auto-generated — DO NOT EDIT
baml_client_ts/             # Generated TypeScript client (frontend)
docs/
  adr/                      # Architecture decision records (0001..0013)
helm/invincible-agent/      # Helm chart deploying the full stack
scripts/
  seed_sandbox_predicates.py   # Seed Weaviate Predicate collection
  seed_weaviate_manuals.py     # Seed Engine W's DocumentChunk collection
  seed_datahub_catalog.py      # Seed DataHub catalog
tests/
  sandbox_e2e/              # End-to-end through cortex-bff /orchestrate
  test_*.py                 # Unit/mock pytest tests
pyproject.toml              # Orchestrator project config
```

## Workflow Rules

### Running the tests — the extra is not optional
`uv run --frozen --extra agent-fleet python -m pytest tests/ -q`

`rdflib`, `restate-sdk` and `smolagents` live in the **`agent-fleet` optional extra**, so a
plain `uv run --frozen` (or a bare system `python`/`py`) collects `test_review_starter`,
`test_restate_analyst` and friends as import errors. Those are **environment selection**,
not repo breakage — and reporting them as "pre-existing failures" is how a genuinely red
test hides in the noise. If a suite is red, first re-run it with the extra before
attributing the failure to anything.

### Seals need a REACHABILITY class — "does anything arrive here?" is a separate property
A seal proves the code under it behaves correctly **on the inputs it is given**. It says nothing
about whether those inputs can ever arrive. Every seal built against a constructed fixture
silently assumes reachability, and that assumption is invisible precisely because the tests are
green.

Completes the trilogy: **the seal must bite** (proven-to-bite), **the harness must be able to
report the bite** (harness-can-fail), and **the sealed code must be reachable by the inputs the
seal simulates**.

Three instances: the discard-pattern's dead `recall_override` branch; the svc:review-starter
witness that passed with its capability gate dark (so the gate was never exercised); and refusal
routing — 25 tests, mutation-proven, direction-pinned, and a **no-op on the path that motivated
it**, because the op returned early on zero parts one frame above the routing, and two of the
three content codes arrived on a wire shape the fixture never modelled.

Two rules fall out:
- **Verify-the-pipe is PER-BRANCH, not per-endpoint.** Reading one real response and generalizing
  to sibling codes is the same assumption one level out. Derive fixtures from the producer's real
  behaviour (e.g. the BFF's actual 422 set) rather than hand-writing one shape for all cases.
- **Ask "what produces this input, and can it?"** before trusting a green seal — and where the
  answer is a call-graph fact, assert it (a branch exists, a filing count is exactly N).

### Under a MUTABLE TAG a deploy is not an ACT — it is weather
Every believed-deployed check in this arc assumes deploys are things someone *does*. Under a
mutable image tag they are not: with `image: …/cortex-bff:latest` in the pod spec, an eviction, a
node drain, an OOM restart or a rescheduling pulls whatever `latest` now points at. **The running
code changes because the scheduler moved a pod, not because anyone rolled anything.** Nobody gets
a decision point, nothing appears in a deploy log, and the change is invisible until something
routes wrong.

The corollary that bites hardest: **a pod inspection is a statement about NOW, never about
tomorrow.** Confirming the live image builds the old key does not license a plan whose safety
depends on it still doing so an hour later — which is exactly the shape of a
migration's "dangerous interval" (see below). Found 2026-08-03 while sequencing the
`pcn_disposition:` → `disposition_review:` audience rename: the pod check correctly showed the old
code live, and the mutable tag meant the interval could still have opened *with nobody deploying*.

Two rules:
- **Rolled images pin a digest or an immutable tag.** `latest` is a build-side convenience and
  never reaches a cluster spec. Without this, expand/contract's "deploy step" has no defined
  moment, so its phases cannot be ordered against anything.
- **Where a plan's safety rests on which code is live, make the plan safe in EVERY ordering
  instead** — expand-first, dual-key, add-before-prune. A step that is safe regardless of what the
  scheduler does needs no inspection to stay true.

Inherited by every future migration on a live-synced identity surface — the employee-id rebind at
work, and each rename after it. See `feedback_grant_key_rename_needs_expand_contract`.

### Renames on live-synced identity surfaces run EXPAND/CONTRACT, never an edit
Third instance of the identity-key-transition class (VirtualObject keys at the M2 cutover; this
audience rename; the flip's employee-id migration ahead), so it gets the rule rather than a third
retelling. When a key spans a **pruning sync** and **deployed code that CONSTRUCTS it**, renaming
it is a two-phase migration: a lone sync deletes the relation the running image still builds, and
both single-sided orders break.

  EXPAND (both keys declared → sync) · DEPLOY · CONTRACT (drop old → sync)

The dual-key interval is **explicit in the deploy plan**, and the expand step is the one to run
first *because it is safe in every ordering* — adding a relation prunes nothing, so it closes the
interval if open and pre-positions the migration if not. When two readers disagree about the
current deployed state, run the safe step first and settle the disagreement after.

The tell for whether this class applies: is the key a **literal in code** (`f"{kind}:{domain}"`)
or a value read from data? Literal → expand/contract. Data → a sync suffices.

Guard shape, because the naive seal forbids the only safe ordering: a rename guard must permit the
old key **while the new one is declared alongside it AND a marker names the removal condition** —
old-key-ALONE stays red (that is the real regression), and the marker stops an expand phase
becoming permanent through amnesia.

**FOURTH STEP, learned the hard way 2026-08-04: CONTRACT MUST ALSO ACCOUNT FOR DURABLE ROWS ALREADY
CARRYING THE OLD KEY.** Expand/contract as written above migrates the *code path* and the *grant*. It
does nothing for **data already in flight** — and in-flight rows are exactly where a renamed identity
strands work. Observed immediately after the `pcn_disposition:` → `disposition_review:` contract: four
pending `grouped_review` rows and two `extraction_refusal` rows had been materialized with
`audience = pcn_disposition:SUSTAINMENT`. Because `resolve_task` **re-checks `can_act` against the
task's STORED audience**, and the contract had just pruned that relation, those tasks became
**visible but unactionable** — the reviewer sees them in her queue and every action is denied. No
error, no alert; the queue simply stops clearing.

So a contract phase asks a fourth question before it prunes: **what durable state already references
the old identity, and what re-reads it?** Three honest answers, and the plan must name one:
- **Migrate the rows** to the new key (a data migration, in the same window as the prune).
- **Drain first** — let in-flight work finish under the old key, then contract (the M2 cutover answer).
- **Make the names coincide by construction** so no in-flight state can disagree — the cheapest, when
  the identity is derived rather than literal.

Generalizes past authz keys to **every durable identity surface**: Restate promise names and
VirtualObject keys are journal state, so the same three options apply to them
([[feedback_grant_key_rename_needs_expand_contract]]). A suspended workflow whose new code awaits a
renamed promise can never be resolved by any submission — suspended forever, no error, the kill-seal's
failure mode wearing a promise's clothes.

### A hand-grant that clears an incident is a MITIGATION; the commit is the fix
Second instance 2026-08-05 (`procurement`, after `disposition_review:SUSTAINMENT` in M1), so it gets
the rule. When an incident is cleared by applying a relation **directly to the live directory**, the
work is not done — it is *inverted*. The system now looks healthy while the assertion that
reproduces that health exists nowhere, and the sync that owns the relation **prunes what git does
not assert**. The next routine sync therefore REVOKES the fix, silently, under a green
`+N relations, -1 revoked` line that reads like success.

The tell is the direction of the drift, and both directions are real — check for both:
- **live-but-not-git** → one sync run from revocation (the incident returns).
- **git-but-not-live** → already revoked, or never applied; the grant resolves to NOBODY *right now*
  while the file says otherwise.

Both were live in sandbox when this was written: `procurement` in the first state,
`promotion:DATA_ENGINEERING` and `access_grant:DATA_ENGINEERING` in the second. A file read alone
would have shown three healthy grants and missed all three faults, because **the file is the
assertion, not the observation** — you have to ask the directory.

Ordering is forced whenever a later change will run the sync: **commit the hand-grant BEFORE
running the sync for anything else**, or the unrelated change takes the incident fix down as
collateral.

### Coverage over the audiences that EXIST is not coverage over the audiences code can PRODUCE
The reachability class, in authz form. A probe that walks live rows can only see a queue something
has already routed to; a queue no one has picked yet has no rows, so an ungranted audience is
invisible until the first user reaches it — at which point the effect dies with the decision already
recorded as settled. Enumerate from **the code's declared map**, not from the data
(`_probe_disposition_audiences.py` imports `_DISPOSITION_QUEUE` rather than listing audiences).

Applying it found that notice A's second defect was one of THREE: `procurement` empty (the one that
bit), `sourcing` granted nowhere at all, and `procurement`'s own grant uncommitted. **The bug that
bit was the only one anything could see, and it was not the only one there.** Enumerate the
producer, then check each one it can emit.

### A caller may supply FACTS about itself; it may never supply the AUTHORITY computed from them
Third instance, so it gets the rule: the audience string, the compartment namespace, and now the
trust rung. **Facts cross the boundary; decisions don't.** Every field in a start-request payload is
therefore one of two things — a fact the server verifies, or an authority the server must refuse to
accept — and a payload that has never been sorted into those two piles has an unexamined confused
deputy in it.

The precedent states it exactly (`grouped_review_workflow._compartment_from_request`):

> *"if the trigger could hand over a whole audience string, a caller would be choosing who may act
> on its own review, which is laundering access through the process plane. Taking only the tail
> means a caller can influence WHICH compartment reviews it, never WHICH NAMESPACE decides."*

**The confused deputy hides in the WORDING of a plan, not just in code.** Phase 1.3 was packeted as
"the sensor decides which workflow to start" — written imagining the sensor as part of the trusted
mechanism. But the sensor's decision crosses an HTTP boundary (`POST /reviews`) and becomes a
client-supplied field, at which point *every* caller entitled to `mesh:startReview` inherits the
sensor's authority to choose its own supervision level. The enumeration caught it before it shipped;
the fix was to send `format_fingerprint` + `pipeline_version` as FACTS and compute `rung_for(...)`
server-side in `ReviewStarter`.

The residual question the split always leaves: **are the facts themselves verifiable?** A
caller-asserted fact that selects an authority is the same escalation one level down. Where it
cannot be verified yet, the backstop must be named along with its EXPIRY — 1.3's fingerprint is
unverifiable but harmless only while the dispatch capability is granted to nobody, so "close it
before the grant lands" became a written precondition of the ceremony rather than a follow-up.

### A policy artifact without a PRODUCTION READER is unshipped policy
Third instance, which is the filing threshold. The ratification test is behavioural:
**changing the artifact must change behaviour, witnessed, before any real decision rides on it.**

The three:
- **`trust_table.yaml`** — `rung_for()` is built, correct, and sealed, with zero production callers.
  The sensor hardcodes `trust_rung=DEFAULT_RUNG` and loads the table only for its HASH. Promoting a
  format today edits a YAML and changes a hash, and changes nothing else anywhere.
- **git-asserted grants absent from live Topaz** — the file says granted, the directory says no.
- **expired credentials still legible in suspended journals** — the record outlives its meaning.

Each is locally consistent and silent at the join, which is why none of them announce themselves.

The failure mode this rule exists to prevent is the worst of the three shapes: not a blocked
decision but **a decision that appears to succeed**. Ratify a promotion against an unread table and
the table reads `monitored`, the grant reads live, the pipeline stays `supervised`, and nothing
anywhere disagrees — a no-op wearing a governed decision's clothes, arriving from the direction
nobody watches.

So a governed artifact is not shipped when it validates, or when its resolver is sealed. It is
shipped when a CHANGE to it has been observed to move the system. Until then, treat every ceremony
that depends on it as blocked, however complete the surrounding engineering looks.

### A guard must assert a value the system CANNOT produce by default
Eleventh probe-correctness instance, and a new species: a guard whose asserted value coincides with
the default cannot distinguish **"the mechanism worked"** from **"the mechanism never ran."**

Found 2026-08-05 stamping doc-tools' version into `review.json`. The verify-the-pipe guard asserted
`"DOC_TOOLS_VERSION=doc-tools@"` appeared in the build workflow — a string the `ARG` line's OWN
DEFAULT (`ARG DOC_TOOLS_VERSION=doc-tools@unstamped`) satisfies. Deleting the build-args pass
entirely left the guard GREEN: the image would have shipped **permanently stamped `unstamped` while
the suite claimed the pipe was verified.**

This completes a family with the tautological guard and the uniform-zero probe. All three are
instruments whose PASSING STATE IS REACHABLE WITHOUT THE MECHANISM UNDER TEST EXISTING — which is
why none of them can be found by reading the assertion and agreeing with it.

**The operational test: assert the NON-default, or inject a sentinel the default cannot collide
with.** Here the fix was pinning `${{ github.sha }}` interpolation, which only the real pass
contains.

And note the discovery mode, because it is the only one that works: break-on-purpose found it by
breaking the pipe and the guard NOT turning red. A guard's green surviving its mechanism's death is
exactly what break-on-purpose exists to surface.

### A proof's HARNESS must assert presence — detection by absence is the weakest signal
Twelfth probe-correctness instance, and the one that diagnoses the family rather than adding to it.

Break-on-purpose is how a guard is trusted. But the break-proof is itself a mechanism, and it can
fail the same way the guard can. Observed 2026-08-05, proving a validator refused a sentinel-keyed
promotion: the proof appended a second `formats:` key (**YAML silently deduplicates**, so the
fixture asserted nothing) and read `tail`'s exit code instead of Python's through a pipeline
(`cmd | tail; echo $?`). It reported success while testing nothing.

**The only tell was a line of expected output that did not appear.** Nothing went red. Detection by
absence is the weakest signal available — it depends on the reader remembering what should have been
there.

So: **a proof asserts a POSITIVE ARTIFACT of the mechanism firing, never a status code alone.** Not
*"the run exited non-zero"* but *"the run exited non-zero AND the output names the rule I
disabled."* Seals already do this (the break-on-purpose message check); this extends the same
discipline to the harnesses that verify seals. Status codes are exactly where a pipeline lets `tail`
answer for the program.

**AND THE HARD PART, which is why this is filed as a construction rule rather than a lesson:** this
defect was written by the same author who had filed the parent rule an hour earlier, in the commit
enforcing it. **Knowing the rule does not prevent writing the defect** — the defect is invisible at
write time by its nature: the proof looks right, runs green, and reads as evidence. So the class is
not addressed by learning; it is addressed PER INSTANCE, by a guard, every time. That is what the
guards are for, and it is why "we know about this one" is never a reason to skip one.

### Every hop that REBUILDS a payload is a field-dropping surface
Third instance, so it gets the rule. Any field a downstream tripwire or derive depends on gets a
pin at EVERY hop between producer and consumer — not only at the ends.

The three seams: **sensor→BFF**, **BFF→starter**, and **plugin→writer**. The first two are not
hypothetical — a hand-enumerating `/reviews` handler ate `review_state_source` and
`extraction_warnings`, and the downstream tripwire then did its job perfectly against a field the
middle hop had silently removed, refusing every honest request for days.

A wholesale copy (`dict(aug0.review)`) survives new fields BY CONSTRUCTION and is the right shape —
but wholesale copies decay into hand-enumerated dicts under refactoring pressure, and that decay is
silent. Pin the shape, so the decay is red.

The tell for where to look: any place a payload is REBUILT rather than forwarded — a Pydantic model
re-enumerated into a body, a dict comprehension, a hand-written literal. Forwarding preserves;
rebuilding is where fields go to die.

### An instrument must not share FATE with the event it measures
A witness that dies with the subject reports the subject's death as health. Tenth probe-correctness
instance and a distinct species: not wrong about timing, scope, anchor or fixture — wrong about
**survival**.

Measured 2026-08-05 building Engine D's replay seal. The obvious manufacture was killing the pod
mid-handler; Restate retried (a handler killed at t=5s returned 200 after 30.6s), but the trace
showed **ONE span for TWO executions** because the killed pod's OTel batch exporter never flushed.
It undercounts in exactly the scenario it exists to measure, silently, **in the direction that reads
as success** — had the fix already been in, that identical reading would have been indistinguishable
from working. A false-green built into the METHOD rather than the code.

The repair is the pattern: **manufacture the failure AFTER the work but WITHOUT killing the
observer** — fail the handler, don't kill the pod. Every counter (stdout, exporter, journal)
survives to report honestly, and it is deterministic instead of racing a 12–42s LLM window, so the
seal is repeatable rather than lucky.

Note the backward connection, because it stops this from over-generalising: Engines A and E's replay
witnesses DID use pod kills and were valid — their instrument was the inner span count, which
journals through **Restate**, not through the dying exporter. So the operational half is a question,
not a ban: **before trusting any kill-based witness, ask which side of the kill the instrument's
persistence lives on.**

**AMENDMENT (2026-08-05, telemetry thread — the above is half right and the wrong half matters).**
Checked against the source rather than inherited: `mem0_context_retrieval` is a `@safe_observe` OTel
span (`restate_analyst/main.py:632`) created INSIDE the `run-smolagent` `ctx.run` body (`:1290`).
Restate journals that step's RETURN VALUE, not its spans — the inner span count reaches Langfuse
through the same batch exporter that dies with the pod. It survived A's kill by TIMING (the span had
ended, so it had already flushed), not by structure. Applying the rule's own question to it: the
instrument's persistence lived on the DYING side.

The consequence is sharper than the exoneration, and it lands on this arc's own work. Under the
UNFIXED code the killed attempt's boundary span never ENDS (the pod dies mid-work), so it never
exports — a kill-based reading returns `boundary=1` whether or not the fix is present. **A and E's
"after" leg cannot discriminate fixed from unfixed.** Their before-picture (`4d66e2903df6`,
`analyst=2`) came from an ORGANIC replay with no kill, where both spans flushed — so the pair that
was reported as "same instrument both times" matched the COUNTING tool while differing in the REPLAY
MECHANISM, and the mechanism is what decides whether evidence survives.

What still holds, stated exactly: the fix's mechanism is proven HERMETICALLY by
`tests/test_replay_safe_boundary.py`, which re-enters the boundary twice against an in-memory
exporter and asserts zero boundary exports — not subject to flush loss. The organic before-trace
proves the defect was real. The live after-trace proves the DEPLOYED code emits one boundary and
(via `mem0=2`, which can only overcount from real executions) that a replay occurred. What is
missing is a same-mechanism before/after pair. **Ledger item: re-run A and E's witnesses with the
fail-not-kill seal D now has.** Filed rather than quietly repaired, because a witness whose weakness
is known and recorded is worth more than one silently re-run.

The general form this adds: **an instrument that survived is not the same claim as an instrument
that could not have died.** A and E's inner-span count survived; it was never structurally safe. Ask
which, because only the second is a method.

### A journaled step's contract is its RETURN VALUE — side effects do not replay
The memoization mirror of the time-machine rule: a journal replays what was **returned**, not what
was **done**. `ctx.run` memoizes the return value and does not re-execute the body, so anything the
replay path needs must ride the return.

This is a defect class the durability pattern ITSELF creates, which is why it needs its own line.
Found in Engine D before the wrap landed: `sources_collected`, `access_denials` and the fumble
metric were all produced as side effects INSIDE the agent loop and read AFTER it. Wrapping the loop
naively would have returned the right answer with an **empty provenance trail**, and an empty
`access_denials` turns a genuine 403 into a reported success — the durability fix minting a **silent
authz-visibility regression**.

Repair: the step returns its outputs; the caller re-hydrates from the return value, never from the
closure. Check it by asking of every name read after a `ctx.run`: *was this written inside it?* If
yes, it must come back through the return or it is empty on replay.

Scales with the ambient state the body mutates — an agent loop mutates far more than a handler, so
Engine A's eventual idempotency work meets this class at much larger surface area
(`docs/plans/agent-loop-effect-idempotency-engine-a.md`).

### A fixture that collapses two roles into one identity cannot witness which role did what
The tautological-guard class in provenance clothing, and the reason the approver misattribution
survived so long: the seal's fixture passed ONE identity as both the review's initiator and its
approver, so every who-did-what assertion passed BY CONSTRUCTION — there was nothing for the code to
confuse. The guard could not fail, so its green was a claim about the fixture.

**The defect was invisible in tests for the same reason it was invisible in production:** nothing
distinguished the roles ANYWHERE. Production is a SERVICE starting the review and a HUMAN approving
it; the fixture said "alice" twice.

The repair is the two-independent-sources construction from the promise-name seal: give each role a
DISTINCT value and assert they stay **different**. Then a future merge of the fields fails loudly
instead of silently. Applies to every pair a system keeps deliberately separate — initiator vs
actor, requester vs approver, subject vs caller, proposed vs ratified.

### A seal pinned to an INTERIM state becomes a brake on its own fix
Corollary of "a test asserting the wrong claim is worse than a missing test", and it bit twice in
one arc on the same assertion, in opposite directions. v1 asserted the row NAMES the approver — red
against a system that could not yet satisfy it. v2 asserted the row must NOT say `approved_by` —
correct for the interim label-truthfully repair, and WRONG the instant the real fix landed, going
red against a row that was finally right.

When a repair is explicitly interim, its seal must assert the **end state's invariant**, not the
interim shape. Where the interim genuinely needs pinning, say so IN the assertion message so the
next person reads "this is scaffolding" rather than "this is the contract" — otherwise the seal
quietly acquires standing it was never granted, and the fix arrives looking like a regression.

### A test that supplies its own provenance will agree with itself
A seal that PASSES IN the value it later asserts has tested its own fixture. Every offline test of
the effect-failure row handed the driver a `requested_by` and then checked the row carried it — all
green, all meaningless, because the question was never "does the value survive" but "is the value
the system actually has the RIGHT one". The first live drive answered it in one row: the field held
`svc:review-starter` (whoever STARTED the review) while the approving human sat in `acted_by` one
row away. The row said a service had approved a human's decision.

Generalises past provenance to every value a test injects and then asserts: identity, timestamps,
audience, compartment. The test proves TRANSPORT; it cannot prove SOURCING. Ask separately where
the production value comes from, and get that from the running system — the composed-path seal
applied to a field rather than to a call chain.

Corollary, from the same hour: **a test asserting the wrong claim is worse than a missing test.**
That live leg went RED against a system that could not possibly have satisfied it, and the correct
fix was to the SEAL, not the code. A red you cannot satisfy is a red that will eventually be
"fixed" by weakening something that was right.

### A guard that has never failed has not been shown to guard anything
Distinct from "verification must be able to fail", which is about a check with no failing path at
all. This is narrower and nastier: a guard with a perfectly good failing path, aimed slightly wrong,
that has therefore never fired. `assert "user_jwt" not in payload` inspected only the OUTERMOST
dict. Reintroducing the credential where it would REALLY go — nested inside `human_task`, the
sub-dict the request body is built from — left the guard green with a live token riding a durable
journal payload. Two independent suites carried the same blind assertion.

The technique that finds it is break-on-purpose, and the tell is the SHAPE of the break: reintroduce
the defect the way the CODE would reintroduce it, not the way the guard expects to see it. If the
guard stays green, you have found a defect in the guard — which is more valuable than the green was.
Then widen from the one field that bit to the CLASS (a family of credential-shaped names, walked
recursively), because guarding the instance is what left the hole.

### Build the fixture as a SUPERSET of reality, not an approximation of it
Where the real input cannot enter the repo (restricted boundary) or does not exist yet, build the
fixture **deliberately as degraded as the contract permits**, so any real input is a SUBSET of it.
That inverts the usual fixture relationship: instead of the test approximating reality, reality is
guaranteed to be easier than the test, and the code meets nothing new when the real thing arrives.
It is a coverage argument BY CONSTRUCTION rather than by enumeration — you do not have to have
seen the real input to have covered it.

Applies wherever the input is unavailable rather than merely inconvenient: restricted sources,
vendor formats you cannot obtain, failure modes a healthy pipeline no longer produces. Pair it
with a guard that asserts the fixture still EVOKES what it claims
(`tests/fixtures/failure_path/`), or a later tidy-up quietly turns the superset back into a
sample.

### A query that has never returned a row is a query nobody has tested
Ship every acceptance/diagnostic query with something for it to FIND — a deliberate disagreeing
pair, a planted stale record. A query that has only ever returned empty is indistinguishable from
one that is silently broken (wrong graph, wrong predicate, a FILTER that excludes everything), and
the first time it matters is exactly when you need to trust it. Reachability applied to queries:
the mechanism must be witnessed returning a row before an empty result means anything.

### A rejection must be STRUCTURAL, or it only held once
When a review rejects something — a citation, a status, a grant — remove it from the
**enforcement layer**, not just the artifact. Killing a wrong citation in the file while leaving
its target in the seal's verified set locks the door and leaves the key in it: the next author
re-cites it, the seal passes it as previously-verified, and the ruling silently reverses.

Removing it from the verified set converts the ruling from an EDIT into an ENFORCEMENT —
re-citation now fails loudly, and reversing the decision requires re-adding it visibly, which is
a diff a reviewer sees. That is where a reversal belongs. Same shape as revocation-by-removal in
the rails: **absence from the authoritative set is a first-class, enforced state.**

The clause: *ratification outcomes live in the enforcement layer, not just the artifact — a WRONG
updates the seal's world, or it is advisory.*

### Negative assertions over source must be scoped to the SYNTACTIC FORM they forbid
`assert "X" not in source` bans the string, which includes **the prose explaining why X is
banned**. Three instances: `"prime" not in fn.lower()` matching the docstring that said "NEVER
prime"; a byte-window standing in for a content check; and — the perfect form —
`"BreakdownElementRevision" not in _TTL` failing on the comment that documented its removal. The
assertion failed on the explanation of why the assertion should pass.

Scope to the form: `"mesh:derivedFrom s3kl:BreakdownElementRevision"`, not the bare name.

**And seal the explanation's SURVIVAL.** An empty-and-labelled slot whose label gets tidied away
regresses to a bare empty, which regresses to "someone forgot" — the exact ambiguity the label
existed to kill. The record of why something is absent is sealed CONTENT, not commentary, so
something must bite if it leaves.

### A probe must demonstrate it can SEE the category of thing it is checking for
Six instances now, and this is the rule's final form. A probe that returns zero because it was
looking in the wrong place — or at the wrong KIND of thing — is indistinguishable from a probe
that correctly found nothing, and the two states it exists to separate are exactly the two it
cannot.

The instances: `helm template -s` selecting nothing; a `--with` overlay supplying a dep the
image lacked; a mutation test invoking a `python` that did not exist; `pytest` silently skipping
9 of 12; a `grep` against a container path that did not exist (the image flattens directories);
and an S3000L coverage query that asked only for owl:Class and reported `quantity: 0` when
`quantityOfChildElement` is a PROPERTY — which would have been written up as a standards gap.

**Seventh, and the one that shows how the class survives verification: a grep for `@sensor`
DECORATORS cannot see FACTORY-CONSTRUCTED sensors.** 2026-08-03, the question was whether an
unattended ingest path existed. A decorator grep found only two sensors and concluded "no ontology
sensor exists" — while `ontology_sensor` was defined as an `S3SensorComponent(...)` instance in
`doc_tools/definitions.py` and was `RUNNING` in the deployed Dagster instance the whole time.
Dagster sensors are built BOTH ways; the probe asked for one shape and reported on the category.

The part worth keeping: a second search was run against the deployed pod to confirm it, and the
pod search **used the same decorator pattern** — so it agreed, and the agreement was read as
corroboration. **Two independent-looking verifications with one shared flaw are one verification
wearing two coats.** Independence is a property of the METHOD, not of the number of times you run
it or the number of places you run it against. When a second check confirms the first, ask what
assumption they share before counting it as evidence — and if the answer is "the same query
shape", it is not a second check. The thing that finally settled it was asking the RUNTIME what it
had (`DagsterInstance.all_instigator_state()`), which cannot be fooled by how a sensor was
declared.

**So: locate before you grep, list before you count, and ask for every category the answer could
live in.** The general statement, of which "prove the harness can fail" is the test-shaped case:
**every verification needs a demonstration that it can return the other answer.** And its social
form: **a conclusion that travels by repetition rather than by evidence gets re-derived, not
inherited** — chat-borne claims have no verification gate, so any claim important enough to cross
a session or a handoff crosses as a checkable statement WITH its evidence, or not at all.

### A RED result lies more dangerously than a green one, because nobody attacks it
This arc's whole discipline aims at greens that lie. 2026-08-04 produced the mirror: a probe
reported **RED on a healthy system**. It read the reviewer's queue immediately after `start_review`
returned — but the grouped task registers INSIDE the workflow, so the response races the row
materialising. The probe sampled the gap and reported failure.

**The asymmetry is the point.** A false green gets hunted here by habit. A false red gets *believed*,
because it confirms the caution everyone already feels — so nobody attacks it, and the plausible
next move was rolling back a correct migration. A wrong red costs you the fix; a wrong green costs
you the bug. Both are wrong; only one has a standing immune response.

**So: probes get the same verification discipline as the system they probe. A probe that reports RED
must be shown to report GREEN under a known-good condition before its RED is acted on.** The positive
control is not only for absence-checks (the Fuseki `s3kl:` 4180 control); it is for **every assertion
whose failure would trigger a revert**. And note the specific mechanism here — **a probe's TIMING is
part of its correctness**: an assertion that samples asynchronous state must either wait for the
state it asserts on or assert on something synchronous with the call it made.

### A ruling that asserts a string identity gets EVALUATED, not read
Sibling of the false-RED rule above, and the same root: believing an assertion because of who
produced it. 2026-08-04's promise-name ruling stated that `approval_{step.id}` and the handler's
`decision` promise are "the same string by construction, since the grouped step's `id` IS
`decision`." Evaluate it: `f"approval_{step.id}"` with `step.id = "decision"` is `approval_decision`.
The `approval_` literal lives in the EXECUTOR, so no assignment to definition content can delete it.
The ruling asserted an equality between two expressions and checked neither, and as written it
produced the exact silent-suspension failure it was authored to prevent.

Second instance this arc — the first was the M3.1 verb registrations, also caught by reading the
source instead of executing the recipe.

**So: an architect's ruling that asserts two names, keys, or paths are equal is a CLAIM, not a
premise. Evaluate the expressions on both sides against the source before building on it.** The
verification discipline applies to a ruling's sentences exactly as much as to green test output —
a ruling is the highest-authority unverified assertion in the system, which is precisely why it
gets attacked rather than deferred to. Where the identity matters, prefer making it DECLARED
(explicit content the author controls) over ENGINEERED (a coincidence arranged through naming),
and seal it with an equality guard: a construction you have to reason about is one a future rename
can silently break.

### The projection and the journal are TWO SURFACES OF ONE STATE — settle both, or record why not
Found 2026-08-04 by joining them for the first time. M3.1 "expired" four stranded grouped reviews by
UPDATEing projection rows; the durable Restate workflows kept waiting. Each surface was internally
consistent — rows said settled, journals said suspended — and the disagreement was invisible from
either side alone. Five instances were simultaneously **unresolvable** (audience pruned, so no human
could act) and **invisible** (rows said expired, so nothing surfaced them).

**Rule: any settlement on dual-surface state settles BOTH surfaces in the same operation, or records
why not.** "Expire" was implemented as a row update when it needed to be a row update PLUS a
cancellation.

**The mechanism, identified — not merely the symptom.** The projection is maintained by the BFF layer:
cortex-bff's `/human_tasks/{id}/act` resolves the row AND calls the workflow handler. So **every path
that touches Restate directly — admin API, seals, migration scripts, future tooling — is a divergence
source BY CONSTRUCTION and owes a join check after use.** Proven deliberately: calling
`submit_decision` straight at the ingress during the M3.2 seals reproduced the divergence in seconds
(Restate `completed`, projection `pending`). That makes the owed cross-surface probe's positive
condition sharp — *any settlement that did not transit `/act`* — rather than "compare on a schedule".

### Code renames orphan JOURNALS, not just keys
The M2 review predicted the rename would strand in-flight state and named VirtualObject dedup keys as
the surface. The actual casualty was one layer up: **workflow journals whose replayed code paths no
longer match the deployed code.** Restate cannot make progress on those and retries forever — and
`cancel` itself FAILS, because cancellation requires resuming the invocation to unwind it. Three
instances carried `[570 journal mismatch]` and one `[404 service unregistered]`; all four needed
`kill` after `cancel` provably failed at 8 retries. The date boundary was exact: everything created
on or after the rename cancelled cleanly.

**So: a rename or refactor of workflow code orphans every in-flight journal whose shape it changes,
and those orphans are INVISIBLE until a join or a cancellation attempt touches them.** Drain before
cutover, and try `cancel` FIRST — its documented failure is the evidence that licenses `kill`.

### A ruling made in CONVERSATION is UNSHIPPED until it is committed
Second instance, and the mirror image of the first. In the §391 case the DOC carried a ruling the
conversation had already invalidated. In the M3.2 shipping case the CONVERSATION carried a ruling the
doc never received — image-baked definitions, decided with three reasons and a rider, present nowhere a
future window could reach. The build re-raised it as an open question, which is not a lapse: it is the
proof. A window holding the whole repo and no transcript cannot execute a decision that exists only in
chat.

**So: the transcript is where a decision is BORN; the repo is where it LIVES. A ruling is unshipped
until it is committed — to the packet, the ADR, or these conventions — with its reasons attached.** The
corollary binds the citer too: **a claim that something "was already decided" is INPUT requiring
validation, not a premise, including when it comes from the architect.** If it cannot be sourced to a
commit or to the transcript in hand, it does not get recorded as RULED on the citer's say-so — an
unsourceable "RULED" is the §391 failure with the evidence deleted, and it costs a future window
executing a decision it cannot audit. Re-raising a settled question costs one round trip; the asymmetry
is not close.

When a conversational ruling IS confirmed, record it with its origin stated exactly — ruled in-session
on DATE, and whether it PRECEDED or POSTDATED the work that needed it. "Decided" and "decided in time"
are different facts, and the second is what tells the next window whether the process worked.

### A probe's OUTPUT is part of its claim — truncated, sampled or windowed output gets labeled in the line that reports it
Third probe-correctness catch in the M3.2 build session, and three is where this arc files a rule. The
other two: an assertion that sampled asynchronous state and reported RED on a healthy system (timing),
and a gate stub patched onto the wrong module object so a DENY arm passed while the stub was never
consulted (tautology — the ALLOW arm exposed it). This one: a full-suite run piped through
`Select-Object -Last 14` reported `42 failed` above a list of 13 names. Nothing was wrong with the
test run; the WINDOW was narrower than the measurement, and a partial list carries the shape of a
complete one. Twenty-nine failures were invisible with no marker saying so.

**So: a probe that truncates, samples, paginates, or windows its output must SAY SO in the same line
that reports the result — `42 failed (showing 13)`, never `42 failed` over 13 rows.** The failure is
not the truncation, which is often necessary; it is a result presented at a completeness it does not
have. This is the reporting-side sibling of the RED rule above: there the probe's timing was part of
its correctness, here its output window is.

Corollary for comparison runs (base-vs-HEAD, before-vs-after): **classify environment-dependent tests
BEFORE the comparison and exclude them from the verdict by name, or run them twice per arm.** Live-service
and provider-env tests can lie in BOTH directions across two runs minutes apart — a flake that fails at
base and passes at HEAD reads as "you fixed it"; the reverse reads as "you broke it". A verdict over the
stable set with the exclusions named beats a wider verdict containing coin flips.

### A stored authz value re-checked at action time is a MIGRATION SURFACE that does not look like one
Broader than the identity-key rule, and it is what actually bit the M3.1 rename. `audience` is a
**denormalized authz value copied onto a durable row and RE-EVALUATED later** (`resolve_task`
re-checks `can_act` against the task's STORED audience). Rename or revoke the audience and every row
already carrying the old value is stranded.

**The failure mode is SILENCE, not an error.** Deny-by-default plus a stale stored value produces a
*correct denial*, so the loud-fail machinery never fires — and **a queue that has stopped clearing is
indistinguishable from a queue nobody is working.** Six rows sat that way for an hour and were found
by driving a live notice, not by anything automated.

Generalise past keys: **any value copied onto durable state and later re-evaluated against live
vocabulary is a migration surface, even when it is not an identity key and does not look like one.**
Keys announce themselves; stored-and-rechecked values do not — which is how this got past a plan
written by people who had just generalised the key rule.

Standing assertion rather than another instruction:
`tests/sandbox_e2e/_probe_orphaned_audiences.py` — live task rows whose stored audience grants
NOBODY. It carries its own positive control (if NOTHING resolves, that is a broken resolver, not a
universe of revoked audiences — it returns INCONCLUSIVE rather than a confident RED, per the rule
above). It found a second, unrelated orphan on its first run.

### SERIAL FAILURES MASK — after a fix, re-verify the whole path, not just past the repaired step
A failure early in a chain hides every failure after it. Fix the first and the second appears — not
as a regression, but as something that was always there and unreachable. 2026-08-04: an expired
credential killed a dispatch at the task-register step; repairing it revealed that the target
audience (`procurement`) had **never been granted** and resolved to `[]`, so that dispatch would have
died one step later anyway. Nothing could have found the second defect while the first was in the way.

**So a fix's definition of done includes walking the REMAINING path's preconditions before executing
it** — read the state the next step depends on, rather than running the step to discover it. This is
the false-RED rule applied *prospectively*: **do not manufacture a red you can already see.** Where
the execution consumes a finite identity (an idempotency key, a single-use workflow key, a one-shot
token), the economics are explicit — spending one to witness a predictable failure spends evidence on
a fact already in hand, and buys a cleanup afterwards.

### A guard's ANCHOR is part of its claim — source-anchored guards fire on refactors, not regressions
Sixth in the probe-correctness set. A guard anchored to **where code lives** fires when code MOVES; a
guard anchored to **what code does** fires when behaviour BREAKS. The failure mode is that the two are
**indistinguishable at alarm time** — so every legitimate refactor is taxed with a false-positive
investigation, and a real regression hiding among them reads as "probably just the move again."

Found 2026-08-04: `test_review_identity_from_artifact` asserted a source STRING inside
`grouped_review_workflow.py`. M3.2's delegation moved that construction to `main.py`; the guard went
red on a correct change while the PROPERTY it defends (task identity derived FROM the workflow key,
never recomputed beside it) was never violated.

- **Prefer behaviour-anchoring wherever it is possible** — assert what the code produces, not where
  it is written.
- **Where source-anchoring is genuinely required** — deletion seals, the de-pcn mechanism scan, the
  seed-script scan — the **anchor list is maintenance-bearing**, and "does this move touch a guard's
  anchors?" belongs in the mover's definition of done. An anchor list is a dependency nobody declares
  unless it is written down as one.

### A status field asserts what its author WITNESSED — intent-only statuses get renamed
`ctx.object_send` is fire-and-forget by construction: the caller **cannot** know delivery. So a
workflow returning `{"status": "DISPATCHED", "count": 2}` is reporting journaled INTENT wearing an
effect's name. Demonstrated 2026-08-04, and the counterexample is unarguable: notice A returned
`DISPATCHED` for two dispatches that both **failed 160ms later**. Honest form is `RESOLVED` +
`dispatch_enqueued: N`; a stronger claim requires awaiting outcomes, which is a design change, not a
wording choice. Same class as the M2 upload reporting `[OK]` per file while every ingest failed on a
metadata bug. **Either the status names what was observed, or it is never cited as proof.**

### Seals resolve at MACHINE latency; some defects only exist at HUMAN latency
A grouped review is designed to suspend for hours or days. Anything captured at suspend-time and
used at resume-time (credentials above all) is therefore *routinely* stale in production and
*never* stale under test — because every automated witness resolves in minutes. The suite is
**structurally** incapable of finding that class: a defect whose trigger is ELAPSED TIME cannot be
caught by witnesses that never elapse. Notice A's expired-JWT dispatch failure is instance one, and
it survived a 12-seal M3.2 suite that passed green.

**Closure is the kill-seal move: manufacture the condition, don't wait for it.** Inject a
deliberately expired or near-expiry token and resolve the review with it — turning ninety minutes of
wall clock into a fixture. Generalise: for any suspend/resume mechanism, ask *what expires while we
are suspended?* and seal it by injection.

Corollary that caused the bug: a token threaded from the human's action into POST-decision machinery
is carrying two facts at once — **provenance** (who approved) and **authorization to execute
effects** (the pipeline's own entitlement). Those separate. Provenance belongs in the decision
record; effects run under the acting identity, minted AT USE.

**AND THE SHARPER FORM, which is the one to quote when citing this rule: A DURABLE JOURNAL IS A TIME
MACHINE.** The defect is not that a credential *went stale* — that framing makes lifetime the
variable and invites the wrong fix (tune the TTL). The defect is that a credential was **placed in a
replay medium**. A Restate `object_send` body is durable journal state and the object RETRIES, so
anything put there will be **re-presented at arbitrary future moments** — after expiry, after
rotation, after the grant that authorized it was revoked. No lifetime survives that; only *not
storing it* does. So mint-at-use is not the better of two options, it is **the only shape that
survives the medium**, and the standing guard is the one asserting the field cannot come back
(`tests/test_dispatch_driver.py`: no `user_jwt` on any journaled payload).

Generalises past credentials: **anything whose meaning is time-bound — a token, a signed URL, a
freshness verdict, a "currently entitled" answer — must not be written into durable journal or
event state.** Store the INPUTS needed to re-derive it, and re-derive at use.

### Provenance comes from PROVENANCE-BEARING fields — never inferred from CLASSIFICATION fields
Third instance in two days, and the sharpest form of the naming rule. `kind` says what a row IS;
`subject_ref` says where it CAME FROM. The M3.1 stranded-row split read `kind` — migrating two
`extraction_refusal` rows as "real refusals with provenance" while expiring four `grouped_review`
rows as residue. Both sets were residue. The rows' own `subject_ref` said so
(`sustainment/inbound/witness_summon/…`, `witness_norender/…`) and was never read. **The split ran
on the wrong axis.**

The sibling instances, same fortnight: a ruling that read plausibly and evaluated false; a
screenshot classification ("real inbound traffic") asserted from names and disproved on inspection.
**A thing's dependency class — test vs live, fixture vs work — is established by INSPECTION, never
by what it is called or what type it is.**

And the trap has a second floor, found the same day: the convention that was supposed to carry
provenance **did not even cover the artifact in question.** `witness_*` marked three fixture
directories — but the one whose provenance was actually disputed, `Diodes_PCN_2683_FULLGREEN.pdf`,
sat at `inbound/generated/` with no marker at all, and its projection row carried
`subject_ref: NULL`. Classification fell back to name-inference precisely because the
provenance-bearing field was empty. **A path convention is unenforced AND usually incomplete; the
case it misses is the case you will argue about.**

The settled form: **provenance is a DECLARED, REQUIRED field — an enumerated origin
(`live` | `witness` | `synthetic`) populated at the front door and REFUSED when absent** — not a
directory-name convention that humans read and nothing validates. Same shape as the audience
binding: a string that means something must be made to prove it. Filed on the owed-engineering
ledger; sibling to the cross-surface probe (one detects state that bypassed the settlement path,
the other declares state that bypassed the provenance convention).

### Provenance is a field, never a join
**No assertion enters a graph without its provenance riding in the same write.** A sidecar audit
table you *could* join against always decays, because the join is OPTIONAL and optional joins stop
happening — the query that omits it is shorter, works, and becomes the one everyone copies.
Embedded provenance cannot be skipped: reading the claim IS reading its origin.

The doctrine line: **the claim that cannot say where it came from doesn't get written.** Enforced,
not documented — `src/iagent/provenance.py` refuses an incomplete block at WRITE
(`validate_ruleset` discipline applied to instance data). Block: `authoritative_source` (who owns
the truth — the same value for every path to it), `obtained_via` (the degradation path),
`as_of` (**`unknown` is a sentinel, never a blank**), `ingested_at`, `ingest_run` (chains claim →
run → sensor → source object → ETag), `standing` (the source's rung FROZEN at write time, because
"standing now" is a different fact from "standing then").

This was decided piecemeal five times before it was named — `ruleset_ref`, `resolved_via`,
`requested_by`, decision records' inputs-not-verdicts, and source lineage. See ADR-0035 §4.

### Sentinels over empties, for immutable evidence
An empty string collapses "we could not know" into "we forgot to record". For data that is written
once and read forever, that collapse is unrecoverable and poisons the corpus's own audit — an
analyst counting gaps cannot tell instrument failure from process fact. Use a DECLARED sentinel:
`as_of: "unknown"`, `ruleset_ref: "none:no-composition"`, `trust@unavailable`. Sibling of
inputs-not-verdicts: both refuse to let a record be silent about its own limits.

### A field's seal lives at its point of CONSUMPTION, not its construction
`era` was added to the decision-record schema, sealed at the builder, and green — while it reached
neither the writer payload nor the store, so "exclude commissioning records" filtered nothing. The
builder tests were **true and useless**: they asserted the field existed where it was built and
nothing asserted it survived to where it filters. Fifth instance of the payload-drop class.

Generalizes the reachability rule to the query side, and shares a parent with per-branch
wire-shape verification: **assert a field where it is USED.** Corollary for temporal data —
**absence maps to the older, less-trusted state, never the more-trusted one** (a record with no
`era` counts as commissioning), which is deny-by-default for time.

### Two escapers are two chances to disagree about what a quote means
The single-decider rule applied to string semantics. When a repo already has an escaper, a
serializer, or an identity derivation, USE IT — a second one is not duplication of code, it is
duplication of *meaning*, and the two will disagree exactly once, in production. Caught mid-write
on the decision-record writer (a second SPARQL escaper) and in the review identity (`task_key`
re-deriving what `ctx.key()` already knew).

### The error path is itself an error surface — a reporter must fail louder than what it reports
**A channel that reports failures must fail LOUDER than the failures it reports.** Every
link in an error path — the notification POST, the token mint, the task registration, the
audience resolution — can itself fail, and swallowing any of them hides the original
problem behind a **green** run: strictly worse than the loud-but-misaddressed state you
were fixing.

Applied: the extraction→review sensor's triage POST raises on 403 / 422 / timeout, so a
missing capability grant degrades refusals to the old bad behaviour LOUDLY instead of to
silence; `mint_service_token` raises rather than quietly starting no reviews. The
consequence to internalize is that such a grant is **load-bearing for VISIBILITY, not just
permission** — unseeded, it silently reverts the fix, so it ships in the same window as
the code that depends on it.

Test it directly: enumerate every way the reporting call can fail and assert each RAISES
(`tests/test_refusal_routing.py::test_triage_routing_failure_fails_the_run`). Sibling of
the fail-to-NONE rule — a heuristic that can refuse degrades to no-check, never to a
confident wrong answer; a reporter that can fail degrades to a loud failure, never to a
quiet success.

### When routing by audience, seal the DEFAULT DIRECTION, not just the mapping
When work is routed by category (content→owner, systemic→ops), the membership list is the
easy part; the **default for unrecognized input** is the load-bearing decision, because
both directions "work" on every case in today's fixtures. Route unknown to the LOUD side:
filing a per-item task asserts "look at this item", which is a false statement when the
truth is "the system is broken". Keep the routed set a CLOSED allow-list, and pin the
direction with a test that feeds it invented categories.

### When adding an S3-watching Dagster sensor — use the shared cursor contract
Do NOT hand-roll "what have I seen". `dag-tools`' `S3SensorComponent`
(`dag_tools/components/s3_sensor/`) is the reference implementation; use it directly
where the repo can depend on it (doc-tools does), and match its SEMANTICS where it
cannot (invincible-agent's `extraction_review_sensor`, which has no dag_tools dep and
no Dagster components system — see its docstring for the two upstream changes adopting
the component would need). Two properties, both non-negotiable:

1. **Cursor = arrival time (`LastModified`), never lexicographic.** A `StartAfter` key
   cursor skips everything sorting BELOW it, permanently and silently. This lost two real
   notices on 2026-07-30 (`.../onsemi_look/...` behind `.../onsemi_run6/...`;
   `.../inbound/generated/...` behind the same). Sort position is not arrival order.
2. **`run_key` = content hash + artifact key (`ETag`+`Key`), never a derived field.**
   run_key was once `doc_id`, an LLM-extracted header value; when that model degraded,
   every artifact in one prefix derived the same fallback and Dagster's run-key dedup
   discarded all but the first — no run, no failure, no log line. **A model-derived value
   must never key deterministic machinery.**

Seal a new sensor with the three-object test: a late-arriving LOW-SORTING key fires · an
untouched key skips · a rewritten key (same name, new content) fires. See
`tests/test_sensor_cursor_contract.py`.

### When adding a new Dagster asset
1. Create or edit a file in `src/iagent/defs/`.
2. Use the `@asset` decorator from `dagster`.
3. If the asset calls an agent pod, use only `requests.post()` with
   `timeout=120`. Do NOT import any agent SDK or ML library.
4. Return `dict` (parsed JSON from the agent response).
5. Add a docstring explaining what the asset does.

### When modifying data contracts
1. Edit `baml_shared/baml_src/contracts.baml`.
2. Regenerate clients:
   ```bash
   cd baml_shared
   uv run --no-project --with baml-py==0.219.0 baml-cli generate --from baml_src
   ```
3. **Never hand-edit anything in `baml_shared/baml_client/` or
   `baml_client_ts/baml_client/`** — they are regenerated.
4. Commit BOTH the `.baml` change AND the regenerated client files in
   the same commit. CI does not regenerate on its own.
5. Verify downstream agents still conform to the updated schema —
   BAML's structured-output enforcement will catch mismatches at
   runtime.

### When modifying a tool docstring on a smolagent engine
1. Tool docstrings (the body of the `@tool def some_tool(...)` function)
   are **part of the BAML grounding contract**, not just documentation.
   The smolagent's tool-selection step reads them at runtime.
2. If the upstream service the tool wraps changes its response shape,
   update the docstring in the same PR. See ADR-0013 for context.
3. Do NOT hard-code wire-format details into the engine's system
   prompt. Wire-format documentation lives on the tool, not the prompt.

### When adding a new engine
1. Create `agent_fleet/<engine_name>/`.
2. Add `pyproject.toml`, `uv.lock`, `Procfile`, `main.py`.
3. Register the engine's verbs at startup via
   `utils.mesh_registration.register_engine_to_mesh(...)` — this is
   what makes ADR-0004's predicate routing actually find it.
4. Engine declares its `domains=[...]`, `owner_persona=...`,
   `cost_class=...` so the routing graph can filter by entitled
   domains and cost.
5. Add the engine to the CI build matrix in
   `.github/workflows/build-containers.yml`.
6. Add a deployment block in `helm/invincible-agent/templates/`
   (most are auto-generated from `engines.yaml`).
7. Add an end-to-end test in `tests/sandbox_e2e/` exercising the new
   engine through `cortex-bff /orchestrate`.

### When adding a BPMN workflow to bpmn_catalog
1. Insert a row into the `bpmn_catalog` table with a valid BPMN JSON
   payload. The payload must have `tasks`, `gateways`, and
   `sequence_flows` arrays.
2. Each task must have: `id`, `name`, `type`
   (service_task | user_task), `agent_endpoint`.
3. Set `is_active = TRUE` so `dynamic_factory.py` picks it up on next
   load.
4. Restart Dagster (or reload definitions) — `build_dynamic_jobs()`
   runs at module-load time and generates jobs/ops from the catalog.

### When adding dependencies to an engine
1. Add to `[project.dependencies]` in that engine's `pyproject.toml`.
2. Regenerate the engine's lock: `cd agent_fleet/<engine> && uv lock`.
3. Commit BOTH `pyproject.toml` and `uv.lock`.
4. CI builds the engine image from its own lockfile, so the lock is
   load-bearing.

## Safety & Boundaries

### DO NOT
- Use `PipesK8sClient` for any agents — Dagster uses only `requests`.
- Mix framework imports across engines (e.g. no Restate in Engine B,
  no LangGraph in Engine A).
- Import Dagster, ML frameworks, or agent SDKs in the ontology service.
- Import Restate, LangGraph, Dagster, or smolagents in Engine B.
- Import Restate, LangGraph, Dagster, or checkpointers in Engine C.
- Add compute or orchestration logic to Engine O — it is pure
  semantic resolution + predicate routing.
- Hardcode wire-format details of one engine in another engine's
  system prompt. Format goes on the tool docstring (see ADR-0013).
- Hardcode secrets, API keys, or credentials anywhere.
- Edit auto-generated files in `baml_shared/baml_client/` or
  `baml_client_ts/baml_client/`.
- Commit `.env` files or anything containing secrets.
- Use the floating Restate image tag `1.1` — pin to a specific version
  (sandbox uses `1.6.2`). The floating tag has drifted on Docker Hub
  and broken the cluster in the past.

### DO
- Keep the orchestrator lightweight — it only dispatches HTTP calls.
- Use BAML contracts as the single source of truth for schemas.
- Add `response.raise_for_status()` before parsing any HTTP response.
- Set explicit timeouts on all outbound HTTP requests. Smolagent
  loops can take many minutes — engine proxy timeouts should be 600s
  or longer when calling Restate ingress.
- Self-register every new engine via `register_engine_to_mesh` at
  startup, with accurate `domains` and `owner_persona`.
- Write tests in `tests/sandbox_e2e/` for new mesh paths.
- Cite the ADR when introducing a load-bearing architectural change.

## Agent Pod Endpoints

These are the in-cluster URLs the orchestrator and the BFF talk to.

- **Cortex BFF**: `POST http://iagent-cortex-bff:8090/orchestrate`
  Accepts `{message, session_id}` JSON with `Authorization: Bearer
  <jwt>`. Streams SSE events including `event: final_payload` with
  the `DashboardUI` payload.
- **Ontology reasoner (Engine O)**:
  - `POST http://iagent-engine-o:8084/route_intent` — BAML
    `ExtractIntent`, returns `{mode, entity_refs, confidence}`.
  - `POST http://iagent-engine-o:8084/plan` — BAML `DecomposeQuery`,
    returns `SupervisorTaskPlan`.
  - `POST http://iagent-engine-o:8084/search_predicates` — Weaviate
    hybrid search over the Predicate collection. Returns the matched
    engine endpoint scoped by `entitled_domains`.
  - `POST http://iagent-engine-o:8084/resolve` — RDF ontology URI
    classification via `ClassifyDomainIntent`.
  - `POST http://iagent-engine-o:8084/find_tool` — exact lookup by
    `(subject_uri, verb_label)`.
  - `POST http://iagent-engine-o:8084/find_path` — multi-hop traversal
    through the predicate graph (planning support, ADR-0011).
- **Restate analyst (Engine A)**:
  `POST http://iagent-engine-a:8081/analyze`
  Accepts `AgentTask` JSON. Resolves semantic context, runs a
  smolagents `CodeAgent` with `search_datahub`,
  `superset_analytics_manager`, and JIT-bound tools discovered via
  DataHub. Returns `AgentResponse` JSON.
- **LangGraph support (Engine B)**:
  `POST http://iagent-engine-b:8082/support`
  Accepts synthesis context + `thread_id` for memory.
- **Swarms scraper (Engine C)**:
  `POST http://iagent-engine-c:8083/scrape`
- **DataHub wrapper (Engine D)**:
  `POST http://iagent-engine-d:8085/query_metadata` — natural-language
  search; returns matched assets with **owner, last_updated, tags,
  description, upstream / downstream lineage, and schema columns**
  (per the enrichment landed during the 2026-06-02 DataHub work).
  Also `GET /dynamic_context` and `GET /find_tools?ontology_uri=...`.
- **Data analyst (Engine DA)**:
  `POST http://iagent-data-analyst:8089/analyze`
  Restate-durable. Calls CortexDataClient to read Postgres /
  ClickHouse / S3 Parquet / Delta / Iceberg. RLS/CLS enforced by
  Topaz via the central gateway.
- **Neo4j Graph Expert (Engine E)**:
  `POST http://iagent-engine-e:8086/query_proxy`
  Restate-durable Cypher generation via smolagents. Long-term episodic
  memory via mem0 + Weaviate.
- **Presentation Agent (Engine F)**:
  `POST http://iagent-engine-f:8087/render_ui`
  Stateless. Calls BAML `DesignUI(raw_data, persona) → DashboardUI`.
  Six archetypes available (see UI Archetypes below). ADR-0012 tracks
  the planned dynamic-columns refactor.
- **Weaviate Semantic Expert (Engine W)**:
  `POST http://iagent-engine-w:8088/query_knowledge`
  Restate-durable. Weaviate v4 hybrid search (`near_text` + BM25)
  over technical manuals. Strict per-domain segregation via filter.

## Development Log

The phase log captures the architectural evolution. Each phase
references the relevant ADR where one exists.

### Phase 1 — Shared contracts (complete)
Defined BAML contracts: `AgentTask`, `AgentResponse`,
`SemanticResolution`, `AgentStatus`. Ontology classes dynamic.

### Phase 2 — Orchestrator control plane (complete)
Lightweight Dagster `@asset` HTTP dispatchers, no SDK imports.

### Phase 2.5 — Engine O: Ontology Reasoner (complete)
`agent_fleet/ontology_service/main.py` on port 8084. Loads
`iof_mro.ttl` into rdflib, SPARQL queries for classes, BAML
`ClassifyDomainIntent`.

### Phase 3 — Engine A: Restate + Smolagents Analyst (complete)
Durable `analyze` handler. Smolagents `CodeAgent`. BPMN workflow
runner for long-running workflows with `UserTask` promise suspension.

### Phase 4 — Engine B: LangGraph Support Agent (complete)
Two-node graph + `AsyncPostgresSaver` checkpointer.

### Phase 5 — Engine C: Swarms.ai Scraper (complete)
Stateless `SequentialWorkflow` for extraction.

### Phase 6 — Multi-stage Docker via uv (complete)
**Migrated from Cloud Native Buildpacks (Paketo) to dynamic
multi-stage Docker builds powered by `uv`.** Dockerfiles are
generated within the CI/CD pipeline to keep the repo root clean
while sharing modules (`baml_shared`, `llm_utils.py`) during build.

### Phase 7 — Late Binding & Mesh Discovery (complete)
Deprecated `data_layer.py`'s direct dbt/SQL mapping; migrated to
`doc-tools`. Semantic resolution uses Weaviate hybrid search + BAML
TypeBuilder for zero-hallucination routing.

### Phase 8 — Engine D: DataHub Metadata Wrapper (complete)
`/query_metadata` against DataHub's GraphQL search.

### Phase 9 — Dynamic BPMN Interpreter (complete)
Imperative-declarative hybrid in `dynamic_factory.py`. BPMN payloads
in `bpmn_catalog`, generates `@op` and `@job` at module-load time.

### Phase 10 — Engine E: Neo4j Graph Expert (complete)
Restate + smolagents Cypher generation against military technical
manual graph.

### Phase 11 — Dynamic Supervisor & Synthesis (complete)
Engine O `/plan` for multi-domain decomposition. Dagster
`dynamic_supervisor.py` for fan-out / fan-in. Recipe 1 (stateless
Dagster synth) and Recipe 2 (stateful LangGraph synth).

### Phase 12 — Engine F: Presentation Agent (complete)
`/render_ui` with BAML `DesignUI` mapping to UI archetypes.

### Phase 13 — Composite DashboardUI (complete)
`DashboardUI` wrapping `(TopologyUI | HazardUI | MetricUI |
DocumentUI)[]`. Persona icon broadcasting via `AssetMaterialization`.

### Phase 14 — Comprehensive Helm Charting (complete)
Single Helm release covers every engine + infra (Postgres, Restate,
Neo4j, Weaviate, Fuseki, Keycloak). Post-install hooks for restate-
init and db-init.

### Phase 15 — Multi-Domain Agentic Mesh (complete)
Intelligent routing via BAML `Domain` + `Intent` extraction. Strict
data segregation in SPARQL named graphs and Neo4j domain-specific
node labels. **ADR-0009** later sunsetted the classification axes
once predicate-graph routing landed.

### Phase 16 — Engine W: Weaviate Semantic Expert (complete)
`agent_fleet/weaviate_expert/main.py` on port 8088. Weaviate v4
`near_text` + `Filters`. Optimized for `mesh:retrieveKnowledge`.

### Phase 17 — Agentic Auth Middleware (complete)
`agent_fleet/core/authz.py` with `require_topaz_auth` FastAPI
dependency. Decodes Keycloak JWT, queries Topaz REST API, injects
validated `user_jwt` into route handlers.

### Phase 18 — Zero-Trust Data Mesh & Engine DA (complete)
Three-component data plane: smolagents driver (Engine DA), policy
injector (central gateway extracts `allowed_columns` and
`row_filters` from Topaz response), enforcer (CortexDataClient
applies CLS/RLS to the Polars `LazyFrame` before LLM-generated SQL
runs). Covers Postgres / ClickHouse / S3 Parquet / Delta / Iceberg.

### Phase 19 — Predicate Graph Routing (complete, **ADR-0004**)
Replaced LLM-driven engine selection with a Weaviate `Predicate`
collection. Each engine self-registers its verbs, owner persona,
domains, and endpoint at startup via
`utils.mesh_registration.register_engine_to_mesh`. Engine O's new
`/search_predicates` does hybrid vector search to pick the right
engine per subtask, filtered by the caller's `entitled_domains`.

### Phase 20 — Verb + Concept Namespaces (complete, **ADR-0005**)
Standardized the `mesh:` verb namespace and the concept URI scheme.
Engine registrations validate against the RDF-namespace-defined
verb registry.

### Phase 21 — Routing Fallback Policy (complete, **ADR-0008**)
When `/search_predicates` returns no match for the caller's domain
scope, Engine A is invoked as the generalist fallback with an
explicit "no specialist matched" preamble so its tone calibrates to
uncertainty.

### Phase 22 — Sunset Classification Axes (complete, **ADR-0009**)
Retired the legacy `RouteAndPlan` 3-axis classifier in favor of
predicate-graph routing + a simplified `ExtractIntent` BAML function
(mode + entity_refs only). The persona split (caller-side vs
answerer-side) is also formalized here.

### Phase 23 — Distributed Tracing (complete, **ADR-0010**)
OTel-style trace propagation across BFF, Dagster, engines, and
Restate invocations. Enables end-to-end latency tracking per query.

### Phase 24 — DataHub Stack Stand-Up (complete)
Stood up the full DataHub v1.6.0 stack in the sandbox: GMS,
OpenSearch 2.18.0 (DataHub v1.6 incompatible with OpenSearch 3.x),
Redpanda (Kafka-compatible, no Zookeeper), Postgres (existing
`iagent-postgresql`). `DATAHUB_REVISION=3` mismatch between the GMS
and upgrade images required running a separate system-update job to
land the right schema marker.

### Phase 25 — Engine D Enrichment (complete)
Extended `_GENERIC_SEARCH_QUERY` to fetch `ownership`, `tags`,
`schemaMetadata`, upstream/downstream relationships, and the most
recent `operations.timestampMillis`. Response formatter emits per-
asset pipe-separated headers (`owner=`, `last_updated=`, `tags=`)
plus indented `description:`, `upstream:`, `downstream:`,
`columns:` continuation lines. **ADR-0013** scopes the planned
follow-up: replace the single fuzzy-search tool with a set of
capability tools (`get_owner`, `get_lineage`, `list_stale_assets`,
etc.) so the agent can ask specific questions rather than parse a
multi-line response.

### Phase 26 — UI Archetype Grounding Patch (complete)
BAML `DesignUI` prompt extended with explicit grounding rules
forbidding URN invention and steering catalog Q&A to
`KNOWLEDGE_DOCUMENT` (preserves owner/lineage/freshness as prose)
instead of `ASSET_STATE_METRIC` (a 4-column table widget that drops
those fields). **ADR-0012** documents the architectural tension —
the rigid `MetricUI` schema — and proposes the dynamic-columns
generalization as the long-term fix.

### Phase 27 — Engine A Tool Docstring Refactor (complete)
Engine D's wire format moved out of Engine A's system prompt and
into the `search_datahub` tool's docstring. Engine A's prompt is
again domain-level ("analyst persona, ground in tool results");
each tool documents its own response shape via its docstring. This
keeps Engine A loosely coupled to Engine D's format. Tool
docstrings are part of the BAML grounding contract, not
documentation prose.

## Persona Reference

Five domain-expert personas (BAML `PersonaTarget`). The supervisor
assigns sub-tasks; engines execute; Engine F maps to UI archetypes.

### MECHANIC
- **Icon:** Wrench (amber)
- **Engine E Response:** `MechanicResponse` — tool_list, safety_warnings, short_answer
- **Typical UI:** `HAZARD_DECLARATION` / `ASSET_STATE_METRIC`

### TECH_WRITER
- **Icon:** BookOpen (blue)
- **Engine E Response:** `AuthoringResponse` — draft_content (Markdown), missing_info_flags
- **Typical UI:** `KNOWLEDGE_DOCUMENT`

### LOGISTICS
- **Icon:** Truck (emerald)
- **Engine E Response:** `LogisticsResponse` — impacted_platforms, blocked_procedures, risk_severity
- **Typical UI:** `ASSET_STATE_METRIC` / `HAZARD_DECLARATION`

### AUDITOR
- **Icon:** ShieldCheck (red)
- **Engine E Response:** `AuditResponse` — non_compliant_nodes, rule_violated, recommended_fix
- **Typical UI:** `HAZARD_DECLARATION` / `KNOWLEDGE_DOCUMENT`

### PROCESS_ENGINEER
- **Icon:** Network (purple)
- **Engine E Response:** Any (depends on sub-query)
- **Typical UI:** `PROCESS_TOPOLOGY`

### DATA_STEWARD
- **Engine D / Engine A Response:** `DataStewardResponse` — tool_list, safety_warnings, short_answer
- **Typical UI:** `KNOWLEDGE_DOCUMENT` (catalog Q&A) / `ASSET_STATE_METRIC` (catalog listings)

## UI Archetypes

Engine F returns `DashboardUI` with `components` array of:

- **`PROCESS_TOPOLOGY`** — Full-width React Flow graph (nodes + edges).
- **`HAZARD_DECLARATION`** — Inline 2-col card. Risk alerts with severity.
- **`ASSET_STATE_METRIC`** — Inline 2-col card. id/name/type/description.
- **`KNOWLEDGE_DOCUMENT`** — Full-width Markdown via `react-markdown`.
- **`CHART_WIDGET`** — Recharts BAR / LINE / PIE / SCATTER.
- **`DIGITAL_TWIN_3D`** — three.js scene with anomaly highlighting.

Known limitation: `MetricUI`'s 4-column schema is too rigid for
catalog Q&A. ADR-0012 proposes a dynamic-columns generalization.

## ADR Index

| ADR | Subject | Status |
|-----|---------|--------|
| 0001 | mem0 LLM decouple | Accepted |
| 0002 | mem0 monkeypatches | Accepted |
| 0003 | LLM rightsizing | Accepted |
| **0004** | **Predicate graph routing** | **Accepted (current router)** |
| 0005 | Verb + concept namespaces | Accepted |
| 0006 | Verb registry location | Accepted |
| 0007 | Survey before mint | Accepted |
| 0008 | Routing fallback policy | Accepted |
| **0009** | **Sunset classification axes** | **Accepted** |
| 0010 | Distributed tracing strategy | Accepted |
| 0011 | Multi-SPO routing | Proposed (deferred) |
| 0012 | UI archetype rigidity | Proposed (workaround in place) |
| 0013 | Engine D capability surface | Proposed (workaround in place) |

When adding a load-bearing architectural change, draft an ADR in
`docs/adr/` following the template of the most recent ones.
