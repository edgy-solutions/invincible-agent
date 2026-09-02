---
id:         a-fallback-that-absorbs-every-failure-reports-none
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0017 (rendersAs / the presentation paths); ADR-0033 (route | ask | abstain); ADR-0042 §2 (the selector decides from the payload)
code-site:  agent_fleet/presentation_agent/main.py (the four X-Presentation-Path branches; `_render_document_deterministic` is the terminus of three of them), agent_fleet/presentation_agent/capability_registry.py:239 (select_archetype, whose provenance ALREADY discriminates)
summary:    THREE UNRELATED SEAMS PRODUCED ONE INDISTINGUISHABLE SYMPTOM. A missing rendersAs binding, a fill_slots timeout that turned a specified question into an ask, and a subject-coverage gap that made four verbs non-candidates ALL rendered as `Knowledge Document / No content available`. The diagnosis took a night precisely because the card carried no discriminating information, and fixing the first only revealed the second. THE LAW, and it is the uniform-fallback form of the count law: a fallback that absorbs every failure class reports none of them. The fix is cheap and mostly already built — `select_archetype` ALREADY returns a provenance naming which refusal fired (`unrenderable` vs `no registered capability menu` vs an absent output_uri), and `/render_ui` ALREADY stamps X-Presentation-Path with four distinct values. Both are discarded before the card. Carry the reason to the card.
---

# A fallback that absorbs every failure class reports none of them

## The three seams, and the one thing a person saw

| # | seam | what was actually wrong | what the card said |
|---|---|---|---|
| 8 | `rendersAs` binding absent | `fin:` missing from a CURIE prefix map → Contract D refused six registrations | `Knowledge Document · No content available` |
| 9 | `fill_slots` timeout | mandatory slot unfilled → correct ASK → ask card has no `output_uri` | `Knowledge Document · No content available` |
| 10 | subject coverage | question grounded to `fin:Program`; four verbs hang off sub-entities → `no_match` | `Knowledge Document · No content available` |

**A timeout, a coverage gap and a missing binding are not similar problems.** They live in three
different services, have three different owners, and three different repairs. They were
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

## The fix is mostly already built and then thrown away

**This is the part worth emphasising: the discriminating information EXISTS at every one of the
three sites and is discarded before it reaches a person.**

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

Three layers each hold the answer. A person holds a sentence that fits all three.

## What to build

**Carry the reason to the card.** The KNOWLEDGE_DOCUMENT fallback should state which of these
fired, in the reader's language:

* *"no view is registered for this answer type"* (binding absent — an operator problem)
* *"I need to know which program"* (an ask — and it must be honest about whether that was a
  considered elicitation or a timeout, per `[[a-mandatory-slot-does-not-refine]]`)
* *"nothing I can do answers this about a program"* (coverage — and it should name what the
  question CAN be asked about)

**And the seal that makes it stay true: no two distinct failure classes may produce
byte-identical card text.** That is assertable over the fallback's own reason vocabulary, and it
fails today with three collisions.

## Scope

Not specific to finance. Every one of these three failure modes is reachable by any engine; Engine
F merely hit all three in one week, which is what made the collision visible at all. **A single
engine hitting one of them would have paid the same diagnosis cost with no way to know why.**

## Related

* `[[a-mandatory-slot-does-not-refine]]` — seam 9, and the one whose card text is most misleading.
* `[[four-subjects-means-four-questions]]` — seam 10.
* `[[engine-f-ui-path-seam-audit-v1]]` — the audit where all three were separated.
* `[[a-plausible-negative-is-not-a-considered-one]]` — the same family: an output that reads as
  deliberate because nothing distinguishes it from one.
