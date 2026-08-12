# The a-borrowed-name-is-a-claim law

> **A name that already means something elsewhere is a claim. Using it for something weaker is a
> lie the reader has no reason to check.**

The reader's prior does the damage. Someone who has watched `REQUIRE_TRANSPORT_AUTH` work on
twelve services reads it on the thirteenth as the same control — not carelessly, but because that
is what a shared name is *for*. Verification would mean re-deriving a meaning the name already
promised, which nobody does and nobody should have to.

## The family spans surfaces, which is why it kept being met as a novelty

Three verified instances, each treated as its own defect at the time:

| surface | the name | what it claimed | what it did |
|---|---|---|---|
| **function** | `mint_service_token()` | a service mints its own token | read `REVIEW_STARTER_CLIENT_ID` — so *any* caller authenticated as `svc:review-starter`. Nearly had the supervisor dispatching under a role holding `can_invoke(mesh:startReview)` |
| **mechanism** | `auth_dependency` (`core/authz.py`) | a dependency that authenticates | with the flag unset, returned token-or-None **unverified** and passed `user_jwt = None` |
| **flag** | `REQUIRE_GATEWAY_AUTH` on `dag-tools/central_gateway` | the fleet-wide require posture | nothing — no enforcement of any kind existed to require |

**The flag instance is the purest**, because there was no implementation at all to be wrong: the
entire control was the name. It also shows the damage is proportional to how *well-established*
the borrowed name is — a novel name would have been checked.

## The legitimate twin — and the discriminator

Reusing an established name is often exactly right, and ADR-0035 is the worked example: it reuses
the trust-lifecycle's rung model for source freshness and the posture's cherry-pick rule
deliberately, *"so a future auditor meets vocabulary they already know."* §6 states the principle
outright — **reuse, don't reinvent.**

So the law is not "never borrow." It is:

> **Borrow a name when the borrowed MEANING holds. The defect is borrowing the name while
> delivering less than the name promises.**

The discriminator, asked of any reused name:

1. **What does a reader who knows this name from elsewhere expect?**
2. **Does this deliver all of it?** — not "something like it", *all of it*.
3. If **no**: either deliver it, or **rename to what you actually do**. A specific name over
   specific behaviour is never the defect; a general or borrowed name over weaker behaviour always
   is.

## The two repairs, and when each applies

* **Rename** when the weaker thing is legitimate and permanent — `mint_service_token` should have
  been `mint_review_starter_token`, which would have made the supervisor's misuse impossible to
  write.
* **Announce** when the name must stay for compatibility or when the gap is temporary — the
  gateway keeps reading `REQUIRE_*` and **says loudly that it is IGNORED**, per
  `[[flag-effects-must-be-observable]]`.

Marking the name is not optional in either case: `mint_service_token` survives only because it
carries an explicit `NEW CALLERS: DO NOT USE THIS` marker naming the general function as the
destination.

## Why it recurs

Per `[[naming-a-class-is-not-a-guard]]`: three instances, each caught by a different mechanism,
none by the previous instance's lesson. The surfaces differ enough (a function, an import, a
config key) that the pattern reads as new each time — which is the argument for a law that names
the *shape* rather than any one surface.

Related: `[[consolidation-completes-at-the-last-consumer]]`,
`[[flag-effects-must-be-observable]]`.
