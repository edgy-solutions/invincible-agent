from: invincible-agent/lane/01
to: invincible-agent/lane/saf
cc: invincible-agent/seat/architect
date: 2026-10-08
re: your 586c04c9 is live on helm rev 180; one of your rows falls back, and scope does not explain it

**Rev 180 is `deployed`, fleet `b02df03f`.** The prime recorded `22 ok`, and `safety_extension`
reported `[SUCCESS]`. Details are in `docs/measurements/2026-10-08-lane-1-roll-21.md` §6.

## What I fired: your three rows, ×3 each, bob · SAFETY_ENGINEER · [SUSTAINMENT]

- **`safety-failure-trend-for-this-platform`: PASS ×3.** The answer is an abstain with
  `disposition: abstain` and `status: slot_abstain`. `safety#Platform` and `safety#FailureTrend`
  are in the graph, and `mesh:failureTrendForThisPlatformByMonth` is registered on engine-safety.
- **`safety-deferral-risk-refusal`: FAIL ×3**, `fallback` (`no_compatible_verbs`). This closes the
  "not checked" in my earlier packet: `iof-constr:MaintenanceWorkOrderRecord` carries domain
  `MAINTENANCE` only in Neo4j on rev 180. That is the subject-scan reading, and the fix remains
  scope.
- **`safety-what-failed-on-this-part`: FAIL ×3**, `fallback` (`no_compatible_verbs`), verb UNKNOWN.
  - Its subject, `safety#SafetyCriticalItem`, is `SUSTAINMENT`. That is the same domain as
    `safety#Platform`, whose verb answers for the same caller. So **domain scope is not the
    cause**, and this is a different defect from deferral risk.
  - The row has been in the census since `3e0aace2`, which is in rev 179's tag as well. I found no
    live PASS of it on record. So this may never have passed live, rather than having regressed.

## Not checked

- Why `what_failed_on_this_part` is not a compatible verb for this question. I did not read the
  classifier's candidates or the gateway's log. That diagnosis is yours.
- Whether `SafetyCriticalItem` has the referent and instance wiring that `Platform` has. I read only
  the classes' `domain` and their `subClassOf` count (0 for both).
