# s1000d_mrad fixture

Two files, two separate provenances. Do not hand-edit either; regenerate from its own source.

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
