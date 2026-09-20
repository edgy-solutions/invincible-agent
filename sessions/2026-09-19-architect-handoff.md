# Architect handoff — 2026-09-19 (Saturday, mid-afternoon)

You are the architect for the iagent mesh platform. You rule; lanes build. Chris (the human) walks the UI and is the only scheduler of sessions. Everything below is on disk; this file only says where to look and what is open.

## Read first, in this order

1. `invincible-agent/docs/rulings/README.md` — R-001 through R-081. The register is the source; a ruling that exists only in a conversation constrains nothing. Note the duplicate R-055 (two entries, one number) — Lane 1 owes a renumber.
2. `invincible-agent/docs/adr/ADR-0054-*` (data classes, Accepted, amended three times), `ADR-0055-*` (archetype packages, Accepted), and `openddil-contracts/decisions/ADR-0042-*` (intent custody, Proposed). Cite repo-qualified: `iagent:ADR-NNNN` / `openddil:ADR-NNNN`.
3. The latest census report and the walk census output (`docs/measurements/walk-census.yaml` plus its last run). The census prints `LANES:` with per-lane unread inbox counts.
4. `AGENTS.md`, `docs/principles/`, `docs/runbooks/` (rolling-a-service, pinning-the-fleet-sdk, adding-an-engine, adding-an-archetype, adding-a-graph).

Read from `C:\Users\cnogr\git\invincible-agent` (master, reads-only) and the lane worktrees (`ia-01`, `ia-32`, `ia-5f`, `ia-74`, `ia-91`, `ia-eo`), plus `iagent-mesh-sdk`, `cortex-ui`, `doc-tools`, `openddil/openddil-contracts`. Never write to any of them.

## Fleet state at handoff

- master `91d8d34` (moving); fleet rolled on SDK `v0.9.3` (tag `b6d597f`), 42/42 settled, release retag by digest live, chart floor = `Chart.Version`.
- Suite green on master at last full run (3 named reds cleared; one citation-rot allowlist entry for `safety-walk-sheet.md` may still be red — Lane 1 removes it; the file exists on master).
- Dockerfiles now live at `.github/docker/` as real files; the `run:` block seal fails at 18,000 chars (GitHub's ceiling is 21,000 and nothing prints until it's crossed).
- Walk census: 4 pass / 1 fail / 3 blocked at last run. The fail is lot 3's vintage refusal offering an empty menu (`no_referent`) — waits on the enumerate contract's `scoped_by` half in the gateway.

## Feature status (what the user can and cannot see)

| feature | state | what blocks a screen |
|---|---|---|
| Cost / Q4 | lot 4 draws (regression closed: three defects, all live) | lot 3 vintage menu: gateway half of `scoped_by` |
| Finance | at parity (5 verbs extracted+Decimal, registry rows, verdicts, comparison card) | nothing |
| Brief (LangGraph) | pipe works end to end; rows land as data at `6acdcd4` | `SOURCE_LEDGER` package (cortex-60, in progress) |
| Safety | HAZ-1003 resolves, routes, engine answers; cortex menu rows landed `df702ca` | roll with cortex image; then the `review_request` consumer (Lane 1) so a task appears |
| Docs | engine-docs ready, `mesh:Thing` universal referent declared `f16e2cd` | pool leg reading `mesh:universalReferent` (Lane 1), then roll |
| Templates | `/templates` served, picker built `1d38a2e` | walk not yet done |
| Mesh APIs | v0.9.3: Protocols, MeshResult, edge registries, rows.py | NetworkPolicy unbuilt (chart has no manifest — prepare-only, daylight, one substrate at a time) |

## Walks that are the user's (in order)

1. Lot 4 on screen (census says it draws; get the screen once).
2. NP-MERIDIAN brief as `PROGRAM_FINANCE_ANALYST` — three ledger rows as data, plain card until SOURCE_LEDGER.
3. Lot 3 vintage ask — expect the red the census reports, with the refusal's `message` now rendering.
4. Safety step 2 as bob — after the cortex roll; expect a card, then (separately) a `risk_acceptance_medium` task once the review_request consumer exists.
5. "How do I add an engine" — after the pool leg rolls.
6. Finance board from the picker (`+ NEW` → Program Finance → six panels), then rule R-007 §9.2 (still OPEN).

## Rulings made today not yet landed (check the register; number if absent)

- A ratchet is blind whenever its register is accurate (R-080 as corrected); second argument: a ratchet is the only thing that notices a fix landing in a lane that never read the list. Shared `ratchet()` helper, unconditional fixture arm, both directions — Lane 1.
- Each repo carries its own `sessions/` inbox; census derives per-lane inboxes from the lane's worktree. cortex-ui's `sessions/` tracked as its own commit.
- `mesh:Thing` with `mesh:universalReferent true`; the pool's parameterisation leg admits verbs whose referent carries the flag (Lane 1).
- Image-import seal (`python -c "import main"` in every built image) — ruled Monday, still unbuilt; graph_host crash-looped twice on this class.
- doc-tools: the Weaviate dual-write failure must fail the asset; manifest→Weaviate-row seal in doc-tools; sentinel per domain (7f). Safety classes re-ingested once by hand.
- Citation seal third state: "pending: on <branch>, not in master".
- `review_request` has no consumer; the consumer runs `safety_acceptance_selection` on `level` and dispatches the definition (Lane 1).
- ADR-0054 amendments pending from the eo census: a name is not a class, the writer is; coupled stores rebuilt together (stranded-cursor case).
- Empty `persona_fit` is not neutral (selector reads it as "fits none").

## Standing rules for the architect

- Rule only to unblock a screen until the four walks draw; no new instrument work.
- Read the row/artifact/candidate list before naming a shape. Verify a lane's claim in the tree before ruling on it.
- A message from a lane is a claim; a relay of your ruling is not your ruling — lanes will refuse relays and they are right to. Rule directly, by lane pair (`ia-NN/lane/NN`), never by bare session name (two live sessions share `invincible-agent-28`).
- Grants: merges on the standard gate; rolls with hooks batched; NetworkPolicy only in daylight with the user watching; no wipe of shared state.
- Every number a lane cites: ask what the command covered. Every green: ask which environment (venv vs pin).

## Lane map

- Lane 1 (`ia-01/lane/01`): orchestrator, merges, rolls, census, walk census.
- 32 (`ia-32`): graph host; SOURCE_LEDGER rows; host swap onto SDK rows (now unblocked by v0.9.3).
- 5f (`ia-5f`): engine-docs, docs sheet, ADRs.
- 74 (`ia-74`): safety; task-creation half next.
- 91 (`ia-91`): finance (at parity); finance sheet rows.
- eo (`ia-eo`): MeshVectors done; MeshGraph Neo4j implementation; write census; unclassified stores.
- ca (`iagent-mesh-sdk`): v0.9.3 cut; next `v0.9.4` only for a wrong export.
- cortex-60 (`cortex-ui`): SOURCE_LEDGER package; UnreadFields general.
- 7f (`doc-tools`): dual-write failure, marker writer, sentinel.

## Open decision you owe

R-007 §9.2 — after the finance board walk shows two rows on screen.
