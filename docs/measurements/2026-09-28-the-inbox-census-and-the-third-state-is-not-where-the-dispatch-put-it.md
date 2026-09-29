# The inbox census with its third state — and the third state is not a property of the `to:` line

Date: 2026-09-28. Lane: `ia-np/chart/networkpolicy`. Dispatch item 4, remaining halves.

Item 4 asked for "the inbox census with the third state (unenumerable)" and "the R-055→R-081
citation grep". Both are below. The census's headline is that **the third state exists and the
dispatch located it in the wrong place**: it is not an address that fails to parse, it is a packet
that was never committed.

## 1. The population, and getting it wrong is the whole finding

`CLAUDE.md` is explicit that the handoff channel is `sessions/` **in the repo — tracked and
committed**. So a census of the inbox has to ask, before anything else, which files are on the
channel at all.

| population | count | who can read it |
| --- | --- | --- |
| tracked `sessions/*.md` | **86** | every lane, from any worktree |
| untracked in the `master` working tree | 9 | only a session in `master` |
| untracked in `ia-01` | 6 | only Lane 1 |
| untracked in `ia-74` | 9 | only 74 |
| **union of untracked, deduplicated by filename** | **21** | — |
| of those, present ONLY in `ia-74` | **8** | nobody but 74 |

A census run from `master` — the obvious place to run one — sees 86 + 9 = 95 and reads `ia-74`'s 8
as **a clean zero**. Not as "unknown". As "not there".

### ⛔ And three of those invisible eight are OUTBOUND

```
2026-09-26-packet-to-ca-the-ontology-arm-fired-and-was-right-one-of-its-own-examples-cannot-match.md
2026-09-26-packet-to-cortex-the-fallback-already-says-so-render-it-as-a-sentence.md
2026-09-28-packet-to-ca-the-write-half-is-on-main-and-in-no-tag-and-a-sha-pin-is-enough-to-start.md
```

Each is addressed to a recipient who **cannot see it**. They are written, correctly named, correctly
addressed — and sitting untracked in a worktree only their author can read. A packet that is not
committed was not sent. It was drafted.

There is a fourth of the same shape one level up: one of `ia-01`'s own untracked files is
`2026-09-23-packet-from-74-a-dispatch-addressed-to-lane-01-was-delivered-into-74s-session.md` — a
packet *about* a misdelivery, itself sitting off-channel.

## 2. The three states, measured over the 86 tracked packets

| state | count | what it means |
| --- | --- | --- |
| **ROUTABLE** | **58** | `to:` parses as `<repo>/<lane\|seat>/<branch>` |
| **PROSE** | **17** | `to:` is present and names a person, a seat, or a condition — unroutable by any parser |
| **NO `to:` LINE** | **11** | nothing to parse |

The 17 prose addressees, verbatim:

| `to:` value | n |
| --- | --- |
| `Chris` | 6 |
| `the architect` | 4 |
| `whoever takes the shared master tree` | 1 |
| `whoever picks up ADR-0033's ask disposition, and to Lane 1 for the roster` | 1 |
| `the architect seat (lane-less by R-019 — the inbox seal has no word for this; known, held)` | 1 |
| `cortex-ui` (bare repo, no branch) | 1 |
| `Chris, and the architect on item 1's second half` | 1 |
| `7f` (bare lane, no repo) | 1 |
| `(no lane) — whoever next occupies the shared master tree` | 1 |

Of the 17: **7 name a human**, **6 name the lane-less architect seat**, 3 name whoever next occupies
the shared master tree, 1 is a bare repo and 1 a bare lane.

The architect-seat figure is the one that matters, and one of those six says so in its own `to:`
line: *"the inbox seal has no word for this; known, held."* That seat is lane-less by R-019, so a
packet addressed to it is its **only** evidence of existing — and a census keyed on
`<repo>/<lane>/<branch>` loses precisely that addressee, reporting the gap as a zero rather than as
six held packets.

### ⚠ My first matcher over-reported this by 8, and the instrument was the defect

My first pass counted 25 unparseable. Seven of those were well-formed and my regex could not hold
them: `ia-cortex-60/lane/cortex-60` (5 — a hyphenated repo suffix, against `ia-[a-z0-9]+`) and
`doc-tools/lane/7f` (2 — a real repo that is not `ia-*`). One more,
`` `ia-74` / `lane/74` ``, was well-formed but backtick-wrapped and spaced.

The matcher's reach did not cover the population's. It is now positive-controlled on all four of
those forms and negative-controlled on `Chris`, `the architect`, `cortex-ui`, `7f` and
`whoever takes the shared master tree`, all five of which it correctly rejects. Without those
controls the prose bucket would have been inflated by nearly half and `doc-tools` would have read as
an unroutable address.

## 3. So the third state the dispatch asked for is real, and it is somewhere else

Adding an `unenumerable` bucket to the `to:`-line taxonomy is the wrong third state. Ranked by how
badly each fails:

| state | exists to every reader? | recoverable? |
| --- | --- | --- |
| ROUTABLE | yes | delivered |
| PROSE | **yes** | yes — a human reads it and re-routes it |
| **NOT COMMITTED** | **no** | **only by its author, who already thinks it is sent** |

A prose-addressed packet is a *routing* failure: the file is on the channel, everyone can read it,
and the cost is that no parser can dispatch it. An untracked packet is a *delivery* failure, and it
is strictly worse — it is invisible, it reads as absent rather than as unknown, and its author has
no signal at all, because from inside their own worktree it looks exactly like a sent packet.

`unenumerable` is therefore a property of **whether the file is committed**, not of what its `to:`
line says. A census that only added a prose bucket would have reported a cleaner inbox than exists
and would have missed all 21 undelivered packets, 8 of them invisible from anywhere but one
worktree.

**The check is one command, and it belongs in the lane loop rather than in a census:**

```bash
git -C <worktree> ls-files --others --exclude-standard sessions/   # must be empty
```

## 4. The citation grep — and the carried number was right for its stated scope

Item 4 asked for "the R-055→R-081 citation grep". Re-run across `docs/ sessions/ tests/ src/
agent_fleet/ policy/`, excluding the register itself:

| window | uncited |
| --- | --- |
| R-055 → R-081 (as asked) | **10** — R-059, R-060, R-061, R-062, R-066, R-067, R-068, R-069, R-077, R-079 |
| the whole register, R-001 → R-087 | **37 of 87** |

The 10 is exactly the list carried in from the earlier session, so that claim holds for the window
it names. The 37 is new, and is the more honest denominator: **42% of the register is cited
nowhere but the register.** R-083, R-084 and R-086 are in it and are uncited *by construction* —
they were numbered today.

⚠ **THE CAVEAT IS LOAD-BEARING AND A ZERO CANNOT BE READ WITHOUT IT.** An uncited ruling is
indistinguishable, from a grep, between at least three states:

1. **invisible** — nobody knows it exists, so it governs nothing;
2. **universally obeyed** — so settled that nobody argues it and nothing needs to cite it;
3. **enforced anonymously in code** — a seal implements it without naming the number, which is the
   commonest case in this repo and the one a citation grep is structurally blind to.

A count of 37 is therefore **not** a count of dead rulings, and must not be reported as one. Telling
the three apart requires reading each ruling and looking for its enforcement by *subject* rather
than by number — which is a different and much larger job than the grep, and is not done here.

## 5. What I did not do

- **Did not move, commit or re-route any other lane's untracked packets.** They are other lanes'
  working trees. The finding is reported; committing another lane's drafts is not this seat's call.
- **Did not re-address the 17 prose packets**, and in particular did not invent an address for the
  lane-less architect seat — R-019 makes it lane-less on purpose, and inventing `seat/architect` is
  a known failure (the repo prefix is required, so the bare form fails exactly like the prose does).
- **Did not classify the 11 packets with no `to:` line by intended recipient.** That needs reading
  each body, and a guess there is worse than the gap.
- **Did not decide whether any of the 37 uncited rulings is dead** — see the caveat in §4.
