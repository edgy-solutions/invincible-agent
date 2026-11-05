---
title: Who may review is a capability: can_review:<subject> and its registry (#196)
feature: training
lane: invincible-agent/lane/gov
repo: invincible-agent
status: blocked
priority: next
blocked_on: [chris:topaz_sync at 0.4.76 or later for alice in alignment-reviewers]
pr: [invincible-agent#196, invincible-agent#204]
ruling_ref: architect 10-31 directive; 11-02 rulings (registry list; sandbox reviewer is alice)
updated: 2026-11-03
---

First row `can_review:alignment`, granted to the capability-only group alignment-reviewers. validate_policy takes subjects from policy/review_subjects.yaml, so a misspelt key fails. Sandbox member alice is a fixture (ruled 11-02; #204 moved it from bob, merged at 729efeeb); production reviewers wait on 01M6A9QDN16Q03BPSJAPWDSAEP. #196 is in 0.4.75 (tag aac9900b); #204 is not, so 0.4.75's policy still gives the group to bob, and alice arrives with a topaz_sync at a release carrying #204, in the streamed form. helm read 0.4.75 at revision 225; gov did not read Topaz, so who holds the group live is whoever the last sync gave it. The check itself is wb's, 01M6A9QDN1VCGZRXDMMKTFWT1T.

0.4.76 is cut and carries #204. This entry does not say the sync has run: gov has not read Topaz since.
