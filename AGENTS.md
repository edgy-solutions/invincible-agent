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

**ONE WRITER PER TREE PER SESSION, AND `git stash` IS BANNED OUTRIGHT (2026-08-10).** Two agents in
one working copy nearly lost work today, and it recovered by luck rather than design: a `git stash`
taken merely to compare a test baseline could not `pop`, because a **generated** file
(`docs/BOARD.md`) had been rewritten in the interim. The stash held four edits, the pop aborted, and
recovery required restoring the generated file to HEAD before the pop would apply.

**The rule:** one agent writes the tree in a session, the other reads only — and **never `git stash`
in a shared tree.** Stash silently reverts files another writer may be holding, and its failure mode
is an aborted pop whose contents survive only if someone notices. Compare baselines with
`git show HEAD:<path>`, a scratch copy, or a second clone — never by mutating the shared tree.

**Branch-per-agent was considered and REJECTED**, for a reason specific to this repo: branches split
the working tree from the **generated** artifacts. Two agents on two branches each regenerate
`BOARD.md` from divergent packet sets and then collide at merge on a generated file — strictly worse
than colliding on a source file, because the correct resolution is not a merge but a regeneration
from the union. Single-writer needs no tooling and matches how the agents are actually run: one
working, one reviewing.

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

### Running the tests — WHICH ENVIRONMENT, then the extra

**Use `./scripts/run-tests.sh`.** It picks the right virtualenv for whichever side you are on
and prints what your result is scoped to. If you run pytest by hand instead, read this section
first — the failure mode here is silent and it damages the OTHER side's environment.

**THIS TREE CARRIES TWO VIRTUALENVS.**

| | interpreter | matches CI? |
|---|---|---|
| `.venv` | **Windows** CPython 3.11 | no |
| `.venv.wsl` | **Linux** CPython 3.12 | **yes** — CI is `ubuntu-latest` / `3.12` |

`.venv.wsl` is a Linux venv living in the shared tree (its `pyvenv.cfg` points into a Linux
uv-managed CPython). From Windows its `lib64` is an untraversable reparse point; from Linux it
is the environment closest to what actually deploys.

**⚠️ `UV_PROJECT_ENVIRONMENT` IS UNSET ON BOTH SIDES.** So **from WSL, a bare `uv run` targets
`.venv` — the WINDOWS venv — and rebuilds it with Linux wheels.** The Windows side then breaks
in a way that looks unrelated to whoever ran the tests. From WSL you must always:

```bash
UV_PROJECT_ENVIRONMENT=.venv.wsl uv run --frozen --extra agent-fleet python -m pytest tests/ -q
```

From Windows the default is already correct:

```bash
uv run --frozen --extra agent-fleet python -m pytest tests/ -q
```

**WHICH TO PREFER.** WSL, when you have the choice — it is closer to the deployment and to CI.
Windows is fine for local iteration. **A Windows green is a real signal and is not a CI
signal**, and any suite result quoted anywhere should say which side produced it. When the two
disagree, WSL is the one that matches what ships.

**The extra is not optional, on either side.**

`rdflib`, `restate-sdk` and `smolagents` live in the **`agent-fleet` optional extra**, so a
plain `uv run --frozen` (or a bare system `python`/`py`) collects `test_review_starter`,
`test_restate_analyst` and friends as import errors. A bare `py -m pytest` on Windows
additionally cannot traverse `.venv.wsl` and reported seven collection errors before
`tests/_treewalk.py` fixed the walks — the same class found on 2026-08-05 and not converted
into a guard until 2026-08-22. Those are **environment selection**,
not repo breakage — and reporting them as "pre-existing failures" is how a genuinely red
test hides in the noise. If a suite is red, first re-run it with the extra before
attributing the failure to anything.

### Verify the STAGED BLOB, not the working tree — a test result is a claim about the file it ran against

**A green suite is evidence about the bytes on disk when it ran, not about the commit you are
about to make.** Those are the same thing only when the working tree and the index agree, and in a
contended tree they routinely do not: your tests may have run against a file that also held
another agent's uncommitted diff — a composition that exists in no commit and that nobody will
ever deploy.

Demonstrated twice on 2026-08-11 in one evening, both times in `restate_analyst/main.py` with two
agents holding hunks. Cheap enough that there is no reason to skip it before any commit that
splits a shared file:

```bash
git add <explicit paths>                 # never `git add -A` with unrelated WIP in the tree
git diff --cached --name-only            # assert the set is EXACTLY what you intend
git diff --cached | grep -c "<other agent's marker>"   # assert 0

TREE=$(git write-tree)                   # the index, as a real tree object
rm -rf /tmp/staged && mkdir -p /tmp/staged
git archive "$TREE" | tar -x -C /tmp/staged
cd /tmp/staged && <compile> && <run the seals here>    # a dir the working tree cannot influence
```

**Why extract rather than reason about it:** "the index equals the working tree, so my tests
apply" is a sound argument and an easy one to get subtly wrong (a partially-staged hunk, an
untracked file the tests import, a `.pyc` shadowing a change). Materialising the tree costs
seconds and converts the argument into an observation.

### In a contended tree, EDIT THROUGH THE EDITOR — a script write is invisible to the tracking

**Editing a file with a script (`sed -i`, a python rewrite) bypasses the editor's change
tracking, so the tooling can no longer tell your own out-of-band write from another agent's.**
Observed 2026-08-15: a reordering script rewrote `docs/demo-day-runbook.md`, and the next edit
surfaced a *"file modified on disk since you last read it"* warning that read exactly like a
concurrent agent touching the file. It was self-inflicted.

The cost is not the warning; it is the **record**. An unexplained modified-on-disk warning
becomes an implied near-miss in the transcript and gets cited later as evidence of a collision
that never happened — a false positive in the one signal a contended session most needs to
trust. Two consequences:

* **Prefer the editor for edits during a contended session.** Scripts are fine for generation
  and for bulk mechanical moves; they are a poor choice for touching a file another agent might
  hold.
* **When a script write is the right tool anyway, say so at the time.** A false alarm reported
  as a false alarm costs one sentence. Left standing, it is indistinguishable from the real
  thing.

### OWN AN ARC, NOT A FILE — and check what moved before assuming your premise holds

**The staged-blob rule above bounds two agents by TREE. It does not bound them by MEANING, and
that is the collision that actually happened (2026-08-15).** Two agents worked the same arc from
different sides, touched no common file, produced no merge conflict, and one invalidated the
other's premise anyway:

* Agent A read Engine O's image digest, established that sandbox was current, and concluded a
  corpus read was runnable.
* Agent B rewrote the `idp:Column` / `idp:Pipeline` definitions in `idp_extension.ttl`,
  re-ingested them, and **measurably moved which class wins a contest** — with the image digest
  unchanged and A's finding still technically true.

Nothing in git flags that. A's number would have answered a question that had stopped being the
question, and it would have looked clean.

**Bound by LAYER, not by arc.** An arc split was tried first (critical-path vs resolver) and was
**wrong**: item 2 *is* resolver work, so that seam ran through the middle of a single
investigation and both agents kept legitimately needing the other's side. Layers cut where the
code actually separates:

| agent | owns the layer |
|---|---|
| **A — extraction / matching** | `ClassifyDomainIntent`'s **identifier** output, the fuzzy matcher, `_resolve_instance`, and the packet formerly called `instance-resolution-nondeterminism` |
| **B — class selection** | `idp_extension.ttl` definitions, recall bias, the class contest, argmax-vs-LLM |

**They meet at exactly one call.** `ClassifyDomainIntent` emits the class **and** the instance
identifier in a single LLM call, so it is the one shared surface:

> **Whoever changes that BAML call or its prompt announces it first, and the other holds any
> in-flight read.** Everything downstream of it splits cleanly.

**The corpus is shared infrastructure, not either agent's.** Both read it; neither changes its
scoring without saying so; and **every run reports all three stamp axes** so one agent's number
is interpretable by the other. That last clause is what would have caught the 2026-08-15
collision automatically instead of by A happening to notice a commit.

**And the standing protocol, which is the general form:**

```bash
git log --oneline -5        # before starting ANY session
```

**Read what landed since your last commit.** Today's collision was not a merge conflict, it was
a *semantic* one — and semantic collisions are invisible to every tool that watches bytes. The
guard is procedural and it is one command: **check what moved before assuming your premise
holds.**

**LIMIT — an extracted tree has no `.git`, so git-dependent checks FALSE-RED there.** Found the
first time this was used: `test_board_drift` shells out to `generate_board.py --check`, which
resolves every `closed-by` sha with `git cat-file`; in `/tmp/staged` that fails for *all* of
them and the drift check reports the board out of sync when it is not. Split the run:

- **Git-independent checks** (unit tests, seals, compile, YAML/schema parse) → the extracted tree.
- **Git-dependent checks** (board drift, sha attribution, anything shelling to git) → the real
  repo, *after* asserting `git status --short` shows every changed path as `M ` (staged) and none
  as ` M` (worktree-modified). That equality is what makes a repo-run a statement about the index.

Report both, and say which ran where. A false red treated as a real one is how a good technique
gets abandoned after its first use.

**The general form is the artifact-complete rule applied to commits:** a check that does not run
against the artifact you are shipping is a check about something else. Same family as *a guard
that does not gate the artifact is source-complete only*.

**Single-writer applies to the FILE, not just the session.** Two agents holding hunks in one file
means neither can commit honestly, and the resolution is always **sequencing, never surgery** —
hand-extracting your hunks out of a file someone else is editing is how the fence gets broken.
Name the owner per contended file, have the other confirm an empty index (`git diff --cached
--name-only`), and let whoever goes second get a clean file. Discovering the contention by
staging and finding someone else's work is detection by collision, not by protocol.

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

### A FORMAT change to a PERSISTED value is a migration — even with no schema in sight
The entry above is about a key whose NAME changes. This is its quieter sibling: a value whose NAME
never changes and whose **encoding** does. There is no rename to notice, no sync to run, no grant to
prune — and the same class of failure.

**The instance (found live 2026-08-07, dead for over a week).** The extraction→review sensor's cursor
moved from a lexicographic S3 key to `<iso>|<key>`. The code changed; the value already sitting in
Dagster's cursor storage did not. Every tick then compared across the two forms —
`"2026-08-07T…|sustainment/…" > "sustainment/inbound/zz_look/…"` — which is False for every object,
because `'2' < 's'`. Seventeen artifacts under the prefix, zero considered new, and the daemon logged
*"no new extractions (review.json) after cursor …"* every thirty seconds. Nothing was red.

**THE MIGRATION BUG WORE THE COSTUME OF THE BUG THE MIGRATION FIXED.** The lexicographic cursor was
replaced *precisely because* its failure mode was silent skipping. The replacement reintroduced silent
skipping through its own changeover — same symptom, opposite cause, invisible either way. When a fix
targets a silent-skip failure, ask what the CHANGEOVER does before the new code's first write.

Three obligations, and they compose:
1. **Distinguish the forms** — not by a cheap tell. Checking for the `|` separator alone would accept
   `not-a-timestamp|key`; the probe parses the timestamp.
2. **Translate when translation is faithful.** The old cursor named the last key processed, so that
   object's `LastModified` is exactly the timestamp the new form should carry: nothing re-fires,
   nothing is newly skipped.
3. **Refuse loudly when it is not.** If the named object is gone, both guesses are bad — no-cursor
   re-fires the whole corpus into humans' queues, `now` skips work in flight. An operator setting the
   cursor is a declared intent; either guess is an accident.

And the part that made it survive a week: **the wedge must not be reported in the idle state's
words.** "No new extractions" is what a HEALTHY sensor says. A skip reason that reads identical to
health is not a diagnostic, it is camouflage — the same finding as the opaque
`review_start_failed` 502 that hid four distinct refusal reasons behind one code
([[feedback_error_path_is_an_error_surface]]).

**Corollary, paid for in the seal itself:** the first version of that seal did NOT bite. It sealed the
helpers, then asserted against the sensor's *source* that the wedge branch preceded the idle branch.
Deleting the migration CALL — the realistic regression, and the sandbox's literal state — left both
strings in the surviving `try`/`except` and every test stayed green. A grep proves presence; it never
proves behaviour. Drive the function ([[feedback_harness_must_prove_it_can_fail]]).

### A dedup key consumed at DISPATCH makes delivery at-most-once — consume it at COMPLETION
An idempotency key answers "have I *started* this?" Delivery needs the answer to "have I *finished*
it?" Those coincide right up until an execution dies without a verdict, and then they diverge
silently and permanently.

**The instance.** The extraction→review sensor keyed `RunRequest.run_key` on the artifact's ETag+key.
Dagster dedups on SUBMISSION, so once a run was submitted no later tick could ever produce another
for that artifact — however the run ENDED — and the cursor had already advanced past the object, so
neither mechanism would re-see it. A run killed by run monitoring therefore dropped its notice
forever: no retry, no log, no trace. Found when unwedging the cursor released a 9-artifact backlog,
the sandbox saturated, and 6 of 9 runs were reaped.

**The discriminant is the design, and it is not "did it fail".** A pipeline that deliberately fails
on a policy refusal must not retry that — it is a loud red run for ops, intended, once, and retrying
buries the signal it exists to raise. It MUST retry a LOST execution, where no verdict was ever
reached and there is nothing for a human to act on. `run.status` says `FAILURE` for both. The tell
lives in the event log:

    reaped           -> FAILURE with ZERO step-failure events    (the run died)
    designed failure -> FAILURE WITH a step-failure event        (the code refused)

Validate that against **both** categories in real history before building on it. A probe that has
only ever seen one category has not been shown to discriminate — it has been shown to agree
([[feedback_integration_positive_controls]]).

**Three properties the retry needs, each of which is a way to get it wrong:**
- **A ledger the key cannot be.** `run_key` is consumed at dispatch and says nothing about outcome,
  so the artifact identity and attempt number must be written somewhere durable — run tags here.
  That ledger doubles as the **opt-in boundary**: history without the tag is invisible to the retry,
  which bounds a new delivery guarantee without an epoch, a cutoff, or deleting anyone's residue.
- **Retry is owed independently of new arrivals.** Gating it behind "did something new land" makes
  delivery depend on unrelated traffic — silent unless something else happens, the wedge's shape.
- **Exhaustion is an EVENT.** Bounded attempts that expire quietly rebuild the same hole one layer
  in. Say what is true of the NOTICE ("has NOT been reviewed"), not of the retry budget.

And suppress on **success, in-flight, and CANCELED**. Cancellation is human intent; re-arming over it
leaves an operator no way to make the pipeline stop trying.

**Corollary on guards, from the break-on-purpose pass on this very fix:** the in-flight guard was
DECORATION — a redundant neighbouring check absorbed the mutation, so deleting the guard left the
suite green, and the test agreed with it by constructing the case the neighbour already covered.
*A guard a mutation cannot reach is not a guard.* When a break-on-purpose comes back green, the
finding is about the guard, not the mutation.

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

### A field acquiring a NEW JOB is the moment to enumerate what it now couples
A detection heuristic, not a post-mortem. Values accrete responsibilities quietly, and each new job
creates couplings nobody chose — the couplings are invisible until two consumers collide on one.

**The instance that produced it:** `request_key` was the artifact pointer; phase 1.3 made it the
admission key; it was already the ingress idempotency key. Three jobs, one string — and the coupling
surfaced only when two witness legs that differed *only* in server-side state collided on it and the
second silently returned the first's result.

**The field already visible as next:** `email` is the login identity, the entitlement claim, **and**
now the subject the ceremony's `can_invoke` grant is keyed on. Three jobs, one string. The
consequence is already on the work-translation list: a Ping broker mapping that lands the employee
identity in a different claim than the local service mapper uses splits the contract — and one side
of that split is now an autonomous effect gate rather than a queue filter.

The check is cheap and belongs in review: *what else reads this value, and what breaks if two of
those readers need it to mean different things?* Ask it when the job is ADDED, because that is the
only moment the answer is small.

### KNOWING the rule did not prevent WRITING the defect — an artifact's IDENTITY is not a POINTER to it
The entry above was filed using `request_key` as its worked example. Hours later, in the same
session, the phase-1.3 derive was written to **fetch** `request_key`. It is
`{epoch}{ETag}-{key}` — an identity minted for ingress idempotency — so the fetch asked S3 for a key
with an ETag glued to the front, and every derive refused. The rule was stated correctly, in
writing, about this exact string, by the same author, immediately before it was violated.

That is the durable part, and it is not "be more careful." **A rule you have articulated does not
fire at the moment you need it, because the moment is not a moment of doubt.** `request_key` is
artifact-derived, it moves when the content moves, and the surrounding comments already called it
"the artifact pointer" — it reads exactly like a location. Nothing felt uncertain. So the defence
cannot be attention; it has to be a mechanism placed where the confusion is *observable*.

Three self-references let it survive review, and they are the reusable diagnostic:
1. **the format was invented.** The parser documented the producer as emitting `<etag>:<key>` —
   COLON. The sensor has always emitted a DASH. Nobody read the emitter;
2. **the fixture asserted the invention.** Written from the same head as the parser, it agreed with
   the parser and never with the producer — the sibling of *a test that supplies its own provenance
   will agree with itself* (below), one level up: not a supplied VALUE, a supplied FORMAT;
3. **the live witness hand-supplied the input** in the shape the parser expected, so the composed
   sensor path was never driven. Green over a path that never ran.

Each alone is survivable. Together they form a closed loop that touches the producer at no point,
and a closed loop can be arbitrarily wrong while every member of it is consistent.

**The mechanism, not the resolve:** a test that proves a consumer reads the right field must obtain
its payload **by calling the producer's own builder** (`tests/test_artifact_uri_contract.py`), and
the field choice must be pinned at the **call site**, because a file-level substring check passes on
the prose *about* the field (`test_the_derive_reads_the_POINTER_field_not_the_IDENTITY_field`).
Naming the job in the field name — `artifact_uri` for LOCATION beside `request_key` for IDENTITY —
is what makes the call site legible enough to pin at all. Species entry: §6 of
`docs/reference/cross-repo-string-contracts.md`. Found by a reviewing agent tracing a live 422 back past
the artifact to the field choice.

### The substrate's DEDUP can substitute a prior result for the experiment you meant to run
Fifteenth probe-correctness instance, and a new species: not a bad instrument and not a bad fixture
— **the experiment never executed, and the answer returned was another experiment's.**

Witnessed 2026-08-06. Two witness legs differed only in SERVER-SIDE state (the trust table) and were
driven against the same artifact. cortex-bff derives an ingress idempotency key from
`(request_key, approver)`, so the second drive produced the same key and Restate — correctly —
ATTACHED to the first invocation instead of running one. Leg 3 returned leg 2's `workflow_id`, leg
2's route and leg 2's admission line. The guard under test was never exercised **and the run looked
successful.**

**Witness legs that vary only in server-side state must vary the IDEMPOTENCY IDENTITY too, or they
measure the first leg twice.** Standing line for every multi-leg drive: **assert each leg's
invocation id is NOVEL before attributing its result.** Nothing goes red when this happens — the
tell is a readback naming the wrong subject, so it has to be checked rather than assumed.

Note the coupling that produced it, because it generalises: one value had quietly acquired three
jobs — artifact pointer, admission key, and idempotency key. When a field takes a third job, ask
what it now couples.

### The DEPLOY LITANY — four rungs, each catching the one above's false positive
Every rung was learned by nearly witnessing the wrong thing:

1. **`kubectl rollout status` succeeded** — and the selector handed back a `Terminating` corpse.
2. **The digest changed** — and the code was not in it: CI had failed upstream (runner acquisition)
   and the new digest belonged to an older commit.
3. **The code is present in the pod** (grep the running filesystem) — necessary, still not enough.
4. **The behaviour is witnessed** — the only rung that is evidence.

**FIFTH RUNG, PREPENDED 2026-08-07 — COMMITTED ≠ UPGRADED.** The litany began at rung 1 because
it assumed the release had been upgraded at all. It had not: a chart commit was pushed, and the
running ConfigMap it renders was stale, because nothing had run `helm upgrade` in four chart
versions. Every rung below is a check on a deploy that HAPPENED; rung 0 asks whether it did.
The chain is five: **committed → upgraded → digest changed → code present → behaviour witnessed.**

### DECLARED-VS-RUNNING DRIFT REQUIRES NO MUTATION
The whole hand-seeded-state class assumed someone TYPED something — a `kubectl set env`, a console
click, a one-off `kcadm`. 2026-08-07 produced the case where nobody touched anything and the states
diverged anyway.

`values-sandbox.yaml` carried **two top-level `keycloak:` keys**. Helm's YAML parser takes
**last-wins, silently** — valid render, wrong value — so the first block's `auth.adminPassword`
override was discarded on every render and Keycloak booted on the CHART DEFAULT. The duplicate was
fixed weeks later, and the fix **could structurally never reach the running server**, because
Keycloak's admin bootstrap reads that value ONCE, at first boot.

**A declaration error captured by a one-shot consumer outlives its own fix.** The birth value is
whatever the declaration said AT BIRTH, including its bugs — and no amount of later correctness in
git can dislodge it. Recovery required git-history archaeology against a live cluster whose admin
credential nobody knew; the password was never lost, it was in the record.

**THE FIRST-BOOT CLASS, COMPLETE TAXONOMY**: realm import (applies once), admin bootstrap (reads
once), Restate registration (registered once, by a job that covered two of four services), and the
compounding case above where *the frozen value was itself a bug*. **Every member has the same
cure: a reconciler that runs EVERY deploy and fails LOUD.** As of 2026-08-07 the system has three —
Topaz seed, workflow definitions, and realm identity — each converging running state to
declaration, each failing loud, each with an explicit-and-announced escape hatch or none at all.
The class stops being *caught* and becomes *unconstructable*.

Authoring-time closure for the silent-merge half: CI refuses duplicate top-level keys in any values
file (`build-containers.yml` lint job), **proven in both directions** — clean on the tree, exit 1
naming the key and file when the historical duplicate is reintroduced.

*rollout → digest changed → code present in pod → behaviour witnessed.* Skipping a rung rarely
fails outright; it produces a confident wrong conclusion, which is worse. Run all four before
attributing any live result to a change.

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
missing is a same-mechanism before/after pair. ~~**Ledger item: re-run A and E's witnesses with the
fail-not-kill seal D now has.**~~ Filed rather than quietly repaired, because a witness whose
weakness is known and recorded is worth more than one silently re-run.

**CLOSED 2026-08-06 (`0d8689c`).** A and E took D's seal (`A_SEAL_FAIL_AFTER_WORK` /
`E_SEAL_FAIL_AFTER_WORK`), placed after the work AND after the boundary emit so both `ctx.run`
steps are journaled and the replay re-executes only the handler's re-entry — the defect, isolated.
Placement was checked per engine rather than copied: A's seal sits inside a broad `try` that is
safe only because its `except` RE-RAISES; E has no enclosing except at all. Results, one
manufactured replay each (seal `#1` only, verified by firing number — the string appears twice in
A's log via the re-raise print and Restate's traceback, which is one firing, not two):

| engine | seal firings | boundary span | inner spans |
|---|---|---|---|
| A | 1 | `analyst` = **1** | 1 each (memoized) |
| E | 1 | `engine-e graph reasoning` = **1** | 1 each (memoized) |

**Why this leg discriminates where the kill could not:** attempt 1's boundary has already closed
and EXPORTED by the time the seal fires, so the unfixed code would read 2 exactly where the fixed
code reads 1. The kill destroyed that evidence and returned 1 either way. Note also what changed
about attestation: with the work memoized the inner-span count no longer doubles, so it cannot
attest the replay — that evidence is the seal's log line plus the completing retry, both surviving
because the process does. The A/E inversion table's shape was a property of killing MID-work, not
of replay witnesses generally.

The general form this adds: **an instrument that survived is not the same claim as an instrument
that could not have died.** A and E's inner-span count survived; it was never structurally safe. Ask
which, because only the second is a method.

And its stronger statement, which subsumes the above and is the thirteenth probe-correctness
instance: **an instrument's identity includes the MECHANISM THAT DELIVERS ITS EVIDENCE, not just
the metric it counts.** Two reads that count the same thing through different survival paths are
two instruments, and a before/after pair built across them is a comparison wearing a pair's
clothes. That is exactly what "same instrument both times" hid here: true of the counting tool
(the observations API), false of the replay mechanism (organic replay vs pod kill) — and the
mechanism is the half that decides whether the evidence exists to be counted.

Note the species, because it is the reason this one was hard to catch: the flawed exoneration was
written INTO THIS FILE as settled, by the same thread that would later rely on it. A ruling that
asserts a MECHANISM ("it journals through Restate") is the sibling of a ruling that asserts a
string identity — both feel like reasoning and are actually claims, and both need the same
treatment: trace where the thing actually lives before writing the ruling down.

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

**This sentence is the header of the whole break-on-purpose doctrine, and every species in the
probe-correctness catalogue is a way a never-failed guard turns out to guard nothing.** So the
operational form is not "write the guard" but "make it fire once, deliberately, before trusting
it". 2026-08-07's duplicate-top-level-key lint is the pattern in four lines: it passes on the
tree AND exits 1 naming the key when the historical duplicate is re-introduced. That second run
is what converts four lines of INTENTION into four lines of EVIDENCE — and it costs one command.

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

### An instrument that CAPTURES the discriminating signal and SCORES on the non-discriminating one is green over the exact thing it exists to measure
2026-08-19, the resolver corpus. Every record carried BOTH signals: `instance_id` (a provider
actually RESOLVED the identifier) and `instance_fired` (the LLM merely EXTRACTED one). The
preflight `stamp()` probed the strong one. The scoring function `score()` keyed on the weak one.
**The corpus's own `requires_instances` note states the distinction and calls `instance_id` "a
stronger signal than an identifier merely being extracted"** — the artifact testified against its
own scoring function, in the same file, and nobody read the two together.

**The cost is not a rounding error, it is a blind spot shaped exactly like the fix.**
provider-empty and success both extract an identifier, so they scored IDENTICALLY. A change that
made providers start resolving — the change the corpus existed to evaluate — would have moved the
primary measure by ZERO and read as a no-op. Measured on the one surviving record set: **27/30
extracted, 0/30 resolved.** Every grounding number published before that day measured extraction.

And it was not localised: a second, ad-hoc probe script had a field *named* `resolved` populated
from the weak signal too. **Two instruments, independently written, both called extraction
"resolution."** When a distinction is subtle enough to lose once, assume it is lost everywhere the
same word appears.

**So: for any instrument, ask which recorded field the HEADLINE consumes, and whether a fix to the
thing being measured would move it.** If the answer is "no", the instrument is decorative over its
own subject. This is the sibling of *a probe must demonstrate it can SEE the category of thing it
is checking for*: there the probe could not observe the category; here it observed it, wrote it
down, and then scored something else. **Capture is not measurement. The signal must reach the
number.**


### Automated passes over a readable corpus fail STRUCTURALLY and DIVERSELY — more passes add error modes, they do not triangulate
2026-08-10, enumerating unminted outbound callers. **Four classifier passes over one tree produced
four different answers, and every error was structural rather than a typo:**

1. **Indirection defeats a string match.** The credential attaches inside
   `_telemetry_headers(config)`, so searching the call block for `Authorization` finds nothing and
   reports a minted caller as unminted.
2. **Over-resolution drops true positives.** The fix for (1) narrowed the target regex and window
   and lost four confirmed-minted calls.
3. **A short window invents missing error handling.** These sites carry 15-line explanatory
   comments *between* the request and its handling, so a 20-line window ended before both
   `raise_for_status()` and the enclosing `except` — and reported "consumes a 401 body as a
   result", an emergency that does not exist and was one step from being filed as a board item
   above the flip in severity.
4. **Proximity is not enclosure.** A backward scan for `try:` cannot tell which *branch* it
   guards. `dynamic_supervisor.py:146` sits in the `else:` while the `try` guards the `if`, so it
   read as caught when it stops.

The tempting inference after (1) and (2) — *run more passes and cross-check them* — is wrong.
The passes do not converge, because each new heuristic brings its own structural blind spot. Two
disagreeing passes tell you only that at least one is wrong, never which.

**Reading all nineteen sites took less time than the four passes did, and it was right the first
time.** It also moved the count twice more (9 stops → 11), both times in the same direction.

**So: for a corpus you can read, read it.** Scripts are for corpora too large to read — and when
you use one there, its output is a CANDIDATE LIST whose closure condition is a read, stated in the
artifact so nobody later mistakes the candidates for the answer.

### A failing test is a CLAIM about what should change, and the claim is checkable
A red test proposes a repair. That proposal is an argument, not an instruction — and the
pressure to obey it is strongest exactly when the test looks principled.

2026-08-10. A newly written guard asserted ADR-0040 header conformance over every packet with
frontmatter. It failed two packets carrying a **June convention** — prose statuses, no `id` —
i.e. it failed them for not conforming to a spec written six weeks later. The repair it pushed
toward was: invent an `id`, flatten a prose status the author would be *interpreting*, and
fabricate a `closed-by` sha nobody had. Each step is a defect this catalogue already names, and
all three arrived by trying to satisfy a test.

**The second-order consequence is why this ranks above ordinary test-fixing.** The fabricated
sha would then have passed the attribution seal — so the wrong repair would have been
**laundered into looking evidenced**. A downstream check does not merely fail to catch a bad
repair upstream of it; it CERTIFIES it. Provenance machinery is only as honest as the first
value entered into it.

The repair was to fix the test's SCOPE: assert conformance only over packets *claiming* it (an
`id:` present), and let legacy packets be disclosed by a coverage line rather than coerced.
**Ask what the test is entitled to assert before asking how to make it pass.**

### A field demanded by a failing check is load-bearing; a field added from a review list is a guess
Same day, same exercise. A review listed five findings, one of which was "the marker seal needs a
`code-site:` field". Independently, the newly implemented attribution check *failed* on a real
item — the closing commit touched the code, not the packet — and the only honest fix was to
declare where the item lives. The field arrived **demanded by** a check rather than **satisfied
because listed**, and that provenance is the difference between a field whose shape is proven by
use and one whose shape is a guess.

When a review yields a list, prefer the items another fix forces into existence. The rest are
hypotheses until something needs them.

### A parser bug wearing a data error's clothes is the most expensive kind to read
`\s*` matches NEWLINES. An empty `closed-by:` therefore consumed its own line break and captured
the following line, and the tool reported `closed-by: repo: invincible-agent does not resolve` —
**accusing the data**. The next twenty minutes go to verifying facts that were never wrong.

Match spaces and tabs explicitly (`[ \t]*`) when parsing line-oriented formats. And when a tool
reports that your data is malformed in a way the data could not plausibly be, suspect the reader
before the read.

### A guard going QUIET and a guard going GREEN are indistinguishable in a summary line
The inverse of the rule above, and a distinct species. That one is a probe reporting zero because
it cannot see. This is a guard reporting zero violations **because nothing it watches exists any
more** — its subjects migrated out of scope, and it kept passing, forever, about nothing.

2026-08-08. Seven pyprojects carried `provenance-telemetry` as a bare git URL, tracked as named
debt in a `_KNOWN_UNPINNED` allowlist so the floating-dependency guard could still block NEW
violations. The package was then published to PyPI and all seven became
`provenance-telemetry==0.1.0`. Emptying the allowlist looked like the debt closing. It was not:
**every test in that file matches on `git+`**, so the moment those became index requirements they
left the guard's jurisdiction entirely. The allowlist would have read as resolved while the check
had gone blind — and the suite would have been greener, not less informative-looking, for having
stopped checking.

Note the shape of the trap: nothing failed, nothing was deleted, and no one made a mistake. A
dependency changed *syntax*, and a guard silently retired. **Subjects migrating out of scope is
how guards retire without anyone deciding** — the supply-chain form of the same undecided-change
class the pin doctrine exists to forbid.

**The paired rule: every scope-defined guard asserts that its scope is INHABITED.** "This guard
currently watches N declarations, N > 0" is the assertion that separates *clean* from *vacant*;
without it the two render identically. Pair it with a break-on-purpose that shows selectivity —
one violation must fail its own case and nothing else — and the guard has proven both that it
looks and that it bites.

And when an obligation crosses a representation boundary, **re-home it rather than retire it**.
The rule here was never "git refs must be pinned"; it was *a build input nobody decided is
forbidden*. On an index that same failure wears different syntax — a bare name resolves to
whatever is newest at build time — so the guard follows the rule, not the syntax it first met it in.

### A range on a fleet-governing dependency is a floating ref with a ceiling
Same 2026-08-08 repin. `>=0.1.0,<0.2` is narrower than `@master` and the same species: an upstream
publish still changes seven components' behaviour on their next rebuild, with nobody deciding and
no diff in this repo to review. The ceiling bounds the blast radius; it does not restore the
decision.

**The discriminating question is not "how risky is the upgrade" but "does this upgrade deserve a
visible diff?"** For a leaf governing fleet telemetry — whose replay-safety semantics were settled
by a week of manufactured-replay witnesses — yes, and `==` is precisely the mechanism that routes
that decision to a human. For a third-party utility, usually no, and a range is right.

Corollary, because the class recurs one level down: a leaf's OWN unbounded dependency is the same
defect inherited. `provenance-telemetry` declares `langfuse>=3.0.0` with no upper bound while
targeting v3/v4, so a future langfuse 5 would arrive unreviewed inside the package whose entire job
is replay-safe span semantics. **Pin doctrine applies to what you publish, not only to what you
consume.**

**Loosen deliberately; never inherit silently.**

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

### A grep proves presence; it NEVER proves absence of behavior
The inverse of the membership error, and the fourteenth probe-correctness instance. The route
conflation claimed an EDGE that did not exist from a PROPERTY that did (middleware possession vs
verb-edge reachability). This one claims a GAP that does not exist from an ABSENCE that does.

Measured 2026-08-06. Grepping `provenance_telemetry` and doc-tools for `flush|atexit|shutdown`
returned nothing, and that true observation was turned into a false conclusion — "spans at risk on
short-lived jobs" — which then led a live diagnosis. The read that settled it was one level down:
the langfuse SDK registers `atexit.register(self.shutdown)` itself
(`_client/resource_manager.py:279`, and the OTel TracerProvider at `sdk/trace/__init__.py:1347`),
with the SDK's own docstring stating that relying on it "is sufficient". No amount of grepping the
CALLER could have shown that, because the behavior is registered by the DEPENDENCY.

**So: absence in your source is not absence in your process.** Before concluding a gap from a
missing call, read what the libraries in the call path already register — atexit hooks, signal
handlers, context managers, `__del__`, framework lifecycle hooks. The evidence was also sitting in
plain sight and was ignored: traces WERE landing, which is only possible if something flushed.
**When a claimed gap contradicts observed behavior, the gap is wrong, not the behavior.**

Narrow the claim rather than dropping it: explicit flush still buys something where atexit never
runs — SIGKILL, OOMKill, eviction, `os._exit`. That is the same mechanism as the shared-fate rule
above: **atexit covers cooperative shutdown; nothing covers murder.** An instrument that must
survive being killed needs its evidence somewhere the process's death cannot reach — the journal, a
completing retry's log, an external counter.

### A fix attached to a non-bug gets remembered as the cause
The stale-record rule applied PROSPECTIVELY: do not mint the misleading record in the first place.

2026-08-06's "missing traces" turned out to be zero telemetry loss — the trace id is seeded on
`doc_id`, so re-runs APPEND to one trace and never surface in a recency-sorted UI. During the sweep
a genuine-but-unrelated improvement surfaced (an explicit `flush()` at the job boundary). Landing it
"in response" would have written a false causal record into history: the next person chasing a real
missing trace finds that commit, concludes flush-placement is the known failure mode here, and
spends their afternoon in the wrong layer.

**So: the repair must match the ACTUAL defect, or the repair is itself a defect — in the audit
trail.** Same discipline as refusing to widen an entitlement to make a seal pass. Land the unrelated
improvement on its own merits, uncoupled, with a commit message that says what it is ("shortens the
buffered window on abnormal exit") and not what it isn't. And fix the real thing, which here was
that NOTHING said the semantics were append-by-design — a one-line comment at the seed site is the
cheapest afternoon anyone will ever buy back.

### A guard that FAILS instead of SKIPPING when its precondition is absent is anesthesia
The third species in the lying-result family, and a new one. The first two were greens that lie
(pass without the mechanism under test existing) and reds that lie (measure the instrument, not the
system). This is a red that means NOTHING — and says so 35 times per run.

Measured 2026-08-05. `tests/routing/test_phrasing_independence.py` documents itself as "Skips if
Engine O isn't reachable"; the skip guard does not fire, so with no port-forward to `localhost:8084`
it emits 35 `ConnectionError` failures instead of 35 skips. Every one is an environmental fact
wearing a defect's clothes.

**The cost is not the failures — it is the TRAINING EFFECT.** A suite that cries wolf teaches every
reader to wave through red, and that acquired immunity is exactly what makes the one real red
invisible. The rule's own family depends on red being scarce enough to be attacked: "a false red
gets believed because nobody attacks it" only holds while someone is still looking.

**So: a suite's signal-to-noise is itself an instrument property, subject to the same discipline as
any probe.** A precondition that is absent is a SKIP; a precondition that is present and unmet is a
FAILURE. Collapsing the two converts environment into noise, and noise at volume is anesthesia.

The adjudication tax is the part worth recording, because it is already paid: every before/after
comparison in the 2026-08-05 telemetry arc had to carry a 35-red baseline exclusion BY NAME, and
each exclusion had to be re-established by stashing the change and re-running to prove the failures
predated it. That labor — repeated per session, per adjudicating agent — is what a broken skip-guard
levies on everyone who adjudicates honestly. The repair is one guard; the debt compounds per run.

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

### Read the RUNNING POD, not the deployment's `env[]` — `envFrom` is invisible there
2026-08-13, and it produced a confident false finding that was one commit from becoming a board
item. `kubectl get deploy -o jsonpath='{...containers[0].env[*]}'` shows ONLY inline env vars; a
cluster that supplies config via `envFrom: [configMapRef, secretRef]` shows NOTHING there. Reading
that empty result as "the env is unset" produced two wrong claims — that engine-o's gate had an
unmet precondition, and that engine-a's `check_can_invoke` was denying on a missing URL rather than
on Topaz's answer. The second was the dangerous one: it would have discredited a ceremony baseline
that is in fact sound.

**So: for "is this configured?", exec the RUNNING POD and read the process environment.** The
deployment spec is a partial view by construction — the same class as a windowed probe output,
one layer down, and the fourth instance of partial-read-as-complete in a single session.

Note the shape of the near-miss: the false finding was *plausible*, *specific*, and *consequential*,
which is exactly the profile of a claim that gets acted on. It was caught only because the next step
— filing the board item — required re-verifying the fact, and the re-verification used a different
method. **A finding worth filing is worth re-reading by a second method before it is filed.**

### A BRIEFING is an unreliable source — the board and the suite outrank it
2026-08-13, and the instance is the useful part: an agent was briefed that two items were open —
twelve undeclared manifest routes with three red tests, and an unheadered handoff needing
disposition. **Both had been done days earlier.** The rows landed on the 12th and the suite read
15/15 green; the handoff had been filed to `docs/plans/archive/` by a commit the briefer had
themselves ratified in detail. The briefing came from conversational memory, which is precisely the
source ADR-0040 replaced — and it was stated as fact, in the voice of the person who ruled it.

**So: a briefing describing repo state is INPUT, not a premise. Check it against the suite and the
packet header BEFORE working from it** — a red test is a checkable claim and a header is a written
one; a recollection is neither. Cheap to verify: two greps and a `pytest` run against the named
suite. The failure this prevents is not doing the wrong work, it is doing ALREADY-DONE work and
reporting it as new, which corrupts the record in the one direction nothing downstream can detect.

**Check in BOTH directions.** The verification that made this correction complete was not only "the
rows are green" but also "the archive is out of the board's scope BY CONSTRUCTION" (`_blocks()`
globs `docs/plans/*.md` non-recursively) and "the carried items were dispositioned BEFORE archival"
(`02209da` closed PCN-2683 as test-campaign residue). A half-check would have found the stale half
and inherited the rest.

Sibling of *a ruling made in CONVERSATION is UNSHIPPED until committed* — same root, opposite
direction: there the conversation held something the repo lacked; here the conversation lacked
something the repo held.

**SECOND INSTANCE, 2026-08-19 — and it generalises the rule from FINDINGS to WORK.** An overnight
job was commissioned: *"read `PcnGroupedReview` against the three step kinds, produce the PCN
process as a draft definition YAML, enumerate what doesn't fit."* Genuinely hours of work, scoped
carefully, fenced properly. **All three deliverables already existed.** `PcnGroupedReview` is in
a FORBIDDEN list in `tests/test_cross_repo_contracts.py` — a green 9-test deletion seal barring it
and six sibling names from the mechanism. The draft YAML is `policy/workflows/grouped_review.yaml`
(`2d268b7`, **2026-07-26**), and it answers the commissioned question in its own header: the
three-kind model expresses PCN with **ZERO new step kinds**, the fan-out dissolving into the
substrate exactly as the ruling said. The commission was formed from conversational memory of the
arc as of 2026-08-04; the answer had been in the repo since **July 26**.

**So: PREMISE-CHECK BEFORE COMMISSIONING WORK, as the sibling of second-method-before-filing.**
Both are one move — *verify the ground before building on it* — aimed at opposite ends of the
pipeline:

> **Second-method before filing a finding. Premise-check before commissioning work.**

**The argument is arithmetic, not discipline.** Checking the M3 premise cost FOUR TOOL CALLS.
Producing the document `2d268b7` already is would have cost the night. At that ratio the check is
not a virtue to be summoned, it is the cheaper branch — and it is cheapest precisely when the
commission is well-scoped, because a careful brief is the kind most likely to be believed without
checking.

**The check has two outcomes and BOTH are wins.** The same session ran it against a second
commission (the presentation-SPO enumeration, ADR-0017 "Hole 4") and that premise **survived with
a correction**: the capability publication DOES carry a shape contract (`expected_fields`, field
NAMES) and does NOT carry types or cardinality. That correction shrank the job from *build a
publication mechanism* to *extend an existing seam* — a materially smaller and better-anchored
piece of work than the one commissioned. A premise check does not only cancel work; it re-scopes
it, and the re-scoping is usually the more valuable half.

### ANY RESULT SET EQUAL TO ITS LIMIT IS UNVERIFIED UNTIL COUNTED
2026-08-21, mid-investigation, in a session ABOUT wrong findings. A scan of the ontology
substrate at `limit:400` returned **exactly 400 rows**, and the conclusion drawn from it —
that `mesh:OwnershipFact` was undeclared — was a **FALSE NEGATIVE**. The substrate holds
**7023**. The finding was one commit from landing in a packet as a missing declaration that
is not missing.

**A scan that returns exactly its limit is a truncated scan wearing a complete one's
clothes.** Nothing in the output says "there is more"; the row count looks like an answer,
and a round number at the boundary is the only tell.

**So: before drawing a negative conclusion from a query, COUNT the population.** One
aggregate call. Then either raise the limit past the count or — better — ask the targeted
question directly, because a targeted lookup has no limit to hide behind. The corrected
table in that investigation came from per-IRI lookups; the truncated scan was discarded
rather than patched.

This is the sixth member of the truncated-read family and the cheapest detector yet. Its
sibling one layer up is the `head`-limited grep that produced an "11 rows / 5 components"
plan for a 14-row table (see the deletion law below): **same defect, different tool, same
tell — the output ended where the flag said, not where the data did.**

**Negative conclusions are the dangerous direction.** "X is absent" from a windowed read is
an assertion about everything you did not look at. A positive hit from the same read is
still true.

### A DELETION TARGET NAMED BY FILENAME HIDES HOW MANY JOBS THE FILE HOLDS
2026-08-20, twice in one build, in the same direction. An acceptance said **"delete
`chart_normalizer.py`"** — the file also held `honest_text_from_response`, correct code in
the wrong home, load-bearing for the honest-degradation path. An acceptance said **"delete
`capabilities.py`"** — the file held THREE exports with three different consumers, and one
of them, `PRESENTATION_CAPABILITIES`, seeds the `rendersAs` triples into the mesh graph at
Engine F startup. **That is the presentation-as-predicate registration ADR-0017 is named
for.** Deleting the file would have silently stopped it, and the symptom — specialist
outputs losing their renderers — would have surfaced days later at render time, three layers
from a commit that claimed completion.

Both acceptances named a **FILE** when the claim was about a **ROLE**. The role really was
dead each time; the file was not.

**So: an acceptance that DELETES must enumerate the target's exports and disposition each
one — remove, relocate, or keep-with-reason — BEFORE the deletion is scoped.** That is
[[consolidation-completes-at-the-last-consumer]]'s enumerate-the-consumers check pointed at
the thing being REMOVED rather than the thing being added, and it costs one grep per export.

**The detection is the tell, and it is the same arithmetic as the premise check above: the
WORK found the extra jobs, not the plan.** In both cases the deletion was scoped from a
filename and corrected only when someone opened the file to remove it. A plan that names a
file has not yet looked inside it.

Sibling disposal rule, from the same build: **a property with two owners is not lost when
one owner retires.** Four tests died with `lookup_capability`; the compact-vs-full IRI
folding they guarded is still pinned where the helper lives, and the registry pins the same
match behaviour independently. Keeping tests for a deleted function is the corpse-guarding
inversion — tests protecting the thing they described rather than the property it served.

**Corollary — conversational shorthand does not exist in the repo.** "Hole 4" appears NOWHERE in
`ADR-0017-presentation-as-predicate.md`; it is a chat-side label. A future agent grepping for it
would conclude the finding did not exist. **A commissioned packet must use the ADR's own
vocabulary and cite the code by file and line**, or it inherits a name only the transcript can
resolve — which is the same defect one layer up.

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

**RETIRED 2026-08-17 — the index lives in [`docs/adr/README.md`](docs/adr/README.md), and only there.**

This table was a SECOND index of the same corpus and it stopped at 0013, so a reader
trusting it concluded twenty-eight ADRs did not exist — an abandoned index does not go
quiet, it lies. Two homes for one corpus is the two-homes defect this file names
everywhere else; the disposal is a pointer, not a backfill.

When adding a load-bearing architectural change, draft an ADR in `docs/adr/` following the
template of the most recent ones, and add its row to the `docs/adr/README.md` index in the
same commit — **a decision record the index does not route to is findable only by people
who already know it exists.** (Generating that index from the ADRs' own headers is owed:
see the OWED 2026-08-17 section of [`docs/plans/board-migration.md`](docs/plans/board-migration.md).)
