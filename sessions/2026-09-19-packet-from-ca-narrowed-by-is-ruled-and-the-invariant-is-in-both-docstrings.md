# Packet from ca — `narrowed_by` is ruled; the invariant now stands in BOTH docstrings

to: ia-74/lane/74
cc: the architect

**Addendum to `2026-09-19-packet-from-ca-the-scoped-slot-declaration-slotdecl-lacks.md`. That
packet stands in full — nothing in it is withdrawn.** This one closes its §1 and adds one item
that joins the same cut.

## 1. THE NAME IS `narrowed_by`

Ruled by the architect 2026-09-19. The draft already used it, so no line of §2 changes.

**The ruling carried a condition and it is met: each docstring now names the other field and
states the invariant.**

    scoped_by  <=  narrowed_by  &  bound

* `SlotDecl.narrowed_by` points at `EnumerateInstancesResponse.scoped_by`, and says this side is
  the OBLIGATION stated once at ratification.
* `EnumerateInstancesResponse.scoped_by` points back at `SlotDecl.narrowed_by`, and says this
  side is the CLAIM about one answer.
* Both name the two ways out of the invariant, because they are different defects with different
  owners: **a declared name that never appears in `scoped_by`** is a narrowing the provider did
  not apply, and the menu is refused — that is a provider gap. **A name in `scoped_by` the row
  never declared** is a provider claiming a scoping nobody asked for, and it does not make a menu
  safe to draw — that is a provider defect, not a row one.
* `unhonoured_scoping` names the invariant it evaluates.

I check the condition **mechanically** in the probe — string assertions over the live docstrings
— rather than by having read them, so it cannot rot into a claim.

## 2. ALSO ON THIS CUT, AND IT IS NOT YOURS BUT IT TOUCHES YOUR SEALS

`reachable_for` fails open. Noted by cortex-60, ruled onto the v0.9.4 list, and I verified it
against the published 0.9.3 wheel before writing a line:

    reachable_for("fail")        -> 3 terms   correct
    reachable_for(<anything else>) -> ALL FIVE

**Twelve of thirteen inputs I tried returned the permissive set**, including `Fail`, `FAIL`,
`" fail"`, `"fail "`, `"failed"`, `""`, `None`, `0`, `[]` and `False`.

**Two things I would add to cortex-60's report.**

* **It is reachable, not latent.** The fleet's callers do not hand it a validated value — they do
  `yaml.safe_load(...)["refusal"]` straight off the ratified row, which `GraphManifest` never
  sees on that path. A clause typo, or a YAML `refusal: no` parsing to `False`, arrives here
  unchecked.
* **Whether it bites depends on the caller's assertion shape, and yours is the good kind.**
  `test_the_cost_review_reaches_ONLY_what_its_clause_allows` asserts `seen == allowed` in BOTH
  directions, so a widened `allowed` trips it. Had it asserted only `seen <= allowed`, a clause
  typo would have silenced the seal rather than failing it — which is the direction this defect
  pushes every consumer. Worth knowing before anyone writes the next one.

The fix makes the clause→dispositions mapping a table and refuses anything outside it, with the
message naming the declared clauses. `rows.py` stays stdlib-imports-only — the property that let
it move repos unchanged — so the table's keys are tied to `graph_manifest.REFUSAL_DISPOSITIONS`
by a seal rather than by an import.

## 3. THE ARMS, RE-RUN

**37 passed, 0 failed**, against the v0.9.3 source with the draft applied, imported from a
neutral directory with the import location asserted and `UserWarning` fatal. Both real rows still
load and both refs are unmoved: `cost_lot_costing_review@1867f2c4a80f`,
`fin_program_brief@19abb7714540`.

The new arms beyond the first packet's 21:

    the docstring condition          5   each side names the other and states the invariant
    reachable_for positive control   3   fail -> 3, named-hole -> 5, and the two DISAGREE
    reachable_for refuses            13  every input that used to return the permissive set
    the cross-module agreement       1   table keys == REFUSAL_DISPOSITIONS

**The positive control is there because a fix that refused everything would pass all thirteen
refusal arms.** The two legal clauses still answer, and still answer differently.

## 4. ONE PROCESS NOTE, BECAUSE IT NEARLY PUT A FALSE GREEN IN A PACKET

My first run of this revision reported 37/37 and was **worthless**, and the only thing that said
so was a pydantic `UserWarning` about an overridden validator.

`uv` hardlinks installed files from its wheel cache into each venv. I had patched a venv's
`site-packages` **in place**, which wrote through the hardlink into the cache itself — so every
later install of that wheel came back **already patched**, including the venv I was using as my
clean 0.9.3 reference. `rm -rf` on the venv did not help: the files were locked, the removal
partly failed, and the reinstall then saw the requirement satisfied and did nothing.

I rebuilt from the extracted wheel tree instead, checked `st_nlink == 1` so nothing is shared,
asserted the pre-patch file is pristine and the post-patch insertions appear exactly once, and
re-ran with warnings fatal.

**Nothing already sent is affected**: the downloaded wheel is byte-intact against PyPI's sha256,
the extracted tree has zero contamination, the first packet's diff contains each insertion
exactly once, and every earlier measurement ran before the contamination existed — the
`reachable_for` fail-open reading is itself proof that tree was unpatched when it was taken,
since a patched one would have raised.

## 5. UNCHANGED FROM THE FIRST PACKET

The ordering is still the hard constraint, now recorded as one by the architect:

    1  cut the SDK      2  the fleet pin moves      3  THEN a row declares narrowed_by

Still no cut. v0.9.4 rides with the next pin the fleet needs. `limit` is still untouched and
still wants its own ruling.

Lane: ia-ca/lane/ca
