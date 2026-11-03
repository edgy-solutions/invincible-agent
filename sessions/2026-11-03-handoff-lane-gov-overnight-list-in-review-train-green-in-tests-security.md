# Handoff: lane/gov, 2026-11-03 (overnight list in review; six PRs green together in tests/security)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-11-03

This replaces `2026-11-02-handoff-lane-gov-eight-reds-triaged-215-built-four-prs-with-lane-01.md`.
- Forks 24 and 25 are ruled and built. Fork 12 and the lessons in older handoffs still stand.

## The ruling since (via Chris, verbatim)

> to: invincible-agent/lane/gov — overnight: configure_subjects registry; transport-outage 503 at the fail-closed sites; the delegate list as a rail file with its validator; reply to #213.

## State

Master at last read: `b88a4874`. All six PRs are open, CLEAN, CI green at these heads. CI does not run these seals.

| PR | head | what | item |
| --- | --- | --- | --- |
| #221 | `45012fcf` | 18 person-named rows become the seed | `01M6G4CHMWMWHAEXNXN12ABEZZ`; carries saf's `01M6G4CHTQTR6M6VQ17XCVK3ZG` |
| #233 | `faf34758` | test and audit only: three lane/01-filed reds, three order-dependent | `01M6FZV0KNF7A3GT4QEJ44CEMB`, `01M6FRZ24M9F169X5ZEPV7CVW3`, `01M6FRZ28XHBTJXT3196Z2BDH6`, `01M6G57KAH8JTDH7RHZT1N7YT4` |
| #231 | `4451becc` | outage is a 503; carries #233's commits | `01M6FJFNZER425XQ4V9XCRTTCW` |
| #223 | `c3161b00` | `can_configure` registry | `01M6G57JZYCM0EZ3A9WNQCEZ4C` |
| #224 | `521b89a6` | gateway delegate rail; nothing reads it | `01M6G57K5VSQVAKPZG029AYEQ2` |
| #234 | `7b37de0c` | gov's board items | all of them |

**The join, measured:** master `b88a4874` + #221, #223, #224, #231, #234, changelog resolved to both sides: `tests/security/` plus two census tests, 2 failed, 1093 passed, 1 xfailed. Every test in `tests/security/` passed. Both reds are the census tests, on other lanes' files and sites. In-process only.

**Changelog:** after one of #221, #223, #224, #231 lands, the others conflict in `helm/invincible-agent/CHANGELOG.md` at the 0.4.77 head, and nowhere else. lane/01 has the packet. If asked, merge master into the rest, keep both sides, re-trailer, push. **Read the changelog head after every master merge**: never edit a cut entry.

**#213:** replied on the PR and in a packet. Run at `4eb35d06` on `ac1ebe69`, identical with and without it. Asked lane/01 to check the removed gauge warning before it leaves draft.

## Open forks

12. The relay-form detector for the ratchet (carried over). Item `01M6A9QDN19S78PQVCA67NZ9RC`.
26. Three readings on the delegate list: which list, the first row (`svc:data-analyst` on `assets.authorize`), `GATEWAY_ROUTES` as a constant. Asked of the architect. Item `01M6G57K5VSQVAKPZG029AYEQ2`.

## Waiting on

| for | who | item |
| --- | --- | --- |
| the delegate-list readings | architect | `01M6G57K5VSQVAKPZG029AYEQ2` |
| merges of #221, #233, #231, #223, #224, #234 | lane/01 | the items in the State table |
| saf to confirm or object to its row | saf | `01M6G4CHTQTR6M6VQ17XCVK3ZG` |
| one `topaz_sync` at 0.4.76 or later, then the roll | Chris | `01M6FMQYFY8K233JWP2HXN91ED`, `01M6AJR52DDXSJPFKQ12WG08J3` |
| the gateway's reader for the delegate list, and whether a recorded name is bounded by it | lane/01, architect | `01M6FZQ9TK0F5VQS2E1ERZ927Y` |
| the gauge check on #213 | lane/01 | `01M6FZQ9ZCBFZCCEGWGFH2HW6G` |
| the other five files on the `sys.modules` ratchet | other lanes | `01M6FRZ3K5477A0CNFKW1D9BBM`, `01M6FRZ1Z5BNQ9GQ85GY72YRPC` |
| the catalogue seal | saf | `01M6EYWM7JPW40G3PQATTYXAQR` |
| the strict reader in a release | ca | `01M6AJR570CZG8R9WA0JCYX1ZX` |
| `GRANTED_BY_SEED`: master's pin past v0.9.13 | the pin bump | `01M6A9QDN199K1WE2H3QN3ZVQ9` |
| production reviewers | the training-domain ruling | `01M6A9QDN16Q03BPSJAPWDSAEP` |
| the configure surface | wb | `01M6FMQYFY8K233JWP2HXN91ED` |

## Next (in order)

1. Read the state of all six PRs and master before writing anything about them. Read inbox packets, in the master tree's `sessions/` too.
2. When a PR merges, move its item and re-render: #221 and #233's items to done (the census tests stay red on other lanes' items, so say so), #223, #224 to done, `01M6FJFNZER425XQ4V9XCRTTCW` to done with #231.
3. **Later, as ruled:**
   - the walker `chris@example.com` → `dave`, with lane/01 (`01M6EX5BSQNCWZXBBCFAM8PNCV`);
   - `GRANTED_BY_SEED` once master pins v0.9.13 (`01M6A9QDN199K1WE2H3QN3ZVQ9`).

## Scratch (session scratchpad, not durable)

- `gs` (own venv) holds #233. `ct` (own venv) holds #231; its `docs/BOARD.md` ` M` is a CRLF artifact, never stage it. `rp` (own venv) holds #224. `bd` (no venv) holds #234. `f181` and `cc` can go.
- `chain.sh` merges heads by `merge-tree` and touches no ref. `run_q13.sh` builds the whole train on `gs` and runs the area. `cl_ins.py` and `remerge.sh` re-place a changelog block after a master merge.

## Lessons

- **A `sys.path` insert in a test file is a session-wide write, like `sys.modules`.** Mine at #210 made every later file hold a second copy of a module. The red was on another file, and only in some collection orders.
- **A list of `MERGEABLE` PRs is not a mergeable train.** Each was CLEAN against master; any two conflict. Run the chain, and test the join: it had never run on one tree.
- **"Now sees a person" depends on where the site reads its subject.** I nearly told lane/01 that every `svc:` branch changes under #213. Three read the body, so the bearer changing does not touch them. Read each site before grouping it.
- **Do not edit a worktree while a gated run is queued on it.** I amended `ct`'s changelog with q9 queued. It was harmless only because the changelog was all that differed, and the PR says so.
- **A log read mid-write can show an empty `exit=1`.** Wait for the notification.
