# RETRACTED IDENTIFICATION — I measured the ASK and asserted about the ANSWER

**Superseded 2026-09-14 by the architect, who has the screens.** The measurement below is
accurate; **the artifact it was taken from is the wrong one**, and the conclusion drawn from it
was wrong in the harmful direction. Kept rather than deleted because the retraction is the
useful part.

## What I claimed, and what is actually true

I read `artifact-1-1789404282812`, found a correct `ask`, and concluded the card rendered its
summary instead of its ELICITATION component — therefore **neither** candidate owner, therefore
both lanes should stand down.

**Artifact-1 rendered correctly.** It is on screen: *"Which program did you mean?"* with
Notional Program Meridian offered as an option, ELICITATION displayed, exactly the 823-byte
payload described below. The elicitation path works, end to end, including the render.

**The empty card is a SECOND artifact** — the rail entry at **11:46, marked 2 hops**, written
after the program was picked. The sequence was:

    ask (correct, rendered)  ->  pick  ->  ~1m09 over two hops  ->  27-byte summary, nothing else

I never opened it. **And my "stand down" told the two lanes whose candidates are exactly right
for that artifact to stop looking** — including my own. For an answer-after-pick, "the brief's
`StatefulSupportResponse` came back empty" and "the `KNOWLEDGE_DOCUMENT` binding cannot render
its shape" are both live, and the first is engine-lg's.

## How I picked the wrong artifact, which is the part worth keeping

**The two artifacts of one exchange share every field I identified it by.** Same question text,
same subject, same verb, both with a short summary. I selected on those, found artifact-1, and
treated a match on the shared fields as an identification.

The fields that actually distinguish them are the ones I did not use: **lineage**
(`DERIVED_FROM` — the answer carries the pick in its ancestry and the ask does not), the **hop
count**, and the **timestamp**. `tests/routing/test_ask_to_answer_lineage.py` exists precisely
because adjacency is not lineage; I made the error its docstring warns about, from the other side.

**A shared identifier cannot identify — and the ask/answer pair is built to share them.** When
two records describe one exchange, select on the relation between them, never on their common
description.

Compounding it: I asserted about **a card I never saw**. Every fact I had was from the payload;
"the card displayed the summary" was an inference presented in the register of a measurement,
and it was the load-bearing claim.

## What still stands

The measurement of artifact-1 is real and worth keeping, because it proves the whole ask path:

```
resolved_intent.disposition   "ask"        accepted_slots {}
rendered_output               823 bytes
  archetype      ELICITATION      slot  program_id     reason  slot-unfilled
  message        "Which program did you mean? Options: Notional Program Meridian."
  option_source  enumeration      options [{Notional Program Meridian / NP-MERIDIAN}]
  provenance     candidates_considered 1, satisfied 1, presentation_source registered,
                 selection_basis output_uri+payload
```

The slot declaration, its referent, the enumeration provider, the disposition declining to guess
a mandatory slot, the presentation selector, **and the render** all work. That is a real result
about the ask; it is not a result about the empty card.

And the generalisation survives its own retraction, because it was never about which artifact:
**an ask is not a degraded answer, it is a different kind of answer.** It just does not apply
here — this ask was rendered as an ask.

## What is still unread

**Artifact-2: the 11:46 rail entry, 2 hops**, whose `resolved_intent` says whether the graph ran
under the picking identity with `program_id` bound, or whether the pick fell back to the full
path and produced a different artifact. Dagster run `8b5b3710` succeeded in 56s inside that
window; the card took 1m09 over two hops, and that gap is unexplained.

That artifact is the subject. Nothing above is evidence about it.
