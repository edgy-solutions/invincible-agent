---
title: pub-tools carries the CP1252 repair and the V_CHARACTERISTICS fold forward on a reviewed build
feature: cross-cutting
lane:
repo: pub-tools
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: architect via Chris 11-05, item 2: pin ed93f7b1, open a pub-tools item to carry the fix forward on a reviewed build
updated: 2026-11-05
---

**The chart pins pub-tools at `ed93f7b1`, and sandbox loses one commit when it rolls back.** From 0.4.80, base values pin the image digest `ed93f7b1`, the `master` build of source `1aa2cbe` that was reviewed on 09-23. Until now sandbox ran `1555b341`, which was never reviewed. It is the build of source `e5612fa`, exactly one commit later.

**`e5612fa` holds two changes, not one:**
- `fix(publog): repair stray CP1252 bytes`. It adds `_stream_utf8_normalized` and `_repair_line_cp1252` to `pub_tools/lake.py`.
- `fold V_CHARACTERISTICS overflow fields`. `MERGE_OVERFLOW_TABLES = {"v_characteristics"}` and `OVERFLOW_COLUMNS = 16` rejoin ragged rows into the last column, 12 of the 44.6M rows.
- It touches `pub_tools/lake.py` (+269), `component.py` (+3) and `test_lake.py`. It changes no lock and no Dockerfile.

Because the commit carries more than the CP1252 repair, the architect ruled that it is not reviewed by reading the CP1252 fix alone. `ed93f7b1` stays pinned until a build that carries both changes has been reviewed.

**Done when:**
- a pub-tools build carrying both changes of `e5612fa` is reviewed, and the review is recorded with its digest;
- the chart's `global.imageDigests` row for `ghcr.io/edgy-solutions/pub-tools` moves to that digest, and the pin comment in `values.yaml` cites the review;
- sandbox's next pub-tools ingest of PUB LOG stages `V_CHARACTERISTICS` without the ragged-row failure.
