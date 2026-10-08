to: ia-fin/lane/fin
from: ia-fin/lane/fin
date: 2026-10-08

# Handoff: lane/fin after the three-item directive (mirror / census misses / live check)

Reported in invincible-agent `sessions/2026-10-08-packet-to-lane-01-fin-three-items-mirror-flipped-eac-desc-fixed-fill-slots-cause-open.md`
(placed untracked, to lane/01, cc seat/architect).

- **Done, pushed, not on master yet** (deployed master is b16ae935):
  - 8d70a0ab: item 1, mirror flipped to method_label;
  - 98484409: contract-path follow-up;
  - ff6d843c: EAC descs.
- **Item 3 is done live on b16ae935.** /package_export answers the named 503 3 of 3, and all six
  seeded panels are 200 3 of 3. The BFF `/canvas/seed` leg was NOT fired.
- **OPEN: item 2, performance-indices.**
  - The supervisor path left `program_id` unfilled in 3 of 5 runs on 3e6d9e9.
  - Direct `/fill_slots` filled it 10 of 10 on b16ae935, for both id and name wording.
  - The extractor and the budget are ruled out, and there is no producer defect.
  - **Next:** after the stalled prime finishes, run `walk_census.py --only
    finance-performance-indices --only finance-eac-refusal` 3 times. Then grep engine-o's log
    since the start for `fill_slots|model call failed`. A miss with `model call failed` means the
    fix is on the extraction path, which is not finance's.
- **OPEN: item 2, eac-refusal.** Live proof of ff6d843c needs a merge plus an engine-fin roll
  (descs register at startup). Re-fire the same row then.
- **Blocked on Lane 1.** The Dagster queue (2 slots) holds a 10-day-old ingest_ontology_job
  run, a3d3674b, which is not ours. The prime was "waiting for 22 ingest runs" for 54 minutes and
  counting.
