to: invincible-agent/lane/01
from: invincible-agent/lane/01
date: 2026-10-23 (Friday)
re: Monday 2026-10-26. 207 merges and rolls, then ca tags v0.9.11, then 208 pins it and builds
    hand entry

# Handoff: 207 merges Monday, then 0.9.11 pins on 208

## State at handoff
- Worktree `/c/tmp/ia193` is on `lane/01-208` at a762122a, pushed.
- 207 is at b102f1f9, pushed. 208 is stacked on 207.
- **207 has no PR, by ruling.** The architect, 2026-10-23: "207: no PR before Monday; the drift
  job's first run is Monday's merge, and if it fails there you fix it before the roll, not
  after."
- The sandbox freeze lifts Friday afternoon. Merging to master still needs Chris's explicit OK,
  each time.

## Monday, in order

### 1. The 207 merge set
- The last commit is a `helm/.../Chart.yaml` bump to 0.4.66.
- Merge by sha, never by ref. Read the second parent afterwards.

### 2. Read the cross-repo drift job's first run on the merge sha
- It is `.github/workflows/cross-repo-kind-drift.yml`, triggered by a push to master on its
  own path.
- It must be green before anything rolls. If it is red, fix it on a lane branch, merge, and
  re-read it. Only then roll.
- A green means three steps passed: the test ran, the JUnit report shows tests>0 and
  skipped==0, and the control went red naming doors-export.

### 3. The release and the roll
- Wait for the build. Then dispatch Release Helm Charts with `chart_version=0.4.66` and
  `sha=<merge sha>`.
- Before the roll, render with `--dry-run` and diff the effective values against
  `helm get values`. Put the diff in front of Chris.
- Roll from the released tgz. Then compare each pod's imageID against `image-digests.json`.
- Cortex PR #29 rolls together with 207.

### 4. docs/releases/0.4.66.md
- If the doc-tools pairing changes, bump `.github/doc-tools.ref` in the same commit as this note.

### 5. When ca tags v0.9.11, one commit on 208

What the tag carries: arrives_as, review_shape, label, EvidenceRef bbox optional,
steward-entered, and the pairing rule.

- **Bump the pin.** pyproject lines 66 and 142, then `uv lock`. Run `uv sync --extra
  agent-fleet` in full; a partial sync is a scope that looks local and is not.
- **`src/iagent/provenance.py`.**
  - Add `STEWARD_ENTERED = "steward-entered"` as the seventh and last rung, with its own
    docstring section, like the sixth's.
  - Add the pairing rule the architect confirmed on 2026-10-23 (below). It goes in both
    validators, `:118-128` (`make_provenance`) and `:163-173` (`validate_provenance`).
  - The refusal text for the other rungs must stop saying "only steward-corrected".

  | rung | corrected_by | extracted_value |
  |---|---|---|
  | steward-corrected | required | required (may be blank) |
  | steward-entered | required | forbidden: "there was no extraction to differ from" |
  | every other rung | refused | refused |

- **`agent_fleet/restate_analyst/steward_correction.py`.** Before changing `provenance_for`,
  check what consumes its block. Today an added row's block carries
  `extracted_value: None`, and under steward-entered that has to be absent.
- **"The equality test covers both" (ruled).** `test_the_rung_tuple_AGREES_with_the_SDKs_copy`
  (`tests/test_the_answer_carries_its_provenance_floor.py:146`) compares only the tuple today.
  - Widen it to compare BEHAVIOUR: for every rung × corrected_by {absent, "bob"} ×
    extracted_value {absent, "", "M-1"}, local `make_provenance` accepts if and only if the
    SDK's does.
  - Derive the rung list from the SDK tuple, never retype it.
  - Make it unable to skip once the pin is in. Today it is an `importorskip`.
  - Mutants: drop the steward-entered arm locally, and allow extracted_value under
    steward-entered. Both must red the agreement test.
- **`tests/test_a_fifth_obtained_via_rung_lands.py`.** The seven-tuple, with `[-1]` as
  STEWARD_ENTERED and `[-2]` as STEWARD_CORRECTED.
- **Then build hand entry.** Lift the 409 `add_missed_part_not_built` on a second-zero
  `document_empty_confirm`:
  - the parts entry becomes `promotion.act` with zero reviewed rows plus N `added` edits at
    steward-entered;
  - each edit carries evidence_ref {page, bbox: null} and corrected_by;
  - an extraction_defect is filed with op=add;
  - it needs the promotion audience's `check_can_act`. A dropper can confirm no parts but
    cannot enter parts.
  - The graph write already takes the edit's own rung (5bb7a3ae).

## Waiting on
- **ca:** the v0.9.11 tag sha, which carries the pairing rule.
- **7f:** `n.provenance_ingest_id` on the three zero-row notices (`PCN-24_0003`, `diodes_2683`,
  `inbound/adi_23_0120`). Asked in
  `doc-tools/sessions/2026-10-23-packet-from-lane-01-the-anchor-is-consumed-...md`. If one is
  absent, hand entry raises on that notice.
- **tr / wb (training, ADR-0059):** Lane 1 builds a training domain and its grants only if the
  contract says the workbench authenticates through the platform. No training domain exists in
  `policy/` today.
  - When tr's training KIND_MAPPING row lands, this repo needs a matching overlay row.
    Otherwise the drift job reds on the first pin bump after it.

## 208 rolls only with
- cortex's empty-confirm card;
- 7f's force-text reader.
