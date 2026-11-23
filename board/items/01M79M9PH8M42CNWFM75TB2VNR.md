---
title: TI page 2 is invisible to find_tables, so its 11 customer part numbers cannot be emitted
feature: pcn-pdn
lane: doc-tools/lane/7f
repo: doc-tools
status: open
priority: later
blocked_on: []
pr: []
ruling_ref: Architect via Chris 2026-11-12 -- put the open gap (TI page 2's table is invisible to find_tables) on the board with an owner. The rule question #107 deferred it behind is settled by #191 (customer_mpn is its own scored row field), so what remains is detection.
updated: 2026-11-12
---

Page 2 of TI PCN#20210316000.1 carries a 15-row DEVICE + CUSTOMER PART NUMBER table. `find_tables` returns **zero** tables for that page, so no tier downstream can see it.

Measured twice, by different methods: 2026-10-10, by the fixture in PR #107 built from the real artifacts pulled in-pod; and again 2026-10-29, recorded in `scripts/pcn_ground_truth.json` — *"pdfplumber finds no table on page 2 under either strategy … NOT CURRENTLY EXTRACTABLE BY ANY TIER."*

What is unreachable: 11 distinct customer part numbers (15 rows, 3 literal `null` cells that emit nothing, 1 duplicate). They are not affected parts, and the nine required devices on page 3 are unaffected — those extract 9/9.

## The rule question it was parked behind is now settled

#107 reported this as *not fixed* because the general question — whether a Customer Part Number column is a parts source — was formally deferred (TYC yes, TI no by ruling). #191 made `customer_mpn` its own row field, scored as its own column, and `tests/test_ti_pcn_live_miss.py::test_the_customer_alias_ruling_is_implemented_on_page_twos_own_header` pins that ruling on page 2's own header.

So this is no longer a rule gap. It is a **detection** gap, and the last one open on this notice.

## Guarded, so it cannot regress silently

All landed in #107/#191 and present in the rolled pin `e73d8b08`:

- ground truth carries `expect_absent_mpns` (the 11 strings verbatim) and `customer_mpns_source`, which records what they ARE and the measurement behind it;
- `pcn_score.py` has `ruled_out`, a **labelled subset** of `spurious` — the part stays counted in `spurious`, so no verdict can be weakened by anything added here, and a test pins exactly that;
- requiring and ruling out the same part aborts as a ground-truth defect;
- tests pin that page 2 can emit nothing not already adjudicated, and that if it is ever detected every spurious part is named.

## What closing it requires

A tier that can read that page: a different table-detection strategy, or a vision pass over page 2.

Detection alone is not sufficient, and this was measured in #107 — if the grid were detected, `grid_outcome` accepts it on its own merits and both `device` and `part number` pair as affected, yielding **19** parts (8 devices + all 11 customer part numbers) and declining nothing. It has to land together with the customer-alias routing, which now exists but has never run on this page because the page has never been visible.

## Why `later`

Nothing is waiting on it: the 11 are not a recall target today (*"scoring them as a recall target would be scoring a page no tier can read"*), and the corpus gate is green on parts at the rolled pin — 512/512 across three fires. It is parked until a detection tier that can read page 2 exists. Reorder freely if a vision tier lands for another reason.

Owner: lane 7f, which owns extraction in `doc-tools`.
