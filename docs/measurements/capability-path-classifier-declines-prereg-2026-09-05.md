---
id:         capability-path-classifier-declines-prereg-2026-09-05
status:     PRE-REGISTERED — written before reading the artifact or any prompt
owner:      agent (lane 1)
repo:       invincible-agent
summary:    "What is the capability path" grounds `Capability` at 0.97, `planCapabilityPath` reaches the classifier flagged `needs_instance`, three candidates are offered, and the classifier returns nothing confident. No exclusions are recorded, so the gate did not remove it — the classifier DECLINED it. The dispatch's hypothesis is that the `needs_instance` marker leaks into the verb description and reads as "not applicable to this question". This records what I expect before looking, because the flag is mine and I am the worst-placed person to evaluate it fairly.
---

# The classifier declines `planCapabilityPath` — pre-registration

## Why I am the wrong person to guess freely here

I added `needs_instance` yesterday. If it leaks, the defect is mine, and the temptation is to
look at the prompt and find whatever exonerates the flag. So the predictions go down first, with
the evidence that would settle each, and the prompt gets read afterwards.

## What is already known (from the dispatch, not from my own reading)

* `Capability` grounds at 0.97 — subject resolution is fine.
* `planCapabilityPath` **reaches** the classifier. It was not excluded.
* **Three** candidates are offered. *(Note: I measured TWO verbs for `idp#Capability` under
  PORTFOLIO_PLANNING on 2026-09-05. Three means the scope differs — a different persona or
  domain set. That difference is itself a thing to record, not to assume away.)*
* The eligibility trace is **empty**, which is the trace working: it says no gate removed
  anything, so the refusal is downstream of every gate.

## Predictions

**P1 — THE FLAG LEAKS INTO THE PROMPT.** The text sent to `ClassifyPredicate` contains
`needs_instance` (or a rendering of it) attached to `planCapabilityPath`, and the model reads it
as a disqualifier — "this verb needs an instance, the question has none, therefore not
applicable". The flag was designed as routing metadata and would be functioning as instruction.
*Settled by:* the `---PROMPT---` block engine-o logs for the classify call. Either the string is
in it or it is not. **This is a binary with no interpretation step**, which is why it goes first.

**P2 — THE FLAG NEVER REACHES THE PROMPT and the refusal has another cause.** The dynamic enum
is built from `verb_iri` (plus a curated description) and the extra dict key is dropped on the
way. Then the decline is about the verb's own DESCRIPTION versus the question — and the likely
sub-cause is the classifier's own instruction to prefer UNKNOWN when a candidate "would be the
wrong substrate or wrong intent", which I read yesterday in the prompt text.
*Settled by:* the same prompt block, plus the model's stated `reasoning`.

**P1 and P2 are exhaustive on the leak question and mutually exclusive.**

## What I expect NOT to find, recorded so a null result still means something

* **If `needs_instance` is absent from the prompt AND the model's reasoning cites the
  question naming no instance**, then the information leaked by a route I have not thought of
  (the slot declarations, `required_args`, the verb's own description mentioning an id). That is
  a third possibility and it is the one I would misread as P2.
* **If the candidate list contains a verb I did not expect** (three, not two), the scope is
  different from the one I measured, and any comparison to yesterday's numbers is invalid.
  Record the persona and domains actually on the request before comparing anything.

## The fix this would imply, stated in advance so it is not reverse-engineered

If P1: **the flag stays on the routing record and comes off the classifier's view.** It is
provenance, not an instruction — the same distinction as the eligibility trace, which is
recorded and never fed back into a decision. The verb dict sent to `/classify_predicate` gets
the key stripped, and the record keeps it.

If P2: the flag is exonerated and the cause is the verb description or the UNKNOWN-preference
instruction, which is a different lane's change and a different packet.

## The measurement after the fix

**Four things per draw**, N draws of the same phrasing: the winner, the candidate SET, set
disjointness across draws, and whether the winner carries a verb in that scope. A fix verified
on one draw of a sampled classifier is not verified.
