from: invincible-agent/lane/saf
to: invincible-agent/seat/architect

# Digest, lane/saf, 2026-10-16: walk on the serving build (rev 193 image, rev 194 complete); FRACAS reaches Engine S; namespace PR

## Serving build (read-only; ns sandbox)

| item | value |
| --- | --- |
| helm rev 192 | chart 0.4.46 = "188b", image 76af7b83, deployed 2026-10-16 05:06Z (Lane 1's figure confirmed) |
| helm rev 193 | chart 0.4.49, deployed 13:17Z; image 86b74d1a (this is the current tag) |
| helm rev 194 | chart 0.4.50, was pending-upgrade from 13:56:42Z through the walk; since completed: "deployed, Upgrade complete" |
| cortex-bff and the Dagster code location | both image tag 86b74d1a; pods started 13:56:56Z and 13:57:02Z (rolled by rev 194's start; tag unchanged) |

Reconciliation: 76af7b83 is rev 192 (05:06Z); 86b74d1a is rev 193 (13:17Z). By ancestry 86b74d1a
contains #46, #51, #55 and #57 at 9a84634f, so the walk ran on what is effectively 189, not 188b.
It contains #57 at 9a84634f including e862aae1 and 8ea51de2 (both ancestors of 86b74d1a), so the shape check is served. It does NOT contain 7aab3b44 and 9ba26b68 (now PR #61):
the two-outcome verb and the IRI fix are not served. That matches the live result: the served shape check refused the IRI. Also not in 86b74d1a: PR #60's HAZ-/CSI-/MIT- declaration.

Nothing was cancelled (the STARTED list was read, not acted on). The walk straddled the
13:57Z pod restart: Q1/Q8/Q10/Q12 x3 and FRACAS #1 ran 13:40Z-13:56Z (before), FRACAS #2 was cut by
the restart (pipeline_error, dagster_run_failed / ui_payload_timeout), the rest re-ran 14:29Z-14:36Z
(after). Run tags carry only `dagster/code_location=iagent`; the person is in the run config, not the tags.

## Walk: bob, SAFETY_ENGINEER, [SUSTAINMENT], cortex-ui, POST /orchestrate, 3 runs each

| prompt | window (UTC) | disposition, 3 of 3 | vs 187 |
| --- | --- | --- | --- |
| Q1 HAZ-1003 | 13:40-13:43 | KNOWLEDGE_DOCUMENT, review_request risk_acceptance_medium:SUSTAINMENT, instance_resolved true | unchanged |
| Q8 HAZ-1001 | 13:44-13:46 | ask, `ambiguous_in_domain`, slot hazard_id, verb draftRiskAssessment | moved: 187 was slot_abstain / no_members; now asks (a reachable verb, still not drafting) |
| Q10 HAZ-1007 | 13:48-13:50 | same ask | same movement |
| Q12 HAZ-1008 | 13:52-13:54 | same ask | same movement |
| HAZ-1004 | 14:33-14:35 | same ask: "I heard 'HAZ-1004', which is not one of them" | not walked on 187 as a ranked row; same cause as Q8/10/12 |
| FRACAS "failures recorded for part 5530-184" | 14:29-14:32 (3 of 3) | refused, `unknown_part`: "unknown part 'http://internal/components/5530-184'" | moved: 188 was `no_compatible_verbs`; 187 was no_verb_classified / fallback. The subject now resolves and binds the verb; the verb is reached |

(FRACAS #1 at 13:56Z gave the same `unknown_part`; #2 was cut by the restart.)

Cause of Q8/Q10/Q12/HAZ-1004: the served Engine S does not declare HAZ-, so engine-o's cross-namespace
refusal never fires and the fan-out stays ambiguous. They should clear when this PR ships (see below);
I have not claimed that, it is the next walk's arm.

Cause of FRACAS `unknown_part`: the router binds a component-IRI subject and hands the verb the IRI,
not the bare number, as `part_number`. The served shape check (`unknown_part`) refuses it. Fixed on
#57 at 9ba26b68 (IRI reduced to its last segment; mutant measured red). It is not served.

FRACAS stays unresolved until a build containing 9ba26b68 and Lane 1's :242 line (739b0c74) is served;
with both, the expected disposition is `no_failures_recorded` (census row `refused`).

## Zombie, not cancelled

A `supervisor_query_job` run (72ad085e) has been STARTED since 13:58:48Z at the step execute_subtask
with no event after it (28+ min at 14:26Z, still STARTED at 14:33Z). It holds one of two slots; my
first FRACAS attempt queued behind it and a second client timed out. Cancel is Chris's call.

## Namespace PR (lane/saf-ns-188b)

Engine S declares HAZ-, CSI-, MIT- on its resolveInstance provider row only; WO- is deliberately
undeclared (control: a WO- fuzzy match is kept, a HAZ- one refused). The consumer on master is
`declared_id_namespaces` (ontology_service/main.py:2411) feeding `refuse_cross_namespace`
(instance_resolution.py:591, applied at main.py:2657). engine-o's HAZ- exclusion IS on master, so the
cross-engine HAZ-1004 test is un-skipped: exactly one candidate with the declaration, three without.
