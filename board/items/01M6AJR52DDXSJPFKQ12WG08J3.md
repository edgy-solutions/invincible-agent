---
title: Who may review is a capability: can_review:<subject> and its registry (#196)
feature: training
lane: invincible-agent/lane/gov
repo: invincible-agent
status: done
priority: next
blocked_on: []
pr: [invincible-agent#196, invincible-agent#204]
ruling_ref: architect 2026-11-07 via Chris (can_review/can_configure registry: #196/#215 merged)
updated: 2026-11-07
---

First row `can_review:alignment`, granted to the capability-only group alignment-reviewers. validate_policy takes subjects from policy/review_subjects.yaml, so a misspelt key fails. Sandbox member alice is a fixture (ruled 11-02; #204 moved it from bob, merged at 729efeeb); production reviewers wait on 01M6A9QDN16Q03BPSJAPWDSAEP. #196 is in 0.4.75 (tag aac9900b); #204 is not, so 0.4.75's policy still gives the group to bob, and alice arrives with a topaz_sync at a release carrying #204, in the streamed form. helm read 0.4.75 at revision 225; gov did not read Topaz, so who holds the group live is whoever the last sync gave it. The check itself is wb's, 01M6A9QDN1VCGZRXDMMKTFWT1T.

0.4.76 is cut and carries #204. This entry does not say the sync has run: gov has not read Topaz since.

Closed 2026-11-07 (Lane 1 sweep) on the architect's ruling, via Chris: "can_review/can_configure registry (#196/#215 merged)". This closure does not say the topaz_sync has run; Lane 1 has not read Topaz.
