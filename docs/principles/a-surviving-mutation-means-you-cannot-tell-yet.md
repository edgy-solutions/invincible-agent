# The a-surviving-mutation-means-you-cannot-tell-yet law

> **A red-proof that survives is not evidence the code is wrong. It is evidence you cannot tell
> yet.**

Break-on-purpose is this repo's standard move: before trusting a guard's green, reintroduce the
defect and watch it go red. When the guard fails to notice, the instinct is to reach for the
code. That instinct is wrong, and the correction changes what the whole discipline is *for*.

## The measurement, across two lanes on 2026-08-26

Every mutation that caught something caught an **ABSENT GUARD**, not bad code:

| lane | mutation | what it found |
|---|---|---|
| eval | truthy `{"default": []}` counted as a vector | the counter had no content test |
| eval | bare component instead of the `components` envelope | no envelope assertion existed |
| eval | `json.dumps(rows)` instead of an array | no encoding assertion existed |
| eval | compacting a partial seed instead of refusing | no ruling was pinned |
| cortex | `toMarkers` mutation survived | that function had **no tests at all** |
| cortex | history case survived | the test asserted the **wrong thing** |

**Not one of them found wrong code.** The code was fine and unguarded — which is precisely the
state that is indistinguishable from guarded until something changes.

## So the technique's real product is a MAP OF WHAT IS UNGUARDED

Not a bug finder. A coverage detector with teeth: it answers *"if a future edit broke this,
would anything notice?"* — which no green suite can answer about itself, because a suite that
never exercises a property passes exactly as loudly as one that guards it.

That reframing has a practical consequence. When a mutation survives, the next step is **not**
"fix the code." It is:

> **Weak guard, or void mutation — prove which.**

* **Void mutation** — the change was a no-op, or the code path is unreachable, or the mutation
  produced an equivalent program. Nothing is wrong and nothing is missing. Discard it.
* **Weak guard** — the behaviour is real, a future edit could break it, and nothing would say
  so. Write the guard. The code stays as it is.

Collapsing those two into "the code must be wrong" is how a survived mutation turns into an
unnecessary edit to working code — the failure mode this law exists to prevent.

## Why the distinction is easy to lose

A surviving mutation *feels* like a positive result, and positive results invite action. But the
signal is about the TEST SUITE, not the implementation. The implementation was never the subject
of the experiment: the experiment asked whether the guard discriminates, and "no" says nothing
about which side of the guard is correct.

Related: [[a-green-check-proves-only-its-scope]] — a green check proves only what it exercised,
and a mutation that survives is that same blindness measured from the other direction.
[[naming-a-class-is-not-a-guard]] — the guard has to assert the behaviour, not describe it.
