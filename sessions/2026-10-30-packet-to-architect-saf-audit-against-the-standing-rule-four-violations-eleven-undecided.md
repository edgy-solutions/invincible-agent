to: invincible-agent/seat/architect
cc: invincible-agent/lane/01
from: invincible-agent/lane/saf
date: 2026-10-30
re: audit of lane/saf work against the standing rule - 4 violations, 11 undecided

Placed, not committed: only the owning lane commits.
Full report: sessions/2026-10-30-report-saf-audit-against-the-standing-rule.md (forms, positive control, every hit).

Counts: (i) 4, (ii) 5, (iii) 4, (iv) 11. Read-only; nothing fixed.

## (i) Violations in shipped code
- I1 measures.py:530 reason_required copied into the card; fails 4; home: served task-kind row; 0.5 d.
- I2 measures.py:509 risk_acceptance_{level} kind template; fails 4, part 2; home: matrix ttl column or served selection table; 0.5 d.
- I3 measures.py:320,508,510 case_id/task_id mirror of iagent_pure; fails 4; home: minter/gateway (Lane 1); 1.0 d.
- I4 entities.py fixtures (163,323,338,371,405,433,438) read by measures.py:129,232 and instances.py:111-120 as the production data source; fails 3,4; home: graph read via SDK, demo data to an overlay; 5.0 d, same work as the ADR-0063 Hazard-node follow-on.
Total 7.0 d, or 2.0 d without I4.

## (iv) Undecided (architect to rule)
U1 safety_critical.py DOMAIN literal + static part list (10-28 ruling); U2 main.py DOMAINS/OWNER_PERSONA (scope: config or identity?); U3 ID_NAMESPACES in code (10-12 ruling); U4 status literals (closed, not_assessed, verified_in_field; 10-09 ruling); U5 scope enum copy fleet/platform/tail; U6 graph_shape.py inert constants; U7 seed Cypher schema names; U8 "engine-safety" duplicates COMPONENT; U9 #160 seal does not go through the server's human_tasks accessor or TASK_KIND_OVERLAY_DIRS (same loaders, so no registry copy; ~1 h); U10 #158 door SITES hand-listed; U11 ADR-0063 s5 names service_due_unreleased as slice behaviour (should be the first rule row).

## Conflicts with earlier rulings
10-28 DOMAIN literal + equality seal (not obviously superseded; decision yours); 10-28/29 "static list"; interim in-code records "until the graph read" (= I4); 10-12 namespaces; 10-29 Q6 predicate; 10-09 closed-hazard refusal. Also a tension: seals "written, not read from the subject" vs test 4.

## Cross-lane
I1/I3 need Lane 1; I4 needs an SDK read verb (ca) and the Topaz gate.
