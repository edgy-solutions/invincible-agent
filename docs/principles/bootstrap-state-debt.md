# The bootstrap-state-debt law

> **Deployed state must be reproducible from `helm install` alone. Direct durable-store
> mutation is never a fix.**

If a running cluster's substrate (Neo4j edges, Weaviate collections, Jena triples, Postgres
rows, DataHub entities) can only be made correct by someone remembering to run a script, that
is **debt, not a fix** — it reverts the moment the store is re-primed, a fresh cluster stands up,
or a cutover happens. The fix belongs in the reproducible path: a helm Job, a Dagster ingest
asset, `prime_databases.py`, or CI — the *source of authority* ([[ADR-0006]]).

This law is the general form of the **phase5 class** (`[[project_phase5_prophecy_resolved]]`):
a `scripts/phase5_catalog_verb_migration.py` that hand-`MERGE`d subClassOf edges while its
docstring *falsely* claimed they "land at TTL ingest" — so every fresh cluster silently lost
the edges and catalog routing fell to the generalist. The resolution was source-authority:
fold the edge creation into `sync_jena_ontologies_to_neo4j` (doc-tools, commit `3dbc83a0`), so
`helm install` + the ingest asset reproduces them. That is what *every* such gap must become.

## Why "direct mutation is never a fix"

A durable-store write from a hand-run script is invisible to the thing that rebuilds the store.
It passes a readback (the row/edge is there) while being absent from the reproducible definition
— the same *presence-in-repo ≠ presence-in-running* / *committed ≠ running* trap
(`[[feedback_presence_in_repo_is_not_presence_in_running_system]]`), on the substrate. "It works
now" is not "it reproduces." The only durable state is state a fresh `helm install` recreates.

## Enforcement — three places, not just this doc

A law that lives only in prose is vigilance, not machinery. This one is enforced:

1. **The fresh-namespace bootstrap test is the executable definition of compliance.**
   `tests/test_bootstrap_reproducible.py` stands up a throwaway namespace, runs `helm install`
   + the gated seed Jobs (no hand-run scripts), and asserts routing reaches green (the Neo4j
   probes: idp classes present, subClassOf edges formed, verbs registered). **A dependency that
   only a hand-run script satisfies fails this test by construction** — that is the definition
   of "done."
2. **Refuse-to-run guards on every `scripts/` file that mutates a durable store**
   (`scripts/_bootstrap_guard.py`, in the ack-flag style already on the two footguns). Each such
   script calls the guard at entry: a **work-shaped target is refused outright — no flag
   overrides it**; a sandbox target still requires an explicit ack env-flag AND is told the
   reproducible fix must land the same session. The invalid action refuses loudly, like every
   other gate in this system.
3. **An honest docstring on every such script**, naming it a **non-reproducible manual action**
   and pointing at its reproducible home. A script must never claim the pipeline does what it
   doesn't (the phase5 docstring lie is the anti-pattern this forbids).

## Exceptions — stated so they are not loopholes

- **Read-only diagnostics are always fine and encouraged.** Inspecting the substrate (counts,
  probes, `git`-style reads) mutates nothing and needs no guard.
- **A hand-run is acceptable only as an *acknowledged throwaway* whose reproducible fix lands in
  the same session.** Never *hand-run-then-fold-later* — the revert lives in "later." If you
  mutate a store by hand to unblock, the helm/asset change that makes it reproducible ships
  before you move on, or you have created debt, not a fix. (This is why the guard prints the
  same-session obligation, and why the bootstrap test is the receipt.)

## When you arrive here from a substrate incident

Ask: *what reproducible artifact should have created this state?* Put the fix there (asset/Job/
CI), make any script that also does it honest + guarded, and add the missing assertion to the
bootstrap test so the gap can never silently reopen. The script becomes a diagnostic or an
acknowledged-throwaway; it is never the fix.
