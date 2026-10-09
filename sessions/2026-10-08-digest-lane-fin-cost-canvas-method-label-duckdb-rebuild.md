to: invincible-agent/seat/architect
from: ia-fin/lane/fin
date: 2026-10-08
re: digest -- cost canvas export, method_label consumption, duckdb rebuild. PR: PR_URL_HERE

No rolls, no cluster writes, cortex-ui untouched. Commits on lane/fin: 3a61c42e, 46374640
(over a15b6282 and 5d646e29 from the gating-manifest fix). Merge-tree against origin/master is
clean (130 commits behind, no conflicts).

## 1. Cost export as a canvas of all cards

Finding: the fleet already exports a canvas, and the canvas is a list of answers.
- Gateway: POST /export/package takes `answers` (each `artifact_id`), src/iagent/gateway.py:1978;
  ExportPackageRequest at :1780-1796; `_resolve_export_answers` :1799 (refused, never dropped).
- Engine: agent_fleet/cost_agent/canvas.py `EXPORTABLE` and `resolve`: eight exportable verbs,
  six page sections; entitlement first, then exportability.
- Acceptance: tests/cost/test_a_canvas_exports_the_alpha_document.py:48-64, `ALPHA_CANVAS` is one
  answer per exportable verb and equals the 09-06 document's lots and sections.
- Template-based precedent (finance): `_export_package_from_template`, gateway.py:1857, with
  `panel_dispatch` / `recipient_scope_for` in src/iagent/canvas_template.py:256 / :280.

Done: tests/test_gateway_export_routes.py, new test at the end -- one answer per EXPORTABLE verb
(derived, not typed) through the gateway; none dropped, order kept, and the forwarded canvas
resolves to all six sections and every entitled lot. That is the join, asserted in one place.
Route behaviour is unchanged, so the manifest rows for /package_export and /artifact stand.

NOT done, deliberately: a ratified cost canvas TEMPLATE (policy/canvases/). It cannot be added
without a ruling -- see Q1 and Q2.

## 2. method_label consumption

- cortex-ui d7d6593 and bd782c5 both exist and are ancestors of cortex-ui master.
  d7d6593: COMPETING_MEASURES and FORECAST_MEASURE row key `method` -> `method_label`, mandatory,
  no fallback (contract.ts, Card.tsx, ForecastMeasure.contract.ts/.tsx). INPUT slot `method`
  unchanged. bd782c5: illustration test settle only, unrelated.
- Fleet side already emits `method_label` (finance_agent/measures.py:819, :937;
  presentation_agent/capabilities.py:433, :446) and `_MIRROR["FORECAST_MEASURE"]` reads it
  (tests/planning/test_producers_speak_their_archetype.py:159). No fleet code reads a row-level
  `method`; the one remaining hit is the INPUT slot name, finance_agent/main.py:711. engine-fin's
  503s unchanged. Added the retirement addendum to the ruling-5 measurement doc (section 8).
- Three reds remain against current cortex master and are NOT method_label (Q3).

## 3. Reproduce dist/cost-validation-notional-customer-alpha.html from the duckdb

Script: scripts/rebuild_cost_package_from_duckdb.py (+ optional `as_of` on build_html in
scripts/build_cost_package.py). Date and sha are arguments; nothing reads a clock. The HTML was
never opened; inspected by sha256, byte count and package-data keys only.
- Inputs: dist/cost-notional-customer-alpha.duckdb (sha256 80e4f2f6...), algorithm sha 06b81540...,
  as-of 2026-10-06 (the last two read from the existing page's package-data via --like).
- Existing page: 18405244 B, sha256 be4a40571996880420a4ac1caf1367ef7133a38c570116f58d8fb3c0fa0a8fd7.
- FINDING: the existing page is the ONE-FILE page: package-data has no `dataset` key and the page
  has zero section markers. It does not embed the duckdb's rows, so a build "from the duckdb"
  (slice 2) is a different, larger page: 18499085 B, sha256 ca293528be9de259..., differing in
  package-data keys `dataset` and `locator` and in the template text.
- `--slice1` rebuilds the one-file page: sha256 be4a4057... IDENTICAL to the existing file, and
  identical on a second build (`--twice`). The duckdb-based page is also identical to itself twice.
- Seal: tests/cost/test_a_package_rebuilds_byte_identically_from_its_duckdb.py (skips by name when
  duckdb or the Pyodide cache is absent).

## Tests (exact)
- `uv run pytest tests/test_endpoint_gating_manifest.py tests/test_gateway_export_routes.py tests/finance -q`
  -> 370 passed, 3 skipped, 2 failed (both in test_the_wire_carries_what_the_engine_declares.py, cortex drift, Q3).
- `uv run --with duckdb==1.5.2 pytest tests/cost -q` -> 347 passed, 3 skipped.
- `uv run pytest tests/planning/test_producers_speak_their_archetype.py tests/finance/test_eac_comparison.py tests/finance/test_the_wire_carries_what_the_engine_declares.py -q`
  -> 56 passed, 3 failed (Q3).
- Rebuild: `uv run --with duckdb==1.5.2 python scripts/rebuild_cost_package_from_duckdb.py --duckdb <duckdb> --like <html> --out /tmp/rb1 --slice1 --twice --compare <html>`
  -> idempotent IDENTICAL, compare IDENTICAL.
Not run: the full suite (Lane 1 only).

## Questions needing an architect ruling
1. What does "cost export as a canvas of all cards" mean as a product? I read it as one export
   covering every card, via the existing answers-list canvas (done, sealed). If it means a
   ratified template like program_finance (cards seeded and exported from one definition), say so;
   that is a larger change.
2. If a template: `Package.audience` is `Literal["program_office"]` and `recipient_scope_for`
   builds `program_office.<program>`, but cost recipients are `notional-customer-alpha|beta`
   (cost_agent/seed.py:169) with their own readers. Does a cost template widen the audience set
   and the scope derivation, or does cost keep its own recipient model? The cost verbs also need a
   `lot` binding, which program_finance's single-slot shape does not carry.
3. cortex master has moved past the fleet's mirrors: SHORTFALL_GRID cell interface unparsed,
   ILLUSTRATION and WORKFLOW_CASE with no projector path, NoticePartSet one-sided. Three reds
   (test_the_contracts_are_actually_being_read, ..._has_SOME_projector_path, ..._MIRRORS_agree_FLEET_WIDE).
   Who owns the projector/mirror updates? Not touched here.
4. Which page is "the" alpha validation document? The shipped file is the one-file page; the
   dataset page ships beside a duckdb. If the duckdb page is intended, the file in dist/ is stale
   by design and should be regenerated with this script.
5. duckdb is declared only by cost_agent (duckdb==1.5.2), not the root venv; the rebuild script and
   its test need `uv run --with duckdb==1.5.2`. Add it to a root extra, or keep it ephemeral?
