---
title: Who may review is a capability: can_review:<subject> and its registry (#196)
feature: training
lane: invincible-agent/lane/gov
repo: invincible-agent
status: blocked
priority: next
blocked_on: [chris:topaz_sync for alignment-reviewers then the roll that carries 0.4.75]
pr: [invincible-agent#196, invincible-agent#204]
ruling_ref: architect 10-31 directive; 11-02 rulings (registry list; sandbox reviewer is alice)
updated: 2026-11-02
---

First row `can_review:alignment`, granted to the capability-only group alignment-reviewers. validate_policy takes subjects from policy/review_subjects.yaml, so a misspelt key fails. Sandbox member alice is a fixture (ruled 11-02; #204 moved it from bob, merged at 729efeeb); production reviewers wait on 01M6A9QDN16Q03BPSJAPWDSAEP. Merged at c788fd50 (2026-11-02) under 0.4.75, which is not yet cut, so it is not live. Before the roll that carries it, Chris runs topaz_sync for the new group. The check itself is wb's, 01M6A9QDN1VCGZRXDMMKTFWT1T.
