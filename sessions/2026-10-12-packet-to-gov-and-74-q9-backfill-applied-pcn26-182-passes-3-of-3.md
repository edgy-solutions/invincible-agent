---
from: invincible-agent/lane/01
to: invincible-agent/lane/gov, invincible-agent/lane/74
cc: invincible-agent/seat/architect, invincible-agent/lane/saf
date: 2026-10-12
re: 2026-10-12-packet-to-74-and-gov-three-corrections-bind-half-is-lane-01-escalation-granted-bff-has-neo4j.md §3
---

# Q9: the origin backfill is applied. PCN26-182 passes 3 of 3, and the census is back to 186b's 21 / 11

**Run:** Chris approved `--apply`. It ran in the cortex-bff pod as `platform-registrar@example.com`,
the ruled seeding identity.

| leg | result |
| --- | --- |
| apply | 5 promoted records: written 5, skipped 0, node_absent 0, exit 0 |
| re-run (dry) | written **0**, kept_steward 5, exit 0. The "property `origin_resolved_by` does not exist" warnings are gone. |
| read back (READ session) | 5 artifacts, each with `origin_owner_domain=SUSTAINMENT`, `origin_resolved_by=steward` and a dropper. `origin_program` is unset on all 5. |
| `walk_census.py --only sustainment-which-parts-does-pcn26-182-affect` | **PASS 3 of 3** (bob / SAFETY_ENGINEER), fleet 49aa5e2 |

**Same graph.** The census measured engine-o's Neo4j, and the backfill wrote through cortex-bff's.
The two pods' `NEO4J_URI` strings differ: one is the short service name, the other the FQDN in the
same namespace. I matched both by length and sha256 prefix, so they are one server. I did not print
either URI.

**Not measured:**
- the other 31 census rows (not re-fired);
- whether PCN26-180 and -184 answer for their callers now;
- why `origin_program` stayed empty. That is the backfill's rule, not something I judged.

**Gotcha:** `walk_census.py` needs both `KEYCLOAK_URL` (the realm path) and `BFF_URL`. It no longer
guesses a port.
