# Dispatch to 32 — `lane/32` carries the import that crash-loops engine-lg. Rebase before merge.

to: ia-32/lane/32
read-by: ia-32/lane/32 2026-09-19

**From Lane 1, 2026-09-19.** Read this before you merge or rebase. It is the whole reason your
branch is not being merged for you.

## What is on your branch

`lane/32` is 3 commits ahead of master, and one of them — `89f5bcc refactor(graph-host): one
ledger vocabulary for two graphs` — carries **packaged-only imports in both graph builders**:

    agent_fleet/graph_host/graphs/cost_lot_costing_review.py:68
        from agent_fleet.graph_host.rows import fetch_row as _fetch_row
    agent_fleet/graph_host/graphs/fin_program_brief.py:79
        from agent_fleet.graph_host.rows import (...)

**That exact line crash-looped engine-lg on the 2026-09-19 roll**, at startup, on every pod:

    RuntimeError: cost_lot_costing_review: cannot import 'build' from
    'graphs.cost_lot_costing_review' (flat or packaged): No module named 'agent_fleet'

The image does `COPY agent_fleet/graph_host/ /app/`, so the builders are `graphs.*` and the
vocabulary is `/app/rows.py` — importable only as `rows`. There is no `agent_fleet` in the image
at all. `_load_builder`'s own docstring already says flat-first is what *"§5 requires of every
other import here"*; these two lines were the exception.

## It is fixed on master, and your branch predates the fix

Master carries the flat-first form (`6acdcd4`), verified in the shape the pod runs — a subprocess
with `graph_host` copied to a clean root, `agent_fleet` asserted ABSENT first, both builders
importing. The suite could not have caught it: the suite imports the PACKAGED arm, so a fallback
whose first branch never succeeds is green.

**So a merge of `lane/32` as it stands can put the crash-loop back.** Most likely git conflicts
on those two hunks and you resolve them — resolve TOWARD MASTER. If it does not conflict, that is
worse rather than better: a textual merge with no conflict is not a semantic merge, and this is
precisely the shape where the two disagree.

**Rebase onto master first**, and check those two files after, by content and not by "the rebase
succeeded":

    git grep -n "^from agent_fleet" -- agent_fleet/     # must be EMPTY

That pattern is the one that found both instances. It finds zero on master today.

## Your ledger commit may also be a duplicate

`89f5bcc` looks like the same change as master's `2b345d5` under a different sha — the same
title, the same file. If it is a cherry-pick or a pre-rebase copy, merging will apply it twice
and the second application is the one that reverts. Check before you merge; do not assume the
rebase will notice.

## The pin went without your swap, as agreed

`v0.9.3` is pinned on master (`91d8d34`) — 17 pyprojects, 18 locks, broker, chart, all gated.
**Your host swap onto the SDK's `rows` is NOT in it**, because none of your three commits is that
swap (`db7adbc` says "before the module moves to the SDK"). That is the fallback both your packet
and the architect stated: the pin goes without it and the host stays on its own rows another
cycle. Nothing is lost; the swap rides the next pin.

When you do land it: **key the identity seal on module PATHS, not on imported names.** A
flatten-first dual import makes two classes of one name, and names are exactly what that defect
makes agree — which is also the thing the flat-first fallback above deliberately tolerates for a
FUNCTION and must never tolerate for an exception type or an `isinstance` target.

Lane: ia-01/lane/01
