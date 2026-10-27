to: invincible-agent/seat/architect
cc: invincible-agent/lane/01
from: ia-saf/lane/saf
date: 2026-10-08
re: FRACAS backend close, PCN26-184 search, PR from lane/saf

## What closed
- Source seam (agent_fleet/safety_agent/failure_source.py): `FAILURE_SOURCE_CONNECTORS`
  (`name=module:callable`, callable(by) -> SystemOfRecordQuery) names the deployment's real
  connectors. Unset = sandbox fixture. Set = ONLY those (the fixture never mixes into a real
  history). Unbuildable connector, raising connector, or unusable hit = `SourceUnavailable`;
  all-or-error; duplicate citation kept once.
- Route: 200 `refused` / `outcome: source_unavailable` / `connector` (never an empty card, never
  a 5xx). `engine_fault` is still what a bug in a measure gets.
- Test change: `test_a_connector_that_cannot_reach_its_source_is_never_an_empty_answer` expected
  a raw ConnectionError; the SUBJECT changed (now `SourceUnavailable`, cause kept). The invariant
  it guards (never an empty answer) is unchanged. Not a weakened seal.
- Overlay registration: `policy/overlays/sample/platform_programs.yaml` already maps PLT-ALPHA and
  PLT-BRAVO (PLT-CHARLIE deliberately unmapped = denied); no change needed.
- Mutants (each killed by the named arm): dedupe off, hit validation off, fixture-always, route
  except removed.

## What cannot close without a roll or live data (checkable blockers)
- B1. The real `sor-events-a` / Relyence connector CLASSES. The SDK ships none (its docstring).
  They live in the deployment overlay image; this engine names them via the env var above.
  Check: `grep -n FAILURE_SOURCE_CONNECTORS helm -r` is empty; no chart value sets it yet.
- B2. Helm wiring of that env var is not done (chart change + roll; no rolls under this order).
- B3. `SANDBOX_PROGRAM_BRAVO` is not seeded in Topaz (human step); alice's BRAVO rows are
  invisible live until it is.
- B4. Live walk of Q6/Q7 and HAZ-1004 row: needs a roll naming my shas and a Lane 1 packet.

## PCN26-184
Searched: c:\tmp\doc-tools-pcn, c:\tmp\pcn-gate-evidence, c:\tmp\doc-tools-fix, doc-tools-mfg,
C:\Users\cnogr\git\doc-tools (grep by content and by name), Downloads, OneDrive Documents. The
PDF/extraction is NOT in any of them; doc-tools' 9-notice PCN corpus does not contain it. The
only place it exists is lane 74's Friday walk (c:\tmp\ia74p\sessions\friday-demo-runbook.md s.3
and c:\tmp\ia74p\tests\test_pcn26_184_the_parts_answer_holds.py): a notice naming parts 5530-184
and 5530-185. It carries NO platform and NO failure mode, so I built NO failure fixture from it
(that would be invention). The one thing derivable is asserted:
`test_PCN26_184_parts_have_no_failure_history_in_the_sandbox_sources` (no source holds a failure
for either part; the verb refuses "unknown part"). No proprietary identifiers in the diff.

## Cortex packet (untracked, invincible-agent/sessions/)
2026-10-08-packet-to-cortex-ts-fracas-bindings-final-shape-supersedes-the-earlier-packet.md
to: cortex-ui/lane/cortex-ts. Card payloads unchanged; new: the `source_unavailable` refusal body.

## Tests (alone, no full suite)
- tests/safety/test_fracas_source_wiring.py + test_fracas_connector_and_trend.py: 19 + 23 passed.
- Area, after merging origin/master: `uv run pytest tests/test_the_walk_census_is_derived_from_the_sheets.py
  tests/test_walk_census_refuses_an_unknown_only.py tests/safety/
  tests/finance/test_the_wire_carries_what_the_engine_declares.py
  tests/test_the_method_block_is_one_shape_across_engines.py tests/test_endpoint_gating_manifest.py
  -q -p no:cacheprovider` = 450 passed, 3 skipped, 0 failed.
- Before the merge, a wider run incl. tests/planning/ had 7 reds, all cortex-ui/lane-74 drift
  (ILLUSTRATION/WORKFLOW_CASE contracts, NoticePartSet); none touch this change. Not re-run after
  the merge (not owned by this lane).

## PR
Base master. Master already holds up to 586c04c9; the PR carries 3e8d5435 (bindings), the
SystemOfRecord seam commit, the handoff, the digest and one merge of origin/master (one conflict
in walk-census.yaml, both sides kept).

## Questions for the architect
1. A source outage is 200 `refused`/`source_unavailable`, unlike the Topaz outage (503). Both are
   "could not verify/read". Keep the split, or make both 503 / both 200?
2. Who owns the Relyence / sor-events-a connector classes and the overlay image that carries them
   (B1), and which lane wires the chart value (B2)?
3. PCN26-184: is the intended source a document outside these paths? As found it supplies part
   numbers only; should failure fixtures wait for a real extraction rather than be authored?
4. Another lane's script at the shared /tmp/edit2.py was run by mine by mistake and edited
   tests/cost/test_a_canvas_exports_the_alpha_document.py in ia-saf; I reverted it before any
   commit. /tmp is shared across lanes: ask for per-lane scratch names?
