---
id:         a-fallback-that-absorbs-every-failure-reports-none
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0017 (rendersAs / the presentation paths); ADR-0033 (route | ask | abstain); ADR-0042 §2 (the selector decides from the payload)
code-site:  agent_fleet/presentation_agent/main.py (the four X-Presentation-Path branches; `_render_document_deterministic` is the terminus of three of them), agent_fleet/presentation_agent/capability_registry.py:239 (select_archetype, whose provenance ALREADY discriminates)
summary:    THE DISCRIMINATING INFORMATION ALREADY EXISTS AT ALL THREE LAYERS AND IS THROWN AWAY BEFORE THE CARD. `X-Presentation-Path` already told seams 8 and 9 apart while the card did not; `select_archetype` already returns a provenance naming which refusal fired; the supervisor already logs the timeout and the no_match. THIS IS A PLUMBING REQUEST, NOT A BUILD REQUEST — carry what exists to the surface that renders. The cost of not doing so, measured: three unrelated seams — a missing rendersAs binding, a fill_slots timeout that turned a specified question into an ask, and a subject-coverage gap that made four verbs non-candidates — ALL rendered as `Knowledge Document / No content available`. A fourth path reaches the same floor (subject_unknown → generalist fallback). Diagnosis took a night because the card carried no discriminating information, and fixing the first seam changed nothing observable, which ARGUED FOR THE WRONG CONCLUSION. The law: a fallback that absorbs every failure class reports none of them.
---

# A fallback that absorbs every failure class reports none of them

> **The discriminating information already exists at all three layers and is thrown away before
> the card.** `X-Presentation-Path` already told seams 8 and 9 apart while the card did not.
>
> **This is a plumbing request, not a build request.** Nothing here needs to be computed. It needs
> to be carried to the surface that renders.

## The four paths, and the one thing a person saw

| # | seam | what was actually wrong | what the card said |
|---|---|---|---|
| 8 | `rendersAs` binding absent | `fin:` missing from a CURIE prefix map → Contract D refused six registrations | `Knowledge Document · No content available` |
| 9 | `fill_slots` timeout | mandatory slot unfilled → correct ASK → ask card has no `output_uri` | `Knowledge Document · No content available` |
| 10 | subject coverage | question grounded to `fin:Program`; four verbs hang off sub-entities → `no_match` | `Knowledge Document · No content available` |
| — | grounding failure | `subject_unknown` → Contract B correctly refuses → generalist fallback, which carries no `output_uri` | `Knowledge Document · No content available` |

**A timeout, a coverage gap, a missing binding and a grounding failure are not similar problems.** They live in four
different services, have four different owners, and four different repairs. They were
indistinguishable at the only surface anybody looks at.

## Why this was expensive rather than merely untidy

Seam 8 was found first and fixed. **Nothing observable changed** — the card still said the same
sentence, because seams 9 and 10 were behind it producing the same output. Without the row counts
(`23 → 29`) and a direct probe of the selector (`6/6, source=registered`), the honest reading of
the evidence would have been *"the binding fix didn't work"*, and the next move would have been to
re-open a repair that was already correct.

**A uniform fallback does not just fail to help; it actively argues for the wrong conclusion**,
because "I fixed it and nothing changed" is evidence against a correct fix.

## This is the count law's uniform-fallback twin

The count law says a count that cannot distinguish two populations is not a measurement. The same
shape one layer out: **an outcome that every failure class collapses into is not an observation.**
Both are cases of a summary that is stable for reasons unrelated to the thing it summarises — the
property already recorded in `[[the-winner-is-a-sample-the-set-is-the-answer]]` about a total that
reproduced because its instability sat inside one bucket.

## Everything needed is already computed, and then dropped

**This is the whole point of the packet, restated where the detail lives: the discriminating
information EXISTS at every one of these sites and is discarded before it reaches a person.**

1. `select_archetype` returns a provenance dict that already separates the cases by name:
   `presentation_source: registered | unrenderable | default-menu`, plus a `reason`
   (`"caller has no registered capability menu"`, `"no registered capability's contract is
   satisfied by this payload"`) and a `selection_basis` (`output_uri+payload` vs
   `payload-only (output_uri matched no capability)`). All of it is logged and none of it is
   rendered.
2. `/render_ui` already stamps `X-Presentation-Path` with four distinct values —
   `deterministic-document`, `archetype-hardened`, `fallback-designui`,
   `fallback-no-output-uri`. Seam 9 shows as `fallback-no-output-uri` and seam 8 as
   `deterministic-document`; **the header already told them apart while the card did not.**
3. The supervisor already logs `fill_slots unavailable … running on defaults` and
   `classify_predicate no_match … compatible=[…]`.

Three layers each hold the answer. A person holds a sentence that fits all four failure paths.

## What to plumb

**Carry the reason to the card — it is already computed at every site below.** The KNOWLEDGE_DOCUMENT fallback should state which of these
fired, in the reader's language:

* *"no view is registered for this answer type"* (binding absent — an operator problem)
* *"I need to know which program"* (an ask — and it must be honest about whether that was a
  considered elicitation or a timeout, per `[[a-mandatory-slot-does-not-refine]]`)
* *"nothing I can do answers this about a program"* (coverage — and it should name what the
  question CAN be asked about)
* *"I could not tell what this question is about"* (grounding failed; Contract B correctly
  refused, and the generalist answered instead — the reader should know the mesh was not
  consulted, per `[[the-winner-is-a-sample-the-set-is-the-answer]]`)

**And the seal that makes it stay true: no two distinct failure classes may produce
byte-identical card text.** That is assertable over the fallback's own reason vocabulary, and it
fails today with four collisions.

## Scope

Not specific to finance. Every one of these failure modes is reachable by any engine; Engine F
merely hit all four in one week, which is the only reason the collision was visible at all.
**A single engine hitting one of them would have paid the same diagnosis cost with no way to
know why** — and would most likely have concluded its own repair had failed.

## Related

* `[[a-mandatory-slot-does-not-refine]]` — seam 9, and the one whose card text is most misleading.
* `[[four-subjects-means-four-questions]]` — seam 10.
* `[[engine-f-ui-path-seam-audit-v1]]` — the audit where all three were separated.
* `[[a-plausible-negative-is-not-a-considered-one]]` — the same family: an output that reads as
  deliberate because nothing distinguishes it from one.
