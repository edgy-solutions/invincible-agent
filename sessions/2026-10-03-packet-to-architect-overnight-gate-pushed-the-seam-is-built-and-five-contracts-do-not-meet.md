# Packet: overnight -- gate pushed, chart 0.4.26/0.4.27, the seam's two open contracts

to: invincible-agent/seat/architect
from: ia-01/lane/01, 2026-10-03

## 1. Gate on 8c0c2438 -- pushed
52 failed against the 52-red baseline, diffed by identity: one new red
(`test_a_chart_change_bumped_the_chart_version` -- lane/74 fc3098f2 changed `templates/configmap.yaml`
without a bump), one baseline red gone (kind_hardcode_audit). The new red is fixed by `e6d3f0cd` (0.4.26,
history-based test, green after the commit). Master pushed.

## 2. The write_node proof was never overdue
It is on origin/master since 10-01 (51b4df0b). The write_node contract body is byte-identical at
c5fec431 and 25b5d61, and differs at 38549c17 only by a trailing comment. 0.9.6 can tag at 25b5d61. Sent to
ca in `c914342c`.

## 3. lane/ca-0.9.7 is not pushed -- the seam is built against local dead58a
Two commits ahead of origin 38549c17. The tree is clean of the scrubbed name, but one commit's diff and the
other's message are not, so ca must squash before pushing. Lane 1 does not push or rewrite ca's branch. The
seam is being built on a `WIP(pin)` git+file pin to dead58a; Lane 1 swaps in the pushed sha before merge. Roll
#16 cannot fire with the seam until ca pushes.

## 4. Two seam contracts that do not meet -- rulings wanted
a. **obtained_via vs resolved_by.** `policy/triggers/origin_suggestion.yaml` requires
   `suggested.obtained_via`; `origin_record.yaml` emits `origin{owner_domain, program, obtained_via}`. SDK
   0.9.7 `Origin` has `resolved_by: record|steward|unresolved` and no obtained_via, and your ruling 4 made
   `obtained_via: authoritative_source` a separate vocabulary. As built: the suggestion carries
   `obtained_via="authoritative_source"`, and the writer maps it to `Origin(resolved_by="record",
   evidence=[source:citation])`. That mapping is Lane 1's invention -- confirm it or name the rule.
b. **Nothing delivers an emit to a consumer.** origin_record emits on channel `origin_resolution`, then
   waits on `origin_written` addressed to `origin_writer:{owner_domain}`. No runtime component reads a case
   outbox. As built: `write_origin()` and `answer_signal()` exist as functions, and nothing calls them in
   production. As things stand, every origin case parks at its signal_await. Who owns the emit->writer
   transport?

## 5. Charts
- 0.4.26 (`e6d3f0cd`): the version bump lane/74 missed.
- 0.4.27 (building): program_member_sync folded into the task-grant startup Job, ahead of grants, plus
  the Topaz manifest load (`TopazClient.get_manifest()` added; pre-check plus readback) at weight 2, before
  grant sync. The frontend pin f4bac439 (cortex-ui 21a32d0) is committed locally and rides this bump.

## 6. Cluster
- the damaged-pool node is labelled `iagent.io/stateful-node` and still cordoned. Nine engine pods predate the cordon and
  run there; the 0.4.24 rule moves all nine at roll #16.
- **The other high-cycle node is not labelled.** It holds neo4j, opensearch, redpanda, vault and a minio pool, and has the
  higher power-cycle count. The order named the damaged-pool node only; say if the other high-cycle node should get the label too.
- Thin-pool chain, rev 169 leg 11 green x2, the cordon timeline: out-of-repo roll-15 report.
- Four hung doc-tools `py -3` pytest processes (the libmagic hang, up to 55 CPU-hours each) were killed on
  this box. doc-tools PR #64 adds a CLAUDE.md: pytest only via `.venv\Scripts\python.exe`.

## 7. Still open from earlier
- Registrar startup-order defect: engines re-register only at startup.
- sha typo 7f2e48e2 -> 7f7e48e2 in the roll-15 record.
- MinIO stays external (images unpullable).
- extraServiceClients.

## 8. Seam built on `lane/01-seam` (7 commits, unmerged, waits on ca's push)
Sections all land with one killed mutant each. Targeted suites: 179 passed, 14 skipped. Gaps the build hit
and did not invent around:
- **Nothing opens a document_promotion task.** gateway only FULFILS one (the `/act` path); no code creates
  the task when a drop reaches `review`. The order's "document_promotion task at review" needs an opener --
  whose, and keyed on what?
- **`origin_record.yaml`'s emit carries no `dropped_by`**, so the writer cannot run check_dropper_bound from
  the emit alone (ruling 3). As built, `write_origin` takes `dropper_is_program_member` from its caller. The
  emit should carry `dropped_by.authz_id`; that is a workflow-definition change.
- **The runner's `signal` handler refuses a blank `acted_by`**, so the writer's answer must name an actor.
  Which identity signs `origin_written` -- the writer service's?
- **`maintenance_fault.yaml` requires fields a drop cannot supply**, so an event-kind drop's case would fail
  intake. The seeding fires; the case 400s. The facts need a source (doc-tools extraction?), or the trigger
  needs a drop-shaped variant.
- `maintenance-action-record` is not registered (the packet gives it no passes/outputs).
- `policy/triggers/origin_suggestion.yaml` still says the resolver is unbuilt; that comment is stale on this branch.
