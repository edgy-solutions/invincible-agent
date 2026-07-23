# PCN/PDN bulk-resolve — the one substrate extension (grouped review: 1 approval resolves N items)

The PCN/PDN part-obsolescence workflow (ADR-0029 Case-2 exemplar, `2b5615f`) needs **zero new
workflow-model step kinds** — the five slices are the whole model. Its net cost is **one narrow
substrate extension**: a HumanTask that a single approval resolves across N items (a grouped
review), keyed so execution stays per-item. This doc + `workflow_bulk_resolve.py` is the pure core
of that extension, in the same rhythm as the slice cores.

## 0. The dual of the Slice-5 join

Slice 5's `evaluate_join`: **N approvals gate 1 step** (fan-IN of approvals onto one grant).
Bulk-resolve: **1 approval resolves N items** (fan-OUT of one human action onto many promises).
They are mirror images and sit side by side — both are HumanTask lifecycle cores, both pure, both
take the authz/relevance decisions as INPUT.

## 1. Governing ruling — approval grain ≠ execution grain (banked)

**Approval grain is a UI decision the backend must serve; execution grain is per-item.** One human
action resolves N promises (the approver clicks once), but each item executes independently —
idempotent on `notice_fingerprint × mpn`, over its own resolved subject, retryable in isolation. So
the core produces **N per-item resolutions from one decision**, each carrying its own idempotency
key.

**DECISION (settled 2026-07-23) — idempotency substrate = VirtualObject-on-composite-key
`{notice_fingerprint}:{mpn}`.** Three-legged: (1) one consistency domain — the workflow model already
runs on Restate, so idempotency lives in the same substrate as execution; (2) keyed addressing IS the
per-item lock — Restate serializes per key and journals the effect (idempotency-as-execution, no
check-then-act TOCTOU); (3) the resolution lifecycle already lives in Restate's durable substrate, so
a Postgres dedup table would split ONE item's state across two stores with no compensating benefit —
the only thing Postgres is better at (querying) is a read-model you build regardless, fed by per-item
dispatch events. The one condition that would flip it: if the disposition effects were same-database
writes (transactional idempotency for free) Postgres would win; they aren't (external effect
dispatches). Reversible only by a scale argument nobody has raised (e.g. 9k-style key cardinality).
Guardrails: a retention/archival policy for resolved item-objects (unbounded keyed state otherwise —
and archival must keep items countable per Seal 1), and emit a per-item dispatch event into the
reporting read-model. Gates only the dispatcher, not this core; the core already emits the key on
every `ItemResolution`.

## 2. The funnel — stack of reducers, each measured by removal (instrument it)

A notice fans out to N part-items; most die before any human sees them. The stack:

```
items ──filter(relevance)──▶ ──auto-dispose(FYI lane)──▶ ──group(residue → approver)──▶ resolve
```

- **filter**: below a relevance floor → dropped (not affected). Not a disposition.
- **auto-dispose**: relevant + low-stakes + system-confident → an FYI lane, no human.
- **residue**: what a human must actually decide.

**PROPOSER — MECHANISM CODE, POLICY DATA (the arc's thesis, applied to the first policy core).** A
condition→disposition dict frozen in the proposer would be the lowercase-graph-map one altitude up:
someone's correct business knowledge frozen in a consumer, going stale the day the process owner
changes the process. So the split the arc uses all week — **mechanism stays code, policy becomes
data**:
- **Policy (data):** `setup/ontologies/pcn_disposition_rules.ttl` — the condition→disposition DECISION
  TABLE as flat `pcn:DispositionRule` individuals (`whenNoticeType` / `whenHasReplacement` /
  `whenAnyChangeClass` / `whenAllChangeClass` → `proposesDisposition`) + the category→change-class
  classification. Ingested via the manifest partition path → versioned, reproducible, owner-ratifiable,
  and **covered by the drift-check like every standards artifact**. v1 is the AGENT'S reading;
  every rule's `prov:wasDerivedFrom` is **deliberately empty** until a domain owner maps it to a
  governing clause (e.g. S3000L obsolescence management) — "drive from standards" made literal, and
  the emptiness is honest, not a TODO.
- **Mechanism (sealed code):** `agent_fleet/restate_analyst/pcn_disposition_proposer.py` + 15/15 —
  `evaluate_rules` (all-match-must-agree over an INJECTED ruleset), `score_relevance` (scope
  membership, no optimistic default), `build_part_items`. Two honest-degradation outcomes, both →
  no proposal → can't ride accept-all: **UNCLASSIFIABLE** (no rule matched) and **CONFLICT** (matching
  rules disagree → *abstain rather than pick* — a new outcome that only exists once rules are data,
  with its own red test).
- **Ingest gate:** `validate_ruleset` — a malformed ruleset fails at INGEST, not at an approver's
  screen (unregistered disposition; identical-conditions-different-disposition contradiction). The
  rdflib-validated discipline applied to rules.
- **Guardrail — decision table, never a rule language.** Fixed closed condition schema, flat rules,
  all-match-must-agree. A rule DSL (nesting/expressions/computed priorities) would be code-as-policy's
  revenge — policy so expressive it's code again, minus the tests. Schema evolution is an owner
  decision, not a DSL feature.
- **The override loop is the growth loop.** Every UNCLASSIFIABLE/CONFLICT part a human disposes (with
  its `override_reason` in `audit_record`) is a candidate rule — recurring → owner ratifies into the
  TTL → the gap closes at source. Policy grows from evidence with provenance: the self-hardening
  phonebook shape applied to business process.
- **Trajectory:** the interview authors *workflows*; this rules artifact is *vocabulary those
  workflows consume*. Both data, both owner-ratified — no conflict with the interview-authored endstate.
- **Third-set trigger (armed):** this is the 2nd per-domain descriptor/policy artifact (after the BI
  matcher's set). When a 3rd domain mints its own, that's the trigger to consolidate the *admission
  decisions* (not the sets) into one reviewed place — same third-instance rule that fired on the
  discard pattern.

**Seal 1 — honest funnel (auto-archived items stay COUNTABLE).** Nothing vanishes: the counts at
every stage sum to the input (`filtered + auto_disposed + residue == input`). Auto-disposed items
are inspectable, not hidden — silent shrinkage at business scale is the funnel telling a comforting
lie. `run_funnel` returns every bucket, not just the residue.

## 3. needs_review is `resolved_via` for the data layer — weak extraction cannot take an automated path

doc-tools' PCN/PDN extraction (`../doc-tools`, `ce168fb`) flags `needs_review: true` when a part's
MPN extraction is uncertain (the vision/OCR read is shaky). That flag is **provenance strength for
the disposition** — the exact analogue of Slice-4's weak-provenance seam one layer down. A
disposition taken over a part whose MPN we're not sure we read is **weak provenance seeding durable
action** — Slice-4 laundering wearing a part number.

Three structural rules (all sealed):
- **A needs_review item may NOT take an automated lane** — never filtered, never auto-disposed. You
  cannot trust an automated relevance/disposition decision on an MPN you're unsure you read
  correctly, so it is forced into human residue. (`run_funnel` routes it to residue regardless.)
- **A needs_review item is a MANDATORY EXCEPTION — it may NOT ride accept-all.** Reaching human
  residue is not enough: the review UI's accept-all is a single gesture over N items, and sweeping an
  unverified row in by default rebuilds the automated lane out of one click — a human "reviews" it by
  not noticing it in a batch of forty. Visibility (the badge) is not friction. So `resolve_batch`
  REFUSES a needs_review item that has no explicit override — it must be individually dispositioned
  (an override, whose reason records the verification), and until it is, the WHOLE batch is blocked,
  exactly like a no-disposition row. Sealed both layers: the core guard + the cortex-ui accept-all
  exclusion (an unverified row shows "override required", is excluded from the accepted count, and
  blocks submit).
- **A resolution CARRIES the needs_review flag forward, visibly** — even once individually verified,
  the durable `ItemResolution` (and the effect it dispatches) records that the underlying extraction
  was uncertain. A disposition approval never silently launders an unverified extraction.

## 4. Grouped review is per-approver-filtered (existence-oracle at batch scale) — Seal 2

The batch a given approver reviews = `residue ∩ {items this approver can see and act on}`. Two
approvers on the SAME notice get **different-sized batches**, correctly. An item an approver cannot
act on is not in their batch and does not leak observer-facing. This reuses Slice-3's
`observer_view` / `audit_record` split: the approver sees their batch (`observer_view`); the
withheld items are the `audit_record` (countable for audit, never surfaced to this approver). The
discriminating seal: approver A and approver B over one notice see batches that differ, each
excluding what the other exclusively owns — proven on the same input, both sides.

## 5. Accept-all-with-exceptions + capture-why is structural (ruling #5)

The review UI is a default-with-exceptions grid: accept the system-proposed disposition for every
row unless overridden. An override MUST carry a reason — enforced by the **type** (`Override` has no
default reason, and `__post_init__` rejects a blank/whitespace one), so capture-why cannot be
skipped. An item with no proposed disposition and no override cannot be resolved (you can't dispatch
an effect with no disposition — refuse honestly).

**The reason is provenance, so route it like provenance — two thin edges.** (1) The core holds only
a **non-empty floor**; it does NOT judge reason quality (whether "ok" suffices is a review-quality
governance question — parked with Decision D, same family as the anonymous-count disclosability, NOT
a validation rule invented in the lifecycle core). (2) The reason names what a human *doubted* about
an MPN, so it is **audit-grade** — when a resolution is later projected for observation/reporting it
belongs in `audit_record`, never `observer_view` (the two-object split from slice-3 §6).

## 6. The pure core — `workflow_bulk_resolve.py`

- `run_funnel(items, *, relevance_floor, auto_dispose_when) -> FunnelResult` (§2, §3-rule-1; Seal 1).
- `grouped_review(residue, approver, *, can_act) -> ReviewBatch` (§4; Seal 2).
- `resolve_batch(batch, decision, *, notice_fingerprint) -> list[ItemResolution]` (§1 execution
  grain, §3-rule-2 carry-forward, §5 capture-why).

Pure — no Restate, no Topaz. `can_act` (Topaz), relevance scores + `needs_review` (doc-tools), and
the system-proposed disposition are all INPUTS. The enforceable innovations are the four seals.

## 6a. resolveInstance for pcn — the descriptor admission decision (provider-work, flag not default)

A pcn `resolveInstance` provider (engine-o-backed, over the SUSTAINMENT graph — NOT engine-d's
DataHub matcher) needs its OWN descriptor-token set, built with the admission rule from
`agent_fleet/datahub_wrapper/instance_match.py` applied to pcn vocabulary — **do not copy the
BI-flavored `_DESCRIPTOR_TOKENS`** (dashboard/superset/table are wrong-domain here).

The happy case is trivial: instances carry deterministic IRIs keyed by MPN and notice-id
(`<http://internal/components/{mpn}>`, `<http://internal/sustainment/doc/{notice_id}>`), so an
exact-match resolves without any stripping.

The **decision-bearing** part is which prose nouns are descriptors, and the trap:
- **Descriptors (strippable):** `notice`, `notices`, `part`, `parts`, `component`, `components`,
  `mpn`, articles (`the`, `a`, `for`, `of`) — "the discontinuation **notice** for 23_0120" → "23_0120".
- **NOT descriptors (identifier-fragments — never strip):** `pcn`, `pdn` (and `ptn`). They look
  like entity-type nouns, but they are almost always part of the genuine identifier — "PCN 23_0120",
  "PDN 23_0120". Stripping them turns a resolvable id into an ambiguous bare number. This is exactly
  the admission-rule judgment the frozen-set comment anticipated ("entity-type nouns, never names"),
  applied to its first non-BI domain. **Flag it in the provider PR; do not let a default list ship.**

**CORE LANDED** (`agent_fleet/ontology_service/pcn_instance_match.py` + 11/11 tests): the pure matcher
— `_PCN_DESCRIPTOR_TOKENS` (notice/part/component + articles, EXCLUDING pcn/pdn/ptn),
`strip_descriptor_tokens`, `name_score` (mirrors the BI matcher), and the DETERMINISTIC exact-match
IRIs `component_iri` / `notice_iri` (byte-matched to doc-tools' `safe_*` transforms and verified
against the REAL live nodes `components/NSR01L30NXT5G`, `doc/IPCN25300X`). MPNs preserved verbatim;
the pcn/pdn trap test-pinned. **Remaining (deploy-gated) = the provider wiring:** (1) a handler that
tries the exact IRI first, then a descriptor-stripped graph query against `SUSTAINMENT_INSTANCES` (now
readable via engine-o's read-union), feeding candidates to the existing `instance_resolution.py`
decision table (exact / fuzzy-unanimous / fuzzy-mixed-abstain / empty); (2) register it as a
`mesh:resolveInstance` provider in the capability graph so the ladder discovers it. Then the 26 real
instance triples become consumable — "NSR01L30NXT5G" or "PCN IPCN25300X" resolves to its node.

## 7. Driver + seals (spec — deploy-gated)

`_run_definition` registers the grouped HumanTask; the dispatcher (per-item, idempotent, OUTSIDE
the workflow graph) emits N invocations on resolve. Composed-path seals, red-first: the funnel
conservation (Seal 1), the per-approver discrimination (Seal 2), the needs_review lane-block +
carry-forward (§3), and capture-why (§5). Depends on: the pcn class vocabulary + registered verbs
(the disposition effects as mesh verbs with endpoints), and the idempotency-substrate ruling (§1, settled).

## 8. Deploy sequencing + gates (before the pcn dogfood can go green)

**8.0 — THE GRAPH COLLISION (found 2026-07-23; the CORE-audit check surfaced it). FIXED.** Two fixes
collided: the doc-tools GRAPH-clause fix pointed runtime extraction at `<http://internal/SUSTAINMENT>`
so the mesh could see it; the PUT→POST/DROP-first fix made prime WIPE and re-land every internal
graph the manifest lists. The manifest lists vocabulary only. So the prime run that lands
`pcn_extension` — the step meant to enable the dogfood — would have DESTROYED the real extracted parts
first. Root rule (now in doc-tools AGENTS.md): **producers with different reproducibility must not
share a graph; DROP-first is only safe for data the manifest can reproduce.** Fix, both ends: (a)
doc-tools writes instances to `<http://internal/{DOMAIN}_INSTANCES>` (the pcn resolveInstance provider
queries THAT graph); (b) `clear_ontology_graphs()` drops MANIFEST-listed graphs only, never globs
`internal/*` — the invariant is enforced by the clearer, not by convention. This gates the prime run.

**8.0a — the split's OWN seam: don't re-hide instances (verified by inspection, then closed).** The
GRAPH-clause fix existed because instances in the default graph were invisible to engine-o, which
scopes to `http://internal/{domain}`. The split moved instances to `{DOMAIN}_INSTANCES` — *also* not
`{domain}` — so it could have re-created the invisibility one graph over. Enumerated the readers:
engine-o's `execute_sparql` is the ONLY reader of `http://internal/{domain}`, and every domain-scoped
caller queries `?cls a owl:Class` (vocabulary); instance resolution runs through Neo4j/Weaviate, not
this path; the supervisor reads via engine-o HTTP, not the graph. So the instance-reading-via-domain
set is **empty today** — but rather than rely on that, `execute_sparql` now scopes to the **UNION**
`{ <…/{DOMAIN}> <…/{DOMAIN}_INSTANCES> }` via `VALUES ?g … GRAPH ?g`, so any future consumer on the
path sees vocab + instances by construction. The read-side rule lives in the one derivation point,
mirroring the write-side split (doc-tools AGENTS.md carries both). rdflib-validated.

**8.0b — two migration residues (small).** (1) Any instances written to `http://internal/SUSTAINMENT`
between the GRAPH-clause fix and the split are manifest-listed and get DROP'd by the next prime —
acceptable ONLY because re-extraction is the plan (the dogfood re-extracts after the split deploys);
this specific batch does not survive prime, stated so the "dogfood data survives prime" guarantee
isn't over-claimed for it. (2) Pre-GRAPH-fix instances still in Jena's DEFAULT graph are permanent
invisible orphans — documented as dead space in `clear_ontology_graphs`; a one-time manual
`DROP DEFAULT` closes it if a store audit shows the default graph non-empty.

**Corrected sequence: graph-split + read-union (done) → B(2) → prime → dual-substrate dogfood → dispatcher.**

Three more seams the dogfood must clear — recorded in the open, not dissolved:

1. **The CORE re-tag audit wake — armed, NOT fired (superseding both the original claim AND its
   first correction).** History, so the record is honest: (i) an early note said "additive; doesn't
   wake the audit" — asserted without checking; (ii) that was corrected to "a FULL prime IS the next
   planned re-ingest and fires the wake" — true for a full prime; (iii) BUT pcn was ultimately landed
   by a **partition-additive ingest** (2026-07-23, `7f713cb` / run card), NOT a full prime. A partition
   ingest does not run `clear_ontology_graphs` and does not re-ingest IOF_Core, so it does **not**
   re-tag CORE and the wake **did not fire**. Net: the CORE re-tag audit is still **ARMED** against its
   original condition — the next of (a) a **full prime** (DROP-first, re-ingests IOF_Core), (b) the
   MANUFACTURING query path going live, or (c) the first observed cross-domain routing ambiguity (a
   query resolving to an IOF_Core class in the wrong domain). The audit is decision-bearing ontology
   governance (how IOF_Core shared under both MAINTENANCE and SUSTAINMENT should be domain-tagged),
   still owed when its wake fires — it just hasn't fired. (Lesson: the stale-assert pattern can operate
   on a process record — a wake logged as "fired/deferred" against an event that never happened.)

2. **B(2) probe gates the dogfood — the sync is under open suspicion.** The interview's authorized
   sets read Neo4j `:OntologyClass` nodes, but "pcn classes ingested" (Fuseki) and "pcn classes
   offered by the interview" (Neo4j) are producer-truth and consumer-truth across the still-suspect
   Jena→Neo4j sync (the InstanceIdentifier/InstanceResolution drop — suspected per-node write bug on
   long comments). So the dogfood red→green must name BOTH substrates: pcn classes present in Fuseki's
   `SUSTAINMENT` graph **and** present as `:OntologyClass` in Neo4j **and** surfaced by `/classes`.
   Run B(2) before or as part of the prime run.

   **Pin the interpretation NOW, before evidence (or a green result closes B(2) by inference).** The
   probe tests the HYPOTHESIS (per-node write fails on long comments), not the SYMPTOM (the
   InstanceIdentifier/InstanceResolution pair absent from Neo4j). The 2×2 — {pcn classes sync: Y/N} ×
   {the missing pair reappears after re-ingest: Y/N}:
   - **pcn syncs, pair reappears** → staleness was the whole story; the long-comment bug hypothesis is
     moot (nothing was ever broken but freshness). Close B(2).
   - **pcn syncs, pair still missing** → the long-comment hypothesis is FALSIFIED and the drop is
     UNEXPLAINED — this is MORE open, not less. Do NOT record as "sync works"; the pair's absence is a
     separate live bug needing its own probe.
   - **pcn does NOT sync (drops)** → hypothesis CONFIRMED (long `rdfs:comment`s break the per-node
     write). Fix the sync; the pcn classes were the probe that caught it.
   - **pcn does not sync, pair reappears** → mixed/weird (two independent effects) — investigate both,
     do not average them into a verdict.

3. **The pcn classes ARE the cheapest live probe of the suspect sync bug — keep their comments long.**
   `pcn:Component` / `pcn:SustainmentNotice` etc. carry long `rdfs:comment`s. That is deliberate and
   load-bearing here: if the suspected per-node-write-on-long-comment bug is real, these classes will
   drop at the Jena→Neo4j boundary — same shape as the descriptor query was for containment. Do NOT
   shorten them to make the ingest "safer"; the length is the test.

**Sequence — DONE through the dogfood (2026-07-23, `7f713cb`; NOT via full prime — partition-additive):**
B(2) probe [CLOSED — pair survives fresh re-ingest, run card] → pcn `pcn_extension` partition ingest
(additive, domain=SUSTAINMENT explicit, no clear) → dual-substrate dogfood GREEN (Fuseki ∧ Neo4j ∧
/classes, all 4 pcn subjects; SUSTAINMENT_INSTANCES + other domains untouched). **Remaining:** the pcn
resolveInstance provider (so the 26 real instance triples become consumable), disposition verbs
per-endpoint, then the dispatcher (idempotency settled, §1). NB: this used the partition-additive
mode; a full prime (DROP-first) was never run, so the CORE-audit wake (§8.1) remains armed.
