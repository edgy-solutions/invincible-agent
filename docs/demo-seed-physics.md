# Seed physics — four facts the room can ask about, with the answers already written

Referenced from [demo-day-runbook.md](demo-day-runbook.md) §C.

Each of these is a **property of the model**, not a bug and not a workaround. Each is something
a sharp person in the room could notice and ask about. The point of writing them down tonight is
that **the presenter answers rather than improvises** — and in three of four cases the honest
answer is a design statement that lands better than the question.

All four are pinned by tests (`tests/planning/test_demo_seed_beats.py`,
`test_producer_declarations.py`, `test_reschedule_policy.py`), so a later seed edit that breaks
one fails a suite rather than a rehearsal.

---

## 1. Site B is the only site that can cross — and it was always near its ceiling

**Measured:** at baseline **no site is over threshold**. Site B peaks at 1.8 against 2.0; the
others have real headroom (1.8/2.0, 2.2/2.5, 2.0/2.5). The scripted drag takes Site B to 2.7.

**If asked "did you rig it so only that site moves?"** — yes, deliberately, and here is the
reason: the beat's payload is *causality*. One line crossed, attributable to one action. Two
sites tipping would be honest and unreadable.

---

## 2. A drag is TWO ops, because a rollout's disruption is narrower than the rollout

**`MoveProject` does not move site-impact windows.** They are deliberately independent: P12 runs
Apr–Sep while its Site B impact is a Jul–Sep *subset*, because the disruptive phase of a rollout
is not the whole rollout. The reschedule endpoint co-emits `MoveProject` **and**
`MoveSiteImpact`, offset-preserved — each impact shifts by the same delta, keeping its position
relative to the rollout.

**If asked "so moving the bar moves everything with it?"** — it moves the work and its
disruption, together, keeping their relationship. It does *not* silently redefine when the
disruption happens.

---

## 3. Moving a project does NOT move its money

**Funding requirements are period-keyed** and never re-derived from a project's interval. So a
bare drag changes the schedule and the site load and leaves the cost curve **identical**.

**Consequence for the script, and it is load-bearing:** the ghost bars (baseline series) have
nothing to draw after a bare drag — both series would be equal and the ghost would sit exactly
behind its own bar. **A visible cost reaction requires a funding op** (`set_cost`) in the
scenario. Beat-design question, filed for the script session.

**If asked "why didn't the spend move?"** — because the plan says *when* the work happens and
*which period the money is committed in*, and those are separate commitments. Moving the work
does not silently re-profile the funding; someone has to decide that, and the system makes them
decide it.

---

## 4. Why a week's slip tips a site over — THE SLIVER

**The physics:** site load counts an impact whose window **overlaps** a period, at **full
weight**. The scripted −7-day pull slides P12's impact from Oct 1 to Sep 24, overlapping FY26-Q4
by seven days — and those seven days carry the same 0.9 a full quarter would.

**This question is certain to be asked.** The answer, verbatim:

> *"Site B was already near its ceiling — this move tips it because even a week of overlap lands
> the full impact in that quarter. That's the model being conservative about change saturation,
> which is what you want from a warning system."*

True, one sentence, and it converts the sliver from a gotcha into a design statement: a cutover
team on-site for a week of Q4 **is** a Q4 disruption, and change-absorption capacity is about
presence, not duration.

---

## The prepared follow-up: "what if I pull it further?"

Someone will ask. **Do it live** — this is a demo of the constraint engine, not an improvisation.

**Measured boundary:** P12 may start no earlier than **2026-03-25**, when P11 finishes (D7,
finish-to-start, zero lag). The scripted drag stops exactly there.

| pull | dependency | Site B | the bar's flag |
|---|---|---|---|
| −7 days (scripted) | clean | crosses | `moved` |
| −14 days or more | **D7 breached, 83 days short at −92** | crosses | `constraint-violated` |

**What to say while dragging further:** the flag changes from `moved` to `constraint-violated`,
because a broken constraint is the *state* and the move is only its *cause* — a status flag
reports state. The diff card is where the cause is attributed.

**Why this is not the scripted beat:** two red things at once, and the constraint flag correctly
*swallows* the moved flag. The room would be watching dependency semantics and load physics in
the same breath, wondering which red thing they caused. One beat, one lesson — and this makes a
better answer than it would have made a demo.
