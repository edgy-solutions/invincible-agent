---
id:         a-resolved-relative-period-must-be-disclosed
status:     open
owner:      cortex
blocked-on:
repo:       cortex-ui (strip), invincible-agent (the resolved value is already on the wire)
ruled-by:   slot_corpus_v1_anchor_amendment.json — disclosure_requirement
code-site:  cortex-ui interpretation strip; the value arrives in the dispatch payload's `params`
summary:    THE ANCHOR STEP IS NOT DONE WITHOUT THIS. "what does spend look like this quarter" now resolves to window=["FY26-Q4"] using a fiscal calendar the user never saw and cannot check. That is an assumption the system made on the user's behalf, and an undisclosed assumption is the silent-narrowing failure the carry work removed, reintroduced one layer up. The strip already renders resolved ROUTING (subject, verb, confidence); it must also render resolved PARAMETERS, at minimum any whose value the user did not literally say. Nothing in invincible-agent blocks this — the resolved value is in `params` on the dispatch payload today.
---

# A resolved relative period must be disclosed

## What changed, and why it needs a surface

Before the anchor, *"what does spend look like this quarter"* filled nothing: the phrase named
a period and the system had no notion of now, so the verb ran on its default and the answer
covered every period. After the anchor, the same phrase resolves to `window: ["FY26-Q4"]`.

That is better — and it is **an assumption the system made on the user's behalf**, using a
fiscal calendar the user never saw. A program manager whose fiscal year starts in April and a
system whose FY26-Q4 ends 2026-09-30 will disagree, and today **nothing tells them.**

## This is the finding the carry work already removed, one layer up

`[[slots-are-extracted-then-dropped-at-dispatch]]` recorded, about a *dropped* parameter:

> the interpretation strip renders resolved **routing** (subject, verb, confidence), not verb
> **parameters** … So an auditing user has **no surface on which to notice the drop.**

The drop is fixed. The surface was never built. So a *resolved* parameter is now invisible
for exactly the same reason a *dropped* one was — and a wrong scope that the user cannot see
reads as an answer, whichever direction the error runs.

**Anchoring without disclosure is a silent narrowing wearing a helpful face.**

## What is asked

Render resolved **parameters** in the interpretation strip beside resolved routing. The
minimum useful rule:

> **Disclose any parameter whose value the user did not literally say.**

That covers the three resolutions now in the pipeline, all of which are the system choosing
on the user's behalf:

| the user said | the verb received | resolved by |
|---|---|---|
| "this quarter" | `window: ["FY26-Q4"]` | the anchor |
| "as of FY26-Q4" | `as_of: "2026-09-30"` | fiscal→date |
| "the Aurora site" | `site_id: "S1"` | `mesh:resolveInstance` |

A parameter the user said verbatim (`"by initiative"` → `group_by: "initiative"`) is less
urgent, though showing it costs nothing and makes the strip's silence meaningful.

## Nothing in invincible-agent blocks this

The resolved value is already on the dispatch payload's `params`, and the referent cases also
carry `resolution` with `spoken`, `instance_id` and `candidates`. Everything the strip needs
to say *"you said Aurora, I used S1"* is on the wire today. **This is a cortex item only.**

## Why it is not optional

The corpus grades the anchor's *correctness* and cannot grade its *visibility* — a battery
asserting on `/fill_slots` output sees the resolved value and has no opinion about whether a
person ever did. So the acceptance for this lives here rather than in the corpus, and the
amendment says it plainly: **the anchor step is not done without it.**

Correcting a wrong assumption also requires seeing it. Without the strip, a user whose fiscal
calendar differs has no way to discover why the numbers look wrong, and the most likely
outcome is that they conclude the data is wrong rather than the scope.
