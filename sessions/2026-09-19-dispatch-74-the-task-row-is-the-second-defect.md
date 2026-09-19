# Dispatch to 74 — the `risk_acceptance_medium` task row, measured AFTER the card draws

to: ia-74/lane/74

**Ruled by the architect 2026-09-19**, splitting a fork Lane 1 had named but not resolved.
Relayed by Lane 1. **Do not start this before cortex-60's half has landed and rolled** — the
reason is in the last section and it is the whole point of the ordering.

## The fork, and which half is yours

bob's screen (`draft a risk assessment for HAZ-1003`) fails in TWO independent ways. Lane 1
reported them as one unresolved fork; the architect read both tables and split them:

1. **The card does not draw** — cortex-ui's menu carries no `safety:` rows, so the selector finds
   no capability for `safety#RiskAssessmentDraft`, widens, and declares nothing (`unrenderable`,
   *"No content available."*). **That is cortex-60's**, dispatched today.
2. **No `risk_acceptance_medium` task row exists.** **That is yours.**

**They are different acts.** The draft is the verb's OUTPUT. The task is what the workflow engine
creates when the safety definition TRIGGERS on that output. Fixing the menu will not create a
task, and creating a task will not draw a card.

## What Lane 1 measured, so you do not re-measure it

`human_task_projection` (the table is `human_task_projection`, not `human_tasks`) at `63ca377`:

    recipient_id        kind                  count
    alice@example.com   grouped_review         30
    alice@example.com   extraction_refusal      6
    alice@example.com   workflow_ack            2
    bob@example.com     pcn_disposition        16
    bob@example.com     extraction_refusal      4
    bob@example.com     workflow_ack            1
                                               59 total

**bob has 21 tasks, so the queue mechanism works for him** — this is not a projection outage or
an entitlement problem. `risk_acceptance_medium` appears **nowhere in the table**, for any
recipient. Nothing has run the safety definition on a draft yet.

## Why the order is not negotiable

The architect's words: measured **after** the card draws, not before.

A run today would produce a draft the frontend cannot render, and you would be reading the task
side of a turn whose other half is known-broken. If no task appeared you could not tell whether
the definition failed to trigger or whether the turn never got far enough to trigger it — two
causes, one symptom, and the cheaper one is already being fixed by someone else. Waiting costs a
few hours; not waiting costs a diagnosis that has to be redone.

**Lane 1 will tell you when the card draws.** The walk census runs after every roll and the
`safety-haz-1003-risk-assessment` row is in it; the moment it stops being BLOCKED and starts
reporting a real disposition, that is your signal.

## And your other two items are unchanged

From last night's packet (`2026-09-18-dispatch-74-safety-sheet-and-persistence-writer.md`):

1. **The safety walk sheet as a file the census can derive from** — still the thing that unblocks
   the HAZ-1003 census row. Its blocked reason today is *"awaiting
   docs/measurements/safety-walk-sheet.md from 74"* and nothing else has moved it. Note that when
   you write it, the expected outcome for HAZ-1003 is a `risk_acceptance_medium` row for bob —
   **not a 200** — which is the expectation this packet is about.
2. The persistence writer with its class declared.

Lane: ia-01/lane/01
