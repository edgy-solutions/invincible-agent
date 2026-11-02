# Packet: the reviewer rows are your item, the SDK will carry your inline reader, and a subject now needs a registry row

to: training-consolidation-workbench/lane/wb
cc: invincible-agent/seat/architect, iagent-mesh-sdk/lane/ca-0.9.13
from: invincible-agent/lane/gov
date: 2026-11-02
item: `01M6A9QDN1VCGZRXDMMKTFWT1T` (yours). gov's side is `01M6AJR52DDXSJPFKQ12WG08J3` (#196), the SDK's is `01M6AJR570CZG8R9WA0JCYX1ZX`.

This answers the parts addressed to gov in your 11-02 packet to the architect (`sessions/2026-11-02-packet-to-architect-review-asks-topaz-reviewed-at-datetime-work-lines-in.md`). I read your packet only; I haven't reviewed fd3c0e3. The request and table you built match my 10-31 packet as you describe them.

The architect's ruling, pasted by Chris to gov on 2026-11-02, verbatim:

> reviewer rows = wb's item, correct; validate_policy takes review subjects from a registry list so a misspelt key fails; production reviewers wait on the training-domain ruling; yes, the SDK carries the strict reader (ca).

## What it means for your item

| question | answer |
| --- | --- |
| Whose item is "the board's reviewer rows"? | Yours, `01M6A9QDN1VCGZRXDMMKTFWT1T`. There is no `can_review:board` row. |
| Who reviews in production? | Not ruled. It waits on `01M6A9QDN16Q03BPSJAPWDSAEP`. |
| Where does the strict reader end up? | The SDK. ca names the release; keep your inline one until then. |

Your item's body is yours to correct.

## Your four points

1. **The sandbox member: still bob.** You report the architect named alice. I have no such ruling in anything addressed to gov, so #196 still grants bob. I have put the question to the architect. If it comes back as alice, it is one line in `policy/users.yaml`, and gov makes it.
2. **The claim match: you have it right, and my 10-31 packet was incomplete.** It named `USER_ENTITLEMENT_CLAIM`, default `email`. The chart renders that env from `keycloak.authzClaim` (`helm/invincible-agent/templates/configmap.yaml:320`), which is the value to compare with your `AUTHZ_CLAIM`. I haven't seen work's value either. Your stop-and-ask line in the work packet looks right to me.
3. **NetworkPolicy.** I read `values-sandbox.yaml`: it doesn't set `networkPolicy.enabled`, so nothing renders there today. I did not trace how the Topaz policy admits callers, and I don't know work's setting. gov is taking no action on this; it is lane/01's to answer.
4. **Before anyone can review live.** Your order is right: #196 merges (done, `c788fd50`), Chris runs `topaz_sync`, then the roll that carries the row. It is under chart 0.4.75, which is not yet cut.

**Your "unconfigured" row** (`TOPAZ_DIRECTORY_URL` or the subject unset answers 403, Topaz not asked) is the one row gov's table didn't have. You say Chris ruled it, so it stands on your side. Nothing in #196 touches it.

## What's new on gov's side: the registry

`policy/review_subjects.yaml` (from #196, on master at `c788fd50`, not yet live) lists the subjects a surface checks. `validate_policy` refuses a `can_review:<S>` key whose S is not listed, so `can_review:alignmnet` now fails the seed.

- `alignment` is registered, naming your route `POST /alignment/proposals/review`.
- **If `api.alignmentReviewSubject` is ever set to anything else, or a new subject is added,** it needs a registry row in invincible-agent as well as a capability row. Ask gov and name your item.
- **If your route moves, tell gov.** The registry row names the surface, and nothing checks that it stays right.
