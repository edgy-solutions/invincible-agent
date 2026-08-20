---
id:         triage-card-archetype
status:     closed
owner:      agent
blocked-on:
closed-by:  906cf64
trigger:    WAKE when the first real unprocessable notice arrives that Re-drive CANNOT fix - i.e. when a human actually needs an escalation lane, not before. Until then Acknowledge-with-reason covers the case honestly. Lifted out of prose into this field 2026-08-20 so a generated board can see the condition.
code-site:  src/iagent/human_tasks.py, src/iagent/gateway.py, tests/test_task_verbs_by_kind.py
repo:       invincible-agent
summary:    A triage task is a THIRD species, not an approval. Offering Approve/Reject on "this notice could not be prepared for review" records a decision the schema cannot represent, and ADR-0034 would archive it as evidence. Verbs are now per-species and a wrong verb is REFUSED, not stored; cortex-ui ships TRIAGE_TASK (e55d308). Verified 2026-08-19: 11 tests green incl. refuses-approve-and-reject and acknowledge-without-a-reason-is-refused.
---

# The triage card — a THIRD task species, not an approval

**Status:** RULED, not built (2026-07-31). Punch list below; mostly reuse.
**Raised by:** the refusal-routing witness. The triage task landed correctly in alice's timeline —
audience-routed, provenance-stamped, consequence-language intact — and rendered with the generic
approval card's affordances, which are **lying about what the task is.**

## The honesty bug

The card offers **Approve / Reject** on *"this notice could not be prepared for review."*

Approve… the failure? The task's actual semantics are **disposition of a broken input**, not a
decision on a proposal. And this is not cosmetic: whichever button alice clicks **records a
decision the schema cannot represent.** `acted_by: alice, decision: approved` on an extraction
failure is provenance nonsense — and it is nonsense that the ADR-0034 decision-record work would
then faithfully archive forever, as evidence, into the corpus that governs promotion.

**Fix the verbs before the first real click writes gibberish into the audit trail.** That ordering
is the whole urgency: the cost is not confusion, it is corrupted evidence.

## The honest verbs

| verb | means | mechanism |
|---|---|---|
| **Acknowledge** *(reason REQUIRED)* | seen; genuinely unprocessable or handled out-of-band | closes the task with its reason |
| **Re-drive** | the underlying issue is fixed — re-fire extraction | one wired call to machinery that **already exists**: a re-extract writes a new `review.json`, whose new ETag the sensor sees as new work by arrival time |
| **Escalate** *(later)* | this is a pipeline problem, not a document problem | the systemic channel, human-invoked — the counterpart to automatic systemic routing |

**Reason-required on Acknowledge is load-bearing**, not a form nicety: "parts entered in legacy
system" and "notice withdrawn by vendor" are entirely different facts about the pipeline, and a
bare acknowledge erases the difference. The reason field is also **v1 of key-it-in** (see the
third act) — it covers the honest cases today without building the lane.

## Evidence: this card needs it MORE than a review does, not less

Today the triage card offers a raw S3 path in monospace. The review card summons page renders,
highlights and crops. **That is inverted.**

Consider what alice is actually asked: judge whether a notice **the machine could not read**
matters — with *less to look at* than she would have for one it read fine. The unprocessable
notice is precisely the case where a human's eyes on the **original document** are the entire
value-add.

The machinery is on the shelf:
- the failed extraction **still ran the partition** — page renders and the surviving crops exist
  (3 of 5 succeeded is the motivating case);
- the **evidence-card summon pattern** is built;
- the **`not_found` treatment** — *"here's the page, we couldn't anchor it, you look"* — is exactly
  the right rendering for *"here are pages 1–5; crops on 3 and 4 failed; scan for the parts table
  yourself."*

So the triage card's evidence summon is the **same component pointed at the same artifacts with a
different framing line**.

## Punch list

1. **`TRIAGE_TASK` becomes its own archetype** — registered in `taskKindRegistry` (per the
   registered-or-honest-fallback rule; an unregistered kind must degrade visibly, not borrow
   another species' affordances, which is exactly how this bug shipped).
2. **Verbs:** Acknowledge / Re-drive. Escalate deferred.
3. **Reason REQUIRED on Acknowledge** — the capture-why discipline, verbatim.
4. **Evidence summon** wired to the existing page renders, with crop-failure framing.
5. **Re-drive** wired to re-extraction (new ETag → sensor sees new work; nothing new to build
   underneath).

## Third act — manual extraction as a fallback lane (FILED, with its wake)

The instinct "maybe the user keys the parts in themselves" is bigger than a text box: it is
**manual extraction as a fallback lane** — the human reads the source pages and enters the parts
the extraction missed, producing a review whose provenance says `extraction: manual,
entered_by: alice` **per part**.

Genuinely valuable: it is the **only** path that recovers a truly vision-hostile scan. Also
genuinely later, because it needs the part-entry form, per-part manual provenance threaded through
the batch (the shape exists — the `needs_review` chain already carries per-part flags), and — the
part nobody should improvise — **manually-entered parts flowing into the disposition pipeline as
first-class citizens with their entry provenance intact.**

> **WAKE:** fires when the first real unprocessable notice arrives that **Re-drive cannot fix** —
> i.e. when a human actually needs the lane, not before.

Until then, **Acknowledge-with-reason covers the case honestly.**

## Note for whoever builds this

The fixture is already maintained: `tests/fixtures/failure_path/cropfail_review.py` builds the
flagged-and-empty notice from a real extraction. Use it — the pipeline no longer produces this
input organically, and it will be rarer still by the time this card changes again.
