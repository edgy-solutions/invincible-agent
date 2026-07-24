# can_act / disposition_item — the Topaz binding, decided on paper (live session reads this)

The `can_act` seam is the ONE piece of the PCN loop that cannot be sealed offline (it needs the live
authz layer). But "can't be sealed offline" ≠ "undesigned": an authz question answered at the console
under demo momentum becomes the entitlement model by accident. So the SHAPE is decided here; the live
session BINDS and OBSERVES, it does not decide.

**The type (born generic per AGENTS.md):** Topaz resource type `disposition_item`, a workflow-model
noun. The domain is a Topaz **attribute** (`domain: SUSTAINMENT`), never baked into the type name — a
`pcn_disposition` type would write the domain into the entitlement contract, the hardest layer to walk
back and where the flip-checklist seals live. Action: the approver's disposition act (e.g. `act`).

## Three decisions (settled now)

**1. A `can_act` DENY excludes the item from the approver's batch (redaction), not visible-but-
unactionable.** Already the implemented behavior — `grouped_review` (Seal 2) computes
`residue ∩ {items this approver can act on}`; denied items go to `audit_withheld` (countable for
audit, NEVER surfaced to this approver). The grouped review IS an `observer_view` computed per-approver
— the Slice-3 finding, one level up. Two approvers on one notice correctly get different-sized batches.
Recorded so the "visible-but-greyed-out" answer (which looks reasonable at 11pm) is not adopted live.

**2. ZERO entitled approvers fails LOUDLY, never parks.** A residue that this approver can act on NONE
of must NOT mask as "nothing to review". BUILT + SEALED (`start_review`, 70a321c+): residue-empty →
`NO_RESIDUE` (honest); residue-nonempty-but-batch-empty → **`NO_ENTITLED_ACTION`** (loud, no workflow
started). This is the deny-for-everyone misconfig — the agentic-auth flip's first-symptom class — and
the join-that-can-never-complete in review clothes (Slice-5 suspend-vs-fail, one level up): fail at
build/registration, never register a review that suspends forever unseen. Proven-to-bite (defeat the
distinction → the deny-all case silently returns `NO_RESIDUE`, red).

> **AUDIENCE RULE (record before the BFF grows an approver path).** `NO_ENTITLED_ACTION` is an
> **initiator-plane** outcome — honest loud-fail for the operator/system that STARTS the review.
> On the **participant plane** (an approver asking about their OWN view) it is an EXISTENCE ORACLE:
> "items exist you're not entitled to act on" is exactly the fact Slice-3 redaction withholds (Seal 2
> puts it in `audit_withheld`, unsurfaced). So: **any participant-facing surface collapses
> `NO_ENTITLED_ACTION` to the same shape as nothing-to-review.** Today the only caller is the operator
> plane (`start_review` is initiator-invoked), so this costs nothing now — but the dashboard work is
> precisely where someone adds an approver-initiated path, and this is the line that stops the leak
> being wired in then. Marked at the point of use in `start_review`.

**3. The three-caller discrimination seal (pcn edition) — the LIVE acceptance, watched not inferred.**
Same shape as the ADR-0025 flip-checklist `can_view` seal (entitled / empty / wrong-domain), applied to
`can_act`. When the binding lands, OBSERVE in-session (status = the menu-growth assertion: watched, not
"nothing errored"):
- an **entitled** SUSTAINMENT approver SEES their batch (non-empty);
- an **unentitled** approver does NOT (their batch is empty → `NO_ENTITLED_ACTION`, per decision 2);
- the **domain attribute actually discriminates** — a hypothetical other-domain approver cannot act on
  a SUSTAINMENT `disposition_item`, proving the born-generic type's *attribute* does the work the
  domain-named type used to. That third leg is the whole point of `disposition_item` + attribute; if it
  doesn't discriminate, the attribute is cosmetic and the type is domain-named in disguise.

> **THIRD-LEG FIXTURE (acceptance — the seal MUST run all three legs).** Everything live on sandbox is
> SUSTAINMENT, so the other-domain `disposition_item` the attribute must reject **does not exist** — the
> third leg requires WRITING a synthetic other-domain item into the authz/graph surface, running the
> reject, and **DELETING it after** (same clean-after discipline as the state-write test — a fixture,
> not residue). Name it in the run card so the seal does not quietly shrink to two legs when someone
> notices there's nothing other-domain to test against — "can't test it, skip it" is exactly how the
> attribute stays cosmetic — and so the fixture does not outlive its test.

## Live-session order (unchanged; this is its first act)

bind `disposition_item` + wire `can_act_via_topaz` against `core/authz.py` → run the three-caller
discrimination seal (observe all three legs) → then the settled sequence: build+roll `restate_analyst`
+ `engine-o` (one each) → journal-verified kill-seal → `IPCN25300X` batch vs its waiting diff, banked →
menu-growth observed → dashboard → five beats. The M1 close-out writes itself from three exhibits: the
banked batch diff, the kill-seal evidence, the menu-growth + discrimination observations.
