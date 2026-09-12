# ADR-0051 — Sustainment safety assessment: the mesh drafts a risk and refuses to accept it

**Status:** Proposed (2026-09-10). **Written before the build, so the wrong build is refusable before
the right one starts.** **Four rulings recorded 2026-09-10**, each marked RULED in place with its
source rather than collected at the top: §3 (`trendMishaps` deferred to slice 3), §5 (the author's
visibility audience; `rejected` joins `accepted` as reason-required), §9 (the SAFETY compartment
deferred, not refused). **Two questions remain open and belong to a domain owner rather than an
architect** — §10.1 (which systems hold the hazard log) and §10.2 (who ratifies the matrix).
**Increments 0 through 4 need neither, so the lane can start.**
**Date:** 2026-09-10
**Deciders:** Architect
**Related:** ADR-0005 (domain vs platform namespaces), ADR-0007 (survey before mint), ADR-0029
Decision 5 (pre-resolved step, initiator identity), ADR-0031 (instance resolution ladder),
ADR-0034 (admission policy / autonomous path), ADR-0035 (two planes), ADR-0036 (seed + overlay),
ADR-0041 (ingest on arrival, provenance-gated truth), ADR-0045 (Engine F — the stamped template for
a domain engine), ADR-0046 §2 (one graph one verb; `run_any_graph` refused), ADR-0049 (cross-engine
composition, `DERIVED_FROM`, refuse-by-default intersection), ADR-0050 (canvas templates)

---

## The claim, in one sentence

Sustainment safety work is *read-and-cross-reference at fleet scale* followed by *a signature at a
defined authority level*; the mesh does the first under the initiator's identity with provenance,
and is structurally incapable of doing the second.

---

## Context — what is already here, read rather than remembered

**SUSTAINMENT is a live domain with six seeded ontologies**, not a greenfield
(`setup/prime_databases.py:193-255`): IOF Core, S3000L, `pcn_extension.ttl`,
`pcn_disposition_rules.ttl`, `product_structure_extension.ttl`,
`qualification_status_vocabulary.ttl`. Four facts from that layer bind this ADR:

1. **`pcn_disposition_rules.ttl` is POLICY AS DATA** — "the condition->disposition decision table
   the proposer consumes", ingested so it is "versioned, reproducible, owner-ratifiable, and covered
   by the drift-check", with every rule's `prov:wasDerivedFrom` **empty pending domain-owner
   ratification**. A severity/probability matrix is the same shape of thing and gets the same
   treatment (§2).
2. **`product_structure_extension.ttl` ruled how to mint**: S3000L's own names where the standard
   covers the need (`Breakdown`/`BreakdownElement`/`ApplicabilityStatement`, "found by reading it
   rather than inventing Assembly/Component/Effectivity and silently forfeiting three citations"),
   house convention **labelled as such and carrying no `derivedFrom`**. A cited-but-invented IRI is
   worse than an empty slot.
3. **`qualification_status_vocabulary.ttl` is a seed MENU, not an enum** — the writer validates
   against the file and an unrecognized status is a loud ingest-time refusal.
4. **The instances are written by another repo.** `prime_databases.py:208`: the pcn class IRIs "are
   EXACTLY the instance types doc-tools' `SustainmentPlugin` writes", and declaring them here "lights
   up `/classes` + the SPO-interview operable-subjects menu over the parts doc-tools already
   extracts." This repo owns vocabulary; doc-tools owns extraction (§6).

**Engine O already owns SUSTAINMENT instance resolution.**
`agent_fleet/ontology_service/main.py:598` registers `engine-o` as the SUSTAINMENT
`mesh:resolveInstance` provider, self-registering every boot. A safety engine does not re-provide it
(ADR-0031).

**There is a stamped pattern for "one review that fans out".** `setup/ontologies/mesh_system.ttl:180`
declares `mesh:DispositionReview` as "a server-authored batch of per-part disposition proposals …
opened as ONE human review that fans out per-part dispatch tasks on approval." A fleet-wide risk
draft is that shape and should not invent a second one.

**And there is a hard-won lesson about how a verb dies.** The comment above that class records why it
was declared: `mesh:proposeDisposition` named the class as its `output_uri` from the day it woke, no
TTL declared it, and it existed only because `scripts/seed_sandbox_predicates.py` MERGEd it into
being. Sandbox had the node; every fresh cluster did not; the registrar MATCHes and refused the edge
with a Contract D 422 that was telling the exact truth. **Nine of Engine A's ten verbs registered and
that one could not, permanently.** Every output class this ADR implies is declared in a TTL before
anything registers, and the seal runs against a fresh prime (§8 seal 1).

**The human-task substrate exists and is not what a design sketch assumes.**
`policy/task_grants.yaml` is the fifth content namespace: deny-by-default, Topaz-decided
(`task_audience` `can_act`), git-asserted, audience key `"<task_kind>:<compartment>"` — the live
instance is `pcn_disposition:SUSTAINMENT` (`AGENTS.md:572`). Two properties of it override the
obvious design:

- **`grant_to` is USERS ONLY.** A group name seeds a phantom `user:<group>` that passes readback and
  routes the approval to nobody — named in-file as "the sharpest silent-wrong-grant". Group-based
  audiences are a deferred design decision, not an option this ADR may quietly take.
- **Existence of a task is sensitive** (existence-oracle). `can_view` is deny-by-default, so a caller
  outside an audience does not *see* the task at all. "Sees it but cannot dispose it" is a
  **second audience**, declared deliberately — never a fallback the substrate provides.

Per-kind decision verbs live in `src/iagent/human_tasks.py:388` (`_VERBS_BY_KIND`, default
`approved`/`rejected`) with `_REASON_REQUIRED` at `:396` for verbs "whose meaning is empty without a
stated reason", sealed by `tests/test_task_kind_declarations_match_code.py`.

### The four failures this addresses

All four are cross-reference failures over unstructured text and structured records — a person's
memory failing at fleet scale. None is a judgement failure, and judgement is out of scope by §7.

1. **Orphaned hazards** — open, with no owned mitigation, or a mitigation closed on paper and never
   verified in the field.
2. **Duplicate hazards** — a new write-up opens a new hazard instead of linking to the existing one.
3. **Blind deferrals** — a work order deferred with no check against the safety-critical items list,
   and no statement of which hazard the deferral re-opens.
4. **Late trends** — a pattern across tail numbers or lots, visible in the narratives months before
   it crosses a threshold anybody watches.

---

## §0 — Claim the names first, and there are eight sites, not four

**An ADR names an engine in prose. It does not allocate a component name.** The runbook's §0 exists
because ADR-0045 called the finance engine "Engine F" and `engine-f` was already the presentation
agent; reusing it would have pointed `PRESENTATION_AGENT_SVC_URL` at a finance engine and taken
`/render_ui` down fleet-wide.

**This ADR calls it "Engine S" in prose and allocates nothing.** The candidate set below is a
*proposal to be re-checked at implementation time*, because a name can be claimed between this ADR
and that commit:

| namespace | candidate | set where |
|---|---|---|
| helm values key | `engineSafety` | `helm/invincible-agent/values.yaml` |
| component / service / deployment | `engine-safety` | `helm/…/templates/engines.yaml` `$engines` list |
| image name | `safety-agent` | `values.yaml` `image.name` |
| Keycloak client id | `iagent-safety-agent` | `keycloak.serviceClients` |
| source directory | `agent_fleet/safety_agent/` | — |

**`engine-s` is rejected deliberately.** The two most recent engines are `engine-fin` and
`engine-cost`; the single-letter convention is already broken, and a one-letter name is the hardest
string in the tree to grep without false positives (`ENGINE_S` matches `COPYENGINE_S_*` in a vendored
site-packages file today). The word costs nothing and greps cleanly.

**The check, run for the candidate before a line is written** (runbook §0):

```bash
grep -rn "engine-safety\|engineSafety\|ENGINE_SAFETY\|safety-agent\|safety_agent" \
  --include=*.yaml --include=*.py --include=*.tpl --include=*.txt --include=*.sh \
  helm/ agent_fleet/ src/ scripts/ tests/
```

Run 2026-09-10 on `881b65a`: **free** (only `.venv` noise). Ports in use at that sha are
8080–8090 and 8095–8098; **8091–8094 and 8099 are free.** Both facts are perishable — the check is
the deliverable, not the answer.

**The eight registry sites**
(`docs/plans/adding-an-engine-has-more-registry-sites-than-the-runbook-names.md`). The runbook names
four; four more each have their own silent failure mode:

| # | site | what breaks if missed |
|---|---|---|
| 1–4 | values key / component / image / Keycloak client | runbook §0 |
| 5 | `values.yaml` `primeSubstrate.reregisterEngines.deployments` | engine never restarts, so never re-registers |
| 6 | `tests/test_reregister_covers_every_registering_engine.py:47` `_KEY_TO_AGENT_DIR` | **every check in that file SKIPS the key** — how `engineFinance` went five days unexamined |
| 7 | `scripts/mirror-to-artifactory.ps1` | work cluster cannot fall back to ghcr → ImagePullBackOff the moment the chart flag flips |
| 8 | `ENGINE_<X>_PUBLIC_URL` in `templates/configmap.yaml` | **silent** |
| — | `.github/workflows/build-containers.yml` matrix | no image is ever built at any pinned sha |

Site 6 matters most here: a missing row does not fail, it **skips**, and a skipped seal reads as a
pass.

---

## §1 — Survey before mint (ADR-0007), against a domain that already has six ontologies

**No `safety:` class is minted until the survey comes back empty for it.** S3000L is a logistic
support analysis standard and IOF Core is an industrial ontology; both plausibly already name failure
modes, failure effects, maintenance tasks, and applicability. The product-structure precedent is the
rule: the standard's own names where it covers the need, citations verified present in the **live**
graph, house convention labelled as house convention with no `derivedFrom`.

The survey is a query against the primed graph, not a reading of the spec PDFs, and its **result is
recorded in the TTL's header comments** — including the terms looked for and *not* found, because a
later reader cannot otherwise distinguish *surveyed and absent* from *never surveyed*.

Minted terms go in a domain namespace (`safety:`), never `mesh:` — ADR-0005's two-class rule; `mesh:`
is the platform's, and a hazard is not a platform concept. Full IRIs in the graph; every URI in a
manifest goes through the prefix helper (runbook §8), because an unregistered prefix passes through
verbatim: the row registers, reports accepted, and never matches.

The shape the survey is trying to fill — stated as *what must be expressible*, not as a class list,
so the survey can satisfy it with S3000L terms:

- a **hazard**: a condition that can cause a mishap, with severity, probability, and a status that
  includes *not assessed*;
- its **causes**, linked to maintenance-plane objects where known;
- its **mitigations**, each with an owner and a field-verification state;
- a **safety-critical item** whose failure or omission opens a hazard;
- a **write-up**: a deficiency, hazard report, or mishap narrative as ingested — typed, not chunked
  (ADR-0041);
- a **risk assessment**: a drafted severity/probability statement over a hazard, with its evidence,
  its acceptance state, and the authority level its severity implies;
- an **acceptance authority** as a *role*, never a person.

**The three-state rule applies to every verdict-shaped property.** No defaults, on the `favourable`
precedent (`agent_fleet/cost_agent/measures.py:516-546`: the producer's verdict, absent when nothing
moved, because `false` would read as "this got worse"). A hazard nobody has assessed is
`not_assessed` — never the bottom of the matrix, which reads as *assessed and negligible*.

---

## §2 — The risk matrix is DATA, and this is the load-bearing decision

**`setup/ontologies/safety_risk_matrix.ttl`, seeded in `prime_databases.py` LAYER 2 SUSTAINMENT,
exactly as `pcn_disposition_rules.ttl` is.** It carries the severity×probability → risk-level table
and the risk-level → acceptance-authority ladder. Seed content is the agent's reading of MIL-STD-882
convention, **labelled SEED, every row's `prov:wasDerivedFrom` empty pending domain-owner
ratification**. An unrecognized severity or probability is a loud refusal at draft time, not a
coerced value (`qualification_status_vocabulary` precedent).

**Why this is the decision and not a detail:** the matrix and the authority ladder are exactly what
differs between programs and customers. In code, the second customer is a fork of the drafting
engine; as ratifiable data, the second customer is an overlay file and a re-prime. It also puts the
*one artifact a safety authority will actually argue with* under git-blame with a named ratifier —
the only form in which they can disown it.

Seal 4 exists solely to prove this claim is true of the build and not just of the ADR.

---

## §3 — Decision: one new engine, governed reading, over the existing SUSTAINMENT plane

**Engine S is a new engine, not verbs bolted onto Engine O.** Engine O is the SUSTAINMENT resolver
and owns `SUSTAINMENT_INSTANCES`; safety assessment is governed *reading* that composes over the
maintenance and product-structure planes. This is ADR-0045's ruling applied a third time and
ADR-0035's two planes: analysis engines read, they do not mutate the plane they read.

**Engine S does not register `mesh:resolveInstance` for SUSTAINMENT.** That provider exists
(`main.py:598`) and a second one is a second truth.

Standard Contract D registration through the fleet helper, with the runbook's REQUIRED items from the
first commit: `/version` and the gating-manifest entry, retry-with-backoff whose readiness **fails on
GAVE UP**, no success line that does not check success, every manifest URI through the prefix helper,
and the boot guard (does every class made findable lead to a verb?).

### Verbs — slice 1 and 2

Every verb declares subject class, slots (§4), explicit arity, a refusal contract, and a **fixed
output type** (ADR-0030). Every output class is declared in a TTL that primes, before registration.

| verb | subject | slots | output | what it does |
|---|---|---|---|---|
| `safety:findOrphanedHazards` | hazard (set) | `scope` (referent-bound) | ranking archetype | open, no owned mitigation — or a mitigation not field-verified. Ranked severity then age. |
| `safety:traceHazardToMitigation` | hazard (single) | `hazard_id` spoken-mandatory, referent-bound | decision-path | hazard → causes → mitigations → work orders → verification, **with every gap named** rather than omitted |
| `safety:assessDeferralRisk` | work order (single) | `work_order_id` spoken-mandatory | risk card | is the item safety-critical; which hazard the deferral re-opens; drafted severity/probability with evidence |
| `safety:classifyWriteUp` | write-up (single or set) | `write_up_id` \| `since` | classification + link **proposal** | maps narrative to the hazard taxonomy and **proposes** a link to an existing hazard or a new one. Proposes. Does not create. |
| `safety:draftRiskAssessment` | hazard (single or set) | `hazard_id` \| `scope` | risk assessment artifact | drafts severity/probability with a citation for every figure; records the implied authority level; opens the acceptance review. **Cannot set accepted.** |

`safety:trendMishaps` is **named and deferred to slice 3** — **RULED 2026-09-10 — see
[rulings#r-004--adr-0051-sustainment-safety-four-rulings](../rulings/README.md#r-004--adr-0051-sustainment-safety-four-rulings) (c)**: a trend
needs a threshold, a threshold is overlay policy, and
shipping it before §2's matrix has a ratifier would put the one number a program office argues about
into an engine parameter. Deferring it costs one verb; shipping it early costs the §2 precedent.

Fleet-scale `draftRiskAssessment` takes `mesh:DispositionReview`'s shape: **one review that fans out
per-hazard tasks on approval**, not N tasks at draft time.

---

## §4 — Slots from day one — and Engine S is the third engine, which has a consequence

`agent_fleet/safety_agent/slots.py`, pattern `planning_agent/slots.py`, per runbook §4. Without
declarations the router cannot know a slot is *missing*, only that nothing cleared threshold — an
information gap wearing a threshold gap's clothes.

Derived from `inspect.signature`, **never hand-transcribed**, with the three details that each cost
somebody a measured failure: `eval_str=True` (or every `Literal` arrives as the literal *text*);
unwrap `Optional[X]` but **stop at a real container** (the double-unwrap that produced
`422 unknown fiscal period(s): F, Y, 2, 6, -, Q, 4` — a message naming characters); and a
**`referent` class URI on every spoken `*_id` slot** (without it the filler puts the NAME in the id
slot — `site_id="Aurora"` at 0.92 confidence, the largest single failure class in the planning
corpus). All four slot kinds declared including the unused ones, so a reader can tell *considered*
from *forgotten*.

Severity and probability vocabularies are **DATA from §2's matrix**, attached in
`with_live_vocabularies()` at registration — `slots_for` stays a pure signature derivation.

**The consequence the runbook predicted.** §4 files, unfixed, that Engine F's `slots.py` is a second
implementation of Lane 1's derivation, and states the trigger: *"A third engine is where this stops
being a cost and becomes the defect."* **Engine S is the third engine.** The extraction to
`agent_fleet/utils/slot_declarations.py` is owed by this lane, under the flat/packaged idiom of §5 so
it survives containerisation. A third copy is refused by name.

---

## §5 — Acceptance is a task disposition, and the substrate for it already exists

**No verb writes an acceptance.** Acceptance is a HumanTask disposition on the existing substrate.

**Audiences, one per authority level**, because MIL-STD-882 ties acceptance authority to the risk
level — which is precisely what the audience key convention expresses:

- `risk_acceptance_high:SUSTAINMENT`, `risk_acceptance_serious:SUSTAINMENT`, … one audience per level
  the §2 ladder names. The ladder is data; the audiences are the git-asserted grants that implement
  it, and the drafter records which one an assessment implies.
- `hazard_link_review:SUSTAINMENT` for `classifyWriteUp`'s proposals.
- **`risk_assessment_author:SUSTAINMENT`, view-only, granted to the drafter at draft time.**
  **RULED 2026-09-10 — see
  [rulings#r-004--adr-0051-sustainment-safety-four-rulings](../rulings/README.md#r-004--adr-0051-sustainment-safety-four-rulings) (a)**
  (source: architect's disposition of §10.3, this ADR's review). Deny-by-default
  `can_view` means the drafter cannot otherwise see their own pending item — they would file a bug and
  they would be right. **The existence-oracle protects against outsiders, not against authors**, and
  that sentence is the rule this audience instantiates, not an exception to it.

`grant_to` entries are **users only** (`validate_policy` refuses a `grant_to` not in `users.yaml`); a
group name would seed a phantom `user:<group>` that passes readback and routes to nobody. Every
audience carries an accountable `granted_by` + `reason`.

**One-per-level is the constraint's workaround wearing a design's clothes, and it is a SCHEDULED
simplification rather than a surprise.** The users-only rule is declared in the same words in three
policy namespaces — `policy/capability_grants.yaml:31`, `policy/ontology_compartments.yaml:32`,
`policy/task_grants.yaml:26` — and each names group support as a deferred design decision. Splitting
acceptance into one audience per authority level is what that constraint costs here: an authority
level *is* a group, and it is being enumerated by hand because it cannot be named. **When group
audiences are ruled in `task_grants.yaml`, §5 collapses to one row per level** and the grant file
stops re-listing the same people under adjacent keys. Recorded on the M3 list so the collapse is
scheduled work rather than a discovery. Nothing here blocks on it: the per-level audiences are
correct under today's substrate, and the seals key on the audience, not on how it is populated.

Decision verbs are `accepted` / `rejected` / `returned_for_rework`, and **BOTH `accepted` and
`rejected` are reason-required** — **RULED 2026-09-10 — see
[rulings#r-004--adr-0051-sustainment-safety-four-rulings](../rulings/README.md#r-004--adr-0051-sustainment-safety-four-rulings) (b)** (source:
architect's review of this ADR, extending the ADR's own proposal, which named only `accepted`). A bare acceptance erases the
rationale, which in this domain *is* the artifact; **a bare rejection erases exactly the same thing**,
and "parts entered in the legacy system" versus "notice withdrawn by the vendor" — the file's own
argument for `acknowledged` at `human_tasks.py:394` — is the same distinction one level over. Sealed
against the declaration, by extending the existing declarations-match-code seal rather than copying
it.

**AMENDED 2026-09-11 — do NOT add rows to `_VERBS_BY_KIND`; the declaration path landed while this
ADR was being written.** Source: the M3.3 lane (`iagent-mesh-sdk-ca`), verified in the tree rather
than taken on report. `policy/task_kinds/` exists with four declared species
(`access_request`, `extraction_refusal`, `grouped_review`, `workflow_ack`), each a YAML carrying
`kind` / `renders_as` / `accepts`; `iagent-mesh` v0.6.0 is pinned fleet-wide (`pyproject.toml:62`,
`values.yaml:666` `meshSdkVersion`) and its `TaskKind` row carries `reason_required` as a field
validated as a subset of `accepts`. `_VERBS_BY_KIND` still stands at `human_tasks.py:388` **only
because its deletion is gated on cortex-ui's parity seal**, not because it is still the way in.

**So the safety kinds are DECLARATIONS, and R-004(b) is a property of the declaration, not of a code
table** — `reason_required: [accepted, rejected]` on the row, which is where it survives the cutover.

**BUT `reason_required` ON THE ROW DOES NOTHING TODAY, and a seal that accepts the declaration as
evidence would be asserting a property the runtime does not have.** Corrected 2026-09-11 by the M3.3
lane against its own R-004 note, traced rather than remembered: `validate_decision` checks
`if decision in _REASON_REQUIRED and not comment.strip()`, and `_REASON_REQUIRED` is a **global set of
verb strings** consulted **without reference to `kind`**. Reason-required is therefore a property of a
VERB everywhere it appears, and declarations are not wired into `human_tasks` at all — that is the
ungated half of the cutover. **Declared-and-unenforced is precisely the shape that produced the
`isRegisteredKind` defect**, and for a risk acceptance it is the gap this ADR exists to close. So
seal 6 asserts the **runtime refusal** — a disposition with an empty comment is rejected — and treats
the declaration as the thing under test, never as the evidence. Per-species semantics (a reason
required for a safety acceptance and not for an access request) are expressible only after the
cutover; until then the global rule is what parity means, and the seal says which one it measured.

**The row's shape**, from the SDK's own model: `kind` as a snake token with **no colon** (a colon
separates an authz audience key from a render contract, and the two have been spelled alike before);
`renders_as` with `badge` ≤12 chars, `title` ≤80, and `archetype` from a closed vocabulary; `accepts`
**required, no default, possibly empty** — an empty `accepts` is a read-only species; `reason_required`
a **subset of `accepts`**, which raises otherwise. An overlay row is a **full replacement, not a field
merge**, and may declare a verb the seed never heard of. Deletion is a tombstone, and a tombstone for
a kind the seed does not ship is an **error, not a no-op**.

**The verb stays `accepted`, not `approved` — RULED here, and deliberately not a synonym.** The
platform seed spells the ordinary pair `approved`/`rejected`, and the SDK constrains verb strings
nowhere (a closed verb vocabulary would be the next code table). Two spellings will therefore appear
in one queue, and that is the point rather than the cost: **an approval says the artifact is in order;
an acceptance says a named authority is taking the residual risk onto themselves.** MIL-STD-882 calls
that act risk *acceptance*, this ADR's audiences, authority ladder and §7 refusal are all built on the
word, and collapsing it to `approved` would make the one irreversible act in the domain read like
document sign-off. The row carries this sentence as its reason, so the next reader finds a choice
rather than a drift.

**And they are domain species, so they do NOT go in `policy/task_kinds/`.** That directory's own
header rules it: *"Structural only; NO domain names may enter this directory. A deployment's own
species live in a work-side OVERLAY (ADR-0036), which is what keeps the generic/domain boundary
STRUCTURAL rather than lexical: there is no row here to put one in."* Safety acceptance is
`grouped_review`-shaped — one approval resolving N affected items, which is exactly the
`mesh:DispositionReview` fan-out this ADR already adopts — so the platform repo gains **nothing** and
the overlay carries the species with its own `accepts` and `reason_required`. **No inheritance**: an
overlay row that omits `accepts` is refused, because `accepts` is required precisely so a domain
species cannot silently borrow a structural one's verbs.

**A LIVE BUG THAT LANDS ON THIS ADR'S REFUSAL, reported by the M3.3 lane and independently
confirmable.** An **undeclared** task kind is handed Approve/Reject on both sides today: cortex-ui's
default archetype renders an approval card unconditionally, and `isRegisteredKind` — the predicate
written to prevent exactly this — has no caller outside its own tests. For every other species that
is a rendering defect. **For this one it is §7's refusal defeated from the outside**: a risk
acceptance reachable through a generic approval card, dispositioned by whoever the default surface
admits, with no authority tier and no required reason. **Seal 14** (below) exists for it, and the
safety kinds must not go live before cortex-ui's parity seal lands — the cutover's safer direction
(an unknown species renders dead rather than actionable) is only safe once `declared: false` actually
renders as *unknown species here*, which is the half that failed to be consumed last time.

The task payload stays clearance-bounded — reference plus a clearance-safe summary, never
compartmented content — because the queue itself must not become the leak.

---

## §6 — Ingestion lives in doc-tools, and that sets the increment order

`SustainmentPlugin` is **doc-tools'**, not this repo's (`prime_databases.py:208`). So:

- **This repo declares the vocabulary.** That alone lights up `/classes` and the SPO-interview
  operable-subjects menu, and the four verbs over hazards, mitigations, critical items and work
  orders run against whatever the plane already holds — **with zero doc-tools change**.
- **The write-up extraction is a doc-tools PR**, sequenced after the vocabulary primes, against the
  class IRIs this repo declares. Cross-repo, so it is scheduled as such and never assumed.
- **A second extraction path in this repo is refused by name.** Two writers of the same instance
  types is the fork that makes provenance unanswerable.

---

## §7 — Refused, by name

- **Any verb that sets an acceptance.** Acceptance is a disposition by an authority, or it is
  nothing.
- **Any verb that creates a hazard without a human task in between.** `classifyWriteUp` proposes.
- **A safety "runner" verb** taking a graph or an analysis id — `run_any_graph` under another name
  (ADR-0046 §2): no slots for the filler, no arity for the gate, and one entitlement grant covering
  every analysis anyone plugs in afterwards.
- **Direct substrate reads** that bypass the mesh (ADR-0049's bypass class).
- **A `payload: object` slot.**
- **Prediction of probability of harm to a person.** Trends are counts over declared groupings
  against a ratified threshold, and the artifact says so.
- **Cross-compartment aggregation.** Entitlement scope is the compartment; a query spanning two
  refuses rather than returning the intersection it happens to be allowed.
- **A defaulted verdict anywhere.**

This engine is not a replacement for the safety engineer's assessment. The artifact says *drafted* in
its own metadata and the card shows it.

---

## §8 — Seals, each with its control, and an honest statement of blind spots

Numbered. **Every seal names the state it cannot distinguish, or asserts there is none.** Where a
mutation is given, the seal is not done until the mutation has been *run* and gone red — a green
where red was expected is a signal about the seal, not about the code.

1. **Every output class is declared in a TTL that primes** — asserted against a **fresh prime**, not
   sandbox. Control: an undeclared class produces the Contract D 422. *This is the seal that would
   have caught `mesh:DispositionReview` in 2026-08, where sandbox was green and every fresh cluster
   was permanently broken.*
2. **No registered verb writes an acceptance.** Enumerate from the mesh via `tests/_mesh_verbs.py`
   — **verbs are relationship types between `OntologyClass` nodes, not nodes**; the first consumer's
   first draft queried `(:Predicate)` and returned a confident uniform `NOT FOUND`. Invoke
   `assert_checkers_can_say_no()` from this consumer's own one-line test, so a red names instrument
   vs data. Mutation: register one → red.
3. **Three-state verdicts, no defaults.** Mutation: default a hazard status → red. Positive control:
   a fixture with an explicit not-assessed value renders as not-assessed and not as blank.
4. **The matrix is data.** Change one row in `safety_risk_matrix.ttl`, re-prime, and the drafted
   risk level changes **with no code edit**. Mutation: hardcode the matrix in the engine → red. This
   seal is the whole of §2; without it §2 is an intention.
5. **An unrecognized severity or probability refuses loudly**, naming the vocabulary and its source
   file. Control: a recognized one passes the same path.
6. **The declaration carries the verbs**, extended from the existing declarations-match-code seal;
   **both `accepted` and `rejected` are reason-required ON THE ROW**, so the property survives the
   `_VERBS_BY_KIND` cutover. Mutation: drop each from the declaration's `reason_required`
   **separately** → two reds. One mutation covering both would pass with one of them still wired.
7. **Three-caller walk, asserting the existence-oracle.** The authority-tier caller disposes; the
   author under `risk_assessment_author:SUSTAINMENT` **sees and cannot dispose**; the unentitled
   caller **does not see the task at all** — asserted as non-visibility, not merely as a refusal,
   because a refusal and an invisibility are different disclosures and only one of them is the
   design. Control: the author's view is asserted **positive** in the same run, or the seal cannot
   tell the §5 ruling from a substrate that shows nobody anything.
8. **Orphan cardinality, both directions.** N orphans in the fixture returns exactly N. Mutate by
   **dropping one and separately by adding one** — containment cannot see cardinality, and a
   one-directional check passes on half the bugs.
9. **Identity end to end.** Every inner artifact's caller identity equals the initiator, none equals
   the engine's service identity (ADR-0049 Ruling 1; runbook §6's law — identity is an argument,
   never derived from the component name). Mutation: swap in service identity → red.
10. **Provenance resolves.** Every `DERIVED_FROM` on a drafted assessment resolves to an object that
    exists, and the assessment is only as fresh as its stalest source and says so. Mutation:
    fabricate one → red.
11. **Cite-or-omit.** The draft cannot state a severity indicator absent from its sources. Mutation:
    inject a figure → red.
12. **Fixture identities are all distinct** — every identity-shaped field in every fixture holds a
    different value, so a read keyed on the wrong field fails instead of coincidentally passing.
13. **Registry census across all eight §0 sites**, derived from the site list rather than a
    hand-written one, so the list shrinks as the work lands. Site 6 specifically: assert the key is
    **present**, since its failure mode is a skip.
14. **An undeclared safety kind must NOT render an actionable card** (added 2026-09-11, against the
    live defect in §5). Assert that a kind absent from the declarations renders as *unknown species*
    and offers **no** disposition verbs — not that it renders "correctly", which today's default
    archetype also satisfies while handing out Approve/Reject. Control: the declared kind renders its
    own `accepts` in the same run, or the seal cannot tell a working narrowing from a dead renderer.
    **This seal belongs to cortex-ui's parity work and this lane consumes it** — if it is not green,
    the safety kinds do not go live, because a risk acceptance reachable through a generic approval
    card is §7's refusal defeated from outside the engine.

    **IT MUST ASSERT THE RENDER, NEVER THE PREDICATE** — sharpened 2026-09-11 by Lane 1, and this is
    the part that decides whether the seal is real. `isRegisteredKind` having no caller outside its
    own tests is **not a missing wire-up; it is a GREEN SEAL OVER AN ABSENT CONSUMER**: the predicate
    is tested, it passes, and it guards nothing, so the suite reports the protection as present while
    the bug is live. A test that calls `isRegisteredKind` directly is therefore **green today, with an
    undeclared kind still being handed Approve/Reject.** Only a test that drives the render can tell
    those two states apart, which is exactly the discrimination this seal is for.

**What these seals cannot see:** whether the seeded matrix is *correct* — no test can tell a wrong
severity table from a right one, which is why §2 makes ratification a named human act and leaves
`prov:wasDerivedFrom` empty until it happens. Also unseen: whether the hazard taxonomy
`classifyWriteUp` maps into matches the one the customer's safety office actually uses. That is an
overlay question (§10), and until it is answered the classification is a proposal against a seed
taxonomy and the card must not imply otherwise.

---

## §9 — Alternatives considered

- **Verbs in Engine O rather than a new engine.** Rejected: Engine O is the SUSTAINMENT resolver;
  folding governed analysis into the resolver is the two-planes violation already ruled on twice, and
  it would put risk drafting behind the resolver's availability.
- **Acceptance as a verb with an entitlement check.** Rejected: it makes acceptance an *engine*
  capability, so one grant covers every future assessment, the audit line is a service's, and there
  is no accountable human decision record. The HumanTask substrate already produces exactly the
  artifact a safety authority must be able to point at.
- **The matrix in code.** Rejected in §2; the second customer is a fork.
- **A new SAFETY compartment instead of SUSTAINMENT.** **Deferred, not refused — RULED 2026-09-10 —
  see [rulings#r-004--adr-0051-sustainment-safety-four-rulings](../rulings/README.md#r-004--adr-0051-sustainment-safety-four-rulings) (d)**
  (source: architect's review of this ADR). Safety data is more restricted than sustainment data in
  some programs and identical in others; splitting on a guess costs a re-prime and a grants
  migration. Revisit on the first customer whose safety office is a separate authority from its
  sustainment office.
- **A safety canvas template (ADR-0050)** — orphaned hazards, deferrals against critical items,
  pending acceptances, recent write-ups. Deferred until two verbs are live, because a template whose
  verbs cannot be named is a board that is not ready to be declared.

## §10 — Open, and answerable only by a domain owner

1. **Which systems hold the hazard log, the write-up stream, the critical items list, and work-order
   deferrals on the work side.** This is the overlay row (ADR-0036 §3) and the platform repo never
   names them. **Engine S with no overlay refuses every verb with "no source declared for
   `<class>`" — it does not return an empty answer**, because an empty hazard list is the single
   most dangerous wrong answer this engine could give.
2. **Who ratifies the risk matrix and the authority ladder**, and therefore whose identity fills the
   `prov:wasDerivedFrom` that ships empty.

   **What the ratifier is actually deciding, in one concrete row** — added 2026-09-11 from the
   seeded matrix, because "ratify the matrix" is too abstract to act on. Take **I/E**:
   catastrophic severity, improbable. `safety_risk_matrix.ttl` seeds it **Medium**, and flags it
   in-file as the row most likely to be wrong. Some programmes hold that a **catastrophic outcome
   never falls below Serious** whatever the odds, because the acceptance decision should reach a
   senior authority regardless of probability.
   
   Both readings are defensible; only one is this programme's. And the consequence is not
   cosmetic: the risk level resolves to an `acceptanceAudience`, so **changing that one cell moves
   which authority the acceptance routes to** — `risk_acceptance_medium:SUSTAINMENT` becomes
   `risk_acceptance_serious:SUSTAINMENT`, and a different set of people can dispose it.
   
   **That is a row edit with a ratifier's name on it, not an engine change** — which is §2's whole
   claim, stated as something a safety authority can actually say yes or no to.

~~3. Whether the drafter's visibility audience is wanted.~~ **CLOSED 2026-09-10 — ruled in §5**:
   `risk_assessment_author:SUSTAINMENT`, view-only, granted at draft time. Struck here rather than
   deleted, so a reader of the open list can tell *answered* from *never asked*.

**Neither 1 nor 2 blocks increments 0 through 4.** The vocabulary, the engine, the acceptance path
and the exemplar all run against a fixture graph and a seed matrix. What 1 gates is increment 5 (the
overlay row is the cluster's first real source) and what 2 gates is nothing at all — it gates a
*claim*: until it is answered `prov:wasDerivedFrom` ships empty, the matrix reads as SEED, and the
seals report exactly that rather than papering over it.

## Indicators for revisiting

- A second program arrives whose acceptance ladder is not expressible as audiences-per-level — the
  §5 mechanism, not the §2 data, would be what is wrong.
- `classifyWriteUp`'s proposals are accepted at a rate high enough that the human link review reads
  as a rubber stamp; that is either a case for narrowing the review or evidence the seal is theatre,
  and it should be measured before either.
- Group-based audiences get ruled in `task_grants.yaml` — §5's per-level audiences collapse to one
  row per level. **Scheduled, not speculative**: recorded on the M3 list, so this is the one indicator
  that arrives as planned work rather than as a surprise.
- M3.3 lands and `_VERBS_BY_KIND` retires with `taskKindRegistry` — §5's rows move to served
  `rendersAs` declarations, and this ADR's reason-required rulings have to travel with them.
- Safety data turns out to need its own compartment (§9).
- A fourth domain engine appears before the §4 slot extraction lands, at which point the second
  implementation has become a fourth.

---

## Appendix A — Lane dispatch recipe

**Read first, and cite in the report:** this ADR; `docs/runbooks/adding-an-engine.md` (all REQUIRED
items, §0 and §4 in particular);
`docs/plans/adding-an-engine-has-more-registry-sites-than-the-runbook-names.md`; ADR-0007;
ADR-0046 §2; ADR-0049 Ruling 1; `setup/prime_databases.py:193-255`;
`setup/ontologies/pcn_disposition_rules.ttl` and `qualification_status_vocabulary.ttl` (the two
precedents §2 copies); `setup/ontologies/mesh_system.ttl:169-183`;
`src/iagent/human_tasks.py:380-420`; `policy/task_grants.yaml` (the header, in full);
`tests/_mesh_verbs.py`; `agent_fleet/planning_agent/slots.py`.

**Increment 0 — names. DONE 2026-09-11 by Lane 1 (`invincible-agent-01`) on `1331e01`**, re-verified
rather than trusted from this ADR: all five candidate strings match exactly one file each — this ADR
— and ports 8091–8094 and 8099 are free. Start at increment 1. (Kept here rather than deleted: a
reader needs to know the check was RUN, and against which sha.)

**Increment 1 — survey, then vocabulary. No cluster.** ADR-0007 survey against the primed graph for
every term in §1's list; record found *and* not-found in the TTL header. Mint only the remainder, in
`safety:`. `safety_risk_matrix.ttl` per §2, labelled SEED with empty `wasDerivedFrom`. Both seeded in
`prime_databases.py` LAYER 2. Declare every verb's output class here. Seals 1, 3, 4, 5 offline, each
with its control, each mutation actually run.

**Increment 2 — engine, no cluster.** `agent_fleet/safety_agent/` on Engine F's stamped template.
`/version` and the gating-manifest entry **in the first commit**. `slots.py` — and per §4, extract
`agent_fleet/utils/slot_declarations.py` rather than writing the third copy. Registration through
the fleet helper with the REQUIRED retry/readiness. `findOrphanedHazards` and `assessDeferralRisk`
against a fixture graph. Seals 2, 8, 9, 12.

> **THE EXTRACTION'S TERMS — approved by Lane 1 (`invincible-agent-01`) 2026-09-11, with one addition
> that is now binding.** Today: `planning_agent/slots.py` 313 lines (Lane 1's, sealed by five files
> under `tests/planning/`), `finance_agent/slots.py` 267 lines, `utils/slot_declarations.py` absent
> — all four facts re-verified in the tree, and Lane 1 is not mid-work (last touch `2f45f00`, clean).
>
> **Green-before-and-after is NOT sufficient, and this is the addition.** It cannot distinguish
> *behaviour preserved* from *both call sites now import a module that behaves like neither*. So
> **run at least one MUTATION against the extracted module and require the five planning seals to go
> RED.** If they stay green, the seals are no longer reaching the code — the failure shape this repo
> hit four times in one day, and the reason an extraction can land looking perfect while silently
> unsealing its own subject.
>
> **Two known asymmetries must survive, each with its own seal** (runbook §4, and Lane 1's first
> version got the second one wrong): `eval_str=True` on `inspect.signature`, because
> `from __future__ import annotations` turns every `Literal` into its literal text; and unwrapping
> `Optional[X]` but **stopping at a real container**, because unwrapping twice declares a
> multi-valued slot a scalar.

**Increment 3 — the acceptance path.** Three audience families in `policy/task_grants.yaml` —
per-level acceptance, `hazard_link_review:SUSTAINMENT`, and `risk_assessment_author:SUSTAINMENT`
(view-only, R-004a) — and the task kinds as **work-side overlay declarations** carrying their own
`accepts` and `reason_required: [accepted, rejected]`. **Not** `policy/task_kinds/` (structural
species only, no domain names) and **not** `_VERBS_BY_KIND` (mid-retirement).
`draftRiskAssessment` opens the review in the one-review-fans-out shape. Seals 6, 7, 10, 11 — and
**seal 14 is a precondition for going live, not a deliverable of this increment**: it is cortex-ui's
parity seal, and until it is green an undeclared kind still renders an actionable approval card. Note the deploy step the M3.1 rename paid for: **between the git edit and
`task_grant_sync` running, a new audience routes to NOBODY** — `register_task` materializes zero rows
→ `NoEntitledRecipients` → 422. Run the sync in the same window and re-drive one draft to witness it.

**Increment 4 — the exemplar.** One hazard, end to end: drafted with citations, implied authority
level recorded, review opened, disposed by an entitled caller with a stated reason, refused for a
caller a tier below, invisible to an unentitled one. This is the walk a safety engineer would
recognise, and it is the demo.

**Increment 5 — cluster.** Overlay row for the sandbox source. Registration via the reregister hook
on the next prime (**not** a separate prime — it restarts the engines it covers). Roll to a commit
tag; census by sha and registration timestamp; verify by symbol on the serving pod, not by log line.
Seal 13 across all eight sites. Three-caller walk under three real personas.

**Increment 6 — doc-tools.** Write-up extraction against the primed class IRIs, in the other repo, as
its own PR (§6).

**Fences:** `agent_fleet/safety_agent/`, the two new TTLs and their `prime_databases.py` rows,
`policy/task_grants.yaml` audiences, the `_VERBS_BY_KIND`/`_REASON_REQUIRED` rows, the eight registry
sites, `agent_fleet/utils/slot_declarations.py` (extraction only — no behaviour change to Engine F or
Engine P, and their seals must be green before and after), and this ADR. **No** changes to Engine O,
Engine F, the supervisor, or cortex. The card is an existing archetype until somebody rules a safety
archetype.

**Report:** what the mesh actually registers, read back from Neo4j by name; the three-caller result
including the non-visibility assertion; one drafted assessment with its citations; the survey's
found-and-not-found list; every seal named **pass / fail / void** — void is a real outcome and must
be reported as one; every mutation that was run and what it did; and what the seals could not see.
