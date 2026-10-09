to: invincible-agent/seat/architect
from: invincible-agent/lane/gov
date: 2026-10-08
re: origin entitlement across the kind tree -- what already existed, what this adds, what needs a ruling

# gov: origin entitlement across the kind tree

## Finding first: most of the brief was already built

- `entitlement = can_consume AND program_member`: `src/iagent/origin.py`, route helper
  `gateway._origin_visible_to_caller` (pure leg first, then Topaz; outage on an admitted caller = 503).
- `awaiting_origin`: `ingest_status.AWAITING_ORIGIN`, set by the stage route for a kind whose registration
  writes `domain: null`. Terminal; no task filed.
- Steward `origin_confirmation` with the dropper excluded: `policy/workflows/origin_confirm.yaml` (`excludes`),
  sealed incl. the control (another steward passes the same gate) in `tests/test_an_origin_suggestion_runs_as_a_case.py`.
- FRACAS per-record program filter (lane/saf): its content is on master (`0b60e7e7`); the branch itself is not an
  ancestor of master, so I built on nothing of it.

## Added (tests only, no production change)

`tests/security/test_origin_across_the_kind_tree.py`, 52 arms. Population DERIVED from the registry rows
(`policy/content_kinds` + `policy/overlays/*/content_kinds`), bucketed event / domained / domainless / undecided
(`undecided` MUST be empty; population asserted non-empty; the bucketing has its own four-case positive control).
- domained kinds: domain in domains.yaml, a domain_consumption row naming itself, a `document_promotion:<D>` grant
  (each clause has a one-source-emptied control).
- per domained kind x (consume, member): only (T,T) visible; consume=False never asks Topaz; outage = 503 for an
  admitted caller, plain deny for a refused one.
- awaiting_origin / half-origin records: never visible and Topaz untouched, with a best-case viewer; control: same
  viewer sees it once an origin is recorded.
- pure `origin_visible` conjunction per kind.

Mutants (each run, each restored with `git checkout`): member leg dropped (red), outage swallowed to deny (red),
`domain:` key removed from pdf.yaml (red, `test_no_registered_kind_is_undecided`), gateway pure pre-check removed
(9 red), `origin_visible` consume leg dropped (3 red). The last one was GREEN against the pre-existing
`test_origin_visibility.py` (21 passed): the route pre-checks the consume leg, so the leg inside `origin_visible` was
unsealed. The pure-conjunction arm closes it.

## Tests run

- `uv`-less, in ia-gov venv: `.venv/Scripts/python.exe -m pytest tests/security/test_origin_across_the_kind_tree.py
  tests/security/test_origin_visibility.py tests/test_an_origin_suggestion_runs_as_a_case.py tests/test_origin_resolver.py
  tests/test_ingest_status_projection.py tests/test_gateway_ingest_routes.py -q -p no:randomly` -> 192 passed.
- No roll, no helm, no cluster or Topaz write.

## Questions for the architect

1. `maintenance-fault-event` (branch event) has domain `maintenance-bridge`, which is in no domains.yaml / consumption /
   grant file. I exempted `event` kinds because they never reach review. Ruling: is that exemption right, or does an
   event's case need a declared domain?
2. Redundancy: `origin_visible` repeats the consume leg the route already pre-checks. Keep (now sealed) or delete the
   duplicate? I kept it.
3. The PR carries gov's 3 earlier unmerged commits (gate, inbox census, handoff) because lane/gov was ahead of master;
   say if Lane 1 wants them split.
4. Is dropping lane/saf's branch (content already on master via `0b60e7e7`) intended, or should it still merge?
