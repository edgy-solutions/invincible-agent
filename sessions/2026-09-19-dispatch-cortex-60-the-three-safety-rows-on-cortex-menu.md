# Dispatch to cortex-60 — the three `safety:` rows are missing from cortex's menu

to: ia-cortex-60/lane/cortex-60

**Ruled by the architect 2026-09-19**, who read both tables and resolved the fork. Relayed by
Lane 1 with the premise re-checked below. **This is the half that makes bob's screen draw.**

## What the walk census measured

`draft a risk assessment for HAZ-1003`, asked as bob (SAFETY_ENGINEER·SUSTAINMENT), frontend
`cortex-ui-desktop`:

    route_status         matched · mesh:draftRiskAssessment · fallback false
    subject              http://internal/sustainment/safety#RiskAssessmentDraft
    presentation_source  "unrenderable"
    reason               "no registered capability's contract is satisfied by this payload"
    refusal              KNOWLEDGE_DOCUMENT — "no typed contract for KNOWLEDGE_DOCUMENT; and
                         output_uri matched no capability, so nothing declared this archetype
                         for this answer"   (verdict: not_evaluated)
    markdown             "No content available."

**Routing is not the problem.** The verb registered, matched, and produced a draft. The selector
then found no capability for that subject on cortex's menu, widened, and declared nothing.

## THERE ARE TWO MENUS AND THE ROWS WENT INTO THE OTHER ONE

74 added all three safety rows to `agent_fleet/presentation_agent/capabilities.py` on Tuesday.
That table writes the **`__system_default__`** menu. Cortex's menu is written by the browser POST
to `/register_frontend_capabilities`, and it is the one `select_archetype("cortex-ui-desktop", …)`
reads. The header above that table's finance rows predicted this failure in as many words —
*"adding them here while believing they fixed cortex would have been a fix aimed one menu to the
left."* That is exactly what happened.

**Verified rather than assumed, with a control in both directions:**

    backend capabilities.py          3 safety rows present
    cortex assembleCapabilities.ts   0 safety, EITHER spelling
    same file, control               7 rows matching http://invincible-agent/cost#

The control matters: cost appears in cortex's menu in BOTH the prefixed and full-IRI forms, so a
pattern finding zero safety rows is a finding and not a blind matcher. (My first attempt at this
check returned 0 for cost and finance too — it had matched the test file. A control that returns
zero for everything proves only that the instrument is broken.)

## The fix — three rows, in `src/registry/assembleCapabilities.ts` (`DERIVED_BINDINGS`)

| subject | contract |
|---|---|
| `http://internal/sustainment/safety#RiskAssessmentDraft` | `MARKDOWN_RENDERER_CONTRACT` |
| `http://internal/sustainment/safety#DeferralRiskCard` | `MARKDOWN_RENDERER_CONTRACT` |
| `http://internal/sustainment/safety#OrphanedHazardSet` | `CONTRIBUTION_RANKING_CONTRACT` |

`persona_fit: ["SAFETY_ENGINEER"]`, `domain_fit: ["SUSTAINMENT"]` on all three.

**Where those two values come from, because the obvious source does not carry them.** The backend
capability rows have `persona_fit: None` and `domain_fit: None` for all three — I checked. The
authority is the engine's own declaration:

    agent_fleet/safety_agent/main.py:108   OWNER_PERSONA = "SAFETY_ENGINEER"
    agent_fleet/safety_agent/main.py:109   DOMAINS = ["SUSTAINMENT"]

(A 2026-09-14 note saying engine-safety registers with NO domains and NO owner_persona is STALE —
it declares both now, which is why the route matches at all.)

`expected_fields` comes from the contract, not from a hand-copied list —
`assembleCapabilities.test.ts` already asserts
`expected_fields === Object.keys(CONTRACT.fields)`. Deriving it is what keeps that green.

## ⚠ THE TRAP: A DIFFERENT AUTHORITY AND PATH

Use the **full IRIs above**. Safety does not live under the authority every other engine uses:

    cost, fin, mesh, …   http://invincible-agent/<engine>#
    safety               http://internal/sustainment/safety#     <- DIFFERENT

`capabilities.py` warns about this at its prefix map (`"safety:"` →
`http://internal/sustainment/safety#`) and calls it out as the silent failure mode: a row written
under the wrong authority registers fine, reports accepted, and never matches. An unknown prefix
passes through verbatim.

## Then the mirror seal closes the class

91's mirror seal was widened fleet-wide for exactly this shape, and their report already names
the gap: *"the 3 `safety:` rows stay unasserted."* Once these three land, the seal asserts them
**both ways** — a row in one menu and not the other becomes visible, which is the check no
per-menu test can make. That closes it for the next engine rather than for this one.

## What is NOT yours

The missing `risk_acceptance_medium` task row is a **separate defect** and is 74's. The card
drawing and the task appearing are different acts: the draft is the verb's output, the task is
what the workflow engine creates when the safety definition triggers on that output. It is
measured AFTER the card draws, not before. See 74's packet.

Lane: ia-01/lane/01
