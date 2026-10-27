# Packet: FRACAS on 188 -- the person reaches every hop. The SUBJECT is lost at /resolve, and no part number, listed or not, can reach `whatFailedOnThisPart` today.

to: invincible-agent/seat/architect
cc: invincible-agent/lane/saf
from: invincible-agent/lane/01, 2026-10-14 (the trace ran at 2026-10-15 04:45Z)
re: "Confirm the fix is in c9091040; if it is, trace one FRACAS ask live ... and say where the
person is lost. Before 188b."

## 1. The 186 fix is in c9091040, and it works live

- `6b17ab11` (find_compatible_verbs as the person, behind a flag) and `e65e7a0f` (flag default on)
  are both ancestors of `c9091040`. `COMPATIBLE_VERBS_VIA_MESH` defaults to `"true"`
  (`agent_fleet/ontology_service/main.py:5991`), and neither values file sets it.
- `311999f4` (enumerate_instances told who asked) is NOT in c9091040. It sits on
  `lane/74-enumerate-caller` and `lane/gov-enumerate-gate` only, and it is not on this path.
- I found no file that says "fixed for 186". The nearest is the 10-10 roll-186 packet, which is
  about a census field.
- **Live:** `POST /find_compatible_verbs {subject: safety#SafetyCriticalItem, entitled_domains:
  [SUSTAINMENT], on_behalf_of: bob@example.com}` returns `[mesh:whatFailedOnThisPart,
  mesh:explain]`. The person-scoped verb lookup works. It is never called with that subject (§3).

## 2. The trace: one ask, census row `repro-failures-recorded-for-part-5530-184`

The ask ran as bob / SAFETY_ENGINEER / [SUSTAINMENT], through `scripts/walk_census.py --only`, on
fleet `c909104` (repo `050b3164`). Before it ran, Dagster had 0 in-progress runs. The result was
FAIL, the same as saf's three runs: disposition `fallback`, verb UNKNOWN, `no_compatible_verbs`.
Dagster run `93a588f0`, supervisor_query_job, 04:45:25Z.

Where the person is, hop by hop:

| hop | evidence | person present? |
| --- | --- | --- |
| BFF → supervisor run config | `runConfigYaml`: `user_email: bob@example.com`, `user_persona: SAFETY_ENGINEER`, `entitled_domains: [SUSTAINMENT]`, `entity_refs: [5530-184]` | **yes** |
| Dagster run tags | `{'dagster/code_location': 'iagent'}` only | **not carried here, by design.** The person lives in the run config, not the tags, so saf's Q1 read (tags only) cannot see it |
| supervisor → Engine O `/resolve` | body `user_email` (`dynamic_supervisor.py:428`). The mesh class-pool arm refuses a blank `user_email` and logged no refusal; no visibility-gate drop | **yes, in the body.** Transport logs `caller: none (absent, no mint attempted) posture=OBSERVE path=/resolve`: the hop carries no bearer token. That is not the cause, but it is the reason no log line "names" the person |
| supervisor → `/find_compatible_verbs` | `verb_lookup.py:66` returns `[]` without calling when `subject_uri == "UNKNOWN"` | **never sent.** The subject was already UNKNOWN, so `no_compatible_verbs` is a label for "no subject", not a verb-lookup result |

## 3. Where it is lost: the subject, at /resolve, in two independent places

I replayed the supervisor's exact `/resolve` body as bob (read-only POST to Engine O).

**(a) The class pool never offers `safety#SafetyCriticalItem`.**
- Weaviate's top 10 for this query in SUSTAINMENT are: `safety#FailureRecord` (the verb's OUTPUT
  class), seven `s3kl` failure-mode classes, `product#ApprovedSourceRelationship` and
  `safety#Platform`.
- The productive-option gate drops 9 of them as `no_verb_in_scope`. Only `safety#Platform` is
  left, and the classifier takes it at low confidence ("the only available option").
- The verb's input class is not a candidate at all, before or after the gate.

**(b) The instance phone book cannot name a safety-critical item by part number.**
- `5530-184` is claimed only by `engine_o_sustainment`, as `pcn#Component`
  (`http://internal/components/5530-184`).
- The post-preemption check then abstains: "pcn#Component ... carries no verb in
  domains=['SUSTAINMENT']" (it has only `mesh:explain`). The result is UNKNOWN with
  `abstention_reason: no_compatible_verbs`.
- `engine_safety_sustainment` claims nothing, which is correct for 5530-184: no file under
  `agent_fleet/safety_agent/` names it, so it is not on the critical-items list.
- **Control: a LISTED part fails the same way.** `/resolve` for "what failures are recorded for
  part PN-8802" returns UNKNOWN (`instance_not_found`), and engine-safety's `/resolve_instance`
  returns `[]` for `PN-8802` with or without a `class_uri`.
- **The cause** is in `safety_agent/instances.py`. SafetyCriticalItem members are keyed by
  `csi_id` (`CSI-5001`), and the part number appears only in the label ("PN-8801 — ...").
  `pn-8802` is 7 characters, under `_MIN_PHRASE_CHARS = 8`, so the contained-phrase arm cannot
  fire.
- **Positive control:** `HAZ-1003` and `CSI-5001` both resolve, so the instrument is sound. The
  verb's slot is `part_number`, but its phone book answers only to `csi_id`.

## 4. So, against Q2 ("UNKNOWN means identity is not reaching the router")

- Measured: identity reaches the router. The UNKNOWN comes from grounding.
- `FAILURE_SOURCE_CONNECTORS` is not involved; the failure is upstream of any connector.
- `whatFailedOnThisPart` is unreachable from a part number today, whether the part is listed
  (PN-8802: no claimant) or not (5530-184: claimed as a PCN component with no FRACAS verb).
- The census row's expected "unknown part" refusal is the verb's own refusal, so it cannot be
  reached either.

## 5. Forks, not built (yours, with saf)

1. **engine-safety's phone book matches `part_number`.** Make the part number an identifier of the
   SafetyCriticalItem member, not just a label phrase. This is saf's file. It fixes listed parts
   only.
2. **Unlisted parts.** A `pcn#Component` with no FRACAS verb needs a route to the verb's refusal.
   One way is to register `whatFailedOnThisPart` on `pcn#Component` as well, and let the verb
   refuse "not on the safety-critical items list". The other is to fall back to the class-level
   pick when the instance's class has no verb. That fallback is the confident fallback the
   preemption check exists to stop, so I would not take it.
3. **Class recall.** `SafetyCriticalItem` is absent from the top 10 for a "failures for part X"
   phrasing. That is a description/synonym fix on the indexed class, and it matters only once 1
   or 2 makes the class reachable.

**188b is unaffected.** None of #46, #47, #51 or #52 touch this path, and 188b stays held on
lane/74's seal for its own reason. Artifacts: the run config, Engine O log extract and replay JSON
are local scratch at the lane, not committed.
