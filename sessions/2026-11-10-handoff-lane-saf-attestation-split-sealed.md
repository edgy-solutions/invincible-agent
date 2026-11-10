---
to: invincible-agent/lane/saf
from: invincible-agent/lane/saf
date: 2026-11-10
---
# Handoff

This is the newest saf handoff. The running log is `sessions/2026-10-25-handoff-lane-saf-after-the-architect-rulings.md` (rounds 33-35 on master; rounds 36-38 ride on the ticket-identity seal PR #330 and land with it). It is a separate file so this PR and #330 do not both append to the end of one file.

## Round 39 - the attestation split sealed (Job 22)

Ruling: "seal the attestation split: under `self` the dropper promotes; under `second_party` exactly the excluded ids are refused; a malformed block is a 503. One PR."

The split is on master (`src/iagent/promotion.py`: `attestation_for`, `attestation_block`, and the act's served-block read). `tests/test_attestation_is_declared_not_constant.py` already pins the cases; the new `tests/test_the_attestation_split_is_sealed.py` pins the SET: second_party refuses exactly the excluded ids over a population that differs only in not being listed (4 excluded-set shapes, both directions); exactly one mode refuses, found by behavior; 17 malformed block shapes x 2 actors are 503 with nothing written; a rejection is not stopped by a malformed block; malformed declared values are 503 at filing and at the read; a legacy task with a malformed row is 503, not the default. Mode names come from `promotion.ATTESTATION_*`, excluded ids from `attestation_block`; ids are synthetic.

The 503 is not a new refusal site (`attestation_undeclarable` exists at two sites); nothing to classify, the refusal ratchet stays green (24 passed).

Mutants (text mode, utf-8, applied once each, restored with cmp): mode guard dropped, promotion dropped (never refuses), prefix match (one too many), last excluded id lost (one too few), act 503 to 200, act 503 to 500, filing 503 to 500, excluded-list type check dropped: all exit 1.

Decisions for the architect: (1) under `second_party` an excluded id is refused only on PROMOTE; a rejection by the dropper is allowed (pinned by the older file, kept). Recommend keep. (2) `_declared_attestation` still returns None (gov names the row); the seal reads through that seam, so it keeps holding when the row lands. Recommend no change here.
