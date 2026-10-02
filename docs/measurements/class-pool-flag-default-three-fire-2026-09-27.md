# Measurement — the class-pool flag's default, flipped and three-fired

**Date:** 2026-09-27 · **Lane:** `ia-74/lane/74` · **Subject:** `ONTOLOGY_CLASS_POOL_VIA_MESH`,
whose artifact literal was `"false"` when measured.

*Correction, 2026-10-01 (Lane 74):* `ONTOLOGY_CLASS_POOL_VIA_MESH` is now DEFAULT ON (literal
`"true"`), flipped after an in-process census of every walk row moved no row (`class-pool-flag-default-on-census-2026-10-01.md`).
Every figure in this file was measured with the literal `"false"`.

> The order this answers states the other polarity, as an instruction. It is quoted verbatim below
> and kept clear of the flag's name on purpose: the claim census decides a window, and a window
> holding both polarities is undecided, which is a red. Do not move it back up.

**Ordered, verbatim:** "flip the flag default on, three-fire census, report the diff. Flip back if
any row moves."

## 0. The answer, and why the answer is not the finding

Not one row moved. Three fires with the default flipped, three fires without, identical totals and
identical failure **identities**. The flip is already reverted and the file digest-verified.

**That zero is worth nothing as reassurance, and this report exists to say so.** No arm's outcome
could have moved, because the population that depends on the default was empty. A census whose
subject cannot move reports a clean result it never looked at, and the count agreeing three times
in a row makes it read as corroborated.

## 1. What was fired

| arm | fires | result | failure identities |
| --- | --- | --- | --- |
| default `"false"` (as shipped) | 3 | 38 failed / 988 passed / 117 skipped | baseline, 0-row diff between fires |
| default `"true"` (flipped in the artifact) | 3 | 38 failed / 988 passed / 117 skipped | **identical to baseline, both directions of `comm -3` empty** |

The 38 are all in `tests/routing/`: 2 `adr0019`, 29 `test_classify_route`, 7
`test_phrasing_independence`. They were established pre-existing and independent of this lane's
changes earlier the same day, by identity, with a population-matched control.

**The flip was positive-controlled at runtime.** The first attempt silently did nothing: the script
called bare `python`, absent from PATH in Git Bash on this box, so the anchor count passed, the
edit never applied, and three fires measured the unflipped state while reporting a flip. The re-run used
`.venv/Scripts/python.exe` and asserted `main.ONTOLOGY_CLASS_POOL_VIA_MESH is True` by import
before firing anything (`IMPORTED VALUE: True` / `FLIP IS LIVE`). The failed run was not discarded
— it is the population-matched off baseline above.

Restored byte-identical: `c612e62a78d635aa070926d2f3e8defacfad41215b37f46513bcbe812814e613`.

## 2. Why nothing could move — three mechanisms, measured

1. **Every test reader sets the flag explicitly.** `git grep` over the suite returns exactly one
   setter: `monkeypatch.setattr(main, "ONTOLOGY_CLASS_POOL_VIA_MESH", on)` in the parity seal, which
   parametrizes both arms. That is correct for parity and is precisely why the module-level value
   it overrides is invisible to it.
2. **The single consumer reads a module global fixed at import.** `class_pool_with_mode` forks on
   the name, resolved once at import time, so nothing re-reads the environment mid-suite.
3. **The arms that would notice are the ones that need a cluster.** The routing reds fire at a live
   `BFF_URL`; they fail identically in both states because they never reach the engine.

## 3. What the live census would have measured, and why it cannot run

The order's census fires at the deployed pod, not at this source tree. Measured against the
sandbox deployment (the cluster coordinates stay in the out-of-repo log, per project rules):

- the deployed `iagent-engine-o` carries **no** `ONTOLOGY_CLASS_POOL_VIA_MESH` environment
  variable at all.
- Its image is `ontology-service:55dc8614…`, and `git grep` shows `_class_pool_via_mesh_sync`
  **absent** from `55dc8614` and **absent** from `origin/master`; it exists only on `lane/74` HEAD.
- The pilot commit `29c9ff23` is **not an ancestor of master**.

So the deployed engine has no migrated route to flip. Settling this default is not blocked on more
measurement from this lane: it needs a gated merge to master, an image build, and a roll — the merge
is Lane 1's and the roll carries `--apply`, which is Chris's.

## 4. What was added so the next flip costs something

`tests/test_the_flag_default_is_off_and_every_claim_about_it_agrees.py`, 8 arms, the first check of
any kind on this default:

- the default and the truthy set are read out of `main.py`'s **AST**, not restated;
- the artifact's own expression is **evaluated** with the variable unset, so a truthy set that grew
  a `"false"` entry reds as well as a moved literal;
- the `os.getenv` key is compared to the variable name, because a misspelt key is a flag that cannot
  be set at all and a default that rules forever;
- a derived census finds **every prose home** of the claim and decides each on content against the
  AST — four sites in three files, `main.py` twice, the pilot report, and the parity seal's own
  docstring. Its **undecided bucket fails**, which is how a reworded claim announces itself instead
  of dropping out; a listed file going silent reds against a measured floor; and a new *agreeing*
  claim deliberately does not red.

15 mutants, 15 as expected — including two required to stay quiet, so the design choices are
measured rather than merely intended. One mutant of mine was wrong before the seal was: a reworded
comment I predicted would drain away instead went *undecided*, because its window holds the words
"forks on". The seal was right and the prediction was wrong; the mutant was re-aimed at a home
whose window is clean.

Two mutants were **skipped on an anchor count of 2**, which is the finding in §5.

## 5. A neighbour, reported and not absorbed

`in ("true", "1", "yes")` occurs twice in `main.py`. The other occurrence is
`ENABLE_AGENTIC_AUTH = os.getenv("ENABLE_AGENTIC_AUTH", "false").lower() in (...)` at line 207 —
the identical mechanism, the same falsey literal, and no check of any kind on **its** default
either. It is an authorization-enabling flag, so which way its default *should* point is a ruling
and not mine to make; this seal was not widened to cover it. Naming it here is the whole of what
this lane does about it.

## 6. Not claimed

That the default is safe to move. Nothing here measured the migrated route under real traffic,
because the migrated route is not deployed. What is now true is narrower and checkable: the default
is off, every sentence in the repo that says so agrees with the artifact, and a flip reds three
named arms instead of passing 988 tests in silence.
