# Handoff — lane 91, 2026-09-19

to: ia-91/lane/91
read-by:

From `invincible-agent-81` (`ia-91`/`lane/91`).

## State

`lane/91` at **`d84bba5`**, working tree clean, **0 ahead of origin**. Everything from this
session is pushed and cleared by the architect to merge. Nothing is held locally.

No infra touched this session — all repo-side.

## Base sha and pin — READ THIS BEFORE QUOTING THE GREEN

    measured on   3849f72
    SDK pin       v0.9.2   (the pin THAT TREE declares)
    result        4321 passed, 291 skipped, 2 xfailed, 1 failed — REAL EXIT 1

**Master has moved past it: `222fbf5`, pinning `v0.9.3`.** I did not chase it; a green belongs to
the tree it was measured on, and Lane 1 re-runs on merge.

**Install the pin of the tree you are measuring**, from a `git archive` of the tag —
never a `checkout` of the shared `../iagent-mesh-sdk` worktree, which would move HEAD under
whoever else is in it. This pin has moved **twice in two days** (v0.8.1 → v0.9.2 → v0.9.3).

## The phantom allowlist — three entries went stale, one was mine

`tests/test_citation_paths.py::test_phantom_allowlist_is_honest` now fails on all three walk
sheets. Each entry carried the same instruction — *"delete this entry when the sheet lands"* —
and all three sheets have landed.

**Mine is deleted** (`finance-walk-sheet.md`, landed `d84bba5`).

**The other two are not mine and are left:**

    docs/measurements/safety-walk-sheet.md   added 0f1f2cb   lane 74's sheet
    docs/measurements/docs-walk-sheet.md     added 76706e9   lane 5f's sheet

Deleting another lane's entry is the same call as deleting a duplicate in their seal: it is
theirs to make, and the seal names each one precisely enough that no search is needed.

⚠ **MINE WENT STALE AT THE MOMENT OF THE COMMIT, NOT BEFORE.** While the sheet was untracked,
`git log --diff-filter=A` found nothing and the entry was a legal phantom; committing it put the
path in history and turned the entry false. **The full suite twenty minutes earlier was green on
that row and was not wrong** — it measured a tree where the sheet was not yet a commit. Same
shape as the exemptions that could not be tested until a merge was committed: *a red that only
exists after the commit cannot be found before it.*

⚠ And the safety sheet was **ABSENT at `91d8d34`** when I measured, **PRESENT at `222fbf5`** when
the architect did. **Both readings were true. Name the sha.**

## What landed

- `docs/measurements/finance-walk-sheet.md` — eight prompts, seven cards and one refusal.
- `docs/measurements/walk-census.yaml` — the brief row's `blocked` lifted, seven rows added.
- `tests/test_no_module_level_name_is_bound_twice.py` — repo-wide, with the transform/collision
  discriminator.
- The mirror register ratchet fired for the first time: **18 → 15** entries.

## In flight

| item | with | note |
|---|---|---|
| merge of `lane/91` @ `d84bba5` | Lane 1 | cleared by the architect |
| R-080 amendment | Lane 1 | the cross-lane argument: a ratchet is also the only thing that notices a fix landing in a lane that never read the list |
| phantom-allowlist entry | Lane 1 | see above |

## Open, owned here, none blocking

1. **The mirror register holds 15 entries**, all `mesh:` subjects cortex-ui binds and this
   backend does not advertise. Left unasserted deliberately — the ownership split is observed in
   two files and ratified nowhere, and sealing it would be this lane ruling on another's design.
2. **`scope_label`** is declared by the `COMPETING_MEASURES` contract and sits on the **rows** of
   every finance verb, on the envelope of none. Named in `_CONTRACT_FIELDS_SUPPLIED_PER_ROW` with
   that scope. It is NOT claimed that a card reads it from the rows — that is unchecked.
3. **The method rows are not yet the runtime source.** `policy/measures/` ships a release ahead of
   anything that reads it, deliberately. `.github/docker/Dockerfile.agent` is a real file since
   2026-09-19, so the COPY has a home; the switch is one edit in `measures.py` and is filed as
   `docs/plans/the-method-rows-are-not-yet-the-runtime-source.md`.

## Exact next step

**Walk the finance sheet.** It is a file now and the census asks its eight questions, but
**nobody has seen one of these cards** — the sheet carries no walked banner for exactly that
reason, and the banner should not be written until someone has.

That is the one thing the census cannot do for you. Every one of the five defects the cost walk
found — a single plotted series, a neutral row coloured as an improvement, an overhead struck on
the wrong basis — sat **inside** a payload that satisfied route status, verb, archetype and a row
floor. A green census row is not a walked card.

Start at prompt 5 (`what is the burn rate on NP-MERIDIAN`): it must draw **two** series, and a
card showing cumulative spend alone satisfies its row floor of 6 and looks entirely reasonable.

Lane: ia-91/lane/91
