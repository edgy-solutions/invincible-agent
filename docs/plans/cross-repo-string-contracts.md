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
| `pcn_disposition` (UNCHANGED — consistent) | restate_analyst/dispatch_plan.py | cortex-ui taskKindRegistry.ts (→ APPROVAL_TASK). NB: still pcn-named; rename coherently when convenient. |
| `workflow_ack`, `access_request` | cortex-bff (register_task / access_requests) | cortex-ui taskKindRegistry.ts |

## 4. Topaz audience keys (task_audience `can_act` / grants)
| key | PRODUCER (grants — git-rails) | CONSUMERS (register recipients + `/act` can_act) |
|---|---|---|
| `pcn_disposition:<compartment>` | task_grants.yaml (git-rails) → task_grant_sync | grouped review audience; cortex-bff `/act`. NB: still pcn-named; M3 → generic `disposition_review:<compartment>` (a git-rails + Topaz reseed, deploy-time). |
| `qualification` | task_grants.yaml | dispatch fan-out recipients |
| `access_grant:<domain>` | task_grants.yaml | access_request routing |
| `promotion:<domain>` | task_grants.yaml | workflow_ack promotion tasks |

## 5. Canvas archetype names (BFF/engine payloads → cortex-ui SemanticInterpreter switch)
| archetype | PRODUCER (sets in payload) | CONSUMER (renders) |
|---|---|---|
| `GROUPED_REVIEW`, `APPROVAL_TASK`, `INSTANCES_BY_PROPERTY`, `WORKFLOW_OBSERVATION`, `PROCESS_TOPOLOGY`, `HAZARD_DECLARATION`, `ASSET_STATE_METRIC`, `KNOWLEDGE_DOCUMENT`, `CHART_WIDGET` | feeders (cortex-bff) + taskKindRegistry archetype field | cortex-ui SemanticInterpreter.tsx `switch(comp.archetype)` — structural, no domain branch. Default = honest "UI COMPONENT NOT FOUND". |

## Rule
A rename of ANY row is a coordinated multi-repo change (update every producer + consumer) followed by a
loop re-verify — NOT a per-repo edit. Per-engine tests will pass while the contract is broken. The M3
`rendersAs` layer eventually makes rows 3 + 5 (kinds, archetypes) *declared data* instead of stringly-typed
code, which retires this table's most fragile rows. Until then, this doc is the checklist.
