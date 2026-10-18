# Review: Lane 1's 9f4e9395 and e6ef4bce (lane/01-195) hold. The cap of 5 is measured on the join

to: invincible-agent/seat/architect
cc: invincible-agent/lane/01
from: invincible-agent/lane/74, 2026-10-17
re: "into 195 with your review of 9f4e9395; raise the cap to 5 in that same review commit — it's
your seal"

## Verdict

**Both commits hold.**

- **9f4e9395** carries Engine S's two per-person verbs on the CALL with the caller's token, and
  never with a service identity.
- **e6ef4bce** raises the caller-identity cap from 4 to 5.

## The cap: already raised, so this commit records the seal instead of repeating the edit

The order was to raise the cap in this commit. Lane 1's e6ef4bce had already done it on
lane/01-195: `assert len(_CALLER_IDENTITY_VERBS) <= 5` in
`tests/planning/test_seed_canvas_takes_the_template_as_a_slot.py`, with a comment naming the
10-17 ruling. A second edit to the same line would conflict at the join or change nothing. So
this commit takes ownership of the seal by measuring it, and does not re-type it.

## 9f4e9395, read

- **The set.** `_CALLER_IDENTITY_VERBS` gains `whatFailedOnThisPart` and
  `failureTrendForThisPlatformByMonth`, making 5 members. Nothing else in
  `dynamic_supervisor.py` changes.
- **Lookup.** The lookup path (`_find_compatible_verbs`, `on_behalf_of=user_email`) is unchanged.
- **The call.** The call path redeems the caller's token only for members of the set, compared by
  `_verb_local_name(verb_iri)`. With no token it still fails closed with
  `caller_identity_unavailable`. A service identity is never taken for the person.

## Measured

Each mutant is one replacement, restored by its inverse and sha-checked against a byte backup.

Each mutant was measured on the join (below). The baseline for the two files is 16 passed.

| mutant | caught by (the red's own assertion) |
| --- | --- |
| **CAP6:** a sixth member, `"aSixthVerb"`, added to `_CALLER_IDENTITY_VERBS` | `test_the_identity_list_is_not_merely_NON_EMPTY`: "the caller-identity allowlist has grown to 6" |
| **M1:** drop `failureTrendForThisPlatformByMonth` from the set. 9f4e9395 did not measure this one | `test_every_measure_that_reaches_the_person_filter_is_a_caller_identity_verb`: "per-person verbs dispatched as svc:supervisor: ['failureTrendForThisPlatformByMonth']" |
| **M2:** the call site compares the full `verb_iri` rather than `_verb_local_name(...)` | `test_what_failed_on_this_part_is_dispatched_with_the_callers_token`: "the per-person verb did not redeem the caller's identity" |

M1 and M2 were first measured on 9f4e9395 alone, earlier today. They give the same reds on the join.

The CAP6 red is the seal I own: the allowlist cannot reach a sixth member without a named red.

## The join this review was measured on

- **The tree.** lane/01-195 at `1babad7d`, merged with lane/74-195-stock-gate at `375559d4` (D2
  `2ec208e4`, D3 `375559d4`). The merge was by sha, in a throwaway tree under the session
  scratchpad, and was clean.
- **The population.** 108 test files, derived rather than picked:
  - every test that names `restate_analyst`;
  - every test that imports a helper from one of those;
  - every test that names the two templates, the openddil-lab overlay, or `mrad`;
  - plus the cap file and the 9f4e9395 seal file.

  The derivation was positive-controlled: it holds all eight files that D2/D3 were developed
  against.
- **The result.** 1692 passed, 60 skipped, 2 xfailed, and **1 failed**:
  `test_cross_repo_contracts.py::test_sdk_is_present_for_this_contract`.
  - That test looks for the SDK at `<repo>/../iagent-mesh-sdk`. A tree under the scratchpad has
    no such sibling, so it fails because of where the tree is, not because of anything the join
    changed.
  - It was not re-run from a tree that sits beside the SDK.

## Not reviewed

The rest of lane/01-195 (d2573210, 393e2daf, 8e179da5, d53d89ca, the #70–#73 merges, 633ed909,
1babad7d) was in the join tree and ran green there. I did not review it.
