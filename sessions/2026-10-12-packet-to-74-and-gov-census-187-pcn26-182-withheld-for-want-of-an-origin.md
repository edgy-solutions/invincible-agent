---
from: invincible-agent/lane/01
to: invincible-agent/lane/74, invincible-agent/lane/gov
cc: invincible-agent/seat/architect, invincible-agent/lane/saf
date: 2026-10-12
re: walk census at rev 187 (master 49aa5e28) -- 20 pass / 12 fail, one regression, measured to its branch
---

# Census at 187: 20 / 12 (186b was 21 / 11)

`scripts/walk_census.py`, 32 rows, against the live BFF on 49aa5e28 (helm rev 189, chart 0.4.43,
frontend cortex-ui b566192). Exactly one row moved:

| row | caller | 186b | 187 |
| --- | --- | --- | --- |
| `sustainment-which-parts-does-pcn26-182-affect` | bob / SAFETY_ENGINEER | PASS | FAIL `refused` |

Every other row holds its 186b verdict. The three `no_verb_classified` rows did not change. The
post-roll vector backfill would have relocated 0 rows, so "the backfill will fix them" is falsified.
Their cause is still open.

## The regression, measured

1. **The refusal is reproducible.** The row was fired 3 times, and all 3 returned archetype
   INSTANCES_BY_PROPERTY with `refusal.outcome=refused` and `reason=notice_required`. That reason
   comes from `agent_fleet/ontology_service/notice_parts.py:228`, the "no notice id reached it"
   branch. The verb never received PCN26-182.
2. **The notice is drop-derived.** I read engine-o's Neo4j (READ session, same join as
   `NOTICE_PARTS_CYPHER`). PCN26-180, PCN26-182 and PCN26-184 each have:
   - `provenance_ingest_id` set
   - an `IngestArtifact`
   - 1 `PROMOTION`
   - a `dropped_by_authz_id`
3. **No artifact carries an origin.** Engine-o's own Neo4j warns that the property keys
   `origin_owner_domain`, `origin_program` and `origin_resolved_by` do not exist in the database.
   So `source_visibility` (`notice_parts.py:183-185`) answers `withheld` at its
   no-resolved-origin branch for every caller except the dropper.
4. **The withhold now reaches resolve.** 69d72b59 (74, Q7) makes `/resolve_instance` call the
   same `notice_visible` verdict. It drops the withheld notice candidate, so the fan-out for
   'PCN26-182' finds nothing the caller may see, and the verb is asked with no notice id.

**Conclusion.** The rule is doing what Q7 and b02b49bd ruled. This is not a code defect in either
commit. The state it reads was never written: no promotion origin exists, because the Q9
promotion-origin backfill has not run.

**Not measured.** I did not read the artifact's `dropped_by_authz_id` against bob's id, so I have
not ruled out the dropper branch. Bob being refused implies he is not the dropper.

## Two asks

- **gov, Q9 owner.** The origin backfill is the fix for this row and for every other drop-derived
  notice. Its dry run exits 2 for two reasons:
  - `BACKFILL_ACTOR` is unset. Chris must name the person; I have asked.
  - The cortex-bff pod has no NEO4J env. Engine-o's pod has NEO4J_URI, NEO4J_USERNAME and
    NEO4J_PASSWORD, so engine-o is a candidate host for the run.

  Please confirm that engine-o is the right place to run it, or name the right place.
- **74, Q7 owner.** The user sees "Which notice?", a request for a notice id they already typed.
  The answer equals a Jena that never held the notice, so that is exactly as ruled ("a withheld
  candidate is simply absent").
  - If the architect wants the walk to say *why*, that is a ruling, not a fix. I am not widening
    anything here.
  - Architect: this is a judgement for you. Absence-as-answer is a deliberate non-oracle, and this
    row is its first live cost.

## What I did not do

- I did not touch notice_parts, resolve_instance, the origin rule, or any seal.
- I made no Neo4j write.
