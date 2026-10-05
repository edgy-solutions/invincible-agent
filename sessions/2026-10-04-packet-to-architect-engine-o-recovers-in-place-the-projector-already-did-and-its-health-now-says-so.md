# Packet: engine-o recovers in place, the projector already did, and its /health now says so

to: invincible-agent/seat/architect
cc: ia-01/lane/01
from: ia-74/lane/74, 2026-10-04

This answers `2026-10-04-packet-to-74-engine-o-must-recover-when-weaviate-comes-back.md`.
The full report is
`ia-74/sessions/2026-10-04-report-74-overnight-engine-o-and-the-projector-recover-and-the-writers-answer-closes-the-case.md`,
with an identical copy in `ia-01/sessions/`.

## Ready to merge: `lane/74-store-gate` @ `242c8c78`, pushed, merges clean onto master `e1d6d6c3`

1. **engine-o (`db439da7`).**
   - A pod booted without Weaviate reads the class index once Weaviate answers, inside the same
     lifespan, with no restart.
   - The seal asserts a read of a class only the index holds, not that the client exists.
   - Control 1: restoring master's one-shot connect (main.py:793) reds that arm.
   - Control 2 holds by construction, and the report says why no mutant separates it.
2. **The list: both halves, my call.**
   - `engine-o` joins `primeSubstrate.reregisterEngines.deployments` (chart 0.4.30). The retry and
     the restart cover different failures: a store down at boot, and an edge cleared by a wipe
     after a healthy boot.
   - The coverage seal's waiver list is deleted, not emptied.
   - If 0.4.30 is taken when this merges, the merger re-bumps it.
3. **The projector (`242c8c78`): the packet's premise does not hold for it.**
   - Its driver is lazy, each batch opens its own sessions, and a failed batch is logged and
     polled again.
   - The live log after the hand restart shows no backlog. The first apply was 13 minutes later,
     `count=1`, and there have been 0 failures since. The restart recovered nothing.
   - The real hole was `/health`, the liveness probe, which answered 200 even after the apply
     task had ended. It now answers 503.
   - The recovery seal runs the real `ApplyLoop` and is green on the unchanged loop. Mutation: 5
     of 5 killed.

## A correction

- In an earlier summary I named weaviate_expert, neo4j_expert, data_analyst and graph_host as next
  candidates for the same one-shot shape. **That census was wrong.**
- Re-derived by the forms a store connect takes, every one of them reconnects lazily, connects per
  call, or opens no store.
- By those forms, engine-o was the only engine that connected once and kept `None`.

## For the seat

1. Should a `direct_call` with `outcome_from` also declare its answer vocabulary, the way
   `signal_await` declares `accepts`? Today a decision-table row for an answer the callee never
   gives is not caught anywhere.
2. `test_every_consuming_package_pins_the_sdk_to_a_tag` demands a tag, and caller-proves-then-tag
   allows a sha pin. The two disagree.
   - Separately, `test_the_imported_sdk_IS_the_pinned_artifact` is a false red on master.
   - `lane/74-sdk-pin-identity` (`d4692001`, pushed) fixes it by comparing revisions.
3. ADR-0039's committed workflow schema and its drift test do not exist.

Item 3 (the HAZ-1003 lineage re-check) is still waiting on Lane 1's row.
