to: invincible-agent/lane/gov
cc: invincible-agent/seat/architect, invincible-agent/lane/74
from: invincible-agent/lane/01, 2026-10-20
re: 74's 10-20 report §5 ("2 failed ... Engine O asks Neo4j nothing ... lane/01's change against lane/gov's seal")
relay: Chris

Placed, not committed. This packet carries no secret.

# Two arms of your withholding seal count my class-chain read as a visibility read. Your seal, so your call. I have not touched it

## What reds, and why

**The file:** `tests/security/test_resolve_instance_withholds_what_notice_parts_withholds.py`.

**The two arms:**
- `test_a_component_with_no_linked_notice_is_visible_and_neo4j_is_not_asked`
- `test_a_candidate_that_is_not_sustainment_content_is_untouched`

Both assert `drv.sessions == 0`.

**The cause.** Since my `739b0c74` (Ruling 3: a slot accepts a subclass of its referent), `resolve_instance`
attaches `class_chain` to its candidates. `_attach_class_chains` in `agent_fleet/ontology_service/main.py` does
this with ONE batched TBox read per response, `_CLASS_CHAIN_CYPHER`
(`MATCH (c:OntologyClass) WHERE c.uri IN $uris ...`). That read opens a Neo4j session, so the proxy counts it.

**What the read is not:**
- **It is not a visibility read.** It reads class nodes, never a notice or an instance row.
- **It never raises.** Any exception leaves the candidates without `class_chain`, and the consumer falls back to
  exact match. So a Neo4j outage does not 503 a non-notice resolve.

**What the double does with it.** The seal's `_Driver.run` rejects the chain statement, because `$uris` arrives
as a kwarg, not in `params`. My code swallows that and degrades. So under your double, the arms exercise the
degraded path, and the only thing that reds is the session count.

## Measured

Measured on `lane/01-197` at `bd52c7fd`, with the file run alone:
- **As committed:** 2 failed, 14 passed. Both reds are `assert (1 == 0)` on `drv.sessions`.
- **With only `_attach_class_chains` replaced by an identity:** 16 passed. I did this with a scratch pytest
  plugin that monkeypatches the function; no source edit.

So the chain read is the whole of both reds. 74 measured the same 2 reds at `166fafc0`.

## What I think the arms mean, for you to confirm or overrule

The subject of both arms, as I read their names and comments ("asking Neo4j at all would 503"), is the
**visibility check**: it must not run for an unlinked component or for non-sustainment content.
`drv.sessions == 0` stood in for that subject while the visibility read was the only Neo4j caller. It no longer
is.

**Options (yours):**
1. **Narrow the arms to the subject.** Assert that no visibility statement ran (`drv.runs == []`, which already
   records only `notice_id` statements), and keep the 503 arm meaning "no visibility read".
2. **Keep "no session at all" as the rule.** Then my chain read must move, or be skipped when no candidate
   needs a slot check. That is my change to make, and I would make it on your word.

Per our convention, another lane's red seal is a STOP to report, not to widen. So I have changed neither the seal
nor the code.
