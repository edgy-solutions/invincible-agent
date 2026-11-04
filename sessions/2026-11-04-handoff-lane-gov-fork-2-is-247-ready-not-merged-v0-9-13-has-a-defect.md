# Handoff: lane/gov, 2026-11-04 (fork 2 is #247, ready and not merged; v0.9.13 has a defect)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-11-04

This replaces `2026-11-03-handoff-lane-gov-overnight-list-in-review-train-green-in-tests-security.md`. Fork 12 and the lessons in older handoffs still stand.

## The ruling since (via Chris, verbatim)

> gov: #149; then the refusal-envelope fork 2 (BFF Refusal via SDK PartialRefusal) — PR ready, not merged.

#149 was already merged (`b4b41ad1`) and needed nothing. If that instruction meant something else about it, Chris will say.

## State

| PR | what | state at writing |
| --- | --- | --- |
| #247 `lane/gov-bff-refusal-via-partial-refusal` | fork 2 and the fleet pin to v0.9.13 | open, CLEAN, CI green (Docker builds only). **Do not merge: the instruction and the merge are lane/01's.** |
| #248 `lane/gov-board-fork2` | board moves, two new items | open |
| #221 #223 #224 #231 #233 | the overnight list | merged, each confirmed in master |

Measured at `92ca2699` on master `8a2717e0`, in-process: 7 failed, 3360 passed, 1 skipped, 4 xfailed. The reds are listed with owners in #247's body. Nothing ran live.

## Open forks

2. Merge #247 now, or wait for ca's patch? With the architect, Chris and lane/01. Item `01M6A9QDN1M16XMBNHHWVK9EHJ`.
12. The relay-form detector for the ratchet (carried over). Item `01M6A9QDN19S78PQVCA67NZ9RC`.
26. Three readings on the delegate list, asked of the architect. Item `01M6G57K5VSQVAKPZG029AYEQ2`.

## Waiting on

| for | who | item |
| --- | --- | --- |
| merge of #247, and the decision above | lane/01, Chris | `01M6A9QDN1M16XMBNHHWVK9EHJ` |
| merge of #248 | lane/01 | `01M6JJVP0KKT9HAM99YX2TEDBZ`, `01M6JJVP4ZEWGEENN2P067EBPX` (both only exist once it lands) |
| a patch release with the version fixed, on SDK master | ca | `01M6JJVP0KKT9HAM99YX2TEDBZ` |
| the five person-refusal seals, red since #229 | lane/01 | `01M6JJVP4ZEWGEENN2P067EBPX` |
| the delegate-list readings | architect | `01M6G57K5VSQVAKPZG029AYEQ2` |
| one `topaz_sync` at 0.4.76 or later, then the roll | Chris | `01M6FMQYFY8K233JWP2HXN91ED`, `01M6AJR52DDXSJPFKQ12WG08J3` |
| the gateway's reader for the delegate list, and whether a recorded name is bounded by it | lane/01, architect | `01M6FZQ9TK0F5VQS2E1ERZ927Y` |
| the gauge, read rather than measured until a chart with #213 rolls | lane/01 | `01M6FZQ9ZCBFZCCEGWGFH2HW6G` |
| the remaining `sys.modules` files | lane/01, saf | `01M6FRZ3K5477A0CNFKW1D9BBM`, `01M6FRZ1Z5BNQ9GQ85GY72YRPC` |
| the remaining kind-audit sites | lane/74, lane/01 | `01M6FRZ2PKYJKHX9FW4W18T24A`, `01M6FRZ3QPBAN8D1R97TTWEC3K` |
| the catalogue seal | saf | `01M6EYWM7JPW40G3PQATTYXAQR` |
| the strict reader in a release | ca | `01M6AJR570CZG8R9WA0JCYX1ZX` |
| `GRANTED_BY_SEED`: master pinning v0.9.13 | #247 | `01M6A9QDN199K1WE2H3QN3ZVQ9` |
| production reviewers | the training-domain ruling | `01M6A9QDN16Q03BPSJAPWDSAEP` |
| the configure surface | wb | `01M6FMQYFY8K233JWP2HXN91ED` |

## Next (in order)

1. Read #247, #248 and master, and the inbox in the master tree's `sessions/` too.
2. If ca cuts a patch before #247 merges: re-pin in one commit (the 17 pyprojects, 17 locks and `values.yaml`, per `docs/runbooks/pinning-the-fleet-sdk.md`), and drop the `index` caveat from `values.yaml` and the changelog. After it merges, the same as a new PR.
3. If master moves: re-read the changelog head, because the #247 entry sits under `## 0.4.79 — not yet cut` and a cut entry is never edited. Re-render #248 if another board PR lands first.
4. When #247 merges: move its item to done and adopt `GRANTED_BY_SEED` (`01M6A9QDN199K1WE2H3QN3ZVQ9`). The refusal seals in `tests/security/` then run on master; re-run them there.
5. **Later, as ruled:** the walker `chris@example.com` → `dave`, with lane/01 (`01M6EX5BSQNCWZXBBCFAM8PNCV`).

## Scratch (session scratchpad, not durable)

- `gs` (own venv, v0.9.13) holds #247. `ct` (own venv, v0.9.12) is detached at master `8a2717e0`, for baselines. `bd` (no venv; use `gs`'s) holds #248. `rp` is free. `f181` and `cc` can go.

## Lessons

- **A chained commit and push will publish a red.** A `sed` missed, the seal stayed red, and my chain committed and pushed `be971196` with a false message. `92ca2699` is the fix and says so; #247's body states it. Check the result between test and commit.
- **A version number is a claim about the artifact.** The tag said v0.9.13, and the package, the wheel and the release assets all said 0.9.12. Read the published artifact before pinning.
- **A consumer's copy of a model's rule moves with the bump.** `validate_policy` restated `ReviewShapeRow`'s required fields. The seal that asks the gate and the model the same questions now catches this, and the bump's first changelog draft was wrong to say no schema moved.
- **A gate that prints BUSY stops nothing unless the command checks it.** I ran two static census tests past a BUSY line on 11-04. They are small and read no shared state, but the check was decorative. Use the `until` form.
- **A census test can be red for reasons other than yours while your item is done.** Name who holds the rest, or the close reads as a claim that the test is green.
