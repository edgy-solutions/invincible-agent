# Standards posture — three rules, by what job the standard does

Cited by ADR-0024 (standards composition), ADR-0029 (process model), ADR-0032 (analyst loop). The arc
adopts standards in three DIFFERENT ways depending on the job the standard does. Written down so the
posture is an arguable, consistent position — not a series of sidesteps a future auditor (or our own
work-deploy architect) reconstructs suspiciously. The deepest rule underneath all three: **one producer
(the graph), many derivations** — standards are the graph's source-authority inputs or its export dialects,
never a second source of truth.

## Rule 1 — DOMAIN / CONTENT standards → adopted as SOURCE-AUTHORITY DATA (always, now)
Vocabulary + policy standards land as their OWN artifacts, consumed by generic mechanism — the strongest
form of adoption.
- **Instances:** IOF Core + IOF MRO, DIN EN 62264 (tagged TTL in the prime manifest), S3000L (the
  sustainment backbone; forked-core caused a real design conversation), JESD22 (the qualification tables
  in the evidence money-shot), mil-spec extensions.
- **How:** the standard's ontologies land in Fuseki → sync to Neo4j → drive `/classes`, the interview's
  authorized subjects, and eligibility checks. No Python enum approximating IOF; the actual artifacts are
  source-authority. Policy TTLs (`*_disposition_rules.ttl`) are the same move for rules.
- **Deviations are governance questions, not smuggled:** the CORE re-tag audit (`IOF_Core` lives inside
  MAINTENANCE by first-consumer accident, arguably belongs to everyone) is a NAMED armed wake with an
  explicit deferral — the discipline applied to the standards' own organization.

## Rule 2 — PROCESS / NOTATION standards → SEMANTICS MINED, runtime DECLINED
Adopt the standard's theory; decline its interpreter. Bet: a small ENFORCEABLE model beats a large
expressive one, because an imported interpreter is unsealed surface area.
- **BPMN** (ADR-0029): superseded as a runtime; kept the process theory as three seal-able step kinds
  (spo_operation / human_await / direct_call) instead of a ~50-element interpreter. Enforcement over
  notation.
- **DMN:** the disposition decision table is DMN's exact territory. Kept DMN's SEMANTIC discipline (flat
  rule individuals, explicit hit policy — the all-match-must-agree + subsumption-rejection IS a hit-policy
  decision) WITHOUT DMN's XML serialization or runtime.
- **PROV:** cherry-picked terms where they fit (`prov:wasDerivedFrom` slots on rules, `ruleset_ref` hashes,
  `requested_by` threads) — not wholesale W3C PROV adoption.

## Rule 3 — INTERCHANGE / ARCHITECTURE-DESCRIPTION standards → adopt as EXPORT/IMPORT SCHEMA at the boundary, ON TRIGGER (not now)
ODCS (Bitol/LF Open Data Contract Standard), ODPS (Open Data Product Specification), CALM (FINOS Common
Architecture Language Model). These describe the system's SHAPE and PROMISES for other tools/orgs to
consume. **Key asymmetry vs BPMN: they have NO runtime to import** — adopting one costs a schema mapping,
not an engine. Their shape (ratifiable git artifacts describing promises, generic-consumed, drift-checkable)
is exactly the mesh thesis. So DECLINING them would be inventing proprietary YAML for what an LF standard
already specifies — a generic-at-birth violation one level up. The failure mode here is **premature
adoption, not sidestep**: mapping before the boundary exists is speculative, and CALM-exporting a
capability graph mid-M2-rename exports names that change next week. So: `directional and greenfield` is the
CORRECT current state — but it becomes three ARMED WAKES with named consumers, adapters at boundaries that
CONSUME the graph (never a second authority; the graph is the producer, the standard is its dialect):
- **ODCS wake = the DQ/coverage verb (ADR-0032, mid-term).** The verb READS declared data contracts, not
  an invented expectation format — coverage assessed against what the contract PROMISED ("no key links
  vendor performance to unit cost" becomes checkable vs the contract) is far stronger than against inferred
  expectations. ODCS contract in the prime manifest = philosophically identical to a disposition-rules TTL.
- **ODPS wake = the first workflow-PROMOTION** (an analyst-loop approved multi-SPO path promoted to a
  product). The promoted artifact's manifest IS an ODPS document — ports + terms + SLOs — which is what
  makes a promoted chain more than a registered path.
- **CALM wake = the first external-architecture ask OR the work-deploy compliance review** (whichever
  first). The mesh already IS an architecture graph (engines, capabilities, providers, registrations in
  Neo4j); CALM makes it EXPORTABLE in a standard architecture language — a machine-validated answer to
  "show me the architecture" instead of a stale diagram. This is the compliance-conversation insurance
  (below) made concrete.

## Standing liabilities (name them, don't improvise them)
- **L1 — the compliance conversation.** The domain-standards answer is STRONG (the actual S3000L / 62264
  TTLs are in the graph with provenance — auditable). The process answer must be PREPARED, not improvised
  in the meeting: "we render BPMN-style views and our workflow YAML maps to a BPMN subset, but we do not
  EXECUTE the standard" (same for DMN decision tables). Defensible; not spontaneous. CALM export (Rule-3
  wake) is the direct mitigation for the architecture half of this.
- **L2 — the expressiveness wake.** ADR-0029 dissolves fan-out/branching/dynamic-subjects via per-item
  invocation + a dispatcher, with ZERO new step kinds. That has a ceiling: the FIRST branch that cannot be
  dissolved forces a real branching step kind. Named risk, not yet hit.
- **(minor)** no Camunda/DMN tooling interop; no standard process diagrams for owners who think in them
  (until the CALM/BPMN-view exports land).

## The one-line policy
Domain standards ARE the data (Rule 1). Process standards lend their SEMANTICS but not their runtimes
(Rule 2). Interchange standards become the graph's DIALECTS at live boundaries, on trigger (Rule 3). The
graph is the single producer; every standard is either its input or its export — never a rival authority.
