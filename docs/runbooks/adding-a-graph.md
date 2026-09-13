---
iri: docs:runbook-adding-a-graph
# Every target must exist in the graph — the invented-IRI rule (ADR-0037 §1). All six below were
# VERIFIED present against the live graph at fleet sha a45a8dd before being listed, not assumed:
# the four classes with a `MATCH (c:OntologyClass) WHERE c.uri IN [...]` and the two verbs with
# `CALL db.relationshipTypes()`. Verbs are RELATIONSHIP TYPES here, not nodes — there is no
# `Predicate` label, and a count of 0 from that label is indistinguishable from a count of 0 from
# an empty one.
explains:
  - mesh:finProgramBrief
  - mesh:costLotCostingReview
  - mesh:StatefulSupportResponse
  - cost:LotCostingReview
  - fin:Program
  - cost:ProductionLot
doc_kind: how-to
# Canonical case from policy/personas.yaml, which R-017 rules outranks prose: ARCHITECT, not
# architect. Sibling runbooks carry the lowercase form and the validator matches
# case-insensitively, so both are accepted — this one is spelled the way the ratified config
# spells it, because the index sentence saying "lowercased" is what taught three pages the wrong
# case.
audience_hint: ARCHITECT
---

# Runbook — adding a graph to engine-lg

**Written 2026-09-12, having done it twice**: `fin_program_brief` (three Engine F verbs, a
named-hole refusal, a checkpointer) and `cost_lot_costing_review` (three engine-cost verbs, a
`fail` refusal, no checkpointer). Every step below is one I actually took, and every error in §N
is one that actually cost time. Marked **DISCOVERED** where I found it by inspecting a pod,
reading source, or hitting it.

**Scope.** A LangGraph graph admitted to the mesh as ONE verb, hosted by `engine-lg`, composing
other engines' verbs under the caller's identity (ADR-0046 §1). It does **not** cover: writing a
graph that mutates state (no ceremony slots exist on a hosted graph yet), a graph hosted in your
own process (ADR-0046 §8.5 route C — the contract is identical, the host is yours), or adding an
*engine*, which is [`adding-an-engine.md`](adding-an-engine.md) and a much larger page.

**Order of work.** §0 and §1–§4 need **no cluster and no seed window** — do all of it first, and
run the offline seals, because that is where the expensive mistakes are cheap. Only §5 needs a
prime, and it is the one thing you cannot schedule yourself.

---

## §0 — The output class, claimed before anything else

**For an engine, §0 is the component name. For a graph it is the OUTPUT CLASS**, and it is
irreversible-ish for a reason that is not obvious: **Contract D refuses atomically, so your row
cannot register until your `output_uri` exists as an `owl:Class` in the graph — and getting a
class into the graph needs a PRIME, which is scheduled infrastructure you do not control.**

Two questions, in this order.

**1. Does a class already exist that describes what your graph ACTUALLY RETURNS?**

```bash
# Every response shape, derived from the ontologies rather than remembered:
python -c "
import rdflib, glob
g = rdflib.Graph()
for f in glob.glob('setup/ontologies/*.ttl'):
    try: g.parse(f, format='turtle')
    except Exception: pass
q = '''PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?u WHERE { ?u rdfs:subClassOf+ <http://invincible-agent/mesh#Response> }'''
print(sorted(str(r[0]).split('#')[-1] for r in g.query(q)))"
```

**2. If one does, is it describing YOUR graph or borrowing somebody else's noun?**

⛔ **DISCOVERED, and it is the trap this whole engine exists because of.** Reusing a class is free
and skips the prime. It is also how Engine B was retired: it returned `mesh:AgentResponse`, whose
comment reads *"the final output of a smolagents CodeAgent run"* — Engine A's loop. That borrowed
noun had a live consequence: Engine A's generalist fallback stamps that `output_uri` on **every**
answer including a `no_match`, so a card selector keyed on *"the first result carrying an
output_uri"* rendered a fabricated card while the routing record correctly named a different
engine.

My second graph hit the same fork. `mesh:StatefulSupportResponse` existed and was mine, so reusing
it was tempting — but that graph declares `checkpointer: false` and the class is named for durable
per-thread memory. **A stateless graph describing itself with a stateful noun is the same defect
with my own name on it.** I declared `cost:LotCostingReview` and paid the prime.

**The decision rule:** reuse only if the existing class's `rdfs:comment` describes your output
*without being read generously*. If you find yourself explaining why it nearly fits, declare a new
one.

**And claim the verb name at the same time.** One name per (verb, subject): the registrar's
compensate-on-rescope sweep DELETES rows matching `(tool_urn, verb_iri)` whose `input_uri`
differs, so a second subject under one name silently replaces the first rather than adding.

```bash
# is your candidate verb or class name taken?
grep -rn "costLotCostingReview\|LotCostingReview" --include=*.py --include=*.ttl --include=*.yaml \
  agent_fleet/ setup/ policy/ src/ tests/
```

---

## §1 — The output class, if you are declaring one

**File:** `setup/ontologies/<domain>_extension.ttl` — your graph's *domain's* extension, not
`mesh_system.ttl`, unless the shape is genuinely platform-wide.

```turtle
cost:LotCostingReview a owl:Class ;
    rdfs:subClassOf mesh:Response ;
    rdfs:label "Lot Costing Review" ;
    rdfs:comment "…what it contains, what question it answers, and what it is NOT…" .
```

**Three conventions that are not stylistic:**

- **`rdfs:subClassOf mesh:Response` is load-bearing, not tidiness.** That one line buys exclusion
  from Engine O's grounding pool at the write site, so your output can never compete with your
  input subject for the question that invokes it. Verify you actually got it — the seal derives
  its population by SPARQL (`?uri rdfs:subClassOf+ mesh:Response`), so run that query and find
  your class in the result rather than trusting that the line is present.
- **The `rdfs:comment` is RETRIEVAL INPUT, not documentation.** doc-tools embeds
  `"<label> — <definition>"` and Engine O scores user queries against it. ⛔ **DISCOVERED:** my
  first comment said *"Distinguished from `mesh:AgentResponse` by…"* and the sibling-bleed seal
  went red — naming another class makes yours compete for that class's traffic, which is how
  `idp:Pipeline` won *"list the datasets in publog"*. **Put the contrast in a `#` comment above
  the class**, which people read and nothing embeds.
- **Say what the shape is NOT.** The per-measure classes in a domain and a *composed* class are
  different answers, and a comment that omits the distinction is how a composed verb loses to a
  single-measure one.

---

## §2 — The ratified row

**File:** `policy/graphs/<graph_id>.yaml`. One file, one graph, reviewed like a grant (ADR-0050
§1's discipline). **This file is the only thing that admits your graph** — ADR-0046 §2 refuses
`run_any_graph`, and the refusal is structural: a module in `graphs/` with no row here is
unreachable and unregistered.

The fields the contract turns on, and what each one decides:

| field | decides |
|---|---|
| `input_uri` / `output_uri` | Contract D's two ends. **Absolute URIs only** — a CURIE here reads at the registrar as a MISSING class rather than a malformed one, which is the confusion that has cost four separate diagnoses |
| `slots` + `kind` | whether the router can know a slot is missing. Without them a slot-shaped question surfaces as `NO_VERB_CLASSIFIED` — an information gap wearing a threshold gap's clothes |
| `referent` on a spoken slot | whether the ask card and the one-option menu work. **Declared, never sniffed from an `_id` suffix**: guessing cost a measured regression where the filler emitted a plausible value at 0.92 confidence and the engine answered an honest 422 to an answerable question |
| `arity` | `single` is FORCED when a slot is both required and a referent; the loader refuses the row otherwise |
| `refusal` | `fail` or `named-hole` — see below, it is a judgement |
| `checkpointer` | per graph, and OFF unless a node READS the state back |

**`refusal` is a design decision, not a default.** It says what your answer MEANS when an inner
verb refuses for the caller:

- `named-hole` — a brief missing one of three findings is still a brief, with the gap **named in
  the output** where the reader sees it. Use it when a partial answer is honestly useful.
- `fail` — a costing review missing one of three views is **not a review**: its whole claim is
  that the three agree, and two cannot support it. Use it when a partial answer presented as a
  whole one would mislead.

The host ENFORCES this (SDK `enforce_refusal`): under `fail`, a graph that returns `holes` gets
its output rejected with a 502 naming which. So declaring `fail` and returning partials is a
contract disagreement the host catches, not a convention you are trusted to keep.

**`checkpointer: false` unless a node reads the state back.** DISCOVERED the expensive way by
Engine B: `AsyncPostgresSaver` keyed by `thread_id`, durable, working — and **no node ever read
`messages`.** Storage with the appearance of statefulness.

---

## §3 — The graph module

**File:** `agent_fleet/graph_host/graphs/<graph_id>.py`, exporting the `builder` your row names.

**Return the graph UNCOMPILED.** The host compiles it, which is what keeps `checkpointer` the
row's decision rather than your module's — a module that compiled itself could attach durable
memory a row said was off.

**Identity is threaded, never ambient.** The host puts the initiator's headers in graph state; every
inner call forwards them. `engine-lg` holds **no standing credential**, so a node that finds no
identity must record a hole or raise and **must not call out** — proceeding would run a governed
read as the host, which is the laundering ADR-0029 Decision 5 forbids arriving through a door it
did not name.

**Read the endpoint contract; do not infer it.** ⛔ **DISCOVERED three times in one night**, each
costing a round trip: `/classify_predicate` needs a prior `/find_compatible_verbs` call (the real
path is **three** hops, not two — without it every question returns `UNKNOWN` with
`classify_called=False`, which looks exactly like a routing defect); `engine-cost`'s measure
endpoint takes `{"params": {...}}`; and `Disposition`'s field is `.action`, not `.kind`. **Derive
the population, never name it** applies to a request body and a NamedTuple field, not only to a
node label.

**engine-cost answers a missing slot with a 200 and a refusal BODY**, not a status code — so check
the payload, not just `status_code`.

**Do not put an LLM in the synthesis node.** The producer computes and the renderer displays; a
model asked to reconcile three payloads is a second implementation of the arithmetic, free to emit
a figure that is in none of them — and on a costing review that figure *is* the answer. Cite the
artifact each line came from and read values out of payloads rather than deriving them.

---

## §4 — Regenerate, and verify before going near a cluster

```bash
python scripts/generate_graph_manifest_schema.py       # validates every row, rewrites the schema
python -m pytest tests/graph_host/ -q                  # the offline half
```

**These are pre-flight on the EDIT. They are never a post-condition on the deployed system** —
stated twice because the distinction is the whole point of §5.

**There is NO host change.** That is the platform claim and it is sealed:
`test_the_host_names_no_graph` derives every `graph_id`, verb, module, subject and output from the
ratified rows and asserts `main.py` mentions none of them. If you found yourself editing the host,
something about your graph wants a contract change rather than a special case.

⛔ **DISCOVERED: that seal once failed on its own subject's DOCUMENTATION.** The host gained a
docstring citing both graphs as examples and the seal went red — it was matching a STRING when the
defect is a BEHAVIOUR. It now strips comments and docstrings and keeps code string literals,
because `if graph_id == "fin_program_brief"` IS the defect and lives in one.

---

## §5 — Verification: ask the authority, by name, at the resolution of the claim

> **Never ask a component about itself; never assert a count.**

**`engine-lg`'s `/health` is the component's own opinion.** It reports the graphs this process
admitted. It is useful for exactly one thing — *did the image contain my row* — and it is **not**
evidence that the mesh can route to your verb.

```bash
# 1. did the image contain the row at all?  (the component's opinion — use it ONLY for this)
kubectl exec -n sandbox <engine-lg pod> -- python -c \
  "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8098/health').read())"
#    expect your graph_id in `graphs`. An EMPTY list with `status: ok` is the defect in §N row 1.

# 2. is the verb in Neo4j?  RELATIONSHIP TYPES, not a node label.
CALL db.relationshipTypes() YIELD relationshipType
WHERE relationshipType = 'costLotCostingReview' RETURN relationshipType;

# 3. is it ELIGIBLE?  Eligibility is a CONJUNCTIVE read — Neo4j AND Weaviate.
#    A verb in Neo4j alone is the row that registers, reports accepted, and never matches.
python -m pytest tests/graph_host/test_ratified_rows_are_served_by_the_mesh.py -q
#    (needs NEO4J_URI, NEO4J_PASSWORD, WEAVIATE_URL, GRAPH_HOST_URL)

# 4. does it ROUTE?  Add your question to the ADR-0018 corpus and run it.
#    MEASURE FIRST, then write the expectation — see the rule in §N.
```

**Confirm every instrument ANSWERS before you believe any count.** ⛔ **DISCOVERED twice in one
day, in different costumes:** a dead port-forward returned `000` for one service while three
others returned 200, and a `pkill` pattern matching more than intended killed a second forward —
both times producing **the same failure count as a real finding**. Probe each endpoint, and keep
an in-cluster control (`kubectl exec` to `127.0.0.1`) so you can tell a broken forward from a
broken service.

**The absence case:** a fabricated verb must come back ABSENT through the same code path. A query
with a wrong label returns a confident uniform NOT FOUND, and that reads as a finding rather than
as a broken instrument.

**PASTE, DO NOT RETRY.** A blind second run cannot distinguish "transient" from "the thing is
wrong", and it destroys the first run's evidence.

---

## §N — Errors hit, and what each one teaches

| what happened | the general lesson |
|---|---|
| The image shipped the graph MODULE and not the ratified ROW. `policy/graphs/` had no `COPY` line. The host admitted **zero** graphs, registered zero verbs, and answered `status: ok` to every probe | **A host with nothing admitted is not healthy, it is unroutable with a green light.** `load_graphs()` failed loud on a row it could not honour and not on NO rows — the floor that was missing is the one for the empty case |
| I wrote *"see the COPY in `Dockerfile.agent`"* in the error message. **There is no such file** — it is generated in a heredoc inside `.github/workflows/build-containers.yml` | A citation to a nonexistent file is worse than none: it looks checkable and fails silently. Same defect as citing a transcript that does not exist |
| `langgraph` is the ENGINE's declared dependency, not the repo root's. A peer's worktree errored on import | **A root venv having a package is an accident of how it was synced.** Split the file: the coverage claim runs everywhere, the import half skips **naming the command** and what remains verified |
| A mutation aimed at `"slots": [s.model_dump(...)]` hit the identical line in a DIFFERENT function. Six tests passed and I nearly recorded "the seal does not bite" | **A mutation aimed at AN occurrence rather than THE occurrence proves nothing about either.** Locate the enclosing `def` first. This is sample-is-not-the-population living inside the instrument |
| Chasing *why* that mutation changed nothing found a real gap: the ref did not cover `referent`, and its seal varied two other fields | **The value came from investigating an anomaly, not from an instrument reporting one.** The tell was a green where a red was expected on healthy code |
| I shipped an SDK minor whose whole purpose — a shared function — was **not re-exported by the package**, only by the submodule | A release's own tests import from inside. **Import the thing the way the consumer will**, from the package. A derived export seal then found three more, one unexported for two releases |
| A routing probe returned `UNKNOWN` with `classify_called=False` for all four questions. It looked exactly like a routing defect | **A uniform extreme from a path you assembled yourself is an instrument failure first.** I had skipped `/find_compatible_verbs`; the graph had held 8 eligible verbs all along |
| My platform seal went red on the host's own docstring | **A check matching a STRING cannot see a BEHAVIOUR** — it flags the prose explaining the fix |
| A `pytest.skip` fallthrough for any field without a perturbation | A skip there is how the original omission survives a second time. **Replace it with a failure that says what to add** |

**One corrected claim, kept rather than edited away.** This page's §5 first said a 403 from an
inner verb and a 403 from a broken engine *"look identical to the graph — both become a named hole
with the same text."* Then I asserted the distinction (the graph separates *"the caller is not
entitled to X"* from *"X returned N"*), which made the sentence false. ⛔ **CORRECTED** — but the
underlying limit stands and is in the next section, because a docstring describing a limitation
the code no longer has is read as a live limitation.

---

## What this page cannot distinguish

- **A row that validates from a graph that works.** §4's seals prove the row is well-formed and
  the payload correct. They say nothing about whether your graph answers the question.
- **The host admitting a graph from the mesh routing to it.** Those are §5 step 1 and §5 step 3,
  and step 1 has been green with step 3 red. Never cite the first as the second.
- **An entitlement refusal from a misconfigured inner engine.** Both are 403, both become a hole.
  The graph is right not to guess. Only a FULL caller succeeding on the same verb a PARTIAL caller
  is refused attributes the refusal to the entitlement — a partial-caller refusal with no
  full-caller success beside it is not evidence about entitlement.
- **A fixture proving your graph branches correctly from the mesh scoping your caller.** A stub
  returning 403 proves the first. Only real persona credentials prove the second, and conflating
  them is the commonest way an entitlement claim is overstated.
- **Whether `refusal` was the right choice.** The host enforces that your output matches what the
  row declares. Nothing can tell you the row declared the honest thing for your domain.

---

## Appendix — the complete change list

**New (3 files, or 2 if you reuse an output class):**

1. `setup/ontologies/<domain>_extension.ttl` — *edit*, one class. **Needs a prime.**
2. `policy/graphs/<graph_id>.yaml` — the ratified row
3. `agent_fleet/graph_host/graphs/<graph_id>.py` — the module

**Regenerated (1):**

4. `schemas/graph_manifest.schema.json` — `python scripts/generate_graph_manifest_schema.py`

**Edits to shared files: NONE.** That is the platform claim, and the count is the point — a graph
is a row, a module, and an ontology line. **If your change list includes `agent_fleet/graph_host/main.py`,
stop:** the seal will catch it, and what you want is almost certainly a contract field rather than a
special case.

**Known gaps, named rather than fixed quietly:**

- **A new output class needs a prime you do not control.** Your row cannot register before the
  class is in the graph, and Contract D refuses atomically. Ride a prime that is already owed
  rather than asking for one — a prime for a single class is infrastructure bought with no
  information.
- **The composed policy directory is not mounted.** `GRAPH_POLICY_DIR` defaults to a path baked
  into the image, so a work-side ADR-0036 overlay would be **silently ignored** — a customer
  tombstoning a seeded graph would find it still registered. Correct while the seed is the only
  source; wrong the moment an overlay exists. Filed.
- **`docs:` WAS an unregistered prefix, and was registered between this page being written and
  being pushed.** ⛔ CORRECTED 2026-09-12: the gap I wrote here said it was declared in no TTL and
  no prefix table (`invincible-agent-f3`'s finding, the fourth instance of
  unknown-prefix-passes-through-verbatim, and the first caught before a row existed). `5685f3a`
  then declared it — `@prefix docs: <http://invincible-agent/docs#>` in `mesh_system.ttl` and
  `"docs:"` in the writer's prefix table — so this page's `iri:` now expands. **Kept rather than
  deleted**, because the reason the note existed is the durable part: an unknown prefix passes
  through VERBATIM, so the row registers, reports accepted, and never matches. If you add a page
  under a prefix the writer does not know, you get that silence and no error.
