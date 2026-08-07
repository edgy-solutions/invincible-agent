# Cross-repo string contracts — the rename checklist (no joint test verifies these)

Every entry is a **stringly-typed value consumed in N repos, verified jointly in ZERO tests** (per-engine
tests each pass while the contract breaks between them — the class that nearly bit the M2 `grouped_review`
kind rename). Before renaming any value here, update EVERY producer + consumer in one coherent change and
re-verify the loop. This is the discovery process the M2 run did by hand, captured so the next one is a
checklist. Values shown POST-M2 (branch `m2-extraction-sort`); the pre-M2 name is in parens.

## 1. Restate service names (the wire names Restate routes on)
| value | PRODUCER (defines/mounts) | CONSUMERS (call by URL string) |
|---|---|---|
| `GroupedReview` (was `PcnGroupedReview`) | restate_analyst/grouped_review_workflow.py `Workflow(...)` + main.py mount | cortex-bff gateway.py `/GroupedReview/{wf}/submit_decision`, `/GroupedReview/{wf}/get_batch` |
| `ReviewStarter` (was `PcnReviewStarter`) | restate_analyst/review_starter.py `Service(...)` + main.py mount | cortex-bff gateway.py `/ReviewStarter/start_review`; restate_analyst/main.py start URL |
| `DispatchItem` (was `PcnDispatchItem`) | restate_analyst/dispatch_driver.py `VirtualObject(...)` + main.py mount | fan_out_dispatch keyed sends; cutover dedup-marker surface (see m2-cutover-plan.md) |
| `BPMNWorkflowRunner` | (the sealed runner) | cortex-bff workflow_ack resume `/BPMNWorkflowRunner/{wf}/approve` |

## 2. HTTP route paths
| route | PRODUCER (defines) | CONSUMERS (call) |
|---|---|---|
| engine-o `/write_item_state` (was `/write_pcn_disposition_state`) | ontology_service/main.py | restate_analyst/dispatch_driver.py |
| engine-o `/instances_by_property` (was `/pcn_parts_by_state`) | ontology_service/main.py | cortex-bff dashboard feeder |
| engine-o `/resolve_instance` (was `/resolve_pcn_instance`) | ontology_service/main.py + self-reg endpoint_url → Neo4j | restate_analyst/review_composer.py; the `/resolve` fan-out (via capability graph) |
| engine-o `/policy_rules` | ontology_service/main.py | restate_analyst/policy_rules_client.py |
| bff `/reviews` (was `/pcn/reviews`), `/reviews/{wf}/batch`, `/instances_by_property` (was `/pcn/parts_by_state`) | cortex-bff gateway.py | cortex-ui api/client.ts (`fetchReviewBatch` etc.) |
| bff `/notices/{id}/provenance` | cortex-bff gateway.py | cortex-ui EvidencePane (`fetchNoticeProvenance`) — domain-named, behind evidence boundary (not renamed) |

## 3. Task KIND values (minted by engine-a, matched by BFF + UI)
| kind | PRODUCER (mints) | CONSUMERS (match) |
|---|---|---|
| `grouped_review` (was `pcn_grouped_review`) | restate_analyst/grouped_review_workflow.py | cortex-bff `/act` bridge + batch lookup; cortex-ui taskKindRegistry.ts (→ GROUPED_REVIEW archetype) |
| `pcn_disposition` (UNCHANGED — consistent) | restate_analyst/dispatch_plan.py | cortex-ui taskKindRegistry.ts (→ APPROVAL_TASK). NB: still pcn-named, and DELIBERATELY so as of M3.1 — it is a UI **render contract**, not authz vocabulary, so it retires with `taskKindRegistry` in M3.3 rather than in a two-repo string rename now. Do not conflate with the audience key in §4, which was renamed. |
| `workflow_ack`, `access_request` | cortex-bff (register_task / access_requests) | cortex-ui taskKindRegistry.ts |

## 4. Topaz audience keys (task_audience `can_act` / grants)
| key | PRODUCER (grants — git-rails) | CONSUMERS (register recipients + `/act` can_act) |
|---|---|---|
| `disposition_review:<compartment>` (was `pcn_disposition:<compartment>`) | task_grants.yaml (git-rails) → task_grant_sync | grouped review audience; cortex-bff `/act`. RENAMED M3.1 — git side landed; needs its `task_grant_sync` run to seed the new Topaz relation and prune the old. Between the two the review routes to NOBODY (`NoEntitledRecipients` → 422), so sync in the same window. Guarded by `test_cross_repo_contracts.py` FORBIDDEN `pcn_disposition:` (the colon discriminates the audience key from the task kind in §3, which stays). |
| `qualification` | task_grants.yaml | dispatch fan-out recipients |
| `access_grant:<domain>` | task_grants.yaml | access_request routing |
| `promotion:<domain>` | task_grants.yaml | workflow_ack promotion tasks |

## 5. Canvas archetype names (BFF/engine payloads → cortex-ui SemanticInterpreter switch)
| archetype | PRODUCER (sets in payload) | CONSUMER (renders) |
|---|---|---|
| `GROUPED_REVIEW`, `APPROVAL_TASK`, `INSTANCES_BY_PROPERTY`, `WORKFLOW_OBSERVATION`, `PROCESS_TOPOLOGY`, `HAZARD_DECLARATION`, `ASSET_STATE_METRIC`, `KNOWLEDGE_DOCUMENT`, `CHART_WIDGET` | feeders (cortex-bff) + taskKindRegistry archetype field | cortex-ui SemanticInterpreter.tsx `switch(comp.archetype)` — structural, no domain branch. Default = honest "UI COMPONENT NOT FOUND". |

## 6. IDENTITY vs LOCATION — two artifact-derived strings on ONE payload (a different species)

Rows 1–5 are all **one value, N repos**: the failure is a rename that lands unevenly. This row is the
inverse and is worth naming separately: **two DIFFERENT strings, both derived from the same artifact, on
the same payload**, where the failure is a consumer reading the wrong one. No rename is involved. Every
per-hop test passes. The value is present, well-formed, and travels correctly end to end — it just does
not mean what the consumer thinks it means.

| field | WHAT IT IS | FORM | PRODUCER | CONSUMERS | job |
|---|---|---|---|---|---|
| `request_key` | the artifact's **IDENTITY** | `{epoch}{ETag}-{key}` | `extraction_review_sensor.start_review_op` | cortex-bff `_ingress_idempotency_key`; `ReviewStarter.compose_workflow_id` | ingress dedup + the Restate workflow key |
| `artifact_uri` | the artifact's **LOCATION** | `s3://{bucket}/{key}` | `extraction_review_sensor.start_review_op` | cortex-bff forward; `ReviewStarter` → `derive_provenance` | the ADMISSION posture (ADR-0034 trust key) |

**What happened (2026-08-06).** The phase-1.3 derive was written to fetch `request_key`. It is
artifact-derived, it moves when the content moves, and the surrounding comments already called it "the
artifact pointer" — so it *reads* like a location. It is not one. The fetch asked S3 for a key with an
ETag glued to the front and **every derive refused**, which the refuse-not-floor ruling correctly turned
into a loud 422 rather than a silent supervise.

**Why nothing caught it** (three self-references, zero contact with the emitter):
1. the parser's docstring declared the producer format as `<etag>:<key>` — COLON. The sensor has always
   emitted a DASH. The format was **invented**;
2. its fixture asserted the same invented format, so parser and test agreed with each other and neither
   ever agreed with the producer;
3. the live witness hand-supplied a bare key in the shape the parser expected, so the composed sensor
   path was never driven.

**The generalisable rule** — *when two fields on one payload are both derived from the same artifact, the
test that proves a consumer reads the right one must obtain the payload FROM THE PRODUCER.* A hand-written
fixture cannot distinguish them, because the author who confuses them writes the fixture the same way.
Pinned by `tests/test_artifact_uri_contract.py` (payload built by calling the sensor's own
`build_start_review_payload`) and `tests/test_cross_repo_contracts.py`
(`test_the_derive_reads_the_POINTER_field_not_the_IDENTITY_field`, asserted on the CALL SITE — a
file-level substring check passes on the prose *about* the field).

**Bare-key tolerance was removed with it.** `parse_pointer` used to resolve a bare key against
`ARTIFACT_BUCKET`, making the artifact's location depend on two runtimes agreeing on an ambient env var —
a cross-repo string contract smuggled in as a fallback. One form only, refused otherwise: the full URI
carries its own bucket. **Tolerance IS the coupling.**

**Refusals are legible.** `ArtifactUnreadable.reason` ∈ {`malformed_pointer`, `artifact_absent`,
`store_unreachable`, `unparseable`, `schema_alien`}. Same verdict (refuse), different *destination for the
reader*: `artifact_absent` sends you to the producer, `store_unreachable` to MinIO. The first release
refused a malformed pointer with the same message shape as an unreadable artifact — true, and useless.

## Rule
A rename of ANY row is a coordinated multi-repo change (update every producer + consumer) followed by a
loop re-verify — NOT a per-repo edit. Per-engine tests will pass while the contract is broken. The M3
`rendersAs` layer eventually makes rows 3 + 5 (kinds, archetypes) *declared data* instead of stringly-typed
code, which retires this table's most fragile rows. Until then, this doc is the checklist.

**Row 6 adds a second rule, for a failure a rename checklist cannot catch:** when a payload carries two
values of the same PROVENANCE but different JOB, name the job in the field name and pin the consumer's
call site. Discovery credit for this instance goes to the reviewing agent that traced a 422 back to the
conflation rather than to the artifact.
