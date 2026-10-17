# s1000d_mrad fixture

Three files, three separate provenances. Do not hand-edit the first two; regenerate each from its own
source. The third is authored, and changes only by ruling.

## `mrad.ttl`

Six sample S1000D data modules for the array-module fault (`MRAD-ARR-0417`), turned into `mil:`
triples by doc-tools PR #63 (head `4a6df088`, open/unmerged at the time this copy was made). This
is a SAMPLE corpus over six sample MRAD XML data modules, not the whole MRAD manual. Regenerate it
from PR #63's parser output when that PR's parsing rules change — never edit the triples by hand.

## `GROUND-TRUTH.json`

Copied unchanged from `dt63/tests/fixtures/s1000d/mrad/GROUND-TRUTH.json` (the doc-tools PR #63
branch). Its own `status` field says what this README repeats: it is a **DRAFT** — "ground truth
when both sides confirm it" (ADR-0046 v2 §9) — not yet a ratified cross-repo contract. Treat
disagreements between this file and what the declared-query verb actually returns as findings to
report, not defects to silently patch over in either file.

## `walk-MRAD-ARR-0417.json`

THE CONTRACT 7f BUILDS TO (architect, 2026-10-16): the expected rendered walk for `MRAD-ARR-0417`,
options and all. `mrad.ttl` stays the per-module drift check. Ruled shape: an option's DMC became
`procedures[]` (ordered, min 1), and an option may carry cited values `{value, evidence_ref}`.

- `citations` is the real `s1000d_fault_walk` rendered over `mrad.ttl`, not a transcription.
  DMCs are canonical labels, with no `DMC-` prefix. `bit_text` is the module's own text.
- `options` are `GROUND-TRUTH.json`'s four. Each one's `dmcs` is split by what it is
  (OVERRULED, architect 2026-10-17: 421A is the module an option comes FROM, not a procedure):
  - `procedures[]` holds only the procedural modules: `520A` then `720A` for the two replace
    options, and none for options 1 and 2, whose whole action is 421A's own text. That empty list
    is in tension with the earlier "min 1"; it is with the architect;
  - 421A stays in `citations.fault_isolation`, and each `action` cites it: the values are 421A's
    `isolationAction` text, verbatim;
  - the IPD module (941A) is the `evidence_ref` of the part values it supplies;
  - option 4 cites the 320A interval, `{value: "180 days", evidence_ref: 320A}`, the same shape
    (the value is the label of 320A's `Periodic_Array_Inspection` planning interval).

`tests/test_the_mrad_walk_contract_agrees_with_its_fixture.py` seals it against `mrad.ttl`. The
procedure ORDER is not in `mrad.ttl` (`refersToDataModule` is a set), so no arm checks it yet: 7f's
output carries it (an `rdf:List` or an explicit `mil:stepIndex`), and the order arm goes in once 7f
says which.
