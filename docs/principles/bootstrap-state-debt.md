# The bootstrap-state-debt law

> **Deployed state must be reproducible from `helm install` alone. Direct durable-store
> mutation is never a fix.**

## Definition of done (read this first)

A change to this system is **done** when:

> A fresh, empty namespace that got **only** `helm install` (chart + its gated seed Jobs, **zero**
> hand-run scripts from `scripts/`) reaches **working routing AND delivery AND rendering** — a
> catalog subject resolves to its verbs, a data query returns real rows through the broker, and a
> result renders through a registered presentation capability instead of the legacy fallback.

That is the whole law in one sentence. Everything below is why, how it's enforced, and what to do
when you arrive from an incident. The three-way widening — *routing* **and** *delivery* **and**
*rendering* — is itself a finding: the debt was first found in routing (subClassOf edges), but it
lives in all three layers, so "done" has to assert all three, not just the one that broke last. The
*rendering* leg earned its place concretely (commit `a1ada51`): a nuclear wipe cleared the
once-seeded `mesh:rendersAs` triples, the presentation agent couldn't re-register them from a slim
image, and specialist answers rendered as **blank cards** — a routing-green cluster that was
delivery- and rendering-broken. A definition of done that stopped at routing would have called that
cluster healthy.

If a running cluster's substrate (Neo4j edges, Weaviate collections, Jena triples, Postgres rows,
DataHub entities, Redis routes) can only be made correct by someone remembering to run a script,
that is **debt, not a fix** — it reverts the moment the store is re-primed, a fresh cluster stands
up, or a cutover happens. The fix belongs in the reproducible path: a helm Job, a Dagster ingest
asset, `prime_databases.py`, or CI — the *source of authority* ([[ADR-0006]]).

This law is the general form of the **phase5 class** (`[[project_phase5_prophecy_resolved]]`): a
`scripts/phase5_catalog_verb_migration.py` that hand-`MERGE`d subClassOf edges while its docstring
*falsely* claimed they "land at TTL ingest" — so every fresh cluster silently lost the edges and
catalog routing fell to the generalist. The resolution was source-authority: fold the edge creation
into `sync_jena_ontologies_to_neo4j` (doc-tools, commit `3dbc83a0`), so `helm install` + the ingest
asset reproduces them. That is what *every* such gap must become.

## The sibling invariant — a running cluster can't silently drift from source

The definition of done is the **forward** direction: a fresh cluster reaches working state from
`helm install` alone. It has a sibling the forward direction does **not** imply — the **ongoing**
direction: *a running cluster, once built, must not silently drift from its source.* The reproducible
path being **correct** does not make a **running** cluster **current** — a cluster stood up at time T
does not follow a source change at T+n unless something re-runs the ingest.

This week's B(2) close is the proof. `mesh_system.ttl` gained the `InstanceIdentifier` /
`InstanceResolution` classes at some point; the cluster's Jena→Neo4j sync predated that; **no
mechanism noticed the gap for weeks**, until a human ran a probe and it turned out to be staleness,
not a sync bug. The long survival of the lowercase graph-map was arguably a second instance. Both
drifts were found by a human probing; neither by the system noticing — that is the gap.

The cure has the shape of the machinery that healed it (a per-TTL partition run), in ascending
ambition:

1. **Runbook rule (do now):** a TTL edit runs its partition in the same PR. Cheap, human-enforced.
2. **Checksum drift-check (ITEM-C LIST — the actionable next rung):** store each partition's source
   TTL hash at ingest; a probe-style check compares live source hash vs last-ingested hash per
   partition. This turns *"is the cluster stale?"* from an **investigation** into a **query** — the
   same move that turned "does the sync drop long comments?" from a mystery into a Cypher line.
   Deterministic, no LLM, no teardown. It is the sibling of "fresh empty cluster reaches working
   routing with zero hand-run scripts": *a running cluster can't silently drift from source.*
3. **Dagster source-sensor (do NOT build now):** auto-trigger a partition when its TTL changes. Full
   automation; deferred — the checksum query is the high-leverage rung, not this.

Drift is this law read in the time dimension: *only state a fresh install recreates is durable*
(forward) **+** *only a cluster that follows source is current* (ongoing).

## The same law in the DEPENDENCY dimension — a passing environment over a broken declaration

Third dimension, found 2026-08-11. The law reads *only state a fresh install recreates is durable*
(forward) **+** *only a cluster that follows source is current* (ongoing) **+ only dependencies the
declaration names are actually yours.**

`dag_tools/central_gateway/main.py` imports `redis` and `jwt` at **module level**, and neither was
declared in the `broker` extra. So `pip install "dag-tools[broker]"` — the documented, declared
way to install the gateway — produced a service that **could not import at all.** It worked
everywhere it had ever been run, because something else in those environments happened to pull
both in transitively.

**This is the hand-seeded cluster wearing a virtualenv.** The environment that works is not the
environment anyone declared, the gap survives indefinitely because the working environment never
exercises it, and the first person to install the declared way inherits a break they did not
cause. Same shape as the `iagent-mesh` dev-group defect: *a passing environment over a broken
declaration, invisible until someone installs it the declared way.*

**Why it is worse than the cluster case, and worth its own line:** a hand-seeded cluster fails
loudly for the next person who builds one. A transitively-satisfied import fails for a *stranger* —
whoever first consumes the package as published — and the failure surfaces in their environment
with your name on it. The forward-direction test ("a fresh install reaches working state with zero
hand-run steps") is the same test; only the substrate changed from a namespace to a virtualenv.

**The check:** for any module a deployment imports, the extra that ships it must name every
module-level import. Transitive availability is not a declaration — it is a coincidence that has
not been disturbed yet.

## Why "direct mutation is never a fix"

A durable-store write from a hand-run script is invisible to the thing that rebuilds the store. It
passes a readback (the row/edge is there) while being absent from the reproducible definition — the
same *presence-in-repo ≠ presence-in-running* / *committed ≠ running* trap
(`[[feedback_presence_in_repo_is_not_presence_in_running_system]]`), on the substrate. "It works
now" is not "it reproduces." The only durable state is state a fresh `helm install` recreates.

**The sandbox is the worst possible reproducibility oracle.** It is never torn down, so every
hand-run accretes into it invisibly and *stays* — "it works in sandbox" quietly means "it works in
the one cluster that has accumulated every manual step anyone ever ran." Only a **throwaway
namespace** that gets nothing but `helm install` can tell you the truth. That is why the definition
of done is written against a fresh namespace and nothing else.

## How this happened (the frame, not the blame)

This was not one bad decision. It was months of individually-reasonable "hand-run now, wire the
reproducible path later" against a sandbox that never got bootstrapped from empty — so "later"
never arrived and nothing forced the question. Any agent (human or model) building against a
long-lived cluster drifts here by default; the sandbox rewards it every single time. The point of
writing it down is not to attach the pattern to whoever hit it — it is to convert a habit that felt
free into an operating rule that has a cost attached at the moment of the shortcut, not months
later on someone else's fresh cluster. Read the morals as *"here is the trap and the tripwire,"*
never as *"here is who tripped."*

## The morals — checkable where they can be

These are the specific failure shapes this law generalizes. Each names the trap, then the check
that catches it (built, or specified-and-owed).

**Moral 1 — Reproduce from source authority, not from the store's current contents.**
The fix goes where the store is *rebuilt* (asset / Job / CI), never as a write to the live store.
*Check:* `tests/test_bootstrap_reproducible.py` — the fresh-namespace probe; a hand-seeded
dependency fails it by construction. **Built (cluster-gated).**

**Moral 2 — A missing prerequisite on the bootstrap/registration path must block a green
*somewhere*, not just emit a warning.**
This is subtler than "raise, not warn," and the subtlety matters. Registration is *deliberately*
non-fatal at the serving engine: `register_engine_to_mesh` logs-a-warning-and-returns on failure
(`agent_fleet/utils/mesh_registration.py`, per ADR-0006 — a bad registration must not DoS a serving
engine; this is `[[feedback_trailing_steps_nonfatal]]`), and Engine F wraps each
`register_presentation_to_mesh` in `except Exception → logger.warning(...)` on top of that. So
**every engine in the fleet warn-and-continues on registration**, and that is correct *at the
serving layer*. The bug is not the warning. The bug is when the warning is the *only* signal —
Engine F "came up green" with its presentation capabilities silently unregistered, `/render_ui`
silently falling back to legacy BAML, and **nothing downstream re-asserted that the registrations
landed.** A warn-and-continue is safe **iff** an aggregate reproducibility gate re-checks the
outcome; without that gate the warn *is* the hole. *Check:* the same fresh-namespace bootstrap
test is that aggregate gate — but it is **skipped by default today**, so the fleet-wide
warn-and-continue is currently caught *nowhere*. **Owed: make the aggregate gate actually run**
(throwaway namespace in CI), because it is the single place this whole class becomes visible.
*Discovery aid (not a blocking lint — the warn is intended, so a blanket lint would false-positive):*
grep the fleet for `register_*_to_mesh` call sites and confirm each is backstopped by the aggregate
gate, not just by its own log line.

**Moral 3 — A fix to one writer of a shared resource is unverified until you have enumerated
*every* writer, because the store will happily let the wrong one win the race.**
Durable stores are first-writer-wins on a shared key: whoever creates the collection / schema /
node first fixes its shape, and every later writer either no-ops or silently diverges. So a fix
applied to *one* writer looks applied — the readback is green — while a *different* writer, earlier
in the boot race, already wrote the wrong shape and won. **Worked example (Predicate collection):**
`register_engine_to_mesh` and `seed_sandbox_predicates.py` and Weaviate's own auto-schema-on-first-
insert are *all* potential first-writers of the `Predicate` collection's schema; a fix to the seed
script is worth nothing if an engine's auto-insert races ahead of it and creates the collection with
the default vectorizer. This is the substrate twin of the endpoint-audit finding (one route gated,
the family ungated — see `[[project_endpoint_gating_audit]]`): *fixing one instance of a class is
not fixing the class.* *Check / procedure:* before declaring a shared-resource fix done, run the
**enumerate-all-creators** procedure — grep every writer of that key (`.collections.create`,
`MERGE (…)`, `CREATE TABLE`, auto-create-on-insert), confirm they converge on one declared shape or
that exactly one is authoritative and the rest refuse. Owed as a documented procedure with the
Predicate case as the worked example.

**Moral 4 — A capability's own production dependencies must be declared on *that* service, not
assumed present.**
A slim production image is built with `uv sync --no-dev` (or just the service's own `pyproject`). An
import the running image *cannot resolve* degrades the capability to a silent skip and comes up
green. **Worked example (commit `a1ada51`):** the presentation agent registers `mesh:rendersAs`
triples by emitting to DataHub *directly* (its triple shape has no mesh-registrar gateway path), so
it — alone among the six capability-registering engines — *requires* `acryl-datahub`. Its `pyproject`
was the only one that omitted it, so at work every presentation registration silently skipped
(*"acryl-datahub is not installed"*); with no `rendersAs` triple, `generate_ui_payload` emitted an
empty payload, `rendered_output` persisted `NULL`, and the answer card rendered blank. It "used to
work" only because the triples were seeded pre-wipe — the exact bootstrap-state-debt story, one
layer up from routing. This is the same "green with a hole" as moral 2, sourced in packaging: the
missing dep turns registration into a no-op, and the no-op is only caught if something re-asserts the
aggregate (moral 2's gate). *Check (specified, owed):* a CI step that, per service, asserts the
service's own dependency set resolves every import on its startup path — i.e. the shipped image can
actually import what it runs.

## Enforcement — three places, not just this doc

A law that lives only in prose is vigilance, not machinery. This one is enforced:

1. **The fresh-namespace bootstrap test is the executable definition of compliance.**
   `tests/test_bootstrap_reproducible.py` stands up a throwaway namespace, runs `helm install` + the
   gated seed Jobs (no hand-run scripts), and asserts routing/delivery/rendering reach green. **A
   dependency that only a hand-run script satisfies fails this test by construction** — that is the
   definition of "done." (It is cluster-gated and skips offline; moral 2's owed item is to make it
   *run*, since it is also the aggregate backstop for the fleet-wide registration warn-and-continue.)
2. **Refuse-to-run guards on every `scripts/` file that mutates a durable store**
   (`scripts/_bootstrap_guard.py`, sealed by `tests/test_bootstrap_guard.py`). Each such script calls
   the guard at entry: a **work-shaped target is refused outright — no flag overrides it**; a sandbox
   target still requires an explicit ack env-flag AND is told the reproducible fix must land the same
   session. The invalid action refuses loudly, like every other gate in this system.
3. **An honest docstring on every such script**, naming it a **non-reproducible manual action** and
   pointing at its reproducible home. A script must never claim the pipeline does what it doesn't
   (the phase5 docstring lie is the anti-pattern this forbids).

## Exceptions — stated so they are not loopholes

- **Read-only diagnostics are always fine and encouraged.** Inspecting the substrate (counts,
  probes, `git`-style reads) mutates nothing and needs no guard.
- **A hand-run is acceptable only as an *acknowledged throwaway* whose reproducible fix lands in the
  same session.** Never *hand-run-then-fold-later* — the revert lives in "later." If you mutate a
  store by hand to unblock, the helm/asset change that makes it reproducible ships before you move on,
  or you have created debt, not a fix. (This is why the guard prints the same-session obligation, and
  why the bootstrap test is the receipt.)

## One master, don't fork

Keep the reproducible definition in **one** place per resource, and keep the repo on **one** master
you actually deploy from. The failure mode is identical to everything above: state (a config, a
seed, a branch) that lives in a second place diverges from the first *silently*, and the store —
or the cluster, or the reader — happily serves the stale one. A forked master is a durable store you
forgot you were writing to.

## Two ways to carry this (both agents bank it, differently)

This law is banked twice on purpose, because the two vantage points need different artifacts:

- **The operating agent carries it as discipline** — *this document.* When you hit a hand-run: open
  the fold-into-source change in the same breath, fix at the source of authority ([[ADR-0006]]), and
  never hand-run-then-fold-later. The morals above are the tripwires to run *before* you call
  something done.
- **The audit agent carries it as a debt inventory + closure state** — the running list of every
  script that still mutates a store, which are folded into a reproducible home vs. still owed, which
  are Tier-3 archival candidates, and the systemic moves that retire them (promote demo seeds to
  gated Jobs; enumerate-all-creators on each shared key; make the aggregate gate run). Discipline
  prevents new debt; the inventory closes the debt already on the books. Neither substitutes for the
  other.

## When you arrive here from a substrate incident

Ask: *what reproducible artifact should have created this state?* Put the fix there (asset/Job/CI),
make any script that also does it honest + guarded, run the enumerate-all-creators check on the
shared key you touched (moral 3), and add the missing assertion to the bootstrap test so the gap can
never silently reopen. The script becomes a diagnostic or an acknowledged-throwaway; it is never the
fix.
