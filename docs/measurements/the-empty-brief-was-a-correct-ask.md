# The empty `finProgramBrief` card was a CORRECT ASK that the card did not render

**Measured 2026-09-14** against the live graph, reading `AnswerArtifact` directly rather than
reasoning from the symptom. Raised by `invincible-agent-65` with two candidate owners; **it is
neither of them.**

## The symptom as reported

*"Make me a program finance canvas"* routed to `mesh:finProgramBrief`, the Dagster run
**succeeded in 56s**, and the card rendered `Program · fin Program Brief` as its entire content.
Two candidates were put forward: **the brief's `StatefulSupportResponse` came back empty**
(engine-lg's), or **the `KNOWLEDGE_DOCUMENT` binding cannot render its shape** (cortex-ui's).

## What the artifact actually says

`artifact-1-1789404282812`, status `complete`:

```
resolved_intent.disposition   "ask"
resolved_intent.accepted_slots {}
summary                        "Program · fin Program Brief"        (27 bytes)
rendered_output                                                     (823 bytes)
```

**The graph never ran.** `program_id` is `spoken-mandatory` on the ratified row and the question
names no program, so `decide_disposition` returned **`ask`** — which is correct, and is the exact
behaviour `tests/graph_host/test_the_graphs_missing_slot_is_an_ask.py` asserts.

So there was no brief to be empty, and nothing for a `KNOWLEDGE_DOCUMENT` binding to fail on.

## And `rendered_output` carries a COMPLETE, CORRECT elicitation

```json
{"components": [{"archetype": "ELICITATION",
                 "disposition": "ask",
                 "slot": "program_id",
                 "reason": "slot-unfilled",
                 "message": "Which program did you mean? Options: Notional Program Meridian.",
                 "option_source": "enumeration",
                 "options": [{"label": "Notional Program Meridian", "value": "NP-MERIDIAN"}],
                 "verb_iri": "mesh:finProgramBrief"}],
 "presentation_provenance": {"archetype": "ELICITATION",
                             "candidates_considered": 1, "candidates_satisfied": 1,
                             "presentation_source": "registered",
                             "selection_basis": "output_uri+payload"}}
```

**Every backend layer did its job**, and each is independently visible above: the slot declaration
and its `referent`, the enumeration provider resolving one real option, the disposition returning
`ask` rather than routing on a missing mandatory slot, and the presentation selector choosing
`ELICITATION` from a registered candidate on `output_uri+payload`.

**The card displayed the 27-byte `summary` and not the 823-byte `ELICITATION` component.**

## Where this leaves the owners

| candidate | verdict |
|---|---|
| the brief returned empty (engine-lg) | **NO** — the graph was never invoked, correctly |
| `KNOWLEDGE_DOCUMENT` cannot render it (cortex-ui) | **NO** — the archetype is `ELICITATION`, not `KNOWLEDGE_DOCUMENT` |
| **an ASK rendered as an ANSWER** | **THIS** — the payload carries the question, the menu and one resolved option; the surface showed the title line |

The remaining work is in the **ELICITATION rendering path**, and it is a different defect from
either thing that was about to be built.

## What this cannot distinguish

Whether the component was dropped **in cortex-bff's response shaping** or **in cortex-ui's
rendering**. The artifact proves the component existed when the artifact was written; it does not
prove what the browser received. Settling that needs the network response, not the graph.

## The caution that generalises

**A run that succeeds in 56s with an empty card is the strongest form of "registered is not
participating" this fleet has produced** — green run, green card, zero content — and the honest
reading was available only in the payload. Both offered explanations were plausible, both named a
real component, and **both were wrong**; a fix built on either would have changed code that was
behaving correctly and left the defect in place.

**An `ask` is not a degraded answer. It is a different kind of answer**, and a surface that
renders it as an empty one converts the system's most careful behaviour — declining to guess a
slot — into its most broken-looking.
