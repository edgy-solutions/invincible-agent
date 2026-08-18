# ADR-0041 — User-contributed documents: ingest on arrival, truth is granted later (quarantine is a STATUS, never a PLACE)

**Status:** Proposed — decision recorded 2026-08-17, **build deferred**. The ruling is cheap while the design conversation is fresh; the build is a cross-repo arc (backend seam → doc-tools provenance threading → UI label) and it queues behind the critical path like everything else. The ADR existing is what lets it queue safely.
**Date:** 2026-08-17
**Deciders:** Platform team
**Related:**
  - [ADR-0021](ADR-0021-deterministic-content-kind-selection-at-ingest.md) — the kind is **never** produced by the LLM; `manifest.metadata.content_kind` is the explicit declaration channel and it wins over everything. This ADR routes the drop-box classifier **into that existing channel** rather than opening a second kind-selection path.
  - [ADR-0025](ADR-0025-instance-plane-access-control-as-provenance.md) — access control as provenance: the system does not hide the existence of things, it **labels data and filters at query time**. This ADR is that pattern applied to *trust* instead of *access*.
  - [ADR-0026](ADR-0026-persona-entitlement-topaz-authorization.md) — the entitlement plane that decides who sees an unpromoted document at all (§R1).
  - [ADR-0027](ADR-0027-composable-approval-policy.md) — single-decider, grant-as-primitive, `task_audience`/`can_act`. Promotion registers **as a verb on the existing approval plane**; no second approval mechanism.
  - [ADR-0034](ADR-0034-trust-lifecycle-admission-policy-decision-records-autonomous-path.md) — born-supervised; decision records carry inputs-and-thresholds, never bare verdicts; `standing` is **frozen at write** and a later promotion may not retroactively upgrade evidence gathered under weaker standing. That clause is what forces §5's shape.
  - [ADR-0035](ADR-0035-two-planes-process-and-data-with-embedded-provenance.md) — provenance is a **field, never a join**; source authority is **distance from truth** (`authoritative_source` constant, `obtained_via` + `as_of` varying). The user-drop path is a new rung on that existing ladder, not a new ladder.
  - [ADR-0037](ADR-0037-ratified-docs-corpus-help-surface-grounding.md) §OKF cut — *"`generated` vs `verified` kept distinct: who wrote a doc need not be who confirmed it."* Same cut, one plane over: who **contributed** a document is not who **vouched** for it.
  - [`principles/select-from-authorized-set.md`](../principles/select-from-authorized-set.md) — the classifier proposes, the authorized set disposes.
  - [`principles/gate-class-follows-the-effect.md`](../principles/gate-class-follows-the-effect.md) — upload writes effects; promotion writes **authority**. Neither may ever be gated by in-cluster reachability (§8).

## Context

The ask is a generic way for **non-technical users to put documents into the system from the UI** — a PCN or PDN lands in someone's inbox, they drop the PDF into iagent, and it becomes usable knowledge. The honest end state is an **ingress mailbox** that IT owns; that requires cooperation we do not have, so the drop box is the bridge. Bridges get built. This ADR is about building it in a shape the mailbox can later inherit **without redesigning anything downstream** — because the mailbox is just a different door onto the same seam.

### What already exists (read 2026-08-17)

The inbound path is not greenfield; three quarters of it is live and event-driven:

| piece | where | state |
|---|---|---|
| bucket provisioning | `helm/invincible-agent/templates/minio-bucket-init-job.yaml` (`minioBucketInit.buckets`) | idempotent `mc mb`, pre-install/pre-upgrade hook |
| MinIO upload → doc-tools extraction | doc-tools (sibling repo) | auto-fires on upload |
| extraction → grouped disposition review | [`src/iagent/defs/extraction_review_sensor.py`](../../src/iagent/defs/extraction_review_sensor.py) | cursor-based sensor on `review.json` under `**/generated/**`, `run_key = doc_id` |
| the provenance block | [`src/iagent/provenance.py`](../../src/iagent/provenance.py) | `authoritative_source`/`obtained_via`/`as_of`/`ingested_at`/`ingest_run`/`standing`, **all required at write** |
| decision records | [`src/iagent/decision_record.py`](../../src/iagent/decision_record.py) | pure builder + validator, inputs-and-thresholds rule |
| trust rungs | [`src/iagent/trust_table.py`](../../src/iagent/trust_table.py) | `supervised` / `monitored` / `trusted`, born-supervised |

What is **missing** is exactly two things: a door a human can push a file through, and an answer to *what an unvouched document IS while it waits*. The first is plumbing. The second is the decision, and it is the whole of this ADR.

### The design that had to be rejected first

The obvious shape is **quarantine-as-place**: user drops land in a holding bucket outside the pipeline, unprocessed; an approver blesses one; approval copies the object into the canonical bucket and *only then* does doc-tools ingest it. Airtight, trivially explained, and the graph only ever contains truth.

It is also unbuildable as a governance gate, for a reason that is a property of this product rather than a preference: **everything the UI can show comes from processing.** No extraction, no instances, no chunks, no triples — therefore no preview, no search, no "here is what this document would add," not even confirmation that the classifier guessed the type correctly. The approver's actual choices are *open the raw PDF in another tab* or *trust the filename*. A review step that reviews filenames is not a gate, it is a formality, and it costs the uploader every bit of value between drop and blessing — which for a PCN that landed this morning is precisely when they need it.

That observation is not a caveat. It settles the design: **ingestion and truth-granting are two different events, and they were only ever coupled by the accident of the pipeline having one entry path.** Processing is what makes a document *legible*. Promotion is what makes it *authoritative*. Decoupling them is the decision.

And decoupling is the **house pattern**, not a novelty. ADR-0025 refused to hide the existence of instances a user cannot access — it labels data and filters at query time. ADR-0034 does not prevent unproven formats from running — it labels their standing and gates what the label permits. ADR-0037 keeps `generated` distinct from `verified` in the same corpus. **Label and filter; do not exclude.** Quarantine-as-place is the one shape in this family the project has already refused three times under other names.

## Decision

**Every user-contributed document is processed on arrival. What it produces enters the graph carrying a structural stamp that says it is unvouched. Promotion is a separate, later, recorded event that grants truth without rewriting history.** Eight parts.

### 1. Ingestion and truth-granting are separate events

Stated first because everything else is a consequence. Ingestion is mechanical and immediate. Truth-granting is human, deliberate, and happens on data that **already exists and is already visible**. The approver reviews *the extraction* — "this PCN produced these 3 instances, affects these parts, links to these existing entities" — not a PDF. This is the first genuinely informative review surface the feature has, and it is where misclassification gets caught: a PCN filed as a tech manual produces obviously wrong instances, and no amount of staring at the cover page reveals that.

### 2. The door is the stamp — `ingress-user/` and a fifth `obtained_via` rung

A dedicated landing prefix (`ingress-user/…`, sibling of the existing `sustainment/…` tree) still exists, but its job shrinks: **it is how the pipeline knows which stamp to apply, not how documents are hidden.** Different watch path → different provenance, mechanically, with nothing to remember.

The stamp is **not a new vocabulary**. `provenance.py` already models exactly this: `authoritative_source` names who owns the truth and is *the same for every path to it*; `obtained_via` names the degradation path, ordered nearest-to-truth. A hand-carried PDF from an individual's inbox is a **degradation path**, and the farthest one we have:

```python
DIRECT, ETL, WAREHOUSE, MANUAL_EXPORT, USER_DROP = (
    "direct", "etl", "warehouse", "manual-export", "user-drop")
```

`user-drop` extends the existing ordered tuple at the far end. `authoritative_source` remains the vendor who issued the PCN — the drop does not change who owns the truth, only how far this copy travelled from it. `as_of` will very often be `AS_OF_UNKNOWN`, which is what that sentinel is for. `standing` is `supervised` — **born-supervised**, ADR-0034's default, arrived at without an exception.

This is the ruling that makes the mailbox cheap later: the mailbox is a **sixth rung** (or the same one), a different door writing a different `obtained_via`. Nothing downstream changes.

### 3. The stamp is structural, on everything the document produces

Not a tag on the object in MinIO; not a row in a side table. **Every instance, chunk and triple the document produces carries the provenance block**, applied by the ingest path itself — which is already mandatory today (`_REQUIRED`, `ProvenanceIncomplete` raised at write). ADR-0035's clause is the whole argument and it needs no restatement here: an optional join is a join that stops happening, and the query that omits it is shorter, works, and becomes the one everyone copies.

The consequence worth stating plainly: **a consumer that forgets to filter gets labelled data, not laundered data.** That is the difference between this and a pending-flag, and it is the entire safety case.

### 4. The classifier suggests, the human confirms, the manifest declares

Mapping *"this is a PCN"* → *"therefore it lands here and is extracted this way"* is **already decided** and must not be re-decided in the upload path. ADR-0021's precedence is: `manifest.metadata.content_kind` wins → path-derived → **HALT, never LLM**.

So the drop box slots in without amendment:

- the classifier runs **in the upload flow, as a suggestion** — it pre-selects an entry in the picker;
- the picker's options are **the registered kinds**, not free text — `select-from-authorized-set`, so an unregistered kind is not expressible rather than caught later;
- the human's confirmed pick is written to `manifest.metadata.content_kind` — **the existing declaration channel**;
- storage location and extractor-config are **derived from the declared kind by the existing map**. The UI never picks a bucket path. Neither does the next UI.

If the classifier is confidently wrong and the human clicks through, §1's review surface is where it surfaces, with the extraction as evidence. If the kind cannot be determined, the upload is refused at the door — **HALT, never LLM**, unchanged.

### 5. Promotion is a NEW fact plus a decision record — it does NOT rewrite the provenance block

The tempting shape — *"promotion flips the property"* — collides with a clause this project already paid for. `standing` in `provenance.py` is **frozen at write**: the source's rung *at the moment the claim was made*. ADR-0034 refuses regime-mixing precisely so that a later promotion cannot retroactively upgrade evidence gathered under weaker standing. Flipping `standing` in place would do exactly that, and would erase the record of the interval during which answers were served from unvouched data.

So promotion **appends**:

- a **decision record** (ADR-0034 contract, `admitted_by: policy`), carrying inputs-and-thresholds — *what was reviewed, by whom, against which kind's criteria, with which extraction in front of them* — never a bare `approved: true`;
- a **promotion fact** on the document's assertions: `promoted_by` (`human:<id>`, OKF actor spelling per ADR-0037), `promoted_at`, and `promotion_ref` → the decision record's id;
- the original block, **unchanged**. `obtained_via: user-drop` remains true forever, because it is true forever. A promoted PCN is still a PCN that arrived by hand; what changed is that someone competent vouched for it, and that is a *different fact*, recorded as one.

Queries read the promotion fact. History reads the pair. Nothing is rewritten.

Promotion registers as a **verb on the existing approval plane** — `task_audience` / `can_act` / `requested_by` / `acted_by`, ADR-0027's single-decider machinery. **One approval plane.** A second approval mechanism for documents is rejected in §Alternatives.

### 6. Rejection is a property-keyed sweep

Rejection deletes **everything carrying the document's id** — which is only cheap because §3 put the stamp on every produced assertion. This is the second load-bearing reason the stamp is structural: undo is a keyed sweep rather than an archaeology project. Identity is the **artifact's**, per `decision_record.py`'s standing rule — the drop box does not mint its own (that drift is how one artifact becomes "the same work" to one mechanism and "new work" to another, a failure this codebase has now paid for four times).

Rejection also emits a decision record. *"Why is this PCN not in the system?"* must be answerable from an artifact, not from a re-run.

### 7. The label rides the answer envelope — not each UI's discretion

The hazard that will otherwise appear in a demo: a user asks about a component, the answer synthesises over sources, **one of them is an unpromoted user drop**, and the rendered answer says nothing. At that moment quarantine-as-status has collapsed into laundering at the presentation layer.

So: **the answer envelope carries the weakest provenance it drew on, structurally** — the artifact says *"includes unverified user-contributed material"* with the contributing document ids, and every UI renders from that field. A UI that forgets to render it is a UI bug with a visible field behind it; a UI that has to *ask* whether its sources were vouched is a design defect, and the one every integrating client would get wrong differently. This mirrors ADR-0025 exactly: access provenance is *carried by the Artifact*, not re-derived per consumer.

### 8. The backend seam is the product; the gate class follows the effect

The API is the deliverable and **the drop-box UI is its first client, not its owner** — the next UI and the eventual mailbox are peers. Concretely that means kind-suggestion, kind-declaration, provenance stamping, promotion and rejection are **backend verbs**, and nothing in the sequence is expressible only through the UI's flow.

Both new routes write, so `gate-class-follows-the-effect` disposes them without argument:

| route | effect | gate |
|---|---|---|
| upload / ingest-as-user | **writes state** (objects, then assertions) | in-cluster reachability is **NEVER** sufficient — authenticated identity + domain entitlement, deny-by-default |
| promote / reject | **writes authority** (grants truth) | **NEVER** — authenticated identity + `can_act` on the audience, fail-closed |

## Rulings this ADR records rather than defaults

These are policy calls that would otherwise be settled by whichever query path happened to be written first. They are ruled here.

**R1 — Who sees unpromoted material: domain-entitled users, labelled.** Not uploader-and-approvers-only (too tight: the uploader's colleagues are exactly the people who would catch *"that's the superseded revision of that PCN"* before an approver ever sees it, and hiding it wastes the review's best reviewers), and not everyone-the-promoted-version-would-reach (too loose: it makes promotion decorative). Visibility runs through the **existing** entitlement plane (ADR-0026) — unpromoted material is not a new access class, it is ordinary domain-scoped data that additionally carries a weak provenance label.

**R2 — Default query behaviour: include-and-label.** An answer that silently omits the PCN the user dropped ten minutes ago looks *broken* to them, and teaches users that the drop box does not work. Consumers that require vouched-only filter explicitly on the promotion fact — which is available, structural, and cheap (§3). The asymmetry is deliberate: **the default is honest-and-labelled, the opt-in is strict.**

**R3 — Duplicate identity: key on `(issuer, document_number, revision)`, and the official feed wins.** When the same PCN arrives both by drop and later through an official pipeline, the two are the **same document via two `obtained_via` paths** — precisely the case ADR-0035 §5 models (one `authoritative_source`, N degradation paths, differing `as_of`). The nearer-to-truth copy supersedes; the drop's assertions are swept (§6) with a decision record naming the superseding artifact, so the audit trail shows *replaced by the official feed*, never a silent disappearance. **This is the least-evidenced ruling here** — it is made now so the first collision is handled rather than discovered, and it is the clause most likely to need amendment once real documents collide.

## Consequences

**We accept:**

- **doc-tools must thread provenance through extraction → instances → chunks → triples.** This is the real build cost, it lands in the sibling repo, and it is not optional — §3 is the safety case. The ADR-0037 hazard applies again verbatim: doc-tools' pushes to main produce **zero CI runs**, so a change can land unbuilt while reading as shipped. That board item gates this build too.
- **Unvouched data is in the graph.** This will be questioned by someone, later, in good faith. That is what this ADR is for: it is in the graph *labelled*, filterable by construction, sweepable by key, and visible in every answer that draws on it — which is strictly more governable than a folder of PDFs nobody can see into.
- **Query paths must carry the label into answers** (§7), including any path that predates this decision. A synthesising path that drops the field is a laundering bug, and should be tested as one.
- **A fifth `obtained_via` value is a change to a closed ordered tuple** — the order is meaningful, not cosmetic, so every consumer that reasons over it must be checked.

**We get:**

- **Users get value at drop time**, which is the entire point of building the bridge.
- **Approvers decide with evidence** — the extraction, not the cover page.
- **The mailbox is a door, not a redesign.** When IT cooperates, the mailbox writes to a landing prefix with its own `obtained_via` and inherits every downstream behaviour decided here. The bridge does not have to be demolished to cross it properly.
- **One approval plane, one provenance vocabulary, one kind-declaration channel** — three seams reused, zero minted.

## Alternatives considered

- **Quarantine-as-place (hold unprocessed until approved).** Rejected in §Context: everything the UI can show comes from processing, so the approver reviews a filename and the user gets nothing until someone acts. A governance gate that inspects filenames is a formality, and it is the shape this project has already refused under ADR-0025 (hide-vs-filter) and ADR-0034 (block-vs-label).
- **A `pending` tag on objects in the canonical buckets.** Rejected: a tag is metadata **consumers must remember to check**, and every forgetful consumer silently inherits unapproved material as truth. The boundary must be structural — *which door it came through*, stamped on every assertion — not conventional. Same failure family as the optional join ADR-0035 forbids.
- **Flipping `standing` in place on promotion.** Rejected in §5: `standing` is frozen at write precisely so a later promotion cannot retroactively upgrade evidence gathered under a weaker regime. Promotion appends a fact; it does not edit one.
- **A second approval mechanism for documents.** Rejected: promotion is a verb on the existing gate (`can_act`, decision records, `requested_by`/`acted_by`). A parallel approval engine breaks the single-decider invariant ADR-0027 exists to protect, and would need its own audit surface.
- **LLM classifier decides the storage location directly.** Rejected by ADR-0021 without needing new argument — the kind is never produced by the LLM. The classifier suggests into a picker over the registered set; the human's confirmation is what declares.
- **Wait for the ingress mailbox.** Rejected as *sequencing*, not as *design*: the mailbox is the better end state and is blocked on cooperation we do not control. The decisions here are the ones the mailbox would need anyway, which is why building the bridge does not cost the destination.

## Open at build time

1. **Where the promotion fact is persisted** — graph triples vs. relational, deliberately not pre-empted here for the same reason `decision_record.py` declines to decide its own store.
2. **Whether an unpromoted document may be *cited* by a promoted artifact** — a promoted answer resting on unvouched evidence is the mixed-source case one level up. §7's envelope makes it *visible*; whether it is *permitted* is not ruled here.
3. **Ageing** — an unpromoted drop that nobody ever reviews should not stay visible-and-labelled forever. Likely a `stale_after` **absolute date** (ADR-0037's OKF cut, same reasoning: determinism over context-dependence), but the policy is unruled.
4. **Any new predicate minted for the promotion fact** goes through [ADR-0007](ADR-0007-survey-before-mint.md) survey-before-mint and lands in [`minted-concepts.md`](minted-concepts.md). Nothing in this ADR mints one; §2 and §5 reuse existing fields deliberately.

## Indicators for revisiting

- **Users stop dropping documents** because labelled answers are treated as untrustworthy by their colleagues — the label would then be functioning as exclusion, and R2 needs rethinking.
- **The promotion queue never drains.** If unpromoted material is useful enough that nobody bothers to vouch for it, promotion is ceremony and the real decision is about ageing (Open §3), not approval.
- **The ingress mailbox lands.** If official-feed arrival becomes the norm and drops become rare exceptions, R3's supersession rule moves from edge case to hot path and deserves re-examination with real collision data.
- **A second contribution type appears** (a user *asserting a fact* rather than *contributing a document*). The provenance shape here is document-shaped; a claim-shaped contribution may need its own rung rather than a stretched `user-drop`.
- **A consumer is found reading unpromoted assertions without the label** — the structural claim in §3 would be false, and the safety case needs rebuilding rather than patching.
