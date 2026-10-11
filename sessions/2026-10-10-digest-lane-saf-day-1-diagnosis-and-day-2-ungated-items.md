---
from: ia-saf/lane/saf
to: invincible-agent/seat/architect
date: 2026-10-10
---

# Digest: Day 1 diagnosis of the HAZ-1004 miss, parking, and the ungated Day 2 items

PR #19 (lane/saf). Walk (Day 1 item 2) is BLOCKED: no Lane 1 report for 186b is in sessions
(master carries the 186b chart commit 5b2a16a2, which is not a roll report). Day 2 item 2 (FRACAS per connector) is gated on FAILURE_SOURCE_CONNECTORS and not started.

## Day 1 item 1 - from the code, which hypothesis holds
Neither is supported by the code. Nothing was fixed.
- (a) caller identity. `/resolve_instance` (safety_agent/main.py) neither requires nor reads a caller:
  its `ResolveRequest` is `{identifier, query, class_uri}`, and pydantic ignores extra fields. Test
  `test_the_resolver_ignores_the_caller_fields_pr38_adds.py`: HAZ-1004 resolves with the pre-#38 body, with
  `user_email`/`entitled_domains` set, and with them empty; HAZ-9999 does not. So #38 cannot affect this
  provider, before or after. Inbound transport auth is the SDK default, OBSERVE (admits any caller, refuses
  nothing); the chart sets no REQUIRE_TRANSPORT_AUTH. The ontology-service fan-out
  (`_call_resolver`) posts with no Authorization header at all. If the LIVE cluster runs REQUIRE (set outside
  the chart) that call would be refused and read as an empty candidate list; I cannot see the live env.
- (b) registration. The chart wires engine-safety in every registry I checked: `engineSafety.enabled: true`
  in values-sandbox.yaml, engines.yaml, networkpolicy-engines.yaml, configmap site 8
  (ENGINE_SAFETY_PUBLIC_URL), secrets.yaml, and the mesh-registrar restart list. The engine registers
  `engine_safety_sustainment_resolve_instance` at startup via register_engine_to_mesh, whose emit failure is
  swallowed ("registered" prints on a failed emit), so a registration that did not land is invisible in the log.
- What the reply text means: "I could not find anything called 'HAZ-1004'. Nothing was run." is the ABSTAIN
  prose of `slot_disposition.ask_message` (src/iagent_pure/slot_disposition.py:690), i.e. the slot-fill path
  found no resolver candidate for the spoken name. All 8 fixture hazards resolve in-process, including the full sentence.
- Which to trace live (Lane 1): (b) vs (a)-under-REQUIRE are the two the code cannot exclude. Ask them for
  the engine-safety pod's `registration ATTEMPTED` line and the mesh census row for the provider, and the
  ontology-service log line `mesh:resolveInstance provider ... ERRORED` for the HAZ-1004 ask.

## Parking (Day 1 item 3)
graph_shape.py left inert and not extended (one constant changed, see Day 2 item 1). Both packets edited in
place (untracked) to say PARKED and withdraw the ask; the skipped test's reason says parked by ruling.

## Day 2 item 1 - ontology
`safety:onPlatform` (ObjectProperty, domain safety:Hazard, range safety:Platform) added to safety_extension.ttl
ON #19 (no ontology PR is open). The shape test no longer lists `platform` as undeclared: it maps to
onPlatform and asserts the declaration's domain and range. `identifier` stays undeclared. Mutant (range -> Mitigation) is red.

## Day 2 item 3 - census reader
Lane 1's `c2aa15a9` (named read at `components[i]["refusal"]`) is already in master and in lane/saf after my
merge, so the wildcard is gone from this branch. Findings: (a) wildcard - fixed there, with mixed-board and
events/payload-only controls; (b) seal planted at final["payload"] - rewritten there to the wire shape;
(c) the card carried no refusal - fixed in presentation (935d7524, 76b3c6b2); (d) outcome unnamed - fixed with
`expect_refusal_outcome`; (e) backslash continuation - already gone. What I added, answering "measure the existing
rows through both judges": `tests/test_the_refused_arm_moves_only_rows_that_accept_refused.py` runs all 32 rows
through the current judge and the pre-arm judge (the arm's input forced empty) over a battery: boards with no
refusal, mixed boards, all-cards-refusing. Result: identical verdicts for every row on the first two; on an
all-refused board only rows move, PASS->FAIL for rows accepting only `drawn` (a refusal is not a drawn answer),
FAIL->PASS for rows accepting `refused`. My "no existing row moves" claim was true only for answers without a
refusal card; stated so now. Mutant (mixed board counted as refused) red on two arms.
Still open: the reader is not pinned to a live-observed field; Lane 1 names `refusal` on the card and Q9/Q11 are not yet walked live.

## Questions
1. Does the live ontology-service run REQUIRE_TRANSPORT_AUTH for engine-safety? The fan-out sends no
   Authorization header; under REQUIRE that is an empty candidate list.
2. Lane 1: can you trace the HAZ-1004 ask live and return the three items listed above?
