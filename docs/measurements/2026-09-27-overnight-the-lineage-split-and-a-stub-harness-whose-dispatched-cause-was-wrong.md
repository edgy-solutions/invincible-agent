# The lineage split, and a stub harness whose dispatched cause was wrong

**Date:** 2026-09-27 · **Lane:** `invincible-agent/master` · **Items:** overnight dispatch 2 and 4

Items 1 and 3 landed in `fadda10f` and are recorded in
`docs/measurements/2026-09-27-overnight-the-docs-empty-document-is-not-the-mesh-blindness-i-predicted.md`.
This file covers item 2 (committed `d3944da8`) and item 4.

---

## Item 2 — one predicate was deciding two questions

`_answers_something` gated BOTH whether `derived_from_artifact_id` was set and whether the ask's
stored `(subject, verb)` could skip routing. So the HAZ-1003 composer turn — a person reading a
drawn card and typing a sentence about it — had to be refused lineage in order to be refused the
route. The arrow was dropped and the rail showed an orphan card.

The gates now rest on different evidence because they cost different things when wrong:

| gate | evidence | cost of a wrong yes |
| --- | --- | --- |
| lineage arrow | answers, or prose **plus** proven ownership | two cards folded on a lineage nobody produced |
| pre-resolved route | `bound_slots` or `spoken_answer` only | a verb DISPATCHED against a subject nobody confirmed this turn |

**The prose arm pays for itself with a graph read.** Prose is evidence of nothing — every ordinary
question carries prose, so `named + prose` is satisfiable by any caller typing any sentence at any
invented id, and the writer links with `MERGE (parent:AnswerArtifact {id: $parent_id})`, which
CREATES the node when the id is unknown. So that arm requires existence AND ownership via
`_artifact_is_the_callers`, which runs the route lookup's own `_PRE_RESOLVED_CYPHER`, never MERGEs,
decides on whether a row came back rather than on its content, and returns False on every
uncertainty. It is a callable ordered last, so only turns that could widen anything pay for it.

- **Where the rule lives:** `src/iagent_pure/lineage_claim.py`, not inline — a mirror is not a seal.
- **Seal:** `tests/routing/test_a_prose_turn_keeps_its_lineage_and_not_the_route.py`, 11 arms
  calling the real function, 3 reading wiring a pure seal cannot see.
- **Mutation:** 12/12 killed by their named arms.
- **Fires:** 23 green ×3. `tests/routing`: 38 failing identities, the same 38 as before, zero new.

**A known hole is pinned, not closed.** The answering arm still does not verify existence, exactly
as before. Closing it would refuse valid lineage in any window where the ask's write has not landed
when the answer arrives, and whether that race exists here is UNMEASURED.
`test_the_answering_arm_DOES_NOT_PAY_FOR_THE_GRAPH_READ` holds current behaviour so that closing it
is a deliberate act with a red to change.

### Instrument notes

- `_guard_window()` was `i-1200 : i+900` and stopped reaching the refusal when this change grew a
  comment. It redded — the lucky direction. **An absence assertion on the same window would have
  gone QUIET on the same edit.** Both ends are now derived from code landmarks.
- The mutant targeting the ownership Cypher was SKIPPED for matching twice. That anchor count is a
  population fact, not a patch failure: the two call blocks are byte-identical, which is the arm's
  own claim.

---

## Item 4 — ⛔ the dispatched cause was wrong, and the fix it prescribed does not fix it

The dispatch read: *"Stub harness restores sys.modules (21 files); master's two order-dependent
reds go away."* The restore half is real and worth having. **It is not what makes the two reds go
away**, and that was measured in both directions rather than argued.

### What the two reds actually are

`tests/routing/test_adr0019_engine_o_contract_a.py::test_n1_calls_baml_with_two_value_enum` and
`::test_n1_on_topic_still_dispatches`. 2/2 green when the file runs alone; 2/2 red in the suite,
failing with `'TypeBuilder' object has no attribute 'values'` — **the file's own recorder reading an
object it did not build.**

No unrestored stub is involved. `test_an_out_of_domain_hit_is_a_candidate_not_an_authority` loads
engine-o's `main.py` at MODULE level, so the REAL, file-backed `baml_client.type_builder` enters
`sys.modules` during COLLECTION — a legitimate import that belongs there. adr0019 then offers its
recorder under `if "baml_client.type_builder" not in sys.modules:` and installs **nothing**.

So there are two distinct failures wearing one name:

| | symptom | cause |
| --- | --- | --- |
| **LEAKING** | a LATER file fails in its own name | a double left behind (measured 2026-09-04) |
| **DEFERRING** | the file's OWN assertions measure a stranger | `if name not in sys.modules` losing to whatever ran first |

**A guard loses to a legitimate real import as readily as to another test's stub.** That is the
sentence the whole item turns on.

### The rule, which the file had already half-written

adr0019 carried `# Always overwrite weaviate + weaviate.classes; other test modules install
MagicMocks for those that confuse the imports` — the same lesson, for one name, ungeneralised:

- **a double the test ASSERTS ON is installed unconditionally** — it is a recorder, and yielding to
  whatever ran first makes the assertion measure a stranger;
- **a double that only satisfies an IMPORT may defer** — it is an absence shim, and the real module
  is strictly better than a fake of it.

Only `baml_client.type_builder` is a recorder here. `rdflib`, `neo4j`, `baml_client`,
`baml_client.types` and `utils*` are shims and are left deferring on purpose.

### Measured: the change as dispatched does not close it

With the restore harness in place and adr0019 left at its HEAD bytes:

```
2 failed, 6 passed          symptom 'TypeBuilder' object has no attribute 'values' still present
```

With the recorder installed unconditionally as well:

```
8 passed
```

Run as `test_an_out_of_domain_hit_is_a_candidate_not_an_authority.py` then
`test_adr0019_engine_o_contract_a.py` — the exact pairing that produces the reds. The adr0019 file
was restored from its own bytes with a post-restore identity assert, not by `git checkout`.

### A `sys.modules` double is only as good as the import form

Measured against a real package whose submodule was already imported, then overridden in
`sys.modules` alone:

| form | resolves to |
| --- | --- |
| `from pkg.sub import name` | **the double** (reads `sys.modules`) |
| `import pkg.sub as s` | THE REAL ONE (reads `getattr(pkg, "sub")`) |
| `from pkg import sub` | THE REAL ONE (same) |

Engine-o spells its import the first way, which is why the adr0019 repair needed nothing more —
**by luck, not design.** So `stub_modules` sets the parent attribute too and restores its previous
value, or its ABSENCE, with everything else. This is the generalisation of the `wv.classes = wvc`
line adr0019 already carried without saying what it was for.

### The predicate: derived, not listed — and the census caught it being wrong

`_STUBBED_GLOBALS = ("baml_client", "dagster")` is retired by the first file that stubs a third
name, silently, because the restore simply stops covering it. The replacement decides on shape.

**⛔ And its first form had a false positive in the direction that would have been worse than the
leak.** It read `not isinstance(obj, types.ModuleType) -> double`, and it was right about every
example I picked by hand. `test_THE_PREDICATE_IS_RIGHT_ABOUT_THE_WHOLE_LIVE_POPULATION` ran it over
the entire live `sys.modules` against `importlib.util.find_spec` as an independent criterion and
found `zipp.compat.overlay.zipfile`: a `HashableNamespace` — **not a `ModuleType`** — carrying the
real stdlib `zipfile`'s spec, file and `__all__`. The teardown would have evicted a live stdlib
alias, and popping a real module so a later file re-imports it makes two module objects of one name,
at which point an `except SomeError` raised through one cannot catch the other's class.

The predicate now reads one thing: whether `__spec__` is a genuine `importlib.machinery.ModuleSpec`,
the object the import system builds when it actually located something and which nothing in a test
fabricates. `test_A_REAL_MODULE_SERVED_BY_A_NON_MODULE_CLASS_IS_STILL_REAL` rebuilds that shape from
the import system's own spec so the arm does not depend on zipp staying installed.

**A hand-picked sample could not have found that.** The census is the arm that earned its place.

**⛔ And the arm that justified the `isinstance` was itself wrong**, red within a minute of being
written. A plain `MagicMock()` RAISES `AttributeError` for `__spec__`, so `getattr(..., None)` is
`None` and a `is None` test would have classified it correctly — my stated reason for preferring the
`isinstance` was false. It is `MagicMock(spec=<module>)` that answers with a child mock, and a grep
found no such construction for a module anywhere in this repo. So
`test_THE_SPEC_CHECK_IS_AN_ISINSTANCE_AND_NOT_A_NONE_TEST` says out loud that it defends a shape the
population does not yet contain, with positive controls for both mock forms.

### Three matcher defects in one ratchet, two of which read as a moving population

The ratchet over the deferring file set needed its pattern written three times:

1. **14** — double-counted the one file that defers in both spellings.
2. **10** — `[^\n]` inside a grep bracket is the complement of `{\, n}`, so it silently dropped
   every guard whose subject contains the letter **n**.
3. **13** — anchored only the `if` alternative, so `tests/conftest.py` matched on a COMMENT stating
   how many files use `sys.modules.setdefault`: the file that provides the harness reporting itself
   as a member of the population it exists to shrink.

The answer is **12**: 6 by `sys.modules.setdefault`, 7 by an `if`-guard, one file using both.
Defects 2 and 3 read as *a population that had changed*, not as *a matcher that was wrong* — which
is why `test_THE_DEFERRAL_MATCHER_READS_CODE_AND_NOT_PROSE` is an arm and not a comment, with
controls in both directions including the exact comment form conftest tripped on.

### What the harness cannot see, stated rather than implied

- **The snapshot is post-collection.** Taken when the module's first test sets up, so a double
  installed at IMPORT time is inside the snapshot and survives. Measured: exactly 1 of the 39 files
  that assign to `sys.modules` acts at module level, and it registers a loaded `main.py` under a
  unique name rather than stubbing a shared dependency — so bracketing collection would be
  machinery for a case that does not exist yet.
- **It cannot undo a parent attribute.** `sys.modules` is all the fixture sees, so a file that does
  its own stubbing AND repoints `pkg.sub` on a real `pkg` leaves that attribute behind. There is no
  snapshot of module attributes to diff against. `stub_modules` restores it because it knows what it
  set; hand-rolled stubbing does not, which is the reason to prefer `stub_modules`.

### A renamed fixture's name had two homes

`_restore_globally_stubbed_modules` → `_no_module_leaves_a_double_behind`. The name appeared in
`tests/routing/test_a_menu_on_the_wire_can_be_answered.py`'s docstring, where the surrounding
*claim* — that a module-scoped snapshot is taken after collection — is **still true** and is now
written beside the fixture as well. Updated there. The dated measurements file of 2026-09-26 also
names it; that is a record of what was measured then and is left alone, with the rename noted here
so a grep forward lands.

### Instrument notes — two of them are the item's own defect, reproduced inside the seal

- **All 14 conftest mutants SKIPPED with 0 matches.** `tests/conftest.py` sits CRLF in this working
  copy while the new seal is LF; `core.autocrlf=input` means both commit as LF, so nothing in the
  tree needed changing. A target written with `\n` matches ZERO times in a CRLF file, which the
  runner reports as SKIPPED — **i.e. as a patch that no longer applies, when nothing about the
  subject had moved.** The runner now normalises each mutant to the file's own line ending and says
  why.
- **M7 SKIPPED on an ANCHOR COUNT.** `    finally:` appears twice in conftest — the caplog fixture
  has one. That is a population fact, not a patch failure. Widened to the whole `try`/`yield`/
  `finally` spine. `if True:` was chosen over `except BaseException:` deliberately: swallowing the
  exception would make the arm fail on its own `pytest.raises` instead of on the assertion about the
  leak, so the mutant would be killed for the wrong reason.
- **⛔ M7 then reported WRONG FAILURE, and the defect was in the ARM.** Its named arm did fail, but
  the fragment I required belonged to a different arm, because
  `test_stub_modules_RESTORES_WHEN_THE_BODY_RAISES` ended in a **bare** assert with no message.
  **A nonzero exit is not a red, and a named arm without a message cannot prove which red it was.**
- **⛔ The seal about cross-file leakage leaked between its own arms.** The M7 mutant left the
  invented name in `sys.modules` and three later arms take its absence as a premise, so ONE CORRECT
  KILL READ AS FOUR FAILURES — the exact defect the file exists to close, reproduced inside the
  file. Closed with an autouse fixture that pops the invented names before and after every arm. The
  mutation pass found this; a green run never would have.

- **THREE FIRES OF ONE ORDER IS ONE SAMPLE.** My first three fires of this seal ran the arms in
  the SAME sequence: `pytest-random-order` is a declared dependency but is INERT without
  `--random-order`, so a plain `pytest` run is deterministic. For a seal whose whole subject is
  order dependence that is not a fire at all. Re-fired under three explicit seeds with
  `--random-order-bucket=global`, and the three orders were CHECKED to differ (md5 of the collected
  sequence) rather than assumed to — a varying-order run whose order did not vary is precisely the
  quiet arm this file exists to argue against. 22 passed in each.


### ⛔ An unexplained +/-2 in the skip count, recorded rather than explained

The acceptance criterion is met exactly: the failing set went 45 -> 43, the two vanished identities
are precisely
`test_adr0019_engine_o_contract_a.py::test_n1_calls_baml_with_two_value_enum` and
`::test_n1_on_topic_still_dispatches`, and **zero** identities are new.

But the other columns do not fully reconcile. Total collected is +22, exactly the new seal's arms.
Failures are -2, accounted for. That leaves passes +2 and skips -2 that this change does not
explain: **two tests that were skipped in the before run ran and passed in the after run.**

I could not name them, and did not guess:

- `-q` prints one progress character per outcome, so I aligned the two streams with difflib to map
  each flip onto a collected id. **The map failed its own validation** — only 2 of 43 `F` positions
  mapped to a name that actually appears in that run's FAILED lines, because the captured stream is
  5110 characters against 5146 outcomes. The validation existed so that a drifting positional map
  could not hand me two confident wrong names; it did its job and the method was abandoned.
- The population is not small enough to bound cheaply: **130 test files can skip, and 104 of them
  gate on REACHABILITY** (`verify_connectivity`, `connect_to_custom`, "unreachable") against the
  live sandbox, not on importability.

**And that last fact means the delta may not be mine at all.** The before and after runs are 30
minutes apart against a cluster with port-forwards up. For a network-gated skip, the two runs are
not a controlled comparison — the subject moved. The control that would settle it is to VARY
NOTHING and re-run: if the skip set is not stable run-to-run at a fixed tree, the +/-2 is
environmental and this change is not implicated. **That control is queued, not done**, so the delta
stands as unexplained here rather than as harmless.

What can be said without it: no identity that passed before is failing now, which is the property
the commit is claiming.

---

## Numbers

| measurement | figure |
| --- | --- |
| full suite before (`d3944da8`) | 45 failed, 4876 passed, 201 skipped, 2 xfailed — 21m12s |
| full suite after | 43 failed, 4902 passed, 199 skipped, 2 xfailed — 30m41s |
| new failing identities | **0**; the 2 dispatched reds GONE, by identity |
| the adr0019 pairing | 8 passed (was 2 failed, 6 passed) |
| harness seal | 22 arms, 3 fires in 3 DISTINCT orders, 22 passed each |
| harness mutation | 16/16 killed by their named arms, 0 skipped |
| deferring population | 12 files, ratcheted |

## Not done, and why

- **Item 3's "after" half** — recall across MAINTENANCE three fires before/after needs the fix
  RUNNING in the fleet, so it is gated on roll #6 firing.
- **`fadda10f` and `d3944da8` are local only**, on `master` in the master tree rather than
  `lane/01`. Flag for Chris: replay onto `lane/01` if wanted.
