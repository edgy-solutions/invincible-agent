# Handoff — architecture seat (no lane), 2026-09-19

to: whoever takes the shared master tree
read-by:

**This seat holds no lane branch. Read the STATE block before assuming you can commit anything
here — most of what this seat produces belongs on someone else's branch.**

## STATE

    session         invincible-agent-ad [642333]
    tree            C:\Users\cnogr\git\invincible-agent  — the SHARED MASTER tree, not a worktree
    branch          master. No lane branch. No ia-NN worktree. Nothing pushed, ever.
    base sha        master 4dacccd  ("docs(handoff): Lane 1 — state, pin, what is in flight…")
    SDK pin         iagent-mesh v0.9.3 (pyproject.toml:62 and :133, two entries)
    fleet           NOT VERIFIED BY ME. Lane 1's handoff of the same date reports rolled at
                    91d8d34, 42/42, census 4 pass / 4 fail / 2 blocked. Take it from there,
                    not from here — this seat has not touched the cluster.
    working tree    clean of this seat's work. The only untracked file is
                    `sessions/2026-09-19-architect-handoff.md`, which is the ARCHITECT'S own
                    and is not mine to commit, move or tidy.

## IN FLIGHT: NOTHING. Both items routed and landed.

This is the whole of what this seat was carrying, and both left by another lane's hand:

| item | where it landed | by |
|---|---|---|
| **R-010** — canvas-template CI on `pull_request` is a blessed exemption | `docs/rulings/README.md:258`, on master | Lane 1, from the text this seat sent |
| **the back-reference** — the `RULED` line at the section it governs | `docs/plans/canvas-templates-slice-1.md:69` | lane/5f, `8c75931` |

**Neither was committed from this tree, and that was the point.** When R-010 was written here,
master's register held R-001–R-008 while `lane/01` held R-001–R-017. Committing from master would
have regressed nine rulings in a commit that looked like an ordinary doc edit. The content was
handed to the lane that owned the file instead.

**Two flags raised from this seat were acted on, so do not re-raise them:**

* The **R-011 collision** (master's *"Task kinds"* vs lane/01's *"Readiness fails on GAVE-UP"*,
  same number, two branches) is resolved — master:299 now carries the readiness ruling.
* The **anchor style** is fixed fleet-wide and consistently: 12 citations use the GitHub-correct
  double hyphen (`#r-0NN--slug`), 0 use the old single. lane/5f corrected the one this seat wrote
  when they landed it.

**Still open, and it is the live instance of the same defect:** `docs/rulings/README.md` has
**two R-055 entries** (:2070 and :2728). Lane 1 owes the renumber; the architect's own handoff
names it. A register with one number and two rulings is exactly what the R-010 placeholder was
written to prevent, three times over.

## THE EXACT NEXT STEP

**Rule ADR-0050 §9.2 — recorded as [R-007](../docs/rulings/README.md#r-007--92--open), still
OPEN.** It is an architect decision, it is this seat's, and **slice 1 closes on it**: R-007's own
text says so, and the architect's walk list ends with *"Finance board from the picker … then rule
R-007 §9.2 (still OPEN)."*

The question, with the trade already written in ADR-0050 §9.2 — **where does template geometry
live when the second template lands?**

* **Extend cortex's builder registry per template** (today's shape). Geometry stays where the
  measurements are and `CanvasUse` stays a closed union the compiler checks. Cost: a second
  registry to keep in step with the YAML, with a landing order that must not be got wrong —
  frontend row first, per §7.
* **A proportional slot grid in the YAML, realized generically.** One registry; a new board is a
  PR with no frontend change. Cost: it moves arrangement into config, nicking ADR-0042's
  *arrangement is UI-master*, and a grid expressive enough for a real board is a layout language
  nobody asked to maintain.

**The lean recorded in the ADR is the first**, until a third template makes the sync cost real —
and slice 2 is where it should be decided on evidence rather than in prose. The finance picker
walk is the evidence. **Do the walk, then rule.** Ruling it before the walk spends the one piece
of evidence this decision was deliberately deferred to collect.

## THINGS THAT WILL BITE YOU IN THIS SEAT SPECIFICALLY

* **Master is not the newest copy of a shared document.** It was nine rulings behind `lane/01` on
  the day this seat nearly committed over them. **Run the read half before editing any shared
  file:** `git fetch`, then
  `git log origin/master..origin/lane/* --name-only -- <path>`. It is the only thing that makes a
  pushed-but-unmerged change discoverable, and it paid out on its first use here.
* **This seat's output usually belongs on another branch.** Write the decision, hand it to the
  lane that owns the file, say explicitly that you are not touching it. Two lanes fixed the same
  page independently the week before because nothing made a pushed fix visible.
* **The session name encodes nothing.** `invincible-agent-ad` does not say "architecture seat", so
  every roster rebuild asks again. If this seat is meant to persist, it wants a line in `AGENTS.md`
  or the register — otherwise it is indistinguishable from an unassigned lane awaiting work.
* **A dated correction in a separate artifact outranks a co-located comment.** Retraction is
  asymmetric work: whoever corrects a finding updates the packet they are writing in, not every
  comment that quoted the old cause. This cost a near-miss in `gateway.py`'s slot-3 comment,
  which matched the symptom perfectly and had been retracted a week earlier.
* **Do not restate another lane's cluster facts as verified.** Everything in STATE above marked
  NOT VERIFIED is Lane 1's reading, not this seat's.

## WHAT THIS SEAT DECIDED, FOR THE RECORD

ADR-0050 (`c0b9374`) — canvas templates as ratified YAML, a panel as a pre-resolved step, one
seed verb. Since amended by ruling: **R-013 struck §2's empirical claim** (*"the one seal
phrase-based seeding cannot pass"*) after seal 3 passed four times across a prime, correctly
scoped, and rests §2 on the structural argument alone. The law recorded with that strike is worth
carrying into the §9.2 decision: *a population hardened against the failure cannot measure the
failure.*

Lane: none — shared master tree, `invincible-agent-ad`
