# Handoff: lane/gov, 2026-11-05 (#268 merged with the three rulings; #270 reads the routes from dag-tools)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-11-05

This supersedes `2026-11-05-handoff-lane-gov-item-b-is-268-fork-7-done-dag-tools-json-ships.md`.

## The rulings since (Chris, 11-05, verbatim)

> "gov: (a) one levels file, owned by policy (invincible-agent/policy/classification/levels.yaml); dag-tools never ships its own — it reads the deployment's copy (ConfigMap from the chart), so code reads what the server serves. (b) Levels are ordered; a grant at a level is a ceiling and implies every less restrictive one. (c) Relation: `cleared_for:<level>` — `can_read` stays what it is. Then: gateway-routes import, go."

## State

- **#268 is merged** as `d77050cd`, with the rulings built.
  - The registry is `policy/classification/levels.yaml`, top-level key `classification_levels`, and order is list position.
  - The rail is `policy/level_readers.yaml`. Its relation is `cleared_for:<level>`, and a `cleared_for:` capability row is refused. `can_read:` is not refused.
  - Gov reads ruling (b) as "list a group once, at its highest level". A lower listing of a group that is also at a higher level is refused, ordered by the registry, never by row order. This reading is stated in #268's description.
  - Both files ship empty, and nothing reads them.
  - What ran: the seal gave 52 passed, and 7 of 7 mutants were killed. The area run gave 1915 passed, 0 failed.
- **#270 is open and MERGEABLE.** Branch `lane/gov-gateway-routes-from-dag-tools`, head `597dd180`, base master `e84f947d`.
  - It pins `edgy-dag-tools==0.11.0` from PyPI; only that package moved in `uv.lock`.
  - `validate_policy` reads the gateway door's routes from `dag_tools.central_gateway.routes.delegatable_route_ids()`. `GATEWAY_ROUTES`, `GATEWAY_ROUTES_READ_AT` and the read-at seal are gone.
  - What ran: the delegate seal gave 58 passed, 3 of 3 mutants were killed, and the area run gave 2192 passed, 0 failed. On the merge with #268, 205 passed.
  - Board: `01M6KF8279KZ843KG5MMM0R3YH` is in review; `01M6KF821P2C3KRQN86FF0N61N` is done, with lane `dag-tools/seat/owner` because an empty lane is legal only when open; item B `01M6N17JBZK14V4MTTEQQ3HYWZ` is done.
- **The ConfigMap of ruling (a)** is `01M6P8PTFES1FTRD1JAKSSVFFC`, blocked on `chris:name the chart version the levels ConfigMap ships in`.
  - It is a `helm/**` change. Since #267, a `helm/**` merge on an unpublished version publishes it, and one on a published version without a bump fails.
  - The chart is at 0.4.80 and unpublished. 0.4.81 is reserved for #251's forks 1 and 3.
- **Packet placed** (master tree, untracked): `2026-11-05-packet-to-dag-tools-owner-cc-architect-from-gov-one-levels-file-dag-tools-reads-the-deployments-copy.md`. It relays ruling (a) and asks dag-tools for the mount path or env var when step 5 is designed.

## Open forks

12. The relay-form detector for the ratchet (carried over). Item `01M6A9QDN19S78PQVCA67NZ9RC`.
13. `01M6MZX82P0XT6HX984DZEXMV9` (open, later): content kinds and review shapes rest on the "no SDK here" premise. #270 adds a third dependent, dag-tools in the validator. The image is `uv sync --locked --no-dev` of the root, where dag-tools is a main dependency, but that was read, not run. `policy/sync/requirements.txt` has no dag-tools. Measure the premise in the image before relying on it.
- **The BFF door** (raised on #270 and `01M6KF8279KZ843KG5MMM0R3YH`): the json carries only the central gateway's routes, so `BFF_DELEGATE_ROUTES = ("human_tasks.register",)` stays a literal in `validate_policy.py`. Where the BFF's list should be published is the architect's call.

## Waiting on

| for | who | item |
| --- | --- | --- |
| #270's merge | lane/01 | `01M6KF8279KZ843KG5MMM0R3YH` |
| the chart version for the levels ConfigMap | Chris | `01M6P8PTFES1FTRD1JAKSSVFFC` |
| dag-tools' mount path or env var for the levels copy (step 5) | dag-tools/seat/owner | the packet above |
| where the BFF's delegatable routes are published | architect | `01M6KF8279KZ843KG5MMM0R3YH` |
| ADR-0064 (#266) | architect | — |
| carried over: ca's SDK reader, v0.9.14, lane/01's BFF door and person-refusal seals, Chris's topaz_sync, the gateway's reader, the gauge, sys.modules, kind-audit, catalogue seal, strict reader, production reviewers | as in the 11-05 handoff | — |

## Next (in order)

1. Read master, #270 and the inbox in the master tree's `sessions/`.
2. When #270 merges: confirm `01M6KF8279KZ843KG5MMM0R3YH` reaches done on master (it is in review on the branch).
3. When Chris names the chart version: build `01M6P8PTFES1FTRD1JAKSSVFFC`, a ConfigMap serving `policy/classification/levels.yaml`. Show the values diff before any roll. The mount follows dag-tools' answer, if it has one.
4. Fork 13, once it is scheduled: measure the image first.
5. When ca tags v0.9.14: re-pin, per `docs/runbooks/pinning-the-fleet-sdk.md`.

## Scratch (session scratchpad, not durable)

- `gr` holds #270 (own venv). `lv` holds the merged #268 and can go.
- `mut_gr.py` and `mut_lv2.py` are the mutant runners. `gr_pr_2.md` and `lv_pr_4.md` are the PR descriptions.

## Lessons

- **A mutant that survives can be a missing arm, not dead code.** "Skip duplicated levels when building the ceiling map" survived until a test listed one group at a duplicated level. Before deleting the guard as unreachable, write the input it guards against.
- **A board rule can block a status move on another repo's item.** An empty `lane:` is legal only while `open`, so moving a peer repo's item to done means naming an address. Use the one that shipped the work, and say so in the commit.
- **A generated file conflicts on every merge train.** Take either side of `board/BOARD.md`, re-render, then run `--check`. Never hand-merge it.
