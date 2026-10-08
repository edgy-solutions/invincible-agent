to: ia-fin/lane/fin
from: ia-fin/lane/fin
date: 2026-10-08

# Handoff: lane/fin after the day directive (CPI/SPI fill-slots cause, BFF seed leg)

Reported in invincible-agent `sessions/2026-10-08-packet-to-lane-01-fin-day-cpi-spi-fill-slots-cause-named-seed-6-of-6-x3.md`
(placed untracked, to lane/01, cc seat/architect). This supersedes the OPEN items in
`2026-10-08-handoff-lane-fin-three-items-fill-slots-cause-open.md`.

- **Item 1, finance-performance-indices: cause NAMED, and it is not finance's.**
  - **Measured** after the second prime, 3x: engine-o `FillVerbSlots` returned 200 with `{}`
    each time. There was no `model call failed`.
  - The model said it cannot tell whether NP-MERIDIAN is program_id or ca_id. `_slot_spec` never
    renders the referent class, and rule 2 calls omission "safe" even for a REQUIRED slot.
  - The same prompt is sampled stochastically: direct 10/10, supervisor 3/9 overall.
  - Fix options (a)/(b)/(c) are with Lane 1.
  - **lane/fin's next step:** re-fire `walk_census.py --only finance-performance-indices` 3x once
    a fix lands.
- **Item 2, BFF `/canvas/seed` program_finance, from the finance cell:**
  - 200, 6/6 seeded, 3 of 3 fires, 18/18 panel turns ok;
  - pre-resolved, so it never reaches fill_slots.
  - The no-cell control: 502 cause-less `pipeline_error` 3/3, routed to the BFF owner.
- **Still waiting on merge:** 8d70a0ab, 98484409, ff6d843c. Then an engine-fin roll, then
  re-fire finance-eac-refusal 3x.
- **Reported, not mine:** engine-o provider keys are hand-set to `skip`, so every BAML call goes
  to Ollama. Zombie Dagster run a3d3674b is untouched.
