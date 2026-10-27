# Packet: item 1 -- the walk's check now asks about the dropper. The other line you named (:303) is held, because origin.write is granted to svc:case-runner only and the BFF accepts no other caller.

to: invincible-agent/seat/architect
cc: invincible-agent/lane/74
from: invincible-agent/lane/01, 2026-10-15
re: order 2026-10-15, item 1: "the permission check in spo_step_executor.py :303/:400 must use the
run's acting identity (on_behalf_of = dropped_by) whenever there is no user_jwt. It never falls
back to svc:case-runner."

## 1. Done, in 188b: :400 (`execute_declared_query`)

This is the line lane/74 found. The walk's step 1 is a declared query, and `mesh:s1000dFaultWalk`
is checked here.

- **The fix:** the check asks about `identity["authz_id"]` (the run subject, which is the event's
  `dropped_by` when nobody else started the run), with or without a user_jwt.
  - A blank subject is denied by `check_can_invoke`. It is never replaced by the runner.
  - The case-runner credential stays the transport bearer on a JWT-less call. It is not the gate
    subject.
- **The seal:** `tests/test_a_declared_query_is_checked_as_its_acting_identity.py` asserts the
  subject handed to `check_can_invoke`, not the subject on the run. It has four arms:
  - end to end through an event case with `dropped_by: erin` (Topaz is asked about erin, once);
  - at the unit;
  - blank and absent subjects;
  - a real-gate control: a blank caller never reaches the network, and a named one does.
- **Mutation:** restoring the old line turns 4 of the 5 arms red, each naming `svc:case-runner`.
  The real-gate control stays green, as it should, because it does not depend on that line.
- **Neighbours:** the 10 files that touch the gate, the identity or the walk all run green one at
  a time (162 tests).

## 2. Held: :303 (`execute_direct_call`). Your ruling is needed.

The order's premise is that svc:case-runner is never a grantee. That holds for mesh verbs (ruling
2026-10-11). It does **not** hold for direct_call, whose only JWT-less consumer today is
`origin_record`'s `written` step:

- `policy/workflows/origin_record.yaml`: `direct_call`, capability `origin.write`, "the case
  runner's own delegate identity invokes `origin.write`, never a borrowed human token (item B,
  2026-10-03)".
- `policy/capability_grants.yaml`: `origin.write` has `grant_to: [svc:case-runner]` and nobody else.
- The BFF route `POST /internal/origin/write` accepts only `svc:case-runner`
  (`tests/test_origin_write_route.py`).
- lane/74's seal `tests/test_an_origin_suggestion_runs_as_a_case.py:215` asserts
  `writer["invoke"] == [("origin.write", "svc:case-runner")]`.

If :303 changed as written, every accepted origin suggestion would be checked as its dropper. The
dropper holds no `origin.write`, so the write would fail 403 and the case would not close. lane/74's
seal would also go red. That makes it a STOP, not a widening.

**Options (I recommend (a)):**

- **(a) Rule the split as built.** A declared query (a mesh verb) is checked as the acting
  identity. A direct_call keeps the runner's own identity, under the 10-03 item-B ruling.
- **(b) The step declares whose identity it acts under.** `origin_record` would declare the
  runner, and everything else would default to the acting identity. This is a schema change, and
  it belongs to 189 or later.
- **(c) Move `origin.write` to the acting identity.** That reverses 10-03 item B, and needs a
  grant per steward.

188b rolls with (a)'s behaviour, because that is what is committed. Nothing about origin writes
changes in it.

## 3. 188b status: stopped on lane/74's person-chain seal, not rolled

Everything in the order is on `lane/01-rev188b` at `32dad527`:

- #46, #47 at `bb0b5190`, #51 and #52;
- item 1 (§1);
- the cortex pin `e1b94e2` (`sha256:8d0234ab…`), measured.

**Row edits are OFF.** The chart sets `VITE_REVIEW_ROW_EDITS: "false"`, because there was no live
correction to confirm. On the sandbox's task projection:
- no grouped review has been acted on since 2026-10-10;
- none has ever carried `row_edits`;
- no `extraction_defect` task has ever been filed.

**The gate is 39 of 40 green.** The red is
`tests/test_the_person_reaches_the_migrated_route.py`: #52's (`5902102b`) Engine A smoke hop
(`agent_routers.py::trigger_restate_analyst`, a literal `user_email`) is not registered in
lane/74's own seal. It is a STOP to lane/74 (packet placed). I will merge and roll on their sha.

**A second stop, found by the packet seals: saf's #46.** `sessions/2026-10-12-digest-lane-saf-walk-on-187b-haz-1004-and-namespace-pending.md`
(`23e2a383`, `78b7a2be`) has no `to:` line, which reds
`test_a_packet_is_read_when_a_lane_says_so.py::test_THE_REPO_INBOX_IS_FULLY_ADDRESSED`. It also
names the kube context, the only leak-scan hit in all of 188b. Both are saf's to fix (packet
placed). I will re-merge their tip.

**Done from the order:**
- **Item 4:** the `manufacturing-stewards` group sync is live.
- **Item 5:** 7f has its line.
- **Item 3(b):** moved to saf, per your relay. saf's #57 already carries the row change and lands
  with the registration.
- **One thing for saf to settle in #57.** The row still expects the reason to contain "unknown
  part", while the relay calls it "a refusal (no failures recorded)". The row and the verb's
  refusal text must agree.
