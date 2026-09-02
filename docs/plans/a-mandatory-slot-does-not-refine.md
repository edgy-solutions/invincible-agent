---
id:         a-mandatory-slot-does-not-refine
status:     open
owner:      agent (Engine F lane) — FILED, NOT FIXED: the filler is outside this lane's fences
blocked-on: the filler/supervisor lane
repo:       invincible-agent
ruled-by:   ADR-0033 (route | ask | abstain; the four-kind slot vocabulary); ADR-0045 (Engine F declares slots from day one)
code-site:  src/iagent/defs/dynamic_supervisor.py:1517 (_FILL_SLOTS_TIMEOUT_S, env FILL_SLOTS_TIMEOUT_S, default 20), dynamic_supervisor.py:~2009 (the ask_card branch whose expert_response carries no output_uri), agent_fleet/finance_agent/slots.py (the spoken-mandatory declarations)
summary:    THE 20-SECOND FILL_SLOTS BUDGET IS JUSTIFIED BY A PREMISE THAT IS FALSE FOR MANDATORY SLOTS. Its comment reads "a slot REFINES a question that will still be answered without it, so a slow extractor must cost the user a default, never a timeout." That holds for spoken-OPTIONAL. For spoken-MANDATORY it is exactly inverted: without the slot the verb cannot run, so the timeout does not cost a default — it converts a fully-specified question into an elicitation. Measured 2026-09-02: "why are we over budget on Notional Program Meridian" routed to finVarianceAnalysis at 0.96, engine-o extracted `program_id="Notional Program Meridian"` at 0.95 confidence and returned 200 OK, and the supervisor had already given up at 20s. The user is then asked "which Program?" about a question that named the program. EVERY Engine F verb has a spoken-mandatory slot, so this affects all six.
---

# A mandatory slot does not refine — so a timeout on it is not a default

## The premise, quoted from the code it justifies

```python
#: One model call's budget. Short on purpose: a slot REFINES a question that will still be
#: answered without it, so a slow extractor must cost the user a default, never a timeout.
_FILL_SLOTS_TIMEOUT_S = float(os.getenv("FILL_SLOTS_TIMEOUT_S", "20"))
```

**This is right for `spoken-optional` and inverted for `spoken-mandatory`.** ADR-0033's four-kind
vocabulary exists precisely because those two are different things, and this budget is applied to
both identically.

For a mandatory slot there IS no default to fall back to. Losing it does not degrade the answer;
it changes the disposition from **route** to **ask**.

## Measured 2026-09-02

One question — `"why are we over budget on Notional Program Meridian"` — as alice, persona
`PROGRAM_FINANCE_ANALYST`, domain `PROGRAM_FINANCE`:

```
routing_decision  subject_uri=fin#Program subject_conf=0.95
                  verb_iri=mesh:finVarianceAnalysis verb_conf=0.96

WARNING  fill_slots unavailable verb_iri=mesh:finVarianceAnalysis
         (engine-o:8084 Read timed out, read timeout=20.0) — running on defaults
```

**And engine-o answered it correctly, on the same request:**

```
---Parsed Response (class FilledSlots)---
{ "slots_json": "{\"program_id\":\"Notional Program Meridian\"}",
  "confidence": 0.95,
  "reasoning": "The question names \"Notional Program Meridian\", which directly provides
                the required program_id..." }
POST /fill_slots HTTP/1.1  200 OK
```

**Nothing was wrong with the extraction. The client stopped listening before it arrived.**

## What the user sees, and why it is the worst available outcome

With `program_id` unfilled, the disposition correctly becomes an **ask** — `"which Program?"` —
because a missing mandatory slot must never be defaulted. That behaviour is right.

The result is that a question which *named the program* is answered with a request to name the
program. And because an ask card carries no `output_uri`, `/render_ui` takes the
`fallback-no-output-uri` branch and the answer draws as `KNOWLEDGE_DOCUMENT` —
**which is indistinguishable from the presentation-binding failure this lane just fixed.** Two
unrelated causes, one observable.

## THE FAILURE MODE, STATED AS ITS OWN LINE

> **A question that named the program was answered by asking which program.**

And the reason this was invisible for a night is the part that generalises: **every guard
downstream worked correctly.** The disposition was RIGHT to ask — a missing mandatory slot must
never be defaulted, and that rule is one of the better ones in this system. The router was right
to route. The ask card was right to carry no `output_uri`, because it has no output. `/render_ui`
was right to take `fallback-no-output-uri`.

Every one of those components made the correct decision **on inputs that a timeout upstream had
made wrong.** Nothing was in an error state; nothing had a bug to find. The system was working as
designed, on a false premise, all the way down — which is why it presents as a considered
elicitation rather than as a fault, and why no amount of reading the downstream code would have
found it.

**A correct decision on a corrupted input is indistinguishable from a correct decision.** That is
the diagnostic cost of a silent upstream default, and it is the argument for (3) below regardless
of what is decided about the budget.

## Scope: all six Engine F verbs

Every Engine F verb declares at least one `spoken-mandatory` slot (`program_id`, plus `method`
on `fin_eac_calculation` where it is mandatory with no default, by ruling). So this is not a
property of one verb — **it is the whole engine**, and it will be the whole of any engine that
takes ADR-0045's "declare slots from day one" seriously.

## Options, none taken here

1. **Raise the budget.** One env var (`FILL_SLOTS_TIMEOUT_S`) in Helm values. Cheapest, and
   wrong as a resting place: it picks a bigger number for a premise that is still false, and the
   next slower model re-opens it.
2. **Make the budget conditional on slot KIND** — the declarations are already in hand at the
   call site, and `missing_mandatory()` already exists. A verb with a mandatory slot waits; a
   verb with only optional slots keeps the short budget and the original reasoning intact. This
   is the one that matches ADR-0033's own distinction.
3. **Separate the two failures at the card.** A timeout-induced ask and a genuinely
   under-specified question are different events, and today they are the same card. Whatever is
   decided about the budget, `running on defaults` after a timeout should not be able to
   masquerade as a considered elicitation — `[[a-plausible-negative-is-not-a-considered-one]]`,
   in its exact shape.

**RULED 2026-09-02 (architect): (2), and (3) regardless. DISPATCHED TO LANE 1.**

The ruling in the architect's words: *the fill_slots budget becomes conditional on the SLOT
CENSUS of the routed verb — a verb with spoken-mandatory slots gets a budget sized to the
measured fill time, a verb with only optional slots keeps the tight budget.* That preserves the
original comment's reasoning exactly where it is true and stops applying it where it is inverted.

Sizing input, from this measurement: engine-o returned the correct extraction at 0.95 confidence
with a 200 on the very request the supervisor abandoned, so the budget is short of a working
extractor rather than covering for a broken one. The step timings are already in the Dagster
event log — the number is a read, not an instrumentation project.

**Not fixed here: the filler is outside this lane's fences.** Handed over with the evidence
attached rather than diagnosed further.

## Related

* `[[a-plausible-negative-is-not-a-considered-one]]` — an ask that reads as deliberate and was
  produced by a timeout.
* `[[engine-f-ui-path-seam-audit-v1]]` — the full seam list; this is the one that stops all six
  today.
* `[[the-winner-is-a-sample-the-set-is-the-answer]]` — the neighbouring finding on the same path.
