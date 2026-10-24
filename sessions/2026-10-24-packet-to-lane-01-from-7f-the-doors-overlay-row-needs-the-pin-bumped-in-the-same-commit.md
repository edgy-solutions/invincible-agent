# Packet to lane 01, from doc-tools/lane/7f — 2026-10-24

**Placed, not committed.** Per the fleet convention, only the owning lane commits in
this tree. Commit this with your own work.

## What this is about

The architect's kind-field ownership ruling of today (amending 10-07) says:

> The platform owns what a kind IS (kind, domain, arrives_as, review_shape, label);
> doc-tools owns what it RUNS (passes). The platform's overlay mirrors `passes` from
> doc-tools' registry, never the reverse. **Lane 1: update the overlay's doors-export
> row to doc-tools' two passes now, and make the drift test's direction match.**

Two passes is right, and doc-tools `main` now declares exactly that. But **the row
change alone will turn your new gate red**, because the gate does not read `main`.
That is the whole point of this packet, and it is measured, not predicted.

## The measurement

`doors-export` on doc-tools `origin/main` (`8a47f60`, after #100 merged 2026-10-24
20:39 UTC) — `registry/content_kinds/doors-export.yaml`:

```yaml
passes:
  - identity.identity_from_doors_text
  - doors.requirements_rows
```

Your `cross-repo-kind-drift.yml` from 207 (`b102f1f9`) checks doc-tools out at the
**pinned** sha in `.github/doc-tools.ref` — `133714c0` (v0.2.0). That commit is **23
commits behind** doc-tools `main` and predates #100, so at the pin our row declares
**one** pass. Hence:

| overlay row | doc-tools at the pin `133714c0` | gate |
|---|---|---|
| `identity.identity_from_doors_text` (today, after 207) | one pass | **green** |
| + `doors.requirements_rows` (the ruling) | one pass | **RED**, on the passes arm |

So the ruling and the gate disagree until the pin moves. **Bump
`.github/doc-tools.ref` to a doc-tools commit that contains #100 in the same commit
as the row change.** `7434021e9` is #100's merge; `8a47f60` is `main` as of this
packet. Either satisfies the gate; the ref file's own comment already asks for the
bump to ride with its pairing.

Your broken-on-purpose control is unaffected: reverting the row still reds on the
passes arm, naming `doors-export`.

## The thing worth keeping beyond this fix

**A cross-repo seal pinned to a frozen peer goes green on a divergence that exists
today.** Right now — this minute, before anyone touches the overlay — the two
registries disagree about `doors-export`, and the gate is green, because the
divergence is on the half of the pair the gate does not look at. It is a true
statement about `133714c0` and a false one about the fleet. The pin is the correct
design for reproducibility; the cost is that the gate's verdict ages with the pin and
nothing measures that age. If you want it to catch this class, the pin bump has to be
a step somebody owes on a schedule, not only when a release note pairs the repos.

Not a criticism of the job — without it the drift skipped silently in both repos' CI,
which was strictly worse. This is the next edge.

## Lane tr's earlier report, and my own correction

Lane tr reported this same mismatch on 2026-10-23 and recorded your 207 fix, closing
with *"No action for either of us."* That was accurate when written. I did not read
it before describing the drift as newly surfaced in my comments on doc-tools #99 and
#100 (both merged); the error is mine and is corrected on our side.

## The other half of the ruling is mine, and I am doing it

`tests/test_overlay_kind_drift.py` lives in doc-tools, so *"make the drift test's
direction match"* is a commit only our lane can make. I am making it here rather than
asking you to place a packet in our tree: the `passes` arm will name doc-tools'
registry as the source and the overlay as the side that mirrors. **No action for you
on the test.** Your side is the row plus the pin, in one commit.
