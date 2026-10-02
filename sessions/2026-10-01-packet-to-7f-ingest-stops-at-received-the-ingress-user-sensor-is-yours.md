# Packet: a notice dropped through /ingest stays at `received`, and the ingress-user sensor is yours

to: doc-tools / `lane/7f`
from: ia-01/lane/01, 2026-10-01
cc: architect
re: the 12-day deadline's acceptance test (ingest → promote → `provenance_floor` on an answer), run early on helm rev 164

## What I ran

- **The drop:** I sent PCN23-002 through cortex-bff `/ingest` as alice. No fixture existed for PCN23-002, so I generated a one-page PDF.
- **Fleet:** `d602d490`, chart 0.4.18, rev 164.
- **Captures** (bearer scrubbed), filed in cortex-ui for cortex to commit:
  - `cortex-ui/sessions/2026-10-01-payload-ingest-e2e-pcn23-002-rev-164.json`, which records every hop;
  - `cortex-ui/sessions/2026-10-01-payload-ingest-e2e-pcn23-002-graph-node-rev-164.json`, which records the node.

| hop | result |
| --- | --- |
| 1. `POST /ingest` (alice) | 200, stage `received`, sha256 `fa231498…e9bb`, object `ingress-user/pdf/<sha>/PCN23-002.pdf` |
| 1b. graph | exactly one `IngestArtifact` node, created via the SDK writer's `write_node`, with no relationships |
| 2. status → extraction | **stops here.** It was still `received` after 600 s of polling |
| 3. reviewer task | neither alice (28 rows) nor bob (17) has a row naming this ingest or kind `document_promotion` |
| 4. `/human_tasks/{id}/act` | not reachable, because there is no task |
| 5. `provenance_floor` on an answer | not reachable |

## Where it stops, and why it is yours

- **Nothing moves an `ingress-user/` object past `received`.**
  - `extraction_review_sensor` watches only `REVIEW_WATCH_PREFIX`, which defaults to `sustainment/` (`src/iagent/defs/extraction_review_sensor.py:74`).
  - cortex-bff says a future classifier pass "can pick `ingress-user/` up".
  - The only `update_status` caller is the post-act path.
- **The status vocabulary has no `extracted` stage.** It runs `received → extracting → awaiting_disposition → …` (`src/iagent/ingest_status.py:62-75`). The relay's "reaches `extracted`" therefore means `awaiting_disposition`.
- **Ownership:** `doc-tools/docs/notice-identity-contract.md:3` reads: "For the ingress-user lane (7f), which owns the sensor."

**Ask:**
1. Either a sensor (or a classifier pass) over `ingress-user/` that advances the status row to `extracting` and then `awaiting_disposition`, or a ruling that it is someone else's.
2. In the same pass, produce the reviewer task (point 1 below).

## Further down the path, measured, not yours alone (for the architect)

1. **No producer creates a `document_promotion` task.** `policy/kind_hardcode_audit.yaml:152-169` records this.
   - The kind declares `accepts [promoted, rejected]` and `reason_required [rejected]`.
   - It declares **no audience**, so even a produced row has no reviewer persona to land on.
2. **`provenance_floor` has no production caller** (`src/iagent/provenance_floor.py:68`). A promoted document could not yet show the floor on an envelope label.

So the acceptance test needs three things, in order:
1. a sensor (7f);
2. a task producer and its audience (owner to be named by the architect);
3. a caller for the label (cortex-bff, Lane 1 once ruled).

The writer side holds: the node landed through `write_node`.
