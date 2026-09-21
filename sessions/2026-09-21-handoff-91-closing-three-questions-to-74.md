# Handoff — lane/91 closing, three architect questions never landed

to: ia-74/lane/74
from: ia-91/lane/91, 2026-09-21

## Current state

Branch `lane/91`, sha **`8055c4b`**, 0 ahead / 0 behind `origin/lane/91` (measured: `git rev-list
--left-right --count origin/lane/91...HEAD` = `0 0`). Tree clean. Master is **`70541a0`**;
**`f6b3457` IS an ancestor of master** (measured: `git merge-base --is-ancestor f6b3457
origin/master` = true).

**Not yet on master** (measured: `git log origin/master..lane/91 --oneline`):
- `8055c4b` — docs(packet): scope the inbox-red count to its sha, name the disagreement
- `23a7e13` — docs(sessions): 91's packet to lane 1, six read-by stamps

Both are `sessions/` docs only — no engine code is ahead of master. lane/91 is done; nothing
engine-side is stranded.

## Decisions and rulings received

- **f6b3457 accepted, merged.** Finance stands at **6/8**; the 2 remaining failures are both
  ROUTING, not payload (architect confirmed this reading, 2026-09-21).
- **Partition (c) of the 2026-09-19 lexical baseline is now empty** — the architect ruled this
  should be recorded beside the baseline file (`docs/measurements/walk-census-run-2026-09-19-
  lexical-baseline.txt`), not edited into it. **Not yet done — pick this up if it's still open;
  I did not get to it before this handoff.**
- **Item 4 (unaddressed-packet count, 5 vs 6 vs Lane 1's 9) stays recorded and held** — no
  action, per architect: "It stays recorded with your command named, and it stays held."
- Cost-side fix (referent + enumerate) explicitly **held**, not landed — 2026-09-17 packet rules
  the three pieces (referent, enumerate, SDK field) land together or not at all.

## Tried and failed

- Nothing failed this session — this is a closing handoff, no new engineering work was started
  after the architect's last dispatch (three questions below arrived but were not actioned; see
  Open questions).

## Open questions — the three that never reached me in time, now yours

**1. Lot 3's menu — SDK version.** Can the `rate_vintage` referent entry
(`agent_fleet/cost_agent/slots.py:70`, `_REFERENT_KIND`) plus a lot-scoped
`/enumerate_instances` (`agent_fleet/cost_agent/main.py:500`) be built against the **pinned
v0.9.3** SDK, or does it need `scoped_by`/`narrowed_by` from lane/ca's unmerged v0.9.4 draft
(`iagent-mesh-sdk`, `lane/ca`, head `711c6d0` as of 2026-09-19 — **re-check this sha, it's two
days stale**)?

Held reasoning (measured against the installed 0.9.3 wheel, not source): `iagent_mesh
.graph_manifest.SlotDecl` is `extra="forbid"` and has no `scoped_by` field. **The referent alone
gives `class_wide`, not the two scoped chips** — confirmed live: fixing only the referent moves
the card from `no_referent` to `class_wide` because the gateway's `unscoped_but_required` guard
in `src/iagent_pure/slot_disposition.py` (the `if not referent` branch, which returns *before*
any enumerate call) correctly refuses to draw a class-wide menu for a scoped slot. Both pieces
are needed together; the SDK gap is what's blocking the second piece.

Architect's ruling: if 0.9.3 suffices, build both sealed so a referent WITHOUT scoping reds. If
it needs 0.9.4, build nothing against a branch — report and let the architect call the pin
(order is cut → pin → declare, Chris's word).

**2. performance-indices classify.** `finance-performance-indices` returns `no_verb_classified`
when the correct verb (`mesh:finPerformanceIndices`) ranks **first of seven** candidates
(measured 3x, stable). Retrieval works; classification declines to commit. **I never located the
classify step itself this session** — read-only task, report file/line/measured values (is it a
threshold, a margin-between-candidates check, or an abstain rule?), do not fix. Start by grepping
for where `no_verb_classified` / the `verb` slot elicitation is constructed — likely near the
routing/classification code the gateway calls before dispatch, not in `finance_agent/main.py`
(engine-side is confirmed clean: `fin_performance_indices` answers 200, 6 rows, no
`value_unit`).

**3. variance-drivers candidate scores.** "which account is driving the overrun on NP-MERIDIAN"
routes to `fin_variance_analysis` (VARIANCE_TREE) instead of `fin_variance_drivers`
(CONTRIBUTION_RANKING) — regressed from a recorded PASS, stable across 3 fires. **Hypothesis
only, never verified**: `fin_variance_analysis`'s synonym `"what is driving the overrun"` is
near-verbatim to this sheet phrasing. **No synonym fix** — there's no offline harness to score a
question against verb declarations in both directions, so a blind edit can move other rows
silently. Add one measurement if reachable read-only: the live candidate list with scores for
this exact question, as it stands now. I did not capture this before closing — do it fresh
rather than trusting my 2026-09-19 read.

## Gotchas

- **Lot 3 refusal is ~1-in-3 flaky at subject grounding.** Fire 1 of 3 can come back
  `no_match`/`subject_unknown` with no refusal at all — this is NOT a regression, it's the known
  flake. Any claim about this row needs **three fires**, not one (I nearly shipped a false
  finding on a single fire).
- Port 18083 may still hold a stale `fakever.py` stub answering 500 to every keycloak token POST
  regardless of credentials — check identity both directions (real: 400 bogus / 200 good; stub:
  500 both) before trusting a keycloak error from the census runner.
- 8 post-projector finance payload JSONs + an index are placed **uncommitted** in
  `c:\Users\cnogr\git\cortex-ui\sessions\`, by instruction — do not commit them:
  - `2026-09-19-INDEX-finance-payloads-from-91.md`
  - `2026-09-19-payload-finance-*.json` (8 files, one per finance-walk-sheet.md prompt)

## NEXT TASK

Pick up the three architect questions above, in order. Start with (1) — answer the SDK-version
question first, one line, before building anything. Then (2), read-only. Then (3), read-only,
one measurement, no synonym edits. Separately: record the "partition (c) is empty" note beside
the 2026-09-19 lexical baseline if the architect hasn't already had someone else do it.

Lane: ia-91/lane/91
