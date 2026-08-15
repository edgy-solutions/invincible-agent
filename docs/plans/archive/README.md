# Archive — what happened, not what is owed

**Nothing in here is tracked work.** These are witness records, exhibits, run cards, handoff
logs and progress notes: artifacts of episodes that are over. They are kept because they are
evidence, and evidence stays greppable.

Placed here by the taxonomy ruling in
[../board-migration.md](../board-migration.md) (2026-08-15). The rule that put them here:

> A directory is a claim about what its contents are.

`docs/plans/` claims *live work items with an ADR-0040 status*. These have no honest status in
that five-value vocabulary — forcing one would be a category error, and headering them would
make `closed-by` attribution pass for the wrong reason.

**Practical consequence:** `scripts/generate_board.py` globs `docs/plans/*.md` non-recursively,
so nothing here is indexed on the board and nothing here counts against the coverage
denominator. That is deliberate — it is what makes *N of N indexed* reachable at all.

**Do not add live work here.** If it has an owner or a next action, it belongs one directory up
with a header. If it is a standing design or posture that someone consults to decide something
today, it belongs in [`docs/reference/`](../../reference/).

**Citations into this directory are checked.** `tests/test_citation_paths.py` fails if anything
cites a `docs/` path that does not exist, so moving or renaming a file in here breaks the build
rather than rotting quietly.
