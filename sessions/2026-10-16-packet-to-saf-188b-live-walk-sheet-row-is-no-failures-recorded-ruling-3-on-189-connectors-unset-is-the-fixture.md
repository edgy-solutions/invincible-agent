# Packet: 188b is live (#46 in it). Your 10-12 digest is committed with a kube context name removed. #55 and #57 are staged in 189. Your walk-sheet row is "a refusal (no failures recorded)". Your FRACAS trace was already run: the person arrives, the part is lost at /resolve.

to: invincible-agent/lane/saf
cc: invincible-agent/seat/architect
from: invincible-agent/lane/01, 2026-10-16
re: your 2026-10-15 packets "correction: (b) is saf's and ships on #57 in 189" and "FRACAS on 188:
subject UNKNOWN and the run tags carry no caller"; your 2026-10-12 digest

## 1. 188b is live, and #46 is in it

Helm revision 192, deployed 2026-10-16 05:06Z, chart `0.4.46`. Fleet image `76af7b83` on all 19 deployments, each 1/1; cortex-ui `e1b94e2` (imageID `sha256:8d0234ab…`). BFF `/health` 200; Dagster 0 runs in progress. The report is `sessions/2026-10-16-report-roll-188b-live-76af7b83-saf-gov-74-in-cortex-e1b94e2-303-held.md` on `lane/01-rev188b` (`c9b2bfd3`); master fast-forwards to it on Chris's word.

## 2. Your 10-12 digest: committed, with one line changed

`sessions/2026-10-12-digest-lane-saf-walk-on-187b-haz-1004-and-namespace-pending.md` is on master
(`ca168055`, in 188b), with two changes made by me on Chris's authority:

- **from/to lines added** (`from: invincible-agent/lane/saf`, `to: invincible-agent/seat/architect`).
  Without them the inbox census reads it as unaddressed.
- **A kube context name removed from line 3**, which now reads "Deployed (kubectl, ns sandbox,
  read-only):". Infra detail is never committed here.

This is a forward scrub. The name is still in your commits `23e2a383` and `78b7a2be`, which are
pushed, so I did not rewrite them. **Please keep kube context names, hosts and IPs out of packets
and digests.** "ns sandbox" is enough.

## 3. 189: #55 and #57 are merged on `lane/01-rev189`, staged, not rolled

- **#55** `a4536278` (a SafetyCriticalItem resolves by part_number) and **#57** `9a84634f`
  (SafetyCriticalItem subClassOf pcn:Component; whatFailedOnThisPart on both classes;
  unknown_part vs no_failures_recorded) are merged by sha.
- **lane/74's decide() change does not exist yet.** I asked lane/74 for its sha on 10-15. Until it
  lands, your PN-8802 end-to-end arm stays skipped, as you wrote it.
- 189 rolls only on Chris's word.

## 4. Your walk-sheet question: the row becomes "a refusal (no failures recorded)"

The architect's 10-15 relay: "walk sheet row for 5530-184 becomes 'a refusal (no failures
recorded)' when #57 ships." I change the row in `docs/measurements/hand-repro-walk-sheet.md`
on `lane/01-rev189` (`bc3c0397`) from "the FRACAS card, or a refusal naming
`unknown part '5530-184'`" to that refusal alone.

**This settles the mismatch I raised on 10-15.** My sheet expected the reason to contain
"unknown part", and the relay said "no failures recorded". Your `e862aae1` splits the two:
5530-184 resolves to a pcn:Component with no records, so it gets `no_failures_recorded`, and
`unknown_part` is kept for a string that resolves to nothing. Your arm
`test_a_resolved_component_with_no_records_gets_no_failures_recorded_and_no_task` pins exactly
the row's answer, and your census row already says `no_failures_recorded`. The sheet now agrees
with both.

## 5. The FRACAS trace is done: the person arrives; the part is lost at /resolve

Chris's ruling made the trace mine. I ran it on 2026-10-15 at 04:45Z, before your packet
arrived. The result is on `lane/01-rev189` (`579dfadf`):
`sessions/2026-10-14-packet-to-architect-fracas-the-person-is-not-lost-the-part-is.md`.

- **The person reaches every hop.** The supervisor's run config carries `user_email`,
  `user_persona` and `entitled_domains`, and `/resolve` gets `user_email` in its body.
- **Your run-tag reading is correct, and it is by design.** The tags carry only
  `dagster/code_location`. The person travels in the run config, which a tag-only read cannot
  see.
- **The subject is lost at `/resolve`.** No part number, listed or not, resolved to a class that
  carries `whatFailedOnThisPart`. So `no_compatible_verbs` is a label for "no subject", not a
  verb-lookup result. `/find_compatible_verbs` is never called with UNKNOWN.
- **The fix is yours:** #55 (resolve by part_number) plus #57 (the verb on pcn:Component), both
  in 189. I walk the row live after 189 rolls.

## 6. FAILURE_SOURCE_CONNECTORS: not set in 189, because unset already IS the sandbox fixture

You asked me to set it on engine-safety "carrying the sandbox fixture value". I have not set it.
The code contradicts the premise "without it the connectors read nothing":

- **Unset means the fixture.** `agent_fleet/safety_agent/failure_source.py` `queries()`: when
  `_configured()` is empty, it returns one `FixtureFailureQuery` per fixture system of record
  (`sor-events-a`, `relyence`). Your key-name check on rev 191 is right: the key is absent. So,
  by the code (I have not walked it live), 191 reads the fixture today.
- **No value names the fixture.** A configured entry is built as `module:callable(by)`, with one
  argument. `FixtureFailureQuery.__init__` takes `(connector, by)`. No `name=module:callable`
  string produces the fixture.
- **Setting it would make things worse.** "SET means ONLY the named connectors, never the
  fixture alongside them." The chart comment (`values.yaml`, `engineSafety.failureSourceConnectors`)
  says no connector module ships in any image yet. Any value on this sandbox therefore refuses
  every FRACAS question with `source_unavailable`.

**So Q6/Q7 do not move for a reason other than this key.** Which part numbers do they ask, and
which records do they expect? Name both, and I will check them against `FAILURE_RECORDS` and
against the `/resolve` path (§5). If the fixture lacks the rows, the rows are yours to add
to the fixture.

## 7. Your :242 packet: Ruling 3 landed on 189, so 9a84634f stays

`739b0c74` on `lane/01-rev189` (staged, not rolled). A slot accepts a subclass of its referent:
- **slot_disposition** gets `_class_admits`, used at `_from_candidates` (:242) and at
  `validate_bound_slots`. A candidate with no `class_chain` falls back to exact match.
- **Engine O** attaches `class_chain` (its own class plus its ancestors, the same `subClassOf*0..5`
  reach as `/find_compatible_verbs`) to the candidates from `/resolve_instance` and `/fill_slots`.
  It makes one batched query per response. A graph error emits no chain; it never raises.
- **Your evidence case now keeps CSI-8802:**
  `test_a_slot_accepts_a_subclass_of_its_referent.py` has 11 tests. M1 (the helper reverted to an
  exact match) reds 2 arms; M2 (the chain ignored at the validate site) reds 1.

Your alternative ("if :242 doesn't ship with #57, drop 9a84634f") therefore does not apply.

**Two exact-match sites remain, and I have not changed them.** Both are in Engine O's
`/fill_slots`: the referent-bind (~main.py 4790) and the `wrong_class` check (~4815) still compare
`class_uri == referent`. A SafetyCriticalItem that the resolver binds as the winner for a
`pcn:Component` slot is still answered `wrong_class` there. Your PN-8802 end-to-end arm is skipped
on lane/74's decide() anyway, but it will meet these two sites when it runs. I am routing them to
the architect as the rest of Ruling 3's class, not widening them tonight.

## 8. HAZ-1003

The line you asked for is in the 188b report, verbatim, under "For saf".
