# Handoff: lane/gov, 2026-11-02 (alice merged; fork 22 is #210, in review; one question to the architect)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-11-02

This replaces `2026-11-02-handoff-lane-gov-190-merged-196-registry-built-199-board-open-sandbox-member-asked.md`.
- Forks 22 and 23 are ruled, below. Fork 12 and the lessons in older handoffs still stand.

## The ruling since (architect via Chris, 2026-11-02, verbatim)

> to: invincible-agent/lane/gov — sandbox reviewer is alice (my ruling to wb); one-line follow-up before the sync. Fork 22: a malformed PDP answer is 503 at every site, including the ones that already fail closed — same class as 16.

## State

| what | state |
| --- | --- |
| #204, alice | merged at `729efeeb`. master's `policy/users.yaml` gives alice the group, not bob |
| #199, board | merged |
| #210, fork 22 | open, base master, head `b9699db2`, CI 20 passed and 3 skipped, MERGEABLE at last read |
| #211, board | open, head `e89f37da`: corrects the `can_review` item, adds fork 22's item and lane/01's reds item |
| #149 | open (`20d62c4b`), item `01M6A9QDN1M7B3400G8Y0MWH0Y` |

#210's evidence is in its body: 26 of 26 mutants named red; 178 consumer files with 9 failed, and the same 9 fail on plain `34fc18ad`. Nothing ran live, and the Restate ingress turning code 503 into an HTTP 503 is unmeasured.

## Open forks

12. The relay-form detector for the ratchet (carried over). Item `01M6A9QDN19S78PQVCA67NZ9RC`.
24. **A transport outage at the fail-closed sites is still a no; a malformed answer is now a 503.** Asked in `2026-11-02-packet-to-architect-from-gov-fork-22-built-210-one-question-on-a-transport-outage.md`. If yes, one PR on the same seal: the sites are listed there. Item `01M6FJFNZER425XQ4V9XCRTTCW`.

## Waiting on

| for | who | item |
| --- | --- | --- |
| the outage question | architect | `01M6FJFNZER425XQ4V9XCRTTCW` |
| #210 merge | lane/01 | `01M6FJFNZER425XQ4V9XCRTTCW` |
| #211 merge, and the eight master reds | lane/01 | `01M6FJH2HQCN09G0CF14451A48` |
| `topaz_sync`, then the roll carrying 0.4.75 | Chris | `01M6AJR52DDXSJPFKQ12WG08J3` |
| the catalogue seal | saf | `01M6EYWM7JPW40G3PQATTYXAQR` |
| the strict reader in a release | ca | `01M6AJR570CZG8R9WA0JCYX1ZX` |
| `GRANTED_BY_SEED` in v0.9.13 | ca | `01M6A9QDN199K1WE2H3QN3ZVQ9` |
| production reviewers | the training-domain ruling | `01M6A9QDN16Q03BPSJAPWDSAEP` |

wb's reviewer rows are wb's item, `01M6A9QDN1VCGZRXDMMKTFWT1T`. wb's NetworkPolicy question is lane/01's.

## Next (in order)

1. Read #210's and #211's PR state before writing anything about them. If #210 needs a rebase, rerun the seal on the new sha: the census reads tracked sources, so a new reader on master can turn it red, and that is the seal working.
2. Read the architect's answer on the outage question.
3. When #210 merges, move `01M6FJFNZER425XQ4V9XCRTTCW` to done, and regenerate the render.
4. **Later, as ruled:**
   - the walker `chris@example.com` → `dave`, with lane/01 (`01M6EX5BSQNCWZXBBCFAM8PNCV`);
   - `GRANTED_BY_SEED` when ca ships v0.9.13 (`01M6A9QDN199K1WE2H3QN3ZVQ9`).

## Scratch (session scratchpad, not durable)

Worktrees:
- `ct` holds #210, with its own venv; `mut3.py`'s `fk` set runs against it.
- `gs` is merged, but its venv is still the Python for `bd`.
- `bd` holds #211, with no venv.
- `rp` holds #149.
- `f181` and `cc` can go.

Tooling:
- `mut3.py` needs its backup directory to exist. Ids are comma-separated, not space-separated: `fk F26,F23`.
- A waiter that greps a log for a finish line sits out its whole timeout if the runner crashes first. Background the runner itself.

## Lessons

- **A survivor found a hole in the census, not in the code.** `ingest_export_route` could lose its guard unseen, because the census only checked that some raise was present. A hand-read row should hold what the person read, not just the name of the place.
- **Read a PR's state last, again.** #199 and #204 both merged while I was working, and my first wb packet said #204 was open. It was rewritten before anyone could act on it.
- **Measure a figure before writing it.** I wrote "74 test files" in #204's body before counting; the list held 18. Corrected.
