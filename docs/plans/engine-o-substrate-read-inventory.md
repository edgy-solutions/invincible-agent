---
id:         engine-o-substrate-read-inventory
status:     in-flight
owner:      invincible-agent-28 [5401d7] — ia-eo / lane/eo
blocked-on:
trigger:
closed-by:
repo:       invincible-agent
summary:    The engine-o half of the mesh-client census — every substrate touch engine-o makes, derived from its handles rather than listed, with what each one is TRYING TO DO. The candidate named-operation list MeshGraph / MeshOntology / MeshVectors must cover.
---

# Engine-o's substrate reads — the candidate named operations

**Written for the "the mesh has one client" ADR's interface table, to be CITED rather than
restated.** A message is not citable and survives neither its sender nor its reader; the ADR's
author (docs/ADR lane) and the census owner (`iagent-mesh-sdk-ca`) both need this to still exist
when the addresses have changed.

Scope is `agent_fleet/ontology_service/`. The site population was derived at `3247562`; §7 and §7b
read the query texts at `0ef480c`, and §3/§3b record what has changed in between. This packet is
the ENGINE-O HALF of ca's fleet census, not the census.

**THE THIRTEEN QUERY TEXTS ARE READ — §7 has the ten Neo4j and provider-discovery ones, §7b the
three Weaviate ones.** Until both existed this packet's purposes came from docstrings, which is
not evidence for any operation whose signature turns on a detail of its query. Between them they
change six signatures, and §7b's first item changes what `MeshVectors` IS.

## §0 — HOW THE POPULATION WAS DERIVED, and what the derivation cannot see

Nothing here is hand-listed. A hand-written list of a population is a sample wearing a census's
clothes, so the sites come from the **handles**, in two arms that were reconciled against each
other:

* **Arm 1 — handle references.** An AST walk over `main.py` for every `Name` node in
  `{_NEO4J_DRIVER, _WEAVIATE_CLIENT, _LOCAL_GRAPH, _get_local_graph, _JENA_ENDPOINT,
  _JENA_UPDATE_ENDPOINT}`, each attributed to its INNERMOST enclosing function. 26 sites.
* **Arm 2 — handles passed as parameters.** Arm 1 is blind to a function that receives a driver
  as an argument and never names the module handle. Grep for `.session()` / `session.run(` /
  `.collections.` / `def *(driver` across the package.

**ARM 2 EARNED ITS KEEP, WHICH IS THE POINT OF RUNNING IT.** The two real Cypher executions in
`registry_views.py` (L116–117, L137–138) name no handle — they take `driver` as a parameter — so
arm 1 attributed them to the four thin wrappers in `main.py` (L394–407) instead, and a census
built from arm 1 alone would have recorded the call site and missed the query. The arms
reconcile to the same four logical reads.

**WHAT NEITHER ARM CAN SEE, stated rather than left as coverage:** a substrate reached through a
transport that is not a driver at all. That is not hypothetical here — see F2, which arm 1 found
only because `_JENA_ENDPOINT` happens to be a module-scope name. **Had the Jena URL been read
from the environment at each call site, both arms would have reported a clean absence.**

Every site below is either in the basis (becomes a candidate named operation) or in the
exclusion list WITH A REASON. Nothing is silently dropped.

## §1 — Neo4j: nine reads, and ZERO writes

| site | what it is TRYING TO DO | lands in |
|---|---|---|
| `registry_views.fetch_active_personas` / `fetch_active_domains` (+ the two `*_string` shapers) | read the persona and domain REGISTRY — which personas/domains are active | `MeshGraph.registry(...)` |
| `_discover_enumerate_providers` (L1452) | which engines are registered as `mesh:enumerateInstances` providers, on the resolver TTL | `MeshGraph.providers_for(verb)` |
| `_discover_instance_resolvers` (L1495) | the same read for `mesh:resolveInstance` — endpoint_url, provider, timeout_s, domains | same operation, different verb |
| `_served_class_uris` (L1886) | classes carrying a verb in these domains, plus declared referents — the productive-option gate | `MeshGraph.classes_with_a_verb(domains, include_referents)` |
| `get_physical_assets` (L2440) | `(:OntologyClass {uri})-[:HAS_DATA]->(:DataAsset)` — ontology IRI to physical URNs | `MeshGraph.data_assets_for(iri)` |
| `find_tool` (L2537) | resolve one predicate edge from (subject_uri, verb_label), cheapest by `cost_class` | `MeshGraph.edge(subject, verb)` |
| `find_path` (L2721) | shortest composition start→end respecting allowed cost classes | `MeshGraph.path(start, end, cost_classes)` |
| `operable_subjects` (L3593) | OntologyClass nodes carrying at least one registered verb edge, domain-scoped and can_view-filtered | `MeshGraph.operable_subjects(domain, actor)` |
| `find_compatible_verbs` (L3985) + `_get_subject_ancestor_chain` (L4152) | walk `subClassOf*0..max_hops` and return the predicates that can operate on the subject | `MeshGraph.verbs_for(subject, max_hops)` + `MeshGraph.ancestors(iri, max_hops)` |

**EXCLUDED, with reasons:** `lifespan` (L581) — opens and closes the driver, which is the one
thing an implementation package legitimately does and an interface must never expose;
`health` (L3497) — liveness, and it reports `_JENA_ENDPOINT != ""` rather than reachability,
which is a configuration read wearing a health check's name.

**F1 — ENGINE-O PERFORMS NO NEO4J WRITES AT ALL.** Derived, not assumed: zero matches for
`MERGE (`, `CREATE (`, `DETACH DELETE`, `SET n.`, `CREATE INDEX`, `CREATE CONSTRAINT` anywhere
in the package. **So MeshGraph, as its largest consumer needs it, is a READ interface.** The
graph's writer is `mesh_registrar`. This should decide the ADR's table rather than be discovered
during the build: designing MeshGraph with a write half "for symmetry" would mint a surface with
no caller in the engine that holds the driver, and an unused write path on the one interface
every engine depends on is a wider blast radius bought for nothing.

## §2 — Weaviate: two searches, one existence probe

| site | what it is TRYING TO DO | lands in |
|---|---|---|
| `_weaviate_hybrid_search_sync` (L979) | hybrid search over the `OntologyClass` collection — nominate candidate classes for a phrase | `MeshVectors.nominate(collection, text, domain, scope)` |
| `_predicate_hybrid_search_sync` (L1143) | the same over the predicate collection — nominate candidate verbs | same operation |
| `collections.exists(...)` (L1012, L1164, L2612) | is the collection present at all — the guard that distinguishes "nothing matched" from "nothing to match against" | `MeshVectors.collection_present(name)` |

**The existence probe is not plumbing and should survive into the interface.** It is the local
form of a distinction this repo has paid for repeatedly: an empty result and an absent substrate
are different answers, and a search interface that cannot tell them apart hands its caller a
confident zero. If the interface drops it, every implementation re-invents it privately or stops
making the distinction.

## §3 — Jena: five operations, reached WITHOUT a driver

| site | what it is TRYING TO DO | lands in |
|---|---|---|
| `execute_sparql` (L446) | the internal SELECT executor, read-union scoped `{domain, domain_INSTANCES}` | the executor BEHIND `MeshOntology`, not an operation on it |
| `_run_ask` (L3840) | does this IRI / graph exist — used before a decision-record write (L3770, L3774) | `MeshOntology.ask(...)` |
| `_run_construct_turtle` (L3831) | CONSTRUCT a typed subgraph and return Turtle, types intact | `MeshOntology.construct(...)` |
| `_execute_sparql_update` (L3666) | INSERT DATA into a named graph — the write half (`/write_item_state`, `/write_decision_record`) | `MeshOntology` typed write, or stays engine-o's |
| `_check_jena_populated` (L561) | is the store seeded at all — one row across any graph | startup gate |

**F2 — JENA IS REACHED BY RAW `httpx.post`, NOT BY A DRIVER LIBRARY.** `_JENA_ENDPOINT` is a URL;
the calls are `httpx.AsyncClient(...).post(endpoint, data={"query": ...})` with basic auth
(L505, L3670, L3835, L3844). **A dependency seal that refuses driver PACKAGE NAMES is
structurally blind to this entire substrate** — there is no `rdflib` and no `SPARQLWrapper` on
the path, and `httpx` is not a driver name but here it is the driver.

This is the third arm of the same law, and the three together are the shape the seal has to
cover: ca's *the import name is not the capability*; mine from the `agent_fleet/utils/` hole,
*the pyproject is not the import*; and now **the import is not the connection.** A ban list
operating on names can be defeated by a substrate that needs no name.

**`rdflib` inside engine-o is a LOCAL-FILE parser, not a store client** — `_get_local_graph`
(L429) parses `Maintenance.rdf` and a TTL from disk, and is the fallback when `_JENA_ENDPOINT`
is unset. That corroborates ca's ban-list finding from a second direction: the one engine that
legitimately holds every driver uses rdflib for the same non-driver purpose the three "violating"
engines do.

**F6 — RULED AND FIXED 2026-09-13** (this line previously read *"filed, not fixed"* — the ruling
came back the other way, and a stale claim in a packet is read as current by whoever finds it
next). Every Jena call passed `verify=False` and `_JENA_PASSWORD` defaulted to a literal
credential in source. Now: the credential has **no default**, a configured endpoint without one
**fails readiness naming the variable**, and the four call sites go through one client factory
that passes no TLS override. `agent_fleet/ontology_service/jena_posture.py` +
`tests/test_a_missing_fuseki_credential_fails_readiness.py`.

**The `verify=False` half needs its honest scope stated:** the configured endpoint is
`http://…:3030/ds/query`, and TLS verification applies to https — **so the override was inert in
every deployment that exists.** It was not a live hole; it was a **latent** one, waiting for the
first deployment to use the `externalFuseki.url` override with an https address, where
verification would have been off silently with nothing going red. A latent hole reads as coverage
for exactly as long as everyone happens to behave.

**F6b — THE SEAL FOUND A SECOND INSTANCE THE RULING DID NOT NAME.** The credential-default check
was written over the CLASS of secret-ish variables rather than the one that was reported, and it
went red on `NEO4J_PASSWORD`, which defaulted to the literal `"password"` at main.py:378. The
chart's own snippets already read that variable as `os.environ.get("NEO4J_PASSWORD", "")` and
every compose file declares it, so the default was **dead in every configuration in this repo
while reading as a working fallback.** Fixed in the same change. *A filed defect is a sample, not
a census* — the reported one was the one somebody happened to look at.

**STILL OPEN, not fixed:** `_NEO4J_URI` defaults to the in-cluster address
`bolt://iagent-neo4j:7687`. That is a hardcoded fallback for a SUBSTRATE address, which is the
same shape the service-URL readiness ruling prohibited for peer URLs on 2026-09-11. Different
ruling, different owner — named here rather than quietly fixed.

## §3b — F7 IS REFUTED. The write path is correct, and the way I got it wrong is the finding

**RETRACTED 2026-09-13, same day, before anything was built on it.** The claim below said
engine-o's one write path POSTs `update=` to the QUERY endpoint. **It does not.** Lane 1 read the
live pod — `JENA_SPARQL_ENDPOINT=http://iagent-fuseki:3030/ds/sparql` — so the substitution fires
and yields `/ds/update`, the correct Fuseki convention. A CHECKED NEGATIVE, recorded rather than
deleted: an unchecked one leaves the question open forever, and this one cost two commands.

**MY PREMISE WAS FALSE INSIDE THIS REPO, NOT ONLY AGAINST THE CLUSTER.** I wrote *"every endpoint
spelled anywhere in this repo ends `/ds/query`"*. `helm/invincible-agent/values-sandbox.yaml:187`
spells `/ds/sparql`, and carries five lines of comment explaining exactly why. **That file was in
the grep output I derived and quoted from; I read three of its hits and stated a claim about
all of them.** So this is not "a repo census cannot see a deployed value" — that would be a
kinder law than I earned. It is: **I derived a population, then read a sample of it, and reported
the sample in the population's voice.** In a packet whose §0 is about deriving populations.

**WHAT SURVIVED WAS NARROWER, AND IT IS NOW FIXED — by Lane 1, in the chart, where it belonged.**
The sandbox file had been patching a default that was wrong in the chart itself: `values.yaml:279`
and the template at `configmap.yaml:99` both rendered `/ds/query`, which per the sandbox comment
**returns HTTP 405 on POST** for this Fuseki dataset — so a deployment without the sandbox
override had a broken READ path before its write path mattered. **Both render `/ds/sparql` as of
chart 0.3.69, verified at master `216cabd`.** Recorded closed rather than deleted: this line is
the only place the reason is written down, and the next person to see `/ds/query` in an old values
file needs to find it.
The original text follows, struck but intact, because a retraction that deletes its own claim
leaves the next reader unable to check the reasoning.

**AND THE SUBSTITUTION IS GONE ANYWAY — ruled 2026-09-14, on the sharper reason.** Not "it
derives the wrong address" (it did not) but: **`endpoint.replace("/sparql", "/update")` derives
NOTHING while reading like a derivation.** It is string surgery that happens to work on one
spelling. A reader asking "is there an update endpoint?" finds a line that answers yes. It worked,
so nobody looked, and it sat one chart edit away from POSTing updates at a query endpoint. The
endpoint is now DECLARED (chart 0.3.73) and an absent declaration makes the write path refuse
**by name**.

**THE COST OF THE TRADE, because it arrived within the hour and is the honest other half:** the
substitution guaranteed ONE HOST, being surgery on one string. Two declarations can drift — and
the first render of the new key kept the helper's FQDN while the query endpoint used the short
service name. **One substrate, two hostnames, and the new key read as correct on its own.** It was
reading the PAIR that showed it. So: declared beats derived, and a declared pair must be rendered
and read together, never either alone.

### ~~F7 as originally written~~ — ENGINE-O'S WRITE ENDPOINT IS DERIVED BY A SUBSTITUTION THAT NEVER FIRES

Found while enumerating the write path, and it is a correctness defect rather than a posture one.

    _JENA_UPDATE_ENDPOINT = os.getenv("JENA_UPDATE_ENDPOINT", "") or
                            _JENA_ENDPOINT.replace("/sparql", "/update")

* `JENA_UPDATE_ENDPOINT` is set **nowhere** — not in `helm/`, not in either compose file, not in
  `setup/`. Derived by a whole-repo grep; the only occurrences are its own definition and use.
* ~~Every endpoint spelled anywhere in this repo ends **`/ds/query`**~~ — **FALSE, and this is the
  sentence that was wrong.** True of `values.yaml:279`, `configmap.yaml:99` and
  `examples/docker-compose.yml:69`; NOT true of `values-sandbox.yaml:187`, which is the one the
  sandbox actually runs.

**So the substitution fires in no configuration that exists, and engine-o's one write path POSTs
`update=` to the QUERY endpoint.** The comment above it read *"Derived from the read endpoint
(…/ds/sparql -> …/ds/update)"* — written against a spelling the chart does not use, and it has
been describing a transformation that does not happen. *A docstring is not evidence.*

**NOT FIXED, deliberately.** Whether writes currently fail loudly at Fuseki or something else is
true in-cluster is a live question this packet cannot answer, and **changing where a write lands
is not an inventory's call.** The consumers are `/write_item_state` and `/write_decision_record`.
Needs a ruling and a live check, in that order.

## §4 — F3: THE PATTERN THE ADR PROPOSES ALREADY EXISTS HERE, AT A SMALLER SCALE

`policy_rules_sparql.py`, `state_sparql.py` and `sustainment_instance_provider.py` are **pure
query builders with the executor INJECTED** — the provider's own docstring says so: *"Pure — the
SPARQL executor is INJECTED, so the matching is unit-tested against live-shaped rows without a
Jena."*

So "named operation over an injected executor, testable without the substrate" is not a fleet
convention being imposed on engine-o from outside; **it is engine-o's own local convention,
already carrying its own reason** (a brace bug that cost a build/roll cycle, per
`state_sparql.py`'s header). The ADR should cite these three modules as precedent, and the
migration should start where the shape already holds rather than at the biggest read.

**It also supplies the conformance suite's offline arm for free**: an injected executor is
exactly the seam a fake plugs into.

## §5 — F4: THE FLEET'S PROBLEM IS A MISSING CLIENT, NOT AN OPEN QUERY HOLE

Two derived facts that together narrow the ADR's first increment:

1. **Engine-o's HTTP surface is already 24 named operations** — `grep -c` over
   `@app.(get|post|put|delete)(` in `main.py` — and **not one of them is a raw-query route.**
   There is no `/sparql`, no `/cypher`, and no query string reaching an executor from a request
   body; `/instances_by_property`, the closest case, calls `_build_parts_query(...)`, a builder.
2. **No consumer of `execute_sparql` exists anywhere in `agent_fleet/` outside
   `ontology_service/`.** The passthrough executor is internal.

**So the engines reaching past the SDK to hold their own drivers are not routing around a hole in
engine-o's surface — they are routing around the ABSENCE OF A CLIENT for doors that already
exist.** The first SDK increment is a client over operations engine-o already serves, which is a
much smaller and much better-evidenced piece of work than minting a new capability surface. Where
an engine's direct read has NO corresponding route, that gap is a real SDK backlog item and should
be named as one — but the census will likely produce a shorter list of those than the dispatch
assumed.

## §6 — F5: AN INSTRUMENT CORRECTION, recorded because the shape is a repeat

My first classifier marked a site WRITE when the word `SET ` appeared in its line range. It
flagged `_served_class_uris` — whose docstring reads *"RETURNS AN EMPTY SET ON ANY FAILURE"*. A
check matching a STRING cannot see a BEHAVIOUR, and it flagged the prose EXPLAINING the read as
evidence of a write. Corrected by reading the body; §1's zero-writes claim rests on the absence
of Cypher write keywords, verified separately.

## §7 — THE QUERY TEXTS, READ. Five places the docstring and the Cypher disagree

§8 warns that the purposes came from docstrings. Here is the reading, and it changes five
signatures. Every item is from the query text; the line numbers are `main.py` unless noted.

**1. `domains` IS A PERMISSIVE FILTER, NOT A FILTER.** `_SERVED_CLASSES_CYPHER` (L1893) accepts a
verb when `size($domains) = 0 OR coalesce(r.domains, []) = [] OR any(d IN r.domains WHERE d IN
$domains)`. **A verb that declares NO domains is served in EVERY domain.** The docstring says
"classes carrying a verb in these domains". An interface signature typed as a filter would be
documenting the opposite of what the query does for undeclared verbs — and undeclared is the
default state of a verb nobody has scoped yet.

**2. "DOMAIN-SCOPED" MEANS TWO DIFFERENT THINGS AT TWO DOORS.** `operable_subjects` (L3637)
filters `s.domain = $domain` — a **node property, singular**. `_served_class_uris` and
`find_compatible_verbs` filter `r.domains` — a **relationship property, a list**. Same word, same
interface, two data models. An interface that takes `domain` uniformly would hide that one door
asks what the CLASS is scoped to and the other asks what the VERB is scoped to. **Whether the two
can disagree in practice is NOT established here** — I did not find the writer of the node
property (it is not the registrar; likely doc-tools) and I ran no check for a test relating them.
Recorded as the open question it is, because "and nothing asserts they agree" is the kind of
absence that needs its own control before it is worth saying.

**3. `find_tool`'s VERB ARGUMENT IS POLYMORPHIC ACROSS THREE IDENTIFIER SPACES.**
`type(r) = $verb_label OR r.iri = $verb_label OR $verb_label IN coalesce(r.synonyms, [])`
(L2512) — a relationship TYPE, an IRI, or a synonym, all through one parameter named
`verb_label`. **And the cheapest-wins ordering has no tie-break**: `ORDER BY CASE
coalesce(r.cost_class,'slow') …` then `LIMIT 1`, so among equal-cost edges the winner is whatever
the planner returns first. A `MeshGraph.edge(subject, verb)` signature has to say which of the
three spaces `verb` is in, and that ties are undefined — an authority ranking needs a scope.

**4. THE TWO PROVIDER-DISCOVERY QUERIES MIX COMPACT AND FULL IRI SPELLINGS IN ONE MATCH.**
`_INSTANCE_RESOLVERS_CYPHER` (L1390) anchors on the FULL IRI
`'http://invincible-agent/mesh#InstanceIdentifier'` and then filters `r.iri = 'mesh:resolveInstance'`
— the COMPACT form. Both are correct only because the registrar happens to write each property in
that spelling. **An unknown or re-spelled prefix passes through verbatim and matches nothing**, so
the failure is a silently empty provider list, which this repo has already paid for twice. If the
interface takes a verb IRI, it must say which spelling, and the implementation should normalise
rather than inherit two conventions.

**5. THE HOP BOUND IS A HARDCODED 5 IN ONE QUERY AND A CALLER ARGUMENT IN TWO OTHERS.**
`_SERVED_CLASSES_CYPHER` fixes `subClassOf*0..5`; `find_compatible_verbs` (L4000) and
`_get_subject_ancestor_chain` (L4197) substitute `$MAXHOPS$` **by string replacement**, because a
variable-length bound cannot be a Cypher parameter. So three operations answer inheritance
questions at depths that need not agree, and one of them cannot be asked for a different depth.
A default invented locally becomes a contract — pick the bound in the interface, do not let three
queries each carry their own.

**AND ONE THAT IS NOT A DISAGREEMENT BUT DECIDES A PROPERTY OF THE WHOLE INTERFACE:**
`operable_subjects`'s entitlement filter is `_can_view_class(request.user_email, uri)`, applied in
Python AFTER the query, **keyed on an EMAIL**. "Identity is an argument" cannot be honoured at
this door until that keying moves to a principal id — which is the gateway's email-keyed-authz
ruling, arriving inside an engine's read path. The interface should take a principal, and this
implementation will need the gateway's change before it can mean one.

## §7b — THE WEAVIATE QUERY TEXTS, READ. `MeshVectors.nominate(...)` is not what its name suggests

Completing §7: ten of the thirteen sites were read there, all Neo4j and provider-discovery. These
are the remaining three, and they change the interface more than any of the first ten.

**1. THE VECTOR IS COMPUTED BY THE CALLER. WEAVIATE IS DUMB STORAGE.** Both searches call
`embed_query(query)` — `agent_fleet/utils/embed.py` → LiteLLM `/embeddings` — and pass the result
as `vector=` to `collection.query.hybrid(...)`. The module says so outright: *"Weaviate is dumb
storage: NO text2vec module is involved on the cluster side."* So `MeshVectors.nominate(text)`
would be a lie by omission: **the implementation owns the embedding contract**, and a caller
handing text to two implementations can get vectors from two different models against one stored
index. `embed.py` carries `DEFAULT_EMBED_MODEL = "nomic-embed-text"` and `EXPECTED_EMBED_DIM = 768`
**duplicated in two files by hand** (its own header says to update both). The interface must
either carry the model identity or the implementation must assert it against the collection.

**2. THE OPERATION ANSWERS IN TWO RETRIEVAL MODES AND THE RETURN SHAPE CANNOT TELL THEM APART.**
Both sites wrap `embed_query` in `try/except` and fall back to `collection.query.bm25(...)`,
printing to stdout. Same fields, same score key, no marker. **This is not hypothetical: the fleet
ran 67 days with `LLM_BASE_URL` unset, so every embed raised and every search was BM25-only** —
and nothing in any result said so. A `nominate()` that returns rows without the mode that produced
them re-arms that exact failure for every future consumer. **The retrieval mode belongs in the
return, not in a log line.**

**3. THE TWO COLLECTIONS SCOPE DOMAINS BY DIFFERENT RULES, AND ONE IS PERMISSIVE.**

    OntologyClass   domain  (singular)  ->  .equal(d) | .contains_any(ds)      strict
    Predicate       domains (list)      ->  .contains_any(ds) OR length == 0   permissive

The predicate filter deliberately keeps **domain-agnostic** predicates (`domains == []`) via a
length filter, because Weaviate v4 rejects `.equal([])`. That is the exact twin of §7's Neo4j
finding — a verb declaring no domains is in scope everywhere — and the class collection has **no
such branch**. One interface, two domain semantics, and the difference is invisible in a signature
that takes `domain` uniformly.

**4. THE SCORES ARE NOT COMPARABLE ACROSS THE TWO CALLS.** The class path returns Weaviate's raw
hybrid score. The predicate path subtracts an anti-synonym penalty —
`adjusted_score = max(0.0, score - _ANTI_SYN_PENALTY_ALPHA * overlap)` with alpha defaulting to
`0.50` from `PREDICATE_ANTI_SYNONYM_ALPHA`. **So `score` means "what Weaviate said" at one door and
"what Weaviate said, adjusted by a locally-tuned penalty" at the other**, and either may be `None`.
An interface returning a bare `score` invites exactly the cross-provider comparison that an
authority ranking without a scope produces.

**5. EMPTY IS OVERLOADED — ONE WAY, NOT THREE. CORRECTED 2026-09-14, and the correction is the
same defect this section is about.** I first wrote that `[]` conflates collection-absent,
nothing-matched and unreachable, quoting the helper's own docstring: *"Empty list means the
collection is empty, missing, or unreachable — caller should fall back to Cypher exact-match."*
**I took the docstring's account of the helper as the behaviour of the path.** Reading the route
above it, `/search_predicates` checks `_WEAVIATE_CLIENT` and `collections.exists(...)` and raises
**503** before the helper is ever called — matching ADR-0009, which requires exactly that rather
than a silent degradation to exact-match.

**What actually survives is narrower and still real:** inside the helper, `except Exception: print(...);
return []` turns a mid-query failure into an empty success. So one of the three, not three — and
the helper's docstring instructs a Cypher fallback that the route has already ruled out. §2's
`collection_present` probe still belongs in the interface; the remaining fix is that a throw must
not arrive as an empty result set.

**5b. THE PERMISSIVE DOMAIN BRANCH IS A RATIFIED ADR CLAUSE, NOT AN ENGINE-O DEFECT — HELD, NOT
FIXED.** Ruled to this lane on 2026-09-14: *"the two collections scope domains by one rule, and
`domains == []` is not permissive — it's the empty-set-means-all defect."* I did not implement it,
because the branch it names is specified by ADR-0009 **in those words, twice**:

> *"with the entitled-domains filter applied at the vector-store layer (OR of `domains contains_any
> [entitled]` and `domains == []` to keep domain-agnostic predicates visible to scoped callers)"*
> — ADR-0009, and again in its build section: *"OR-filter to keep domain-agnostic predicates
> visible"*.

And `agent_fleet/utils/mesh_registration.py:571-574` carries the same semantic as the FLEET
registration contract, citing ADR-0009: *"domains are a scope filter, not a routing key … empty
list means domain-agnostic."*

**SO THE TWO DIRECTIONS ARE NOT SYMMETRIC, AND EACH IS BIGGER THAN THIS LANE:**

* **If ADR-0009 stands**, the divergent collection is `OntologyClass`, which has NO such branch —
  so "one rule" means adding the permissive branch to the class side, the OPPOSITE change.
* **If the ruling stands**, ADR-0009's clause is superseded and the registration contract's
  documented meaning changes with it. That is a fleet amendment, and **every verb registered as
  domain-agnostic silently stops being a candidate for scoped callers on the next roll.**

**I CANNOT BOUND THE BLAST RADIUS FROM THIS REPO, which is the reason to ask rather than pick.**
A derived census of all 38 `register_engine_to_mesh` call sites under `agent_fleet/` shows every
one passes `domains=` — but three pass a variable or a request field, and registrants OUTSIDE this
repo (doc-tools' sync, SDK `MeshTool` emits) are not visible here at all.

### THE CENSUS LINE — measured against live sandbox 2026-09-14

RULED 2026-09-14: ADR-0009 stands; the class collection comes under it. The measurement changed
what that means. `tests/sandbox_e2e/_probe_domain_agnostic_rows.py`, read-only aggregate counts:

    Predicate       129 rows,  27 with len(domains) == 0   ->  21% ARE domain-agnostic
    OntologyClass 21078 rows,   0 domain-agnostic          ->  8 distinct domains, none empty

**SOMEBODY DID REGISTER AGNOSTIC ON PURPOSE, 27 TIMES.** A fifth of the routing table. Deleting
ADR-0009's branch would have taken all 27 out of every domain-scoped search.

**AND THE CLASS BRANCH WOULD BE DEAD CODE: zero of 21,078 rows carry no domain.** All eight domain
values are non-empty and they sum to the total. So the rule is satisfied vacuously in data, and
writing the branch would be a guard that cannot fire.

**WORSE, IT CANNOT BE WRITTEN AT ALL ON THIS SCHEMA — and that is why the two call sites differ.
The divergence is in the SCHEMA, not in engine-o's code:**

    Predicate      invertedIndexConfig.indexPropertyLength = True    -> len(domains)==0 filters
    OntologyClass  invertedIndexConfig.indexPropertyLength = unset   -> len(domain)==0 RAISES

Verified by running the filter: *"Property length must be indexed to be filterable! add
`indexPropertyLength`"*. And `_weaviate_hybrid_search_sync` wraps its query in
`except Exception: print(...); return []` — **so adding that branch would not fail loudly, it
would empty the class candidate pool in silence.** Routing down, service green. The setting is
immutable after collection creation, so enabling it means recreating `OntologyClass` and
re-ingesting 21,078 objects: a prime-shaped migration, not a toggle.

**WHAT LANDED INSTEAD IS A TRIPWIRE.** The probe asserts the premise the missing branch rests on —
zero agnostic class rows — and reds the day one appears, naming what it would take to serve it. A
revisit-later that cannot go stale is a check that goes red when the world changes; the number in
this paragraph would otherwise be a figure outliving its measurement.

### §7c — AN EXCEPTION RETURNED AS AN EMPTY SUCCESS: the ruled two, and the three the ruling did not name

RULED 2026-09-14 and FIXED for the two Weaviate searches: a mid-query failure now refuses with a
503 instead of returning `[]`. **The consumer is what made it urgent.** `/resolve` reads an empty
candidate list, prints **"WEAVIATE COLD START DETECTED"**, falls back to
`_SPARQL_MAINTENANCE_CLASSES` and answers from the MAINTENANCE ontology — so a transient Weaviate
error produced a confident WRONG-DOMAIN answer under a banner naming a false diagnosis. Not a
missing answer: a wrong one. An empty RESULT still means cold start and still takes that path;
only the FAILURE is separated out.

**THEN THE SAME CHECK WAS RUN OVER THE WHOLE MODULE**, because a reported defect is a sample. An
AST walk for every `except` handler returning an empty container finds **five** sites. Partitioned,
every member in the basis or excluded WITH A REASON:

| site | substrate | disposition |
|---|---|---|
| `_weaviate_hybrid_search_sync` | Weaviate | **FIXED** — refuses 503 |
| `_predicate_hybrid_search_sync` | Weaviate | **FIXED** — refuses 503 |
| `execute_sparql` (L571) | Jena | **BASIS, not fixed** — a SPARQL failure returns `[]`, and its callers include `/policy_rules`, `/resolve_instance` and the cold-start fallback itself. Changing it touches every SPARQL consumer, so it is a ruling, not a lane's call. |
| `_discover_enumerate_providers` (L1539) | Neo4j | **BASIS, not fixed** — a discovery failure returns no providers, which renders as *"this class cannot be listed"*. That exact SYMPTOM has been produced once before by a different cause (a hardwired `ENUMERATE_INSTANCES_URL`), and the module's own comment records it. |
| `_get_subject_ancestor_chain` (L4282) | Neo4j | **BASIS, not fixed** — an empty chain silently narrows verb compatibility to the raw subject, which is the inheritance gap ADR-0018's amendment exists to close. |
| `_served_class_uris` (L2006) | Neo4j | **EXCLUDED, with its reason already written**: *"RETURNS AN EMPTY SET ON ANY FAILURE, AND THE CALLER MUST READ THAT AS 'DO NOT FILTER'"*. It degrades OPEN on purpose — failing closed would empty the candidate pool and take routing down globally. This is the one case where an empty success is the correct answer, and it says so. |
| `_decode_declarations` (L3177) | — | **EXCLUDED** — a JSON decode, no substrate behind it. Different family. |

**6. AND ONE DEFAULT WORTH PINNING BEFORE IT BECOMES A CONTRACT.** The class search declares
`limit: int = 10`; the predicate search requires `limit` from its caller. Two doors of one
interface, one of which has already invented a bound. Pick it in the interface and read it from
there — a default invented locally becomes a contract nobody agreed to.

## §8 — WHAT THIS PACKET DOES NOT ESTABLISH

* It is scoped to `agent_fleet/ontology_service/`. It says nothing about the other engines, which
  is ca's census.
* The purposes are read from docstrings and route handlers, corroborated against the query text
  where the query is inline. Where a query lives in a module constant the purpose is the
  docstring's claim, not an independent reading of the Cypher — **a docstring is not evidence**,
  and any operation whose signature turns on a detail of its query text needs that text read
  before it is fixed in the interface.
* No claim is made here about injection-safety of the builder paths. `state_sparql.sparql_lit`
  escapes; whether every builder uses it was not checked, because it is a different question from
  this one and would have arrived as a plausible aside rather than a measured result.
