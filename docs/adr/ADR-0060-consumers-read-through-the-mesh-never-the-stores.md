# ADR-0060 — Consumers read through the mesh, never the stores

**Status:** Proposed. This is a draft for the architect's ruling. **Nobody builds against it until
it is ruled.** ca reviewed the SDK types on 2026-10-24. §5 records the answers, and §6 items 5–8
carry the parts that are behaviour.
**Date:** 2026-10-24
**Deciders:** architect (decision); Chris (review); ca (SDK types); Lane 1 (draft)
**Related:**
  - [`ADR-0005`](ADR-0005-verb-and-concept-namespaces.md): verb and concept namespaces. A
    domain verb is one outside the `mesh:` namespace; §2 registers the first ones.
  - [`ADR-0041`](ADR-0041-user-contributed-documents-ingest-on-arrival-provenance-gated-truth.md)
    §8 and §8.1: the ingest API is the deliverable and the drop-box UI is its first client, not
    its owner. A delegate is a first-class caller. §4.2 makes the delegate the consumer's read
    identity.
  - [`ADR-0047`](ADR-0047-computation-export-governed-emit-carrying-its-own-algorithm.md) §5 and
    §5.1: entitlement filtering per recipient; what is omitted is itself a disclosure decision; a
    service identity is never a disclosure recipient. §4.2 applies §5.1 to a consumer service.
  - [`ADR-0049`](ADR-0049-cross-engine-composition-a-verb-that-needs-another-engines-data.md)
    Option D: direct substrate reads, refused by name for one engine reading another's database.
    [`ADR-0051`](ADR-0051-sustainment-safety-the-mesh-drafts-a-risk-and-refuses-to-accept-it.md)
    repeats the refusal for its own domain. This ADR extends it from engines to every consumer.
  - [`ADR-0052`](ADR-0052-customer-data-enters-through-dlt-to-datahub-never-into-an-engine.md)
    §3: the read is by URN, under the initiator. "A connector that ingests under a service
    identity does not license a read under one." §4.2 is the same rule for content.
  - [`ADR-0054`](ADR-0054-data-classes-every-write-declares-what-it-is.md): data classes. §2's
    persistence descriptor is the read-side counterpart of that ADR's per-store write fields.
  - The origin rule, `visible_by_origin` (ruling Q1, 2026-10-10). §3 applies it to search.

**Numbering.** No ADR-0059 or ADR-0060 file exists on any pushed branch at `a31b61cb`, checked
with `git log --remotes --all -- 'docs/adr/ADR-0059*' 'docs/adr/ADR-006*'`. The same query finds
ADR-0058 on `lane/74-adr-0058-draft`. 0059 is claimed in prose by the training "restore training
ingestion" packet. 0060 is claimed in prose by the training-workbench contract
(`training-consolidation-workbench/docs/contracts/training-workbench.md`). This draft takes 0060.

**Sources.** Line references are to platform `288a3007` (`lane/01-ingest-v1`), the SDK at `f82f7ae`
(v0.9.10 plus 12 commits), and the workbench needs packet of 2026-10-23
(`training-consolidation-workbench/sessions/2026-10-23-packet-to-architect-and-tr-what-the-workbench-needs-read-side-as-needs.md`,
needs N1–N9, questions A–D).

---

## Context

The platform's promise is that the gate sits between retrieval and synthesis. Every engine
filters what it retrieves against the caller's grants before a model sees it. That promise holds
only if every reader goes through a gate. Today a consumer that wants the content the ingest door
produced has two choices: an engine route that happens to cover its need, or the stores.

**The stores are being read directly.** The training workbench reads Neo4j, MinIO and Weaviate,
and writes labels into Neo4j, with its own credentials (contract v1 §1 "reads DIRECTLY", §4.4).
Its contract calls this interim and names this ADR as the replacement. The overnight directive of
2026-10-24 provisions that interim access as a Secret, `training/wb-store-read`, in a `training`
namespace, "pending ADR-0060". Until this ADR is ruled and built, that Secret is a standing
exception to the gate.

What the Secret holds, as provisioned on 2026-10-24:
- **MinIO:** a read credential scoped to `processing-artifacts/training/`.
- **Neo4j:** the full admin credential. Neo4j Community has no read-only role, and the workbench
  writes its own nodes anyway (`Project`, `User`, `CanonicalConcept`). The architect ruled this
  interim on 2026-10-24.
- **Weaviate:** nothing. The sandbox Weaviate accepts anonymous reads and writes, so there is no
  credential to issue.

The interim is store credentials, not read credentials. §4.1 says how it ends.

**The platform has refused this before, case by case.**
- ADR-0049 refuses direct substrate reads by name (Option D), for one engine reading another's
  database: "no gate, no identity, no provenance, invisible coupling".
- ADR-0052 §3 rules that customer data is read by URN under the initiator, never under a service
  identity.
- ADR-0047 §5.1 rules that a service identity is never a disclosure recipient.

Each refusal names its own subject: an engine, a connector, an export. None names a consumer
service or UI outside the engine fleet, and the workbench is one. This ADR states the rule for
every consumer.

**What exists to build on:**

- **A document's identity.** `POST /ingest` mints `ingest_id = "sha256:" + hex(sha256(bytes))`
  (`promotion.ingest_id_for`). That is the same form as the training `Course.id`. A duplicate
  arrival gets a uuid4 row (`ingest_status.py`), and the bytes keep one id.
- **`artifacts[]`.** `GET /ingest/{id}/status` returns what promotion produced
  (`_ingest_status_body`, gateway.py:11676). The entries come from
  `artifact_reads.CASE_ARTIFACTS_CYPHER` and are filtered by `is_entitled`. As ruled 2026-10-16,
  `[]` means none or none visible, and `null` means unknown.
- **One artifact by id.** `GET /artifacts/{artifact_id}` (gateway.py:6703) reads through the SDK's
  `MeshArtifacts.get` and applies the origin rule (`_origin_visible_to_caller`, :6542).
  `MeshArtifacts.list_by_kind` exists in the SDK (interfaces.py:912), but no route serves it.
- **Verbs.** Every registered engine verb is `mesh:`-prefixed, so by ADR-0005's rule there are
  zero domain verbs. Declared-query verbs (`policy/overlays/*/verbs/*.yaml`, served by engine-o's
  `POST /declared_query`) are hand-written per question. The SDK has no verb descriptor type;
  `MeshGraph.providers_for(verb)` (:298) and `verbs_for(subject)` (:335) discover verbs, but no
  type describes a verb.
- **No persistence descriptor.** A content kind's row (`ContentKindRegistration`, SDK
  `ingest.py`) declares `outputs` (classes), `identity_field`, `parent_link_field`,
  `id_namespaces`, `domain`, `review_shape` and `label`. It does not say which store holds an
  output, which fields a reader may see, or how its instances nest.
- **The origin rule.** `visible_by_origin(viewer_domains, owner_domain, program, table,
  is_program_member)` (`agent_fleet/utils/origin_entitlement.py:129`) is THE one rule. It has two
  callers: the BFF's artifact and answer-body reads, and engine-o's notice parts. One seal holds
  them to one rule (`tests/security/test_one_origin_rule_both_callers.py`). It is not in the SDK.
- **No search applies origin.** `/search_predicates` filters by domain only, and
  `MeshVectors.nominate` (:774) has no origin parameter. No `/documents` or `/search` route
  exists, and there is no list route for `/artifacts`.

## Decision

**A consumer reads platform content through three mesh surfaces and never through a store.** A
consumer is any service or UI that is not the engine owning that store. Each surface applies the
same two checks to every row it returns: the caller's grants, then the origin rule. One property
holds across all three: **anything a caller can find, it can fetch, and anything it cannot fetch,
it cannot find.**

### 1. The document manifest

`GET /documents/{ingest_id}` returns one ingested document as a manifest:

- the ingest row's public fields: `ingest_id`, `kind`, `leaf`, `domain`, `title`, `stage`,
  `arrived_at`, and the origin attributes the gate decided on (`owner_domain`, `program`);
- `artifacts[]`, with the semantics of the ingest status route (`[]` none or none visible,
  `null` unknown). Folding "none" and "none visible" together is a disposition: "omit
  silently", in ADR-0047 §5's existence-oracle terms. The ruling of 2026-10-16 chose it for one
  route. This ADR proposes it for every surface;
- `entities[]`: the root instances the kind's descriptor (§2) names, by class and id, so that a
  reader can go straight to the entity verbs;
- `blobs[]`: byte references (page rasters, embedded images, the source file). Each is a stable
  **reference** (`blob:<ingest_id>/<path>`), never a store URL.

`GET /blobs/{reference}` resolves one reference to a short-lived URL, after the same two checks.
A reference never expires. The URL it resolves to does (workbench N5, N6).

`GET /documents?kind=&domain=&since=` lists manifests, paged, filtered the same way. This is the
route `MeshArtifacts.list_by_kind` was written for and never got.

### 2. Entity verbs, generated from a kind's persistence descriptor

A content kind's row gains a **persistence descriptor**. For each class the kind outputs, it
declares:

- the store that holds it;
- its identity field;
- the fields a reader may see (anything not listed is private to the owning engine);
- its parent class and the field that links to it;
- its facet fields (filterable and countable);
- the fields search ranks on (§3).

The identity and parent fields here are **per output class**, and they are not the row's existing
`identity_field` and `parent_link_field`. Those stay as they are and answer different questions:
`identity_field` (event branch only) is the dedupe key of an *arrival*, and `parent_link_field`
(document branch only) names the field of the *extracted output* that holds its parent for graph
walking. The descriptor's fields say how a generated verb addresses a *persisted row*. A kind that
has both has no reason for them to agree, and nothing should assume they do.

From the descriptor, the platform generates and registers read verbs under the kind's domain
prefix: `<domain>:get_<class>`, `<domain>:list_<class>` (by parent, by facet), and
`<domain>:<class>_by_<relation>` for each declared relation. **These are the first domain verbs
under ADR-0005.** They are registered by the kind's owning engine at startup, the same way
`mesh:` verbs are today. Each returns the declared fields only, gated row by row.

A generated verb is not a query language. It takes ids and facet values, never a statement. The
statement text is the engine's own and is sealed at the call site.

For the training kind, the workbench's needs map as follows:

| need | verb |
| --- | --- |
| N1 catalog, facets | `training:list_course` (facets `business_unit`, `discipline`) |
| N2 outline | `training:list_section` by course, `training:concept_by_section` |
| N3, N4 slides | `training:list_slide` by course, `training:get_slide` |
| N7 concepts | `training:list_concept`, `training:slide_by_concept` (a set of names) |
| N9 identity | the descriptor's identity fields, returned explicitly |

### 3. Origin-filtered search

`POST /search` takes a query, a domain, the descriptor's facet filters and a limit. It returns
ranked hits by class and id. The platform embeds the query, so a consumer needs no embedder
(workbench N8).

**Every hit passes the origin rule before it is ranked into the response.** A search does not
return a hit its caller could not fetch with §1 or §2.

**Proposed: `MeshVectors.nominate` applies the origin rule itself, before it truncates to
`limit`.** It already owns the domain filter for the same reason: its docstring makes domain
scoping a Protocol decision because merging afterwards breaks score comparability. A route that
filtered `nominate`'s results afterwards would return fewer than `limit` whenever a top-ranked hit
failed the origin rule, even though lower-ranked hits the caller could see existed. That silently
narrows what `limit` means. (ca's review, §5.)

### 4. What this rules out, and the interim

1. **No consumer holds store credentials.** That covers the workbench's interim Secret too. Once
   §1–§3 serve the workbench's needs, the Secret is removed. Its removal is part of the build,
   not a follow-up. **The workbench's store client is replaced by the manifest route**
   (§1) and the entity verbs (§2). It is not narrowed, given a read-only credential, or wrapped.
2. **A consumer calls on behalf of a person, not as itself.** It calls as a delegate (ADR-0041
   §8.1; ingest-v1 §3.3). A service identity would see the union of every user's grants, and
   ADR-0047 §5.1 rules that a service is never the disclosure recipient. A consumer may hold a
   service identity for its own writes. As ADR-0052 §3 says of connectors, that does not license
   a read under it.
3. **A consumer's state lives in the consumer's store.** No consumer writes edges onto a
   producer's nodes. The workbench's `ALIGNS_TO`, `SUGGESTED_SOURCE` and `DERIVED_FROM` become
   workbench-owned records keyed by the §2 identity fields (workbench question A: yes).

## Consequences

**Wins.**
- One gate for every reader, and one origin rule at every surface. The seal on that rule gains a
  third and a fourth caller (§3's search, §2's verbs), and the "two callers" seal becomes an
  "every surface" seal.
- A new kind's readers cost a descriptor, not a route. The workbench is the first consumer; the
  next costs no platform code beyond its kind row.
- The stores' schemas become private to their engines. A re-shape no longer breaks a consumer it
  never heard of.

**Costs we accept.**
- The descriptor is a contract. A field once listed as readable cannot be removed without a
  versioned change, the same as ingest-v1's shapes lock.
- A gated read is slower than a direct one, and search pays the origin check per hit. The bound
  that matters is the workbench's catalog and heatmap, and it has not been measured.
- The workbench's saved `minio://training-content/...` references must be migrated (question C).
  A mapping the platform serves once is cheaper than a resolver for a scheme that names a store
  for ever.
- Until this is built, the interim Secret is an exception that this ADR names and does not
  excuse.

## Alternatives considered

- **Per-consumer read credentials, scoped by store ACLs.** Refused. A store ACL knows buckets and
  labels, not grants or origins, so the gate would be re-implemented, worse, in each store. This
  is ADR-0049's Option D again.
- **Hand-written BFF routes per consumer** (`/workbench/course/...`). Refused. It works for one
  consumer and makes every later one a platform change. It is also the shape the declared-query
  verbs already show does not scale: one file per question.
- **A query passthrough** (Cypher or GraphQL with a filter appended). Refused. A filter the
  platform appends to a statement it did not write is a parameter, not a constraint.
- **DataHub as the read surface.** Refused for content. DataHub catalogues datasets and lineage.
  It is not a gate over rows and does not apply the origin rule.

## Indicators for revisiting

- A consumer need that no descriptor field can express without naming a store. Then the
  descriptor is the wrong abstraction.
- A measured catalog or heatmap read through §2 that is too slow for the workbench, after
  caching gated results per caller.
- A second origin rule. If any surface needs a rule other than `visible_by_origin`, the "one
  rule" premise has failed and this ADR with it.

## 5. The SDK types, and ca's review

These are proposals. Names and fields are ca's to change. The behaviour stated in §1–§3 is the
architect's to rule. ca reviewed them on 2026-10-24, against this draft at `a4d396fe` and the SDK
at `26b1238`. Nothing is built, and no SDK release is cut for this.

- **`PersistenceDescriptor`**: a new optional field `persists` on `ContentKindRegistration`, one
  `PersistedClass` per output class, with `store`, `identity_field`, `readable_fields`,
  `parent: (class, link_field) | None`, `facets`, and `search_fields`.
  *Review: settled.* The row's `identity_field` and `parent_link_field` do not move into it. They
  mean something else (§2), and `outputs` is plural where they are not.
- **`DocumentManifest`, `ArtifactRef` and `BlobRef`**: the §1 response shapes.
  *Review: `ArtifactRef` has nothing to reuse.* `MeshArtifacts.get` and `list_by_kind` return an
  opaque `answered` payload, and no model backs it. `ArtifactRef` would be the first typed shape
  those callers have had. That is a choice of behaviour, so it goes to the architect (§6, item 5).
- **`EntityVerb`**: the descriptor a generated verb registers with, carrying class, arity (get,
  list, by-relation) and the facet parameters. It is the first verb descriptor in the SDK.
  *Review: open, for the ruling.* `verbs_for` returns ontology predicate edges, found by walking
  a class's ancestors (`verb_iri`, `input_uri`, `output_uri`, ...). A generated verb is keyed on a
  descriptor and takes ids and facet values. §2 says such verbs register "the same way `mesh:`
  verbs are today", which argues for `providers_for` seeing them. But `EntityVerb` does not fit
  `verbs_for`'s row shape unless that row is widened again (last widened 2026-10-02). See §6,
  item 6.
- **`SearchRequest` and `SearchHit`**, and where the origin check runs.
  *Review: inside `nominate`, before `limit`* (§3).
- **`visible_by_origin` in the SDK.**
  *Review: move it.* Both new SDK-level callers (`nominate` in §3, and a generated verb served by
  an engine that imports only the SDK) need the rule where they live. Importing the platform from
  inside the SDK would invert the dependency direction every other Protocol in `interfaces.py`
  keeps. The platform re-exports the same symbol, so its two existing callers and the one-rule
  seal are unaffected. ca places the module once the move is ruled.

## 6. For the architect: what to rule

1. The principle: no consumer reads a store (§4.1).
2. The three surfaces and their routes (§1–§3).
3. Workbench questions A–D:
   - A. consumer state in the consumer's store (§4.3): proposed yes;
   - B. calls as a delegate of each user (§4.2). The workbench's users sign in to their own
     realm, so it needs token exchange or realm federation. **Not designed here.**
   - C. migrate the saved `minio://` references by a mapping served once: proposed;
   - D. a stable reference plus a short-lived URL (§1): proposed.
4. The reviewer for generated verbs: who ratifies a descriptor's `readable_fields`? This draft
   assumes the kind row's existing review, and has not checked that this is enough.
5. `ArtifactRef` (from ca's review, §5):
   - (a) it becomes the documented shape of `MeshArtifacts.get`'s `answered` payload. That
     closes the opaque-payload gap, and it changes an existing Protocol's behaviour;
   - (b) it stays scoped to the §1 manifest, and `MeshArtifacts` stays opaque.
6. A generated read verb is either:
   - an ontology predicate, in the same registry and row shape as `verbs_for`, widened; or
   - a sibling registration that `providers_for` sees and `verbs_for` does not.
7. The origin rule runs inside `nominate`, before `limit` (§3). Proposed yes.
8. `visible_by_origin` moves to the SDK, and the platform re-exports it (§5). Proposed yes.
