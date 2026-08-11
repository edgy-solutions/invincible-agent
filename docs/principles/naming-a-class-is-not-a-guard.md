# The naming-a-class-is-not-a-guard law

> **Naming a failure class provides no protection against instantiating it. Only guards do.**

The evidence is not that people forget the rules. It is that **the author of a rule instantiates
it within hours of writing it**, while able to quote it. Understanding is not the mechanism that
prevents recurrence, so a commit that only *names* a class has shipped documentation, not a fix.

## The instances

Each is the same shape: the rule was written, understood, and then violated by the person who had
just written it — not later, and not by someone who had not read it.

| the rule | who broke it | how |
|---|---|---|
| *one implementation, not two* | the `iagent-mesh-sdk` v0.3.0 commit | argued in its own message that a second registration implementation is exactly what the rule forbids, built the shared transport — and left `MeshTool`, the SDK's own consumer, on the bare POST |
| *a mechanism must be applied, not merely available* | `core/authz.py` | importable and applied nowhere |
| *the board's header must describe its body* | ADR-0040 | the limitation was found **by the limitation firing** — `retire-inline-task-loop`'s body was updated, its `summary:` was not, and the board rendered the pre-read state |
| *a human ruling lands in the header* | the agent that promoted `[[gate-class-follows-the-effect]]` | wrote the promotion, then left both `dag-tools` packet headers saying they awaited the ruling it had just promoted — caught only by applying its own new sweep test |

The last one is the sharpest, because the gap between writing the rule and breaking it was the
same working session, and the instrument that caught it was the rule itself being applied a second
time rather than any understanding of it.

## What follows

**A finding is not closed by being documented.** When a class is named, ask what would *fail* if
it recurred:

* a test that reads the source and asserts the binding (`test_registration_consumer_is_bound`)
* a generator check that refuses to render (`UNBACKED`, `UNATTRIBUTED`, `DRIFT`)
* a marker in the code the next reader cannot miss
* a periodic sweep with one question (`blocked-on-human`: *has this actually been given?*)

If the answer is "nothing would fail; someone would notice", the class is named and unguarded, and
the next instance is already scheduled.

**Corollary — prefer the guard that fires on the AUTHOR.** The instances above were all caught
late, by a second reader or a later pass. A guard sited where the mistake is *made* (the drift
test at commit, the source-reading pin at test time) beats one sited where it is discovered.

## What this does not license

Not every named class earns automated enforcement, and ADR-0040 is the worked example of the
limit: a generator that inferred `summary` from a packet's body would be a **second decider**, and
a test asserting "the header reflects the body" would have to understand the body. There the
honest repair is procedural and is *recorded as a known limitation* rather than pretended away.

**The rule is not "always automate."** It is: *decide explicitly what would fail, and if the
answer is nothing, say so out loud* — so the exposure is a known property of the design rather
than a surprise the next reader rediscovers from the wreckage.

Related: `[[consolidation-completes-at-the-last-consumer]]`, `[[seals-must-be-proven-to-bite]]`.
