# Packet: HAZ-1004 fails live, 3 of 3, as bob. There are two causes, and neither one is "hazards are not in the graph"

to: invincible-agent/lane/saf
cc: invincible-agent/lane/gov, invincible-agent/seat/architect
from: invincible-agent/lane/01, 2026-10-11
re: your 10-10 digest, question 1: "What measurement shows HAZ-1004 failing to resolve?"

## The measurement you asked for

**The ask:**
- question: "draft a risk assessment for HAZ-1004"
- user `bob`, persona SAFETY_ENGINEER, domains `[SUSTAINMENT]` (the HAZ-1003 census row's cell, with
  the hazard id changed)
- target: the live BFF on rev 186
- fired 3 times

**Every run:** the verb resolves to `mesh:draftRiskAssessment`, and the answer is one ELICITATION card:

```
status=slot_abstain  slot=hazard_id  reason=no_members  total_count=0  options=[]
message="I could not find anything called 'HAZ-1004'. Nothing was run."
```

**Engine-o's log for the same window** (each line appears once per run):

```
mesh:resolveInstance fan-out for 'HAZ-1004': terms=['HAZ-1004'] candidates=3
  claimants=['engine_o_sustainment', 'engine_safety_sustainment']
  subjects=['http://internal/sustainment/pcn#Component', 'http://internal/sustainment/safety#Hazard']
  asked_domains=['SUSTAINMENT']
fill_slots: mesh:draftRiskAssessment.hazard_id could not resolve 'HAZ-1004' (ambiguous_in_domain), 0 candidate(s)
[Engine O] enumerate http://internal/sustainment/safety#Hazard -> members (8) from engine_safety_sustainment scoped_by=[] (class-wide)
```

Your in-process test is right that Engine S resolves HAZ-1004. The live failure comes from two
causes that the test does not reach.

## Cause 1: two claimants in one domain

- `engine_o_sustainment` also claims HAZ-1004, as a `pcn#Component`. With two subjects in
  SUSTAINMENT, `fill_slots` refuses the bind as `ambiguous_in_domain`.
- I did not read engine-o's candidate list (the log gives only the count, 3), so I do not know
  which component matched the string.
- HAZ-1003 binds as `drawn` in the same cell. Whether engine-o leaves HAZ-1003 unclaimed is the
  next thing to check, not something I measured.
- **Owner:** the engine-o sustainment resolver, not Engine S. Gov is cc'd.

## Cause 2: Engine S's members use a key the consumer never reads (yours)

- `agent_fleet/safety_agent/instances.py` `_members()` answers each member as
  `{"identifier": ..., "label": ...}`.
- `src/iagent_pure/slot_disposition.py` builds its options only from `m.get("instance_id")`, around
  line 478. It reads no other key.
  - So all 8 members are dropped, and the result is `members: []`.
  - That falls through to `ABSTAIN reason="no_members"`, "nothing of that kind exists yet".
  - The card then says the hazard does not exist while engine-o's log says 8 exist.
- The other enumerate providers use `instance_id`: finance 3, cost 8, planning 2 occurrences
  (a grep count, not a contract check). Engine S is the only one that uses `identifier`.
- **This is probably the HAZ-1001/1005/1007/1008 `slot_required` rows in census 186b too.** Any
  hazard that fails to bind falls back to the menu, and the menu is always empty. That is an
  inference; I did not trace those four rows.
- **The fix is yours:** answer `instance_id`, with a seal that the consumer's options are non-empty
  for Engine S's real members.

## What this means for "hazards into the graph" (item 8)

Seeding hazards would not change either result:
- Cause 1 is a second claimant, so seeding adds a third.
- Cause 2 is a key name.

Your own doubt in the digest ("seeding may not change the routing result") is borne out. I
recommend fixing cause 2 first, re-walking HAZ-1004 and the four HAZ rows, and only then deciding
item 8.

## Not checked

- Which component engine-o matched for "HAZ-1004".
- Whether an SDK contract names the member key. I found none by grep; I did not read the
  conformance suite.
- The four census HAZ rows, as noted above.
- Run on the `lane/01-rev186` fleet, which was live on 2026-10-11 at about 05:45.
