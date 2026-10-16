# Packet: 191 is live (`9cc830ac`, chart 0.4.52). The watchdog failed the four rows on its first tick, so alice can retry

to: invincible-agent/seat/architect
from: invincible-agent/lane/01, 2026-10-16
re: the four-item 191 directive (via Chris)

## The directive, item by item

**1. 191 = GET /ingest/mine + content_kind + #28 → 0.4.52 + fin Q1 if pushed, else 192.** Landed.

- `GET /ingest/mine`: `53b39095`.
- `content_kind` is on both the status body and every `/ingest/mine` item. It is null when unknown.
- #28 is merged by sha (`648e24c2`) at chart 0.4.52:
  - `networkPolicy.enabled: false`, and no values file turns it on;
  - zero NetworkPolicy objects in the namespace after the roll.
- **Fin Q1:** not pushed. At merge time `lane/fin` was at `fadf6e44`, with no `fin/*` branch newer
  than 10-12. Q1 goes into **192**, and fin has a packet saying so.
- **The roll:** master was fast-forwarded `6bd7e4a2..9cc830ac`.
  - The image build for that sha succeeded, and helm rev 196 is deployed.
  - Every fleet image is on `9cc830ac`.
  - No Dagster run was in flight before the roll.
- **The landed packet is placed for cortex.**

**2. The four rows stuck at extracting (Ask B).** Fixed in `a768c34d`. No direct table write.

- **Stalled rows time out.** The watchdog now also fails rows stalled at `extracting`:
  - the default is 3600 s, set by `INGEST_EXTRACTING_TIMEOUT_SECONDS`;
  - `failure.step` names the stage.
- **A refused review reaches the row.** A 4xx out of the review's find-or-file now writes `failed`
  before it re-raises:
  - `reason_code` is the refusal's error, and `step` is `review`;
  - a 5xx stays transient and writes nothing.
- **A row with no kind adopts the manifest's.** At review, a row with a null `content_kind` takes the
  manifest's `metadata.content_kind` if that kind is registered. The column is filled only where it
  is null.
- **Measured live.** On the first tick after the roll, the BFF log shows exactly four lines, one per
  row:

  > `ingest watchdog: sha256:<id> failed:timeout at extracting (no stage move within 3600s)`

  The rows are `734d9c94` (EOL-36), `c75116ec` (PCN24-060), `fa231498` and `0096a523` (PCN23-002).
  No other row was failed.
- **Next: Chris has alice retry from the UI.** On retry, the review should adopt `pcn` from the
  manifest and file the task. That is the loop proving itself a second time. I will watch the -a3
  runs reach `review`.
- **A choice for you to overrule:** `review` and `awaiting_origin` are **not** watched. Both wait on a
  steward, so a timeout there would fail a row that is correctly waiting. Only `received` and
  `extracting` are watched.
- **Proof:**
  - 15 new arms, and 8 of 8 mutants red on named arms;
  - 13 consequence files green;
  - the joined tree re-run file by file.

**3. part_number gets the bare identifier.** Ruled as declared per slot (`binds: identifier`) and held
for **192**. Saf has been told: Lane 1 edits their `slots.py`, and their last-segment parse keeps
5530-184 working until then.

**4. Merge order #58 → #59 → #60 → #61 (+739b0c74).** Done, by sha:

- #58 `302a4686`, then #59 `bdd0338d`, then #61 `9989b82a`;
- #60 and `739b0c74` were already on master;
- the seven test files the merges touch are green on the joined tree, run one at a time;
- GitHub shows #58 and #61 MERGED.

## What arrived after 191 was cut, and goes into 192

- **74's #59** head moved to `be4b99bf`, which applies your never-raise ruling: `fill_slots: refused` on
  `resolved_intent`.
- **74's #62** at `e5490b2d`: the shared resolve helpers, for saf.
- **Fin Q1.**
- **Item 3:** `binds: identifier`.
- **A Lane 1 cleanup.** `tests/test_steward_correction.py:51,52` binds `INGEST` twice. It came from
  #43 on 10-11 and reds `test_no_module_level_name_is_bound_twice`. 191 adds no new hit to that ratchet.
