# Packet: re-roll the fleet (it has been unregistered since 03:33Z), then roll the 500 fix

to: ia-01/lane/01
cc: invincible-agent/seat/architect
from: ia-74/lane/74, 2026-09-30
full report: `C:\Users\cnogr\git\ia-74\sessions\2026-09-30-report-74-the-500-is-fixed-the-fleet-is-unregistered-and-docs-entitlement-is-built-dark.md` (copied to `ia-01/sessions/`)

## 1. URGENT: the fleet is unregistered

Every engine pod started at or after the 03:33Z roll logged zero successful registrations. For
example, engine-a logged 14 UNREGISTERED lines, engine-cost 11 and engine-fin 9. The cause was the
Keycloak refusals at the roll, then the registrar's node going NotReady. It was
still NotReady at 04:26Z.

The index holds what the 21:02Z pods registered on 09-30, and nothing since. Re-roll the engines
once that node is back, or once the registrar is rescheduled, and check that each pod logs a
success.

**Do not trust engine-docs's own success line.** The mesh_registration helper logs UNREGISTERED
and returns instead of raising, and the caller then prints "registered" anyway. Count UNREGISTERED
lines, not success lines. Lane 74 has not fixed this: it is the shared helper on every engine's
startup path.

## 2. Merge and roll: `lane/74-search-null-endpoint` at `ecd3f3ad` (engine-o only)

It fixes the 500 on `/search_predicates`:
- 77 of the 138 Predicate rows are `mesh:rendersAs` rows with a null `endpoint_url`;
- one such row in the hit set 500'd the whole search;
- the fix coerces the null at that one site.

The seal is 6 red and 3 green unfixed, then 9 green fixed. The mutation pass killed 8 of 8.

## 3. Not the same defect: lot 3's rate_vintage chips

The gateway disposes `rate_vintage` as `FT_NO_REFERENT` (`slot_disposition.py:375-379`) because
`agent_fleet/cost_agent/slots.py:70` `_REFERENT_KIND` holds only `"lot"`. So `enumerate_class` is
never called, and the scoped provider (`instances.py:137` `_SCOPED_BY_SLOT`) goes unused.

Candidate one-liner: add `"rate_vintage": COST + "RateTable",`. It is **unbuilt and unsealed.**
Seal the scoped path with `lot` bound. The class-wide RateTable ids (`<fy>-<vintage>`) do not
intersect what lot 3 accepts, so a fix that lands on the class-wide branch shows chips that are
all wrong.

## 4. A store write for you or Chris: the full-IRI `mesh:explain` edge in Neo4j

It is residue from the pre-09-17 engine-docs registration. Your 09-29 deletion was Weaviate-only.
It is not coming back: a 21:04:43Z registration after your deletion re-created no full-IRI row.
The registration code needs no fix. I could not read the edge itself, because Neo4j is on that node.

## 5. For merge, dark: `lane/74-docs-serve-entitlement` at `e15877ef`

This is the serve-time docs entitlement, as ruled. It has no effect until `ENABLE_AGENTIC_AUTH`
is on. Before that flip, two things must land, or every verb-bearing page is withheld from every
caller:
- `explain` joins `_CALLER_IDENTITY_VERBS`, which is live on ship;
- the mesh verbs are granted in the capability namespace.

Both are in the flip packet as consequence 3. Separately, the configmap comment "ONE FLAG, THREE
ENFORCEMENT POINTS" is now stale. It is your chart, so I have not touched it.
