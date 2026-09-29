# Measurement — what the pinned SDK's surface actually contains, and what the realm can express

**Date:** 2026-09-28 · **Lane:** `ia-74/lane/74` · **Subjects:** SDK pin `8e4a881`, the fleet's
Weaviate/Neo4j write paths, and `keycloak.serviceClients` in the chart.

**Occasion.** Building the two halves of an overnight packet — the mesh writer implementations and
the delegate credential's fleet side. Everything below was found by *writing against* these
surfaces rather than by reviewing them, which is why it is a measurement and not an audit.

> **How to read the figures.** Every claim carries the command that produced it. Where a figure I
> had already written down turned out to disagree with a re-derivation, **both** are shown and the
> disagreement is the finding — see §1.3 and §6.2, which are about my own earlier numbers.

---

## 1. The pin is not the tree, and two contracts exist only in the tree

### 1.1 What is absent at `8e4a881`

`iagent_mesh/delegate_identity.py`, `check_graph_writer_contract` and
`check_vectors_writer_contract` **do not exist at the pinned sha.** They are on the SDK's `lane/ca`
at `1f7af84`, and in **no tag**.

```bash
git -C ../iagent-mesh-sdk ls-tree 8e4a881 iagent_mesh/     # no delegate_identity.py
git -C ../iagent-mesh-sdk show 8e4a881:iagent_mesh/conformance.py | grep -c writer_contract   # 0
```

**Consequence, and it is not "upgrade the pin".** A lookup reported `delegate_identity.py` as
available — it had read the SDK's **working tree**, which is checked out at the lane branch. The
fleet side is therefore written natively and agrees with the SDK by **matching the claim contract**
(`DELEGATE_SUBJECT_CLAIM`, `DELEGATE_ON_BEHALF_OF_CLAIM`) rather than by importing it. Importing
would have moved the fleet's pin as a side effect of a feature.

**A dependency's capability is a property of the pinned sha, not of the checkout next door.**

### 1.2 The pinned conformance surface has no writer-specific arm

The pin's `conformance.py` offers `check_writer_offline`, `check_writer_marker` and
`assert_fixture_discriminates` — all shape-agnostic. Neither a graph-specific nor a vectors-specific
arm exists at the pin, and both exist upstream. The writers' green is therefore a statement about
the pinned object; verified byte-identical rather than assumed:

```bash
diff <(git -C ../iagent-mesh-sdk show 8e4a881:iagent_mesh/conformance.py) \
     .venv/Lib/site-packages/iagent_mesh/conformance.py     # identical
```

Reading the tree-only `check_vectors_writer_contract` is what found the `relocate` defect in §6.1,
so **the gap between pin and tree is not inert: it holds working checks.**

### 1.3 The pin calls itself `0.9.4` and is not `v0.9.4`

```bash
git -C ../iagent-mesh-sdk show 8e4a881:pyproject.toml | grep '^version'   # version = "0.9.4"
git -C ../iagent-mesh-sdk rev-parse v0.9.4   # c75587e96bbe...   <-- a DIFFERENT commit
git -C ../iagent-mesh-sdk rev-parse 8e4a881  # 8e4a88105c14...
```

So `iagent_mesh.__version__ == "0.9.4"` is true in an environment holding code that is **not** the
0.9.4 release. Anything that identifies the installed SDK by its version string — a runbook step, a
support question, a coherence check — is wrong by a commit range and cannot detect it. The
distinguishing fact is the sha, and the sha is not in the version.

---

## 2. `MeshGraphWriter` was shaped against an inventory of zero. The inventory is five

The Protocol's docstring states that nothing in the fleet writes the property graph today, and is
deliberately minimal on that basis. **Measured over the tracked tree, five write paths exist:**

| file | path | writes |
|---|---|---|
| `agent_fleet/mesh_registrar/v2_substrate.py` | `merge_neo4j_predicate_edge` | MERGE |
| | `sync_parameterised_by_edges` | DELETE + MERGE |
| | `compensate_parameterised_by_edges` | DELETE |
| | `compensate_neo4j_predicate_edge` | DELETE |
| `src/iagent/answer_artifact_writer.py` | `write_sync()` → `_merge_artifact` → `_tx_merge` | MERGE ×16 |

Derived from the execution sites rather than from the word MERGE: 5 of 6 `session.run(` calls in
`v2_substrate.py` carry MERGE or DELETE (the sixth, `:866`, undecided at this resolution);
`answer_artifact_writer.py` has 7 execution sites and 16 MERGE statements inside `_tx_merge`.

**A contract sized for "no callers" is not a smaller version of the contract the callers need** —
and the shortfall is concrete: `write_edge` carries no property bag and no `_tool_urn`.

---

## 3. The registrar cannot adopt the Protocol's writer without losing data

The packet line "Registrar adopts the Neo4j writer, old path deleted" **was not executed, and the
reason is a live pinned invariant.** `write_edge(subject, verb, object)` has nowhere to put a
property bag, so adopting it collapses N provider edges into one last-write-wins edge. That exact
regression is the `a44b9fb` defect, and it is pinned by
`test_mesh_resolve_instance_has_one_edge_per_provider`.

So the old path stays, the widening manifest is recorded at `Neo4jGraphWriter.write_edge`, and the
contract gap is routed to the SDK's author rather than worked around. **A dispatched step that
would break a seal is a finding about the dispatch**, not a step to perform carefully.

---

## 4. The marker contract's reader half is wired at no production site

`fetch_marker` is a constructor parameter of `WeaviateVectors`, stored at `:89` and read at `:159`
behind `if self._fetch_marker else None`. **Every production construction omits it.**

```
WeaviateVectors(  — 5 occurrences repo-wide, ENUMERATED not sampled:
  agent_fleet/ontology_service/main.py:1325   production — no fetch_marker
  agent_fleet/ontology_service/main.py:1769   production — no fetch_marker
  tests/test_mesh_vectors_conforms.py:141,196,516   the only suppliers (two lambdas)
```

So the marker is **written** and never **read** outside the suite: the half of the contract that
would catch a collection whose vectorization has drifted is present, tested, and unreachable in
production. The seal is green and the guard cannot fire.

---

## 5. The realm can express a delegate, but only one principal per client

### 5.1 The chart has one mapper slot per service client

`keycloak-configmap.yaml:101-114` emits exactly **one** `oidc-hardcoded-claim-mapper` per
`serviceClients` entry (`authz-id-svc`). A delegate needs a second, for `on_behalf_of`. So "write
the exact realm change" **cannot be satisfied by a realm change**: it needs a chart affordance that
does not exist, in the configmap *and* in `realm-reconcile-job.yaml:131,199`, or the reconciler
converges the claim away and the feature works until the job next runs.

Recorded in [`../runbooks/adding-a-delegate-credential.md`](../runbooks/adding-a-delegate-credential.md),
which is marked **WRITTEN, NOT RUN** for this reason.

### 5.2 The mapper is hardcoded, and that is the design

A hardcoded mapper can only carry a **fixed** principal, so it is one delegate client per person.
The generalisation — let the caller pass the principal per token request — is this fleet's
already-named laundering shape (`values.yaml:1810`, `register-caller-enumeration.md:19`): *a subject
the caller names is not an identity, it is a request field.* An IdP signature around it does not
change what it is; it makes it harder to see. **The constraint is the design, not a limitation of
it.**

### 5.3 DISCOVERED: `authzClaim: "email"` contradicts what `User.email` promises

`keycloak.authzClaim: "email"` (`values.yaml:1776`) and the mapper writes `authzId` into whatever
that names. So **every service client's token carries a non-mailbox value in the `email` claim** —
`svc:engine-d`, `svc:reporting-delegate`.

`User.email` carries a comment that it is never defaulted to a non-mailbox value so that no
consumer can mistake it for a real address. **That is true of the code and false of the system:** the
code invents nothing, and the IdP is configured to supply exactly the value the comment says cannot
appear. Not edited, because the mapper is load-bearing — dropping it makes `authz_id` fall back to
`sub` (a Keycloak UUID) and silently re-keys every grant.

**A comment can be accurate about its own function and wrong about the world.** Both halves need
saying, and the one that is checkable is the code half, which is why this survived.

---

## 6. Instrument findings — four of the five about my own instruments

### 6.1 The double counted one method, and the defect was in the other

The first draft of `relocate()` called `self._embedder.identity()` on **every** call, to get a
dimension to check the supplied vector against. On the stub that is free. On `FleetEmbedder`,
`identity()` is a **live request to the embed endpoint** — so a relocate, an operation that takes a
precomputed vector and needs no embedding whatever, could not complete while the endpoint was down,
and returned `unreachable` about a service it had no business needing. Plus a round trip per relocate
for a number that does not move.

**What made it invisible: the stub counted `embed()` calls and nothing else.** An arm named for
"relocate does not embed" was green throughout, because it was true — and it was about the wrong
method. A double can only falsify claims about the calls it records, so **the arm's name described a
property its instrument could not see.**

Fixed on both sides. The writer prefers the dimension it **observed** when it last stored a vector
and probes only when nothing has been stored yet and there is no other way to learn it — so a
relocate *after a write* touches the embedder zero times, which is the claim that is actually
reachable; a relocate on a fresh writer still probes, deliberately, because the alternative is
checking a supplied vector against nothing. The stub now exposes
`(len(self.embedded), self.identity_calls)` as **one pair**, so no arm can assert about one method
while the other moves, and
`test_the_observed_dimension_still_refuses_a_mismatch_without_asking_the_embedder` pins the no-ask
path by name.

### 6.2 I shipped a red and reported a green from an earlier tree

`81bd55d5` is red on `tests/routing/test_a_vector_is_written_where_the_search_looks.py`, and I
reported "15 passed" for that file. Both statements were true of different trees: the routing file
was run, *then* the writers' test gained a bare `collections.create`, then only the writers' file
was re-run, and the two figures were reported as one state. **A green belongs to a sha.** Verified
by stashing and re-running at the pushed sha rather than inferred.

The same commit's premise table (§2) said `merge()/_tx_merge  MERGE x6`. `merge()` does not exist
and the count is 16. Both errors understated the row, and the sentence they support was already true
on the row's weakest reading — so nothing failed and nothing would have. **A precise figure inside
an argument that does not depend on it is the figure nobody re-checks.**

### 6.3 A widened seal read every `vector=` in the tree as a store write

The widened arm required every `vector=` expression in a self-provided creator to be
`named_vector(...)`. Three shapes in this tree are not store writes: a `query.hybrid(...)` **search**
at `mesh_vectors.py:314`, the SDK protocol's own `relocate(..., vector=...)` parameter, and any test
driving it. As pushed, **the seal reddened on any caller of the very writers it was widened for**,
and the `hybrid` case was a *latent* false red that would fire the day that file gained a create —
accusing a read path.

Narrowed by a discriminator (the callee) rather than an exemption list, with the residue set to
**collect**: an unresolvable callee is treated as a store write, so a new indirection fails rather
than passes. The accepting side was fired — a bare vector on a real `.data.update` still reds — and
that mutant also showed the tree-wide arm is the **only** arm covering the new writer, so relaxing
it rather than narrowing it would have left the writer unguarded.

A fourth mutant went green: the read-exemption clause I had written could not fire, because reads
are already excluded by the write-op check below it. **Deleted with the measurement recorded**, not
kept as reassurance.

### 6.4 The census's largest block is measured against a live endpoint

`tests/routing/` is 38 failed / 701 passed here, in three files, none of them mine. I nearly
accepted the 38 because it matched a number I remembered. The recorded census
([`../plans/suite-signal-session.md`](../plans/suite-signal-session.md), baseline `42a4afa`) lists
the same three files with `test_classify_route.py` at **23**, not 29.

The +6 cannot be mine: that file imports only stdlib, `pytest` and **`requests`** — it drives a live
endpoint. **So the census's largest block moves with the cluster, not with the tree**, and a count
taken on a different day is not comparable to it. Reported, not chased; that census has an owner and
it is not this lane.

### 6.5 The embed module's served-identity is a process-wide global

`agent_fleet/utils/embed.py:167` declares `_LAST_SERVED` at module scope, writes it at `:172` and
reads it at `:214`. Two concurrent embeds interleave, and the identity read can return the other
request's served model. Whatever consumes "which model embedded this" can therefore be given a true
statement about a different call. Not touched — outside both items — and recorded here because it is
the same defect class as §4: a fact that is *available* but not *attributable*.

---

## 7. Open, with owners

| # | item | owner |
|---|---|---|
| 1 | Move the pin, or cut a tag containing the two writer-contract functions and `delegate_identity` | SDK author (ca) |
| 2 | `MeshGraphWriter` needs a property bag and a `_tool_urn` before any registrar adoption | SDK author (ca) |
| 3 | Wire `fetch_marker` at the two production constructions, or delete the reader half | this lane, once §1 settles |
| 4 | The second mapper in the chart + reconcile job (§5.1) | chart owner |
| 5 | Decide whether `User.email` should reject a non-mailbox value, or the comment should go (§5.3) | architecture |
| 6 | Run the delegate runbook's §5.4 — the only leg that tests the actual claim | human, after §5.1 |
| 7 | Run the live scratch-collection arm (`IAGENT_WRITER_SCRATCH`) — **built and unrun**, a store write | human |
| 8 | `test_classify_route.py`'s 23→29 and its liveness dependence (§6.4) | census owner |
