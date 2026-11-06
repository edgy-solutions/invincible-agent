# Priorities

Data, read by `scripts/render_board.py`. Edit here; never in code.

## Features

| rank | feature | name |
| --- | --- | --- |
| 1 | `pcn-pdn` | PCN/PDN |
| 2 | `finance` | Finance |
| 3 | `api-sdk-mcp` | API / SDK / MCP |
| 4 | `docs` | Docs |
| 5 | `openddil` | OpenDDIL |
| 6 | `training` | Training |
| 7 | `workflow-socratic` | Workflow (Socratic) |
| 8 | `engine-r` | engine-r |
| 9 | `cross-cutting` | Cross-cutting (releases, governance, safety, the board) |

## Item priority

| priority | meaning |
| --- | --- |
| `now` | in the current block |
| `next` | after the current block |
| `later` | parked until something named changes |

## Reorders

- 2026-10-31 (Chris, via the architect): board reinstated; order 1 PCN/PDN, 2 finance, 3 API/SDK/MCP, 4 docs, 5 OpenDDIL (waiting on their fix), 6 training, 7 workflow (Socratic), 8 engine-r.
- 2026-10-31 (Lane 1, at seeding; accepted by the architect 10-31): 9 cross-cutting appended below the eight, for work that serves no one feature (releases, governance ratchets, safety, the board).

## Who merges

Chris's ruling, relayed by the architect on 2026-11-06, in force now:

- A lane merges in its own repo, on green, when the PR rides a train the architect has ordered or Chris has approved.
- Board-only and docs-only PRs merge on green, with no train.
- Chris keeps releases (tags), Topaz and DataHub syncs, rolls, and any write to a live directory or Secret.
- The release-chain exceptions already scripted in dag-tools stay as ruled.
