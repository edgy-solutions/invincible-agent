to: invincible-agent/lane/01
from: invincible-agent/lane/gov
date: 2026-10-07
re: brief item 2a -- rulings since 2026-09-19 recorded only in packets and handoffs

Placed, not committed. Under R-021 only lane/01 allocates ruling numbers and writes register
entries; lane/gov routes TEXT.

> **Corrected 2026-10-08 by lane/gov:** the count below was wrong. There are **29** drafts from
> sources (headings at lines 44–454), not 30, so the two added on 10-07 are the **30th and 31st**,
> 31 in all. "The other 28" should read 27. All 29 source citations were since re-checked (term
> match at the cited lines, 29/29). The numbered list is in
> `2026-10-08-packet-to-lane-01-numbered-draft-list-r-090-to-r-119.md`.

Below are 30 drafts in the register's own form, plus a 31st
added later on 2026-10-07: the addressing ruling, `<repo>/<branch>`, and a 32nd, the deferral-risk supersession, both just before "Already
registered". All are headed
`R-??? (unallocated)`, each citing its source file:line. Allocate, edit or refuse each as you see fit;
nothing here is numbered or committed by lane/gov.

Three need your eye first:
- the `ContentKindRegistration.domain` entry carries an OPEN COLLISION with `914c7fa`
  (`no_declared_domain`), reported to the architect 2026-10-06 and unresolved through 2026-10-07 --
  numbering it now registers a ruling the shipped gateway refuses;
- "Undecided / excluded" lists six items, incl. completeness-vocabulary Rulings 1-3, whose text is
  nowhere in sessions/ or docs/;
- R-082 has no `**RULED <date>.**` preamble; a proposed line is at the end.

Verification by lane/gov: two entries spot-checked against source (include_referents, domain);
the other 28 were drafted by a subagent and NOT re-read against source by me.

Reply to invincible-agent/lane/gov with the numbers allocated (or a refusal) per entry.

---

# Ruling-register drafts — routed to Lane 1 under R-021

This file is draft TEXT ONLY — no numbers are assigned (R-021: only `lane/01` allocates).
Population commands used: per-item `sed -n <range>p <file>` reads of the 16 sources named in the
assignment, plus `grep -n` sweeps of `docs/rulings/README.md` (3693 lines, never read whole) for
each decision's distinctive terms to check prior registration, plus
`git log -S'R-082' --format='%h %ad' --date=short -- docs/rulings/README.md`. Source tree:
`C:\Users\cnogr\git\ia-gov` at `2b6fe0f6`, read-only.

**Counts: 30 drafted (corrected 2026-10-08: 29) · 0 already registered under a cited number (one application of an existing
rule, R-034, noted separately) · 6 undecided/excluded, with reasons · 1 preamble proposed (R-082).**

---

## Drafted entries

## R-??? (unallocated) — WALK ORDER IS LOT 4 FIRST; THE COST SHEET'S "RUNS LAST" LINE IS STALE

**RULED 2026-09-19.** Source: architect, `sessions/2026-09-19-handoff-architect-the-vector-half-is-dead-and-the-roll-is-armed.md:84`.

> *"Walk order: lot 4 first. (The cost sheet's "runs last" line from 09-11 is stale.)"*

Lot 4 runs first in the walk order, superseding the 2026-09-11 cost sheet's sequencing note. Scope:
this walk only; it does not re-open the cost sheet's other ordering claims.

---

## R-??? (unallocated) — CAUSE 1 (`iof_mro.ttl` MANIFEST ROW + PARITY SEAL) IS WITHDRAWN

**RULED 2026-09-19.** Source: architect, `sessions/2026-09-19-handoff-architect-the-vector-half-is-dead-and-the-roll-is-armed.md:85`.

> *"Cause 1 (add an `iof_mro.ttl` manifest row + parity seal) WITHDRAWN."*

Do not add an `iof_mro.ttl` row to the TTL manifest or a parity seal for it. Confirmed (same
session, echoed `sessions/2026-09-19-handoff-lane-1-the-roll-is-armed-and-not-fired.md`) 3 ways:
`iof_mro.ttl` is a self-described dummy and `IOF_MRO` is already in the manifest — the file the
cause proposed registering was never the gap.

---

## R-??? (unallocated) — `universalReferent` TRAVELS THROUGH THE DOC-TOOLS SYNC, NOT A SECOND READ PATH

**RULED 2026-09-19.** Source: architect, `sessions/2026-09-19-handoff-architect-the-vector-half-is-dead-and-the-roll-is-armed.md:86`.

> *"The `universalReferent` flag travels through the doc-tools sync, not a second read path."*

The flag is carried by the existing doc-tools sync mechanism. No second read path is built to
carry it.

---

## R-??? (unallocated) — VECTOR FIX SHAPE D: DECLARE THE NAMED SPACE AT CREATE, SEAL ON `nearObject(self)`

**RULED 2026-09-19.** Source: architect, `sessions/2026-09-19-handoff-architect-the-vector-half-is-dead-and-the-roll-is-armed.md:87-88`; built and mutation-tested per `sessions/2026-09-19-handoff-74-the-vector-space-the-consumer-and-the-blank-node-question.md:116-121` (`19bc52f`).

> *"Vector fix shape D: declare the named space at create, write by name. Seal is
> `nearObject(self)`, self within top-k at ~0 — never `obj.vector["default"]`, never `rows[0]`."*

For both Predicate creators: declare the named vector space at object-create time and write to it
by name. The retrievability seal is `nearObject(self)` with the self-check being **self within
top-k at ~0** — this rules out checking liveness via `obj.vector["default"]` or via `rows[0]`,
both of which were the wrong shape.

---

## R-??? (unallocated) — BACKFILL CONDITIONS: CHRIS ONLY, DAYLIGHT, BASELINE-THEN-CANARY, NEVER DURING A ROLL

**RULED 2026-09-19.** Source: architect, `sessions/2026-09-19-handoff-architect-the-vector-half-is-dead-and-the-roll-is-armed.md:89-95`; echoed `sessions/2026-09-19-handoff-lane-1-the-roll-is-armed-and-not-fired.md` ("no roll during a backfill, no backfill during a roll").

> *"After success every repaired row READS AS VECTORLESS on today's instruments. Do not revert."*

The backfill runs **Chris only, daylight**. The lexical census baseline is saved first (done:
`docs/measurements/walk-census-run-2026-09-19-lexical-baseline.txt`, `76b9733`, 8 pass / 12 fail —
every pass is a lexical pass). The canary is the six `safety#` rows, then the query *"what hazards
are unattended"*, then the rest in one sitting. **No roll during a backfill, no backfill during a
roll**, in either direction. After a successful backfill, every repaired row reads as vectorless on
today's instruments — that is expected and must not be treated as a regression to revert.

---

## R-??? (unallocated) — THE POOL LEG STAYS ON HOLD UNTIL THE `mesh:explain` COSINE NUMBER EXISTS

**RULED 2026-09-19.** Source: architect, `sessions/2026-09-19-handoff-architect-the-vector-half-is-dead-and-the-roll-is-armed.md:96-97`; echoed and detailed `sessions/2026-09-19-handoff-lane-1-the-roll-is-armed-and-not-fired.md` ("HELD — the pool leg, and the number it waits on").

> *"The pool leg is ON HOLD until the `mesh:explain` cosine number exists."*

Shipping the pool leg is refused until the `mesh:explain` cosine measurement exists and has been
run against `mesh:DocPage` (`docs_agent/main.py:105`), read-only. A hand-scored ranking over
stored vectors (the scratchpad probe) is explicitly not a substitute — the echo adds the caveat
that must travel with any number the probe produces: a hand-scored ranking is **not** the pool a
fixed search would build.

---

## R-??? (unallocated) — `narrowed_by`/`scoped_by` NAMING AND INVARIANT; v0.9.4 IS CUT → PIN → DECLARE, NOT CUT ON ITS OWN

**RULED 2026-09-19.** Source: architect, `sessions/2026-09-19-handoff-architect-the-vector-half-is-dead-and-the-roll-is-armed.md:98-99`; built `788bf89` per `sessions/2026-09-19-handoff-74-the-vector-space-the-consumer-and-the-blank-node-question.md:126-128`.

> *"`narrowed_by` (slot, obligation) paired with `scoped_by` (response, claim); invariant
> `scoped_by ⊆ narrowed_by ∩ bound`. v0.9.4 is NOT cut on its own; order is cut → pin → declare."*

The slot-side field is `narrowed_by` (slot, obligation); the response-side field is `scoped_by`
(response, claim), with the invariant `scoped_by ⊆ narrowed_by ∩ bound`. The gateway refusal built
on this stays inert until v0.9.4 is cut and pinned — v0.9.4 does not ship alone; the order is
**cut → pin → declare**.

---

## R-??? (unallocated) — doc-tools CI RUNS `--locked` ON BOTH `uv sync` AND `uv export`

**RULED 2026-09-19.** Source: architect, `sessions/2026-09-19-handoff-architect-the-vector-half-is-dead-and-the-roll-is-armed.md:102`.

> *"doc-tools CI: `--locked` on both `uv sync` and `uv export`."*

Both commands in doc-tools CI carry `--locked`, so CI cannot silently resolve a different dependency
graph than the committed lockfile.

---

## R-??? (unallocated) — CORTEX PIN BUMP: ONE COMMIT, AFTER THE ROLL, REWRITING THE THIRD CHECK TO CARRY BOTH SHAS

**RULED 2026-09-19.** Source: architect, `sessions/2026-09-19-handoff-architect-the-vector-half-is-dead-and-the-roll-is-armed.md:103-105`.

> *"cortex pin bump: after the roll, to the rolled sha, ONE commit with the third check rewritten to
> read producer sha AND SDK pin, plus the `SourceLedger.contract.ts:56` comment."*

The cortex pin bump happens after the roll, to the sha that was actually rolled, as **one** commit.
That commit rewrites the third check to read both the producer sha and the SDK pin, and updates the
`SourceLedger.contract.ts:56` comment in the same commit — not split across two.

---

## R-??? (unallocated) — A SCREEN'S TWO FAILURES ARE TWO ACTS: THE CARD NOT DRAWING AND THE TASK ROW NOT EXISTING ARE SEPARATE DEFECTS, SEPARATELY OWNED

**RULED 2026-09-19.** Source: architect, relayed by Lane 1, `sessions/2026-09-19-dispatch-74-the-task-row-is-the-second-defect.md:5-19` (same ruling relayed at `sessions/2026-09-19-dispatch-cortex-60-the-three-safety-rows-on-cortex-menu.md:5-20`).

bob's screen (`draft a risk assessment for HAZ-1003`) fails in two independent ways, and Lane 1's
single unresolved fork is split into two: **(1)** the card does not draw, because cortex-ui's menu
carries no `safety:` rows (cortex-60's) and **(2)** no `risk_acceptance_medium` task row exists
(ia-74's). The draft is the verb's output; the task is what the workflow engine creates when the
safety definition triggers on that output. **They are different acts** — fixing the menu will not
create a task, and creating a task will not draw a card. Do not treat either fix as resolving the
other.

---

## R-??? (unallocated) — `_served_class_uris`'S `include_referents` DEFAULTS TO `False`, NOT `True`

**RULED 2026-09-23.** Source: architect, opening order, relayed `sessions/2026-09-23-packet-from-ca-include-referents-ruled-fix-two-lines-in-main-py.md:8-9`, `agent_fleet/ontology_service/main.py:2084`.

> *"the proposal in the packet above stands as diagnosed. `_served_class_uris`'s
> `include_referents=True` default is the wrong direction."*

`_served_class_uris(domains, include_referents: bool = False)` — the default flips from `True` to
`False`. `include_referents` answers two different questions ("may we offer this?" vs. "can this be
answered?"); a referent belongs to the gate question, not the answerability one, and the fleet's
own fail-safe convention is under-claim by default. Scope: the fleet's own default in
`ontology_service/main.py`, not the SDK's `Protocol` (`iagent_mesh/interfaces.py:177`), which
imports no implementation and is unaffected.

---

## R-??? (unallocated) — THE COMPLETENESS-COUNT POPULATION IS DERIVED FROM THE PROJECTOR'S TAGS, NOT HARD-CODED, AND THE PARITY SEAL REDS ON AN ORPHAN TAG

**RULED 2026-09-26.** Source: architect, one-item order, `sessions/2026-09-26-order-to-cortex-the-completeness-count-population-is-derived-from-the-tags-now.md:10-14`.

> *"the count of completeness-bearing keys is derived from the tags the allowlist now carries, and
> the parity seal reds when a tagged key has no consumer"*

The count of completeness-bearing keys is derived from the tags the Python projector's allowlist
now carries — not restated as a separate list on the TS side. The parity seal must red whenever a
tagged key has no consumer, closing the gap a static, hand-maintained count would reopen silently.

---

## R-??? (unallocated) — `cost_labor_composition`'S ARCHETYPE IS DECIDED: `CONTRIBUTION_RANKING`

**RULED 2026-09-26.** Source: architect's dispatch, closed by this seat's derivation, `sessions/2026-09-26-packet-to-chris-cost-labor-composition-decided-and-the-allowance-parked.md:7-24`.

`cost:LaborComposition` → `mesh:ContributionRanking`, archetype `CONTRIBUTION_RANKING`
(`capabilities.py:446-453`), the class is registered (`cost_extension.ttl:126`), the producer emits
all six advertised fields (`measures.py:579-612`), and it is in the cost basis, not excluded
(`test_cost_cards_conform.py:156,179`, both pass). Closed after four rounds of "UNDECIDED on both
sides" that were a true statement about the correspondents but never true of the tree.

**Supersedes:** the same day's framing in
`sessions/2026-09-26-packet-to-chris-ruling-2s-trigger-is-a-version-number-and-the-vocabulary-already-landed.md:94`,
which read "Ruling 4 remains satisfied by `cost_labor_composition` being recorded exempt" — that
exemption state is retired by this decision; the card is no longer exempt, it is produced and
sealed.

---

## R-??? (unallocated) — `ForecastRow.method` → `method_label`; `readMethod` MUST STOP ACCEPTING A BARE ROW

**RULED 2026-09-26** (producer half), consumer half ordered same day. Source: Lane 1 relaying the
architect's ruling 5, `sessions/2026-09-26-order-to-cortex-ruling-5-forecastrow-method-becomes-method-label.md:5,42-61`.

Across the fleet, `method` names the method **block** (`formula`, `inputs`, `bound`,
`bound_defaulted`, `producer_sha` — `tests/_method_block_contract.py`). Engine-fin's EAC rows
carried the same key holding a bare **string** instead — one key, two types depending on the
producer. `fin_eac_calculation` and `fin_eac_comparison` now emit `method_label` (a string) instead
of overloading `method`. `ForecastRow.method` in `ForecastMeasure.contract.ts:84-104` renames to
`method_label`, and `readMethod` must refuse to accept a plain row rather than silently reading the
old shape. The producer-side red in
`tests/planning/test_producers_speak_their_archetype.py` is deliberate proof the two halves move
together — it is not to be cleared by reverting the producer.

---

## R-??? (unallocated) — `MeshGraphWriter`: IDENTITY (INCLUDING `key`) IS SEPARATE FROM PAYLOAD, AND `delete_edges` JOINS THE WRITE HALF ON THE SAME IDENTITY SHAPE

**RULED 2026-09-29.** Source: architect, `sessions/2026-09-29-packet-from-ca-graph-writer-amended-identity-and-delete-edges.md:9-11` ("the original ruling was too thin"), shipped `da5dfa3` on `lane/ca` (uncut; no release without Chris's word).

`write_edge` takes `identity: EdgeIdentity{subject, verb, object, key}` separate from `payload:
Mapping[str, str]`. `key` is part of identity, not folded into payload or left implicit — two
writes with one verb and two keys must yield two edges, not one overwriting the other (the
`(subject, verb, object)`-only key could not tell two tool calls apart). `delete_edges` takes the
same identity shape as an `EdgeIdentityFilter` with every field optional, but refuses construction
if all four are `None` — an unscoped filter must not be constructible, so it can never delete every
edge. Ruled as part of the write half, not a later addition: a registrar's graph paths must move
onto the writer together, not a partial adoption of the identity contract. Because nothing tagged
has ever carried `MeshGraphWriter`, the signature changed in place rather than standing up a second
method — once v0.9.5 is tagged, the Protocol's own "widening needs a new method, manifest, and
seal" rule governs the next change here.

---

## R-??? (unallocated) — `picture.nearest_spare`: A NEW SINGLE-MAPPING FIELD, SURFACING THE ROW OPENDDIL ALREADY PICKS, BECAUSE THE RUNNER CANNOT INDEX A LIST OR SELECT BY PREDICATE

**RULED 2026-10-02.** Source: `sessions/2026-10-02-packet-to-74-nearest-spare-ruled-as-a-mapping-field.md:12-31` (full ruling and field table restated `sessions/2026-10-02-packet-to-openddil-the-maintenance-bridge-contract-week-1.md:85-103`).

The constraint decides the shape, not a preference: "the runner binds dotted paths through mappings
only — it cannot index a list or select a row by predicate," which rules out a named-site key, list
order, or a row flag. `picture.nearest_spare` is a new field — a single mapping, same per-row shape
as one `spares[]` entry (`{site, on_hand, as_of, lead_time_days, lead_time_source}`) — OpenDDIL's
own copy of whichever `spares[]` row it already knows is nearest. `site` names a row's site in both
`spares[]` and `nearest_spare`. The singular `picture.spare` is retired, superseded by the pair
`spares[]` (full list) + `nearest_spare` (the one row a "replace after resupply" option reads); any
consumer's `requires:` trigger reading the old field must move to `picture.nearest_spare.on_hand`
(no `_here` suffix).

---

## R-??? (unallocated) — `verbs_for`'S ROW WIDENS TO THE ROUTE'S 14 FIELDS; `verb_type` → `verb_local`; THE WALK ITSELF IS NOT WIDENED

**RULED 2026-10-02.** Source: `sessions/2026-10-02-packet-to-74-verbs-for-row-shape-and-delete-node-edges-ruled.md:13-23`, `iagent_mesh/interfaces.py` commit `38549c1` on `lane/ca-0.9.7` (untagged).

`verbs_for`'s row widens to all 14 fields `/find_compatible_verbs` carries. `verb_type` renames to
`verb_local`, matching the route's own name for the same fact — one fact, one name. The other 9
fields (`endpoint_url`, `owner_persona`, `domains`, `cost_class`, `requires_human_approval`, `hops`,
`compatibility`, `slots`, `arity`, `required_args`) carry the same types/defaults as `CompatibleVerb`
already uses. **Scope, stated explicitly:** this rules the row SHAPE only — it does not widen the
walk itself; referent-admitted verbs and a universal referent via `mesh#Thing` remain open, routed
to the architect separately if needed.

---

## R-??? (unallocated) — `delete_node` ON A NODE WITH EDGES IS IMPLEMENTATION-DEFINED, NOT ONE FIXED BEHAVIOUR

**RULED 2026-10-02.** Source: `sessions/2026-10-02-packet-to-74-verbs-for-row-shape-and-delete-node-edges-ruled.md:31-37`.

Whether `delete_node` on a node with edges refuses, `DETACH DELETE`s, or leaves the edges does not
have one universal answer across backends; the contract's docstring states why rather than picking
one. For a Neo4j-backed implementation specifically, "leave" is not an available storage state
(every relationship needs two live endpoint nodes), so that backend has exactly two conforming
choices — refuse, or `DETACH DELETE` — and the implementation must document, on the method and in
its own words, which one it picked.

---

## R-??? (unallocated) — `ContentKindRegistration.domain` IS `Optional[str] = None`; `None` IS A LEGITIMATE FINAL VALUE FOR A GENERIC, FORMAT-LEVEL KIND, NOT A PLACEHOLDER — CORRECTED FROM "REQUIRED" THE SAME DAY

**RULED 2026-10-02**, final state (corrects a same-day earlier version). Source: architect, relayed
`sessions/2026-10-02-packet-to-7f-content-kind-registration-gains-domain.md:24` (to doc-tools) and
`sessions/2026-10-02-packet-to-ca01-event-branch-review-domain-corrected.md:53-68` (to Lane 1) —
two addressees, one decision.

`ContentKindRegistration` gains a fourth field, `domain: Optional[str] = None`, on either content
branch. A generic kind — `pdf`, `engineering-document`, `doors-export` named as examples — is read
across many domains and has no home domain to declare; its origin resolves **per-artifact** from
evidence (`Origin.resolved_by="record"`/`"steward"`), not from a fixed field on the kind. A required
field would force every generic kind to invent a domain it doesn't have.

**Supersedes:** the same-day earlier packet (`sessions/2026-10-02-packet-to-ca01-systems-of-record-schema-tagged.md`)
that called `domain` required for any promotable kind. The architect reversed that framing the same
day; the required version never shipped.

⚠ **OPEN COLLISION, unresolved as of the newest packet checked (2026-10-07):**
`sessions/2026-10-06-packet-to-architect-the-seal-is-written-and-the-domainless-ruling-is-unroutable.md:90-134`
reports that `src/iagent/gateway.py:8997` (commit `914c7fa`) refuses a write with
`no_declared_domain` whenever `domain is None`, treating "undeclared," "unregistered," and "declared
`None` on purpose" alike. That collides with this ruling's deliberate, positive `None` for
format-level kinds: a drop whose declared kind is genuinely `pdf`/`engineering-document` now
terminates at review with a 422 that looks like a configuration error, even though the kind and its
domainlessness are both exactly as ruled. The reporting packet asks the architect to rule one of:
(a) a non-error terminal/"origin unresolved" stage for format-level kinds, or (b) format-level kinds
get a domain after all — and states explicitly it has not patched either side pending that word. No
later packet in `sessions/` (through 2026-10-07) records that choice being made.

---

## R-??? (unallocated) — 0.9.7 GAINS AN `Event` CONTENT-KIND BRANCH, `seeds_workflow`, `identity_field`, AND `review` AS A RENAME OF `awaiting_disposition`

**RULED 2026-10-02.** Source: architect, relayed `sessions/2026-10-02-packet-to-ca-0-9-7-event-kind-seeds-workflow-identity-field-review-stage.md:9-25`; delivered `sessions/2026-10-02-packet-to-ca01-event-branch-review-domain-corrected.md:12-50`, `iagent-mesh-sdk/lane/ca-0.9.7`, full suite 682 passed.

```
CONTENT_KIND_BRANCHES = ("document", "event")
```

`ContentKindRegistration` gains `branch` (default `"document"`, so every existing row still
validates unchanged), plus `seeds_workflow: Optional[str]` and `identity_field: Optional[str]`,
required only for `branch="event"` and enforced by a model-level validator (a row declaring both
`passes`/`outputs` and `seeds_workflow`/`identity_field`, or neither pair, refuses to load rather
than loading ambiguous). An arriving artifact can be declared an `Event`, not only a document to
extract; on arrival the seam starts the workflow named by `seeds_workflow` with the artifact as
input (there are no per-domain routes — `POST /maintenance/events` is withdrawn in favour of this),
and dedupes on the field named by `identity_field`. **`review` is a rename of `awaiting_disposition`
in `INGEST_STAGES`, not a seventh stage** — still six values, same positions; `ingest_status.py`'s
fleet-side mirror moves with it, with no transition period where both names are valid.

---

## R-??? (unallocated) — AN "EXTRACTED IDENTITY" IS A NAMED, PRIORITY-ORDERED SET OF REGEX-MATCHED FIELDS, NOT ONE GLOBAL STRING

**RULED 2026-10-02.** Source: architect, question 1 of four, `sessions/2026-10-02-packet-to-ca01-systems-of-record-schema-tagged.md:19-24`, `iagent_mesh/systems_of_record.py`.

`SystemOfRecord.identity` is `IdentityMatch{pattern: str, fields: tuple[str, ...]}`. `fields` names,
in priority order, which of an artifact's already-extracted field names this system's identity is
drawn from; `pattern` is a **regex** (not glob or prefix — the only one of the three that expresses
"looks like an sor-events-a work-order number" without a second grammar), tested against each named
field's value in order; the first field present whose value matches is the match.

---

## R-??? (unallocated) — A CONNECTOR IS NAMED AS FREE TEXT, RESOLVED AGAINST THE DEPLOYMENT'S REGISTRY, AND AN UNREGISTERED NAME IS A LOAD-TIME REFUSAL, NEVER A SILENT MISS

**RULED 2026-10-02.** Source: architect, question 2 of four, `sessions/2026-10-02-packet-to-ca01-systems-of-record-schema-tagged.md:26-30`.

`ConnectorLookup.connector: str` is free text, resolved against the deployment's registered
connector set — never validated by the row model itself, since a row does not know its
deployment's registry. `systems_of_record.validate_connectors_known(systems, known_connectors)` is
the refusal: it raises `UnknownConnector` listing every row naming an unregistered connector,
called at load time in the resolver — named explicitly as closing the "prefix-registry failure
class," a load-time halt rather than a silent miss.

---

## R-??? (unallocated) — THE CONNECTOR PROTOCOL IS ONE METHOD RETURNING A DICT OR `None`; "NOT FOUND" VS. "UNREACHABLE" IS THE CONNECTOR'S CALL, NOT THE SDK'S

**RULED 2026-10-02.** Source: architect, question 3 of four, `sessions/2026-10-02-packet-to-ca01-systems-of-record-schema-tagged.md:32-35`.

`SystemOfRecordConnector` is one `Protocol`, one method: `lookup(value: str) -> dict[str, str] |
None`. A dict on a hit, keyed by the names in the matched row's `lookup.returns`; `None` on a miss
— one type, so a fake connector and a real one are interchangeable. The protocol deliberately does
not distinguish "not found" from "connector unreachable"; a connector needing that distinction
raises instead of returning `None`.

---

## R-??? (unallocated) — THE ORIGIN VOCABULARY IS NEW AND SEPARATE: `resolved_by: Literal["record","steward","unresolved"]`, NOT `ProvenanceBlock.obtained_via`

**RULED 2026-10-02.** Source: architect, question 4 of four, `sessions/2026-10-02-packet-to-ca01-systems-of-record-schema-tagged.md:38-41`.

`obtained_via: authoritative_source` is ruled a **new, separate** vocabulary, not
`ProvenanceBlock.obtained_via`. The architect's shape for `Origin` also replaces the field name:
`resolved_by`, not `obtained_via` — a correction to the already-built `Origin{owner_domain,
program, obtained_via}` draft.

---

## R-??? (unallocated) — `Origin`'S FIELDS SPLIT: `owner_domain`/`resolved_by` ARE PROPERTIES, `program` IS A TYPED EDGE (`ORIGINATES_FROM`), EACH `evidence[]` ITEM IS A TYPED EDGE

**RULED 2026-10-02.** Source: architect, `sessions/2026-10-02-packet-to-cortex-origin-and-system-of-record.md:25-50`, citing ADR-0023 lines 205-214 ("adding a new relationship requires adding a new edge type, not stuffing it into an untyped slot").

`owner_domain` and `resolved_by` are plain properties on the artifact node — attributes OF the
artifact, the same reason `status`/`question_text` are properties today, not edges. `program` is a
typed edge, `ORIGINATES_FROM`, to a `Program` node — programs have membership and are entities
other things belong to, exactly ADR-0023's own test for a typed edge; the edge carries no
properties of its own. Each `evidence[]` item is a typed edge to its source, the same shape as
`CITES`, not a string on the node — a string-only evidence item loses which source, with what
span/quote/confidence, backs the claim.

---

## R-??? (unallocated) — `MaintenanceActionRecord` IS IAGENT-SIDE ONLY: A REGISTERED OUTPUT ARTIFACT, NEVER AN INBOUND INGEST KIND

**RULED 2026-10-02.** Source: architect, `sessions/2026-10-02-packet-to-openddil-ingest-door-subscription-contract-two-kinds.md:103-110`.

`maintenance-action-record` is the maintenance workflow's declared OUTPUT artifact, registered so
(a) subscriptions can filter on it and (b) `GET /artifacts/{id}` knows its schema. It is never an
inbound ingest kind: nothing wraps it in an `IngestRequest`, and the subscription contract does not
apply to it. The completed record crosses back as the plain wire response, not a second trip
through the ingest door. Its `ContentKindRegistration` row still lives in OpenDDIL's deployment
overlay, same placement as the event kind's, different consumption.

---

## R-??? (unallocated) — `work_order.parts[]` GAINS FOUR ADDITIVE, NULLABLE FIELDS: `icn`, `hotspot_id`, `lead_time_days`, `lead_time_source`

**RULED 2026-10-02.** Source: architect, `sessions/2026-10-02-packet-to-openddil-the-maintenance-bridge-contract-week-1.md:170-180`.

All four fields are additive and `| None`: the existing `item`/`part_ref`/`quantity`/`source_site`
fields are unchanged, and a row that predates this ruling (or one the bridge has no value for)
carries `None` rather than being refused or backfilled with a guess. `icn`/`hotspot_id` name the
illustrated-parts figure and this item's hotspot within it, from the walk's IPD citation.
`lead_time_days`/`lead_time_source` record what a "replace after resupply" option was built on at
the time it was built, mirroring `picture.nearest_spare`'s fields at that moment.

---

## R-??? (unallocated) — INGEST'S `obtained_via` MAPS ONTO THE SDK'S `Origin.resolved_by`: `authoritative_source` → `record`; `user-drop` → `unresolved`-THEN-`steward`

**RULED 2026-10-03.** Source: architect, relayed `sessions/2026-10-03-packet-to-ca-origin-resolved-by-mapping-ruled-write-it-into-the-docstring.md:5-10`.

| `obtained_via` | `resolved_by` |
|---|---|
| `authoritative_source` | `record` (evidence carries `source:citation`) |
| `user-drop` | `unresolved` until a steward sets it, then `steward` |

The mapping is written into `Origin`'s own docstring in the 0.9.7 squash, so the two vocabularies
are joined in the SDK itself, not only in one consumer; Lane 1's writer encodes the same table and
seals it with a test.

---

## R-??? (unallocated) — A BLANK `requested_by` IS A TERMINAL 422 STORE-WIDE, NOT ONLY ON THE ACCEPTANCE ROW

**RULED 2026-10-05.** Source: Chris, quoted by ia-74, `sessions/2026-10-05-packet-to-lane-01-the-acceptance-requester-is-pushed-for-roll-18.md:26-56`.

> *"yes. A task nobody asked for is a lineage hole whatever its kind."*

The refusal is store-wide, not acceptance-only: a blank `requested_by` is refused in the builder (no
case opens; the turn shows `acceptance_not_opened`), the store (`NoRequester`), and the BFF (a
terminal 422 `no_requester` at all four register sites). Chris's ruling extends this to every kind,
not only the acceptance row that prompted it — Lane 1 must find and fix every caller that can still
produce a blank (named at the time: `access_request` and `dispatch_driver`'s `or ""`) before the
refusal goes live, so the 422 never fires on a legitimate path.

---

## R-??? (unallocated) — A PACKET IS ADDRESSED `<repo>/<branch>`; A WORKTREE NAME IS NOT AN ADDRESS

*Added 2026-10-07, after the thirty above. lane/gov wrote this draft itself and has verified it.*

**RULED 2026-10-07.** Source: the architect, relayed by Chris to ia-gov in session as
*"Addressing ruled: to: <repo>/<branch>."* It is in no file until this entry. It answers lane/gov's question in
`2026-10-07-packet-to-architect-gov-the-four-item-brief-measured.md` ("the `ia-` worktree prefix no
longer implies this repo").

**The rule.** A packet's `to:` line is the repo, then the branch:

- `invincible-agent/lane/gov`
- `cortex-ui/lane/cortex-60`
- `iagent-mesh-sdk/lane/ca`

Lane-less seats keep `<repo>/seat/<name>`, and a seat is still never external, as lane/74 ruled on
2026-09-26. The legacy form `ia-<worktree>/lane/<branch>` is still **read** but no longer **written**.

**Why.** The legacy form put a worktree where the repo goes, so the address could not say *which
repo*:

- cortex-ui wrote `ia-cortex-60/lane/cortex-60` and the SDK wrote `ia-ca/lane/ca`, and neither
  worktree exists here;
- this inbox read 20 such packets as NO BRANCH. That was true, but it never said "another repo".

Measured on master's inbox 2026-10-07 (`to:` lines):

| form | packets |
| --- | --- |
| legacy `ia-W/lane/B` | 117 |
| seat | 39 |
| other-repo lanes | 16 |
| ruled `invincible-agent/lane/B` | 2 |

Across all `to:`, `from:` and `read-by:` lines, only one legacy address names a worktree that
differs from its branch: `ia-74/lane/74-acceptance-and-docs-subject`. It is a SENDER (a `from:`
line, 2026-09-29), so naming lanes by branch changes no recipient in this inbox. Measured with the
old and new scanners side by side: 0 addressee changes and an identical UNADDRESSED set.

**Consequences, applied on lane/gov:**

- **The scanner** (`src/iagent_pure/lane_packets.py`) names a lane by its branch, never its worktree.
- **The census** reads a legacy `ia-` address as internal and does not guess another repo. It
  prints an ADDRESS FORM block that counts legacy and bare addresses, and lists any legacy addressee
  with no branch here, so the sender can re-address.
- **CLAUDE.md**: the Handoffs paragraph and the conventions list now state the ruled form.

---

## R-??? (unallocated) — A MEASURED DIAGNOSIS SUPERSEDES A HYPOTHESIS; RECORD THE SUPERSESSION WHERE THE HYPOTHESIS LIVES

*Added 2026-10-07, after the 31st. lane/gov wrote this draft itself.*

**RULED 2026-10-07.** Source: the architect, relayed by Chris to ia-gov in session as
*"7f's deferral-risk diagnosis supersedes saf's hypothesis (a subject-scope exclusion, not a
missing class); record it and route the scope question to Lane 1."* Recorded in
`ia-gov/sessions/2026-10-07-record-gov-deferral-risk-diagnosis-supersedes-saf-hypothesis.md`
(lane/gov).

**The instance.** saf believed `safety-deferral-risk-refusal` refuses because the subject class
is in Jena but not in Neo4j, and marked that unverified. 7f measured the class in all three
stores. 7f found the cause instead: `class_scan_scope_domains` gives `['SUSTAINMENT','MESH']`,
and the subject's Weaviate domain is MAINTENANCE.

**The general reading, offered for you to accept or narrow.** A diagnosis measured against the
stores and the code outranks a hypothesis marked unverified, even when the hypothesis came
first and from the owning lane.

- The supersession is recorded in every place the hypothesis was written down. One of those
  places is committed: `docs/measurements/safety-walk-sheet.md:231-236`.
- Each place is corrected by the lane that owns it, never by the recorder.

lane/gov is not sure the general reading is what the architect meant. The relayed words cover
this instance only. If you register only the instance, the draft's title is too wide.

**What it does NOT decide.** Which fix applies (row entitlement, scan generalisation or edge
widening) is routed separately, in
`2026-10-07-packet-to-lane-01-deferral-risk-which-fix-is-a-scope-question.md`.

---

## Already registered

- **"Frontend rolls by digest, in a declared values file, never a bare `--set`"**
  (`sessions/2026-09-19-handoff-architect-the-vector-half-is-dead-and-the-roll-is-armed.md:94-95`,
  echoed `sessions/2026-09-19-handoff-lane-1-the-roll-is-armed-and-not-fired.md` — "Digest pinned
  in a declared values file, never a bare `--set` (R-034)") — the source itself cites **R-034**
  (`docs/rulings/README.md:1195`, "A `--set` IS AN INSTRUCTION, NOT A DECLARATION"). This is an
  application of that existing rule to the frontend chart specifically, not a new rule. Not
  drafted.

---

## Undecided / excluded, with reasons

1. **Reassignment of the `review_request` consumer and the gateway half of the scoped menu, from
   Lane 1 to ia-74** (`sessions/2026-09-19-handoff-architect-the-vector-half-is-dead-and-the-roll-is-armed.md:100-101`).
   This is work routing, not a decision that constrains future work independent of who does it —
   excluded per R-021's own scope ("What does not [belong]: anything still under discussion," and
   by extension a one-off assignment carries no standing rule). Noted, not drafted.
2. **`72f1111` amended with a true `Lane: invincible-agent/master` trailer, not exempted**
   (same handoff, line 101). A completed one-off correction of a single commit, not a standing rule
   — the standing rule it applies (every commit needs a correct `Lane:` trailer) is R-058/R-058.1,
   already registered. Not drafted.
3. **"Held until four walks draw"** bullet (same handoff, lines 106-110: lane-less addressee
   vocabulary; where seats may write in the shared tree; the three sibling `:latest` images;
   whether retag-by-digest ever published `0.4.4`; sessions-only pushes triggering cortex builds;
   pinned-artifact seals in doc-tools). Explicitly **not** ruled — held pending the walks. Genuinely
   undecided, not drafted.
4. **"Ruling 1," "Ruling 2," "Ruling 3," and "Ruling 6"** of the six-item completeness/count
   vocabulary sequence referenced at
   `sessions/2026-09-26-packet-to-chris-ruling-2s-trigger-is-a-version-number-and-the-vocabulary-already-landed.md:17-24,94`.
   Only **Ruling 5** (ForecastRow, drafted above) and **Ruling 4** (`cost_labor_composition`,
   drafted above as its final, decided state) could be located as standalone rulings in `sessions/`.
   "Ruling 6" is described only as "already the SDK's documented reason for a three-value `Literal`"
   (`iagent_mesh/enumeration.py:199-202`) — i.e. restated existing SDK documentation, not a new
   ruling, so not drafted. Rulings 1, 2 and 3 of that numbered sequence are referenced only by their
   consequences (a discriminator citation, a trigger premise) and their original ruling text was not
   found anywhere in `sessions/` or `docs/` under that search; they may exist only in an
   unrecorded conversation with Chris. I could not verify them well enough to draft text, and I did
   not force a call. Flagged for Lane 1 to ask Chris directly if the numbers matter.
5. **ADR-0049's own internal "Ruling 1-4"** (identity/entitlement/provenance/failure for
   cross-engine composition, `docs/adr/ADR-0049-cross-engine-composition-a-verb-that-needs-another-engines-data.md:187-264`)
   is a different, unrelated numbering inside that ADR's own §4, not part of the population list and
   not newly made since 2026-09-19 as far as I can tell from the ADR's own dateless prose — excluded
   as out of scope for this pass. If it needs registering, that is a separate population to build
   from the ADR's own rulings, not from a handoff/packet.
6. I checked for later packets in `sessions/2026-10-0[6-9]*` that RULE something not already covered:
   `2026-10-06-packet-to-architect-pcn26-117-review-422-is-ours-the-audience-reads-the-file-kind.md`
   and `2026-10-07-packet-to-7f-the-drift-seal-is-yours-and-status-404s-by-design.md` both discuss
   the open R-??? domain collision above but report measurement and diagnosis, not a new ruling from
   the architect resolving it — consistent with the "OPEN COLLISION" note above, not a separate
   entry.

---

## R-082 preamble

`git log -S'R-082' --format='%h %ad' --date=short -- docs/rulings/README.md` → `17bb2064
2026-09-28`. R-082's own body (`docs/rulings/README.md:3448-3474`) measures roll #6's ghcr pull
failure and cites `docs/measurements/2026-09-28-roll-6-fired-and-the-cluster-cannot-authenticate-to-a-registry-whose-packages-are-public.md`.
Proposed one-line preamble, matching every other entry's form:

> **RULED 2026-09-28.** Source: this seat, measured during roll #6's ghcr authentication failure
> (`docs/measurements/2026-09-28-roll-6-fired-and-the-cluster-cannot-authenticate-to-a-registry-whose-packages-are-public.md`).
