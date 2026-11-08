---
title: Tasking: the board for people — three additions (design note, not a dispatch)
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: later
blocked_on: []
pr: []
ruling_ref: architect via Chris 2026-11-08, board note (Cross-cutting, new area Tasking): filed as an open item, priority later, owners Lane 1 (board), cortex (card), 74 (capture verb); not scheduled, filed so it is not reinvented
updated: 2026-11-08
---

**Area:** Tasking, a new area under Cross-cutting.

**Owners:**
- `invincible-agent/lane/01`: the board.
- `cortex-ui/master`: the card.
- `invincible-agent/lane/74`: the capture verb.

This is a design note, not a dispatch, and it is not scheduled. It is filed so it is not reinvented, and so that the answer to "tasking in Teams" at work is a demo, not an argument.

**Principle.** A tool makes the human do the machine's work when it asks for anything that can be derived. The human does two things: says what matters, and decides.

Everything else is derived from the tools people already use, and never captured by hand. That covers fields, status, ordering, dependencies, estimates and metrics. The sources are a commit, a PR, a test run, a merged review, a reply, a card accepted.

This is the same rule as the engineering metrics: new requirement, new code, new tests, tests pass, requirement met. They are read from the tools, never typed.

**What exists.**
- `board/items/<ulid>.md` and a generated render.
- Claim-by-commit.
- A2A state names.
- `human_await` as the attention primitive.

**The three additions.**

1. **Capture costs nothing.**
   - Any message, mail, meeting line or chat sentence becomes an item by being pointed at.
   - The agent fills these from context: title, source, asker, cell, rough size, proposed dependencies, priority section.
   - The person corrects one field at most.
   - A `dispatch` verb from any chat; never a form.
2. **The day's list is computed, not arranged.**
   - Each person declares a scoring row in their own cell, with weights for:
     - urgency (asker, deadline);
     - value (program, money);
     - affinity (learned from thumbs on items);
     - size (from history);
     - staleness (decay on long-running items, so a short valued item can legitimately jump a long one: value density, not raw priority).
   - The list is re-derived on every change.
   - A person overrides with a one-word reason, and the override tunes the weights.
   - A PM reads the same items under a different row. They may write exactly one field, the assignee. That is the field-scoped relation from the August design.
3. **State is inferred, never reported.**
   - Activity moves items: commit, PR, merge, reply, card decided.
   - Ambiguity becomes a one-tap `human_await` to the owner, never a status field to fill.
   - Dependencies and blocks are proposed from what the agent reads, and confirmed with a tap.
   - Sprints are a window the function looks through, not a ceremony.

**Rules.**
- Items stay tiny.
- Nothing hard-codes a project, team or field set; the scoring inputs are declared.
- The person's row and overrides live in their cell.
- Every derived value cites the activity it was derived from.

**Slice 1.** Chris is user zero.
- The "my day" cortex card, over existing board items.
- One declared scoring row (Chris's).
- Chat capture via the `dispatch` verb.
- Inference from the PR, merge and reply events the sweep already reads.

**The first test (the architect, on slice 1).** It is the loop the fleet runs every day by hand.
- Every "for you: merge X, approve Y, run Z, sign in as alice and look" is a `human_await` addressed to Chris. Today it lives in replies and in Chris's head.
- Under slice 1, those asks are items the agents file. The lanes already write "needs Chris" lines in every report; that is the capture.
- The row scores them. A roll approval outranks a merge. A two-minute merge that unblocks three lanes outranks a long review.
- The card shows them in order, with the context attached: the values diff inline, the merge button, the login link.
- Chris taps, and the item moves because the merge happened, not because Chris said so.

**The one line for the lanes, when it is built:** "a needs-Chris line in a report is a board item addressed to Chris, or it doesn't exist." That turns the whole fleet's asks into one queue. It demonstrates the principle on the person who feels the cost most.
