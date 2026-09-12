# Reachability is a property of a path, not a function

**Named by the architect, 2026-09-11**, after a designed refusal that had never once reached the
caller it was written for. **Extended 2026-09-12 with a fourth kind**, named by invincible-agent-65 against a check it had written itself, after an end-to-end measurement separated the question that check asks from the question it was built for.

**Ask "can this fire?" by reading the code and the answer is yes. Ask it by reading the payload
the consumer actually receives and the answer is no.** Both readings are competent. Only one of
them is about the running system.

## What happened

`engine-cost`'s `_require_vintage` raises `VintageRequired(available=['2021-02-01',
'2021-08-01'])`. The `available` list exists for one reason: **so the caller's next question is
answerable.** A rate comparison needs its assumption set named, and a refusal that withholds the
legal values is a dead end wearing a refusal's clothes.

It never ran. `rate_vintage` is spoken-mandatory, so `/measure/{fn}` returns a generic
`slot_required` **before the verb is called**. What went over the wire was:

```json
{"refused": true, "outcome": "slot_required",
 "reason": "cost_rate_comparison needs rate_vintage",
 "missing": ["rate_vintage"], "declarations": [...]}
```

**No values at all.** The caller is told what is absent and given no way to learn what a valid
one looks like.

**This is the third of four kinds of guard that does not protect what it appears to:**

| kind | what goes wrong | how it is usually found |
|---|---|---|
| **born dead** | no input can reach the branch | a mutation cannot produce the state it claims to protect against |
| **orphaned** | its callers changed | a reachability sweep, long after |
| **shadowed** | a **generic guard upstream answers first** | **only by reading the wire** |
| **weakened** | **it runs, its premise is TRUE, and it answers a weaker question than the one it was built for** | **only by a case where the guard passes and the outcome still fails** |

The first two are visible in the file. **The third is not visible in either file**, because both
are correct and they agree with each other. The specific guard is reachable in principle and by
direct call; only the request path shows it is unreachable in fact.

**The fourth is the hardest, because the guard is GREEN.** Named 2026-09-12 by the lane that
wrote the check, against its own work. Engine O's post-preemption check abstains when the
resolved class *carries no verb in the asked domains*. An instance override replaced
`cost:Supplier` with `cost:ProductionLot`; `ProductionLot` carries **four** verbs, so the premise
held and the check passed — **and not one of the four answers the question that was asked.**

> **A guard whose premise is true and whose purpose is defeated.**

The check was built to mean *"can this subject answer this question?"* and implements
*"does this subject have any verb at all?"* Those coincide until the day they do not, and on that
day the guard reports success. **Nothing about the guard is wrong in isolation** — which is why a
test of the guard passes, a review of the guard passes, and only an end-to-end case separates the
question it asks from the question it was for.

**The tell:** a guard phrased with *any*, *some*, or a bare existence check standing in for a
*matching* one. Ask what the guard is FOR in one sentence, then ask whether its condition is that
sentence or a cheaper neighbour of it.

## The corollary that cost the most

**A document written from the code asserts what the code says, not what the wire carries.**

`cost-card-walk-sheet.md` specified Q5 as returning `VintageRequired` and listed, as a check that
matters, *"it names BOTH vintages."* That check **could not pass**. A walker following the sheet
would have scored a **red against a rendering that works**, on the one screen the walk existed to
verify — and the likely repair would have been aimed at the renderer.

The sheet was not careless. It was written from the code, and the code agreed with itself.

> **Sheets carry captured payloads.** Not a description of the payload, not the exception class
> the code raises — the bytes the consumer receives, pasted in.

## How to apply

- **Writing a guard with a carefully-worded message?** Find one log line or screenshot where it
  actually appeared. A rich error nobody has ever seen is the tell.
- **A generic handler earlier in the same request is the hazard.** Order decides which one
  answers, and the specific one usually loses because the generic one is cheaper to reach.
- **Do not fix it by deleting the specific guard or hoisting its logic.** Have the generic one
  **ask the module for what it knows** — in this case `options_for(state, verb, slot, params)` —
  so the knowledge stays with the verb that owns it.
- **Keep the three states apart.** `None` ("not computable from what you supplied") and `[]`
  ("there are genuinely none") have **opposite repairs**: one sends the reader to the question,
  the other to the data. Collapsing them makes *"you did not name a lot"* read as *"no vintages
  exist."* Same rule as [`a-degradation-must-name-itself`](a-degradation-must-name-itself.md) and
  [`nobody-tried-is-not-a-kind-of-no`](nobody-tried-is-not-a-kind-of-no.md).
- **Seal the JOIN, because nothing else can see it.** The verb's `available` and the route's
  `options` are two computations of one truth by paths that never meet: the verb's refusal is
  invisible to endpoint tests, the route's options to direct calls. Assert them equal in one
  test; reversing either must go red.
- **For the weakened kind, the test must be END-TO-END and it must be a case where the guard
  PASSES.** A test of the guard cannot find it: the guard is correct. Only an outcome that fails
  while the check reports success separates the question asked from the question intended — which
  is why this one was found by walking five real prompts and not by any seal in either repo.

**Sibling of [`a-registration-is-not-a-reachable-call`](a-registration-is-not-a-reachable-call.md)**
— there a registration described an edge and said nothing about the payload the consumer sends;
here a guard describes a case and says nothing about whether the request ever arrives at it.
**Both are the same mistake: reading a declaration as if it were a path.**

Related: [`a-green-check-proves-only-its-scope`](a-green-check-proves-only-its-scope.md),
[`check-from-the-consumers-side`](check-from-the-consumers-side.md),
[`seals-must-be-proven-to-bite`](seals-must-be-proven-to-bite.md).
