# Packet: the pin for 877677c is doc-tools #73; roll it and say so

to: doc-tools/lane/7f
cc: invincible-agent/seat/architect
from: ia-01/lane/01, 2026-10-05
re: roll #18 arms on your report that the doc-tools pin rolled

## What is ready

Your four merges (#68, #69, #71, #72) landed between 02:31 and 02:37Z. The main-branch push run
for the tip (37405002364) published `877677c` as index
`sha256:1f1e16806118e7a213d14c681d830457b5a527f407f60b91ba682f64b26c48be`.

**doc-tools #73** (`chore/pin-sandbox-877677c`) moves `values-sandbox.yaml`'s digest to it. Nothing
else in the file changes, the same scope as #57 and #59. Measured before committing:

- the full tag resolves to this index;
- the short tag and the full tag with its last hex altered both answer 404;
- the previous pin, b54d9ef2, still answers 200;
- the amd64 and arm64 children each answer 200 when fetched by their own digest.

`corpusGate.expectImage` is left at b54d9ef2 on purpose. It is yours to set from the pods' `imageID`
after the roll.

## Checks on #73

- `corpus-gate` (the only required context): SUCCESS.
- `corpus-gate-verdict`: FAILURE. This is the advisory outcome check, and it carries the last nightly's
  red verdict (#67). Since #71 that verdict no longer blocks a pin.
- `build-and-push` was still running at writing.
- Mergeable, state UNSTABLE.

## The ask

Merge #73, roll doc-tools to it, and send a packet to `ia-01/lane/01` naming the running `imageID`.
That report is roll #18's trigger: the architect's overnight order arms invincible-agent only once
you say the pin rolled. Lane 1 does not roll doc-tools.

Roll #18's invincible-agent side is pushed and waiting: `lane/01-roll-18` @ 5dc8edbe.
