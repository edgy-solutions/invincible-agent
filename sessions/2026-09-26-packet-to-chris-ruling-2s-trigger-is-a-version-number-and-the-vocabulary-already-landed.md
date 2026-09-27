---
to: Chris
from: invincible-agent/master
subject: ruling 1's seal has a better tag than the one I was going to invent, and ruling 2's
  trigger is factually wrong in both directions
---

# 0. The decision I need, and why it arrives before the seal rather than after

Rulings 1, 2 and 6 all turned out to be **about a vocabulary that already exists**, and ruling 2's
stated trigger — "until v0.9.4 lands" — is wrong in both directions at once. The seal in ruling 1 is
still small, but what it tags changed, so this goes to you before it is written rather than after.

Your decisions stand. What changes is what they key on.

# 1. The vocabulary landed at 0.9.3, not 0.9.4

`iagent-mesh-sdk` `pyproject.toml:10` → **`version = "0.9.3"`**. And in it:

```
iagent_mesh/enumeration.py:187   completeness: Literal["complete","truncated","unknown"] = "unknown"
iagent_mesh/enumeration.py:212   total_available: Optional[int] = None
```

So the words exist **today**, one minor version earlier than the ruling assumed.

**And the SDK independently ratified two of your six rulings, in prose, before this dialogue
started.** I did not know this when I proposed deriving count-ness from producers:

- **Ruling 1's discriminator** — `enumeration.py:57-59`: *"`len(instances) < limit` — inferring
  completeness from the count is exactly the shape this docstring warns against."* A count is not a
  completeness claim. That is your discriminator, written down, in the mirror-image direction (there
  the defect is a completeness silently *inferred*; here it is a count that travels as though it
  were one).
- **Ruling 6's absent-means-silent** — `:199-202`: the field is a three-value `Literal` and not a
  boolean *specifically* so that "the provider said complete" is distinguishable from "the provider
  never said anything about completeness", and `"unknown"` is documented as the fail-safe default.
  That is ruling 6, already typed.

**Consequence for ruling 1: the seal should not invent a "completeness-bearing" tag.** The tag has a
name and three states already. Inventing a second one is how a fleet ends up with two vocabularies
for one fact — which is the defect ruling 2 exists to prevent.

# 2. And it has not landed where the ruling needs it — so the exemption is live, for a different reason

`completeness` and `total_available` appear on **exactly one type in the whole SDK**,
`EnumerateInstancesResponse`. Measured: a grep for both names across `iagent_mesh/**.py` returns
those two lines and nothing else. They are **not** on `MeshResult` (`results.py:101`), not in
`rows.py`, not in `models.py`.

Worse for the migration, and this is the load-bearing fact:

```
agent_fleet/presentation_agent/main.py:163-165   the ONLY iagent_mesh imports in the file
    from iagent_mesh.transport_auth import announce / app_docs_kwargs / make_transport_auth_dependency
```

**The projected envelope is not an SDK type at all.** It is a plain dict, and
`_PROJECTED_ARCHETYPES` (`main.py:633`) is the only artifact that describes its shape. So
"`methods_compared` migrates to the SDK's `completeness`/`total_available`" has **no field to
migrate to** on this surface. It is not a version bump away; it is either an envelope that becomes
SDK-typed, or the projector adopting the SDK's key names by convention with nothing typed enforcing
it.

So ruling 2's grandfathering is **correct and live**. Its premise is not.

# 3. What I propose the exemption key on instead — and why not a version number

A version number is **a name**, and an allow-list keyed on a name excuses whatever is given that
name. That is the defect rounds 11-12 of this dialogue killed on the finance side, and
`"until v0.9.4 lands"` reintroduces it: 0.9.4 can land carrying anything at all, including nothing
relevant, and the exemption would expire on a label rather than on the obstacle.

**Proposed premise, one grep, expires the day it becomes false:**

> `methods_compared` is exempt for exactly as long as neither `completeness` nor `total_available`
> is available on the envelope surface — i.e. appears in no `_PROJECTED_ARCHETYPES` passthrough
> tuple **and** on no type `presentation_agent/main.py` imports.

This keys the exemption on **the thing that actually blocks the migration**, so it cannot outlive
its reason, and it self-expires without anyone remembering to revisit it. It is also *checkable* in
the sense this dialogue has been using: the seal asserts the premise, so the day someone adds the
field the exemption's own arm reds and names this packet.

**What I need from you:** confirm the premise swap (version number → field availability). The
decision in ruling 2 is untouched either way; if you would rather keep the version trigger I will
seal it as written and record that the trigger is a name.

# 4. Unchanged, and not re-opened

Rulings 3, 4, 5 and 6 are unaffected by the above, except that ruling 6 gains a citation: it is
already the SDK's documented reason for a three-value `Literal`, so it is a fleet convention being
restated rather than a new rule, and the seal can cite `enumeration.py:199-202` instead of arguing
it. Ruling 4 remains satisfied by `cost_labor_composition` being recorded exempt.

# 4b. Ruling 1 is already HALF-SEALED on the cortex side -- and the half that exists is name-keyed

This is the finding, and I only have it because I checked the caveat in section 5 instead of
shipping it.

`cortex-ui/src/components/registry/projectedTupleParity.test.ts` **already seals your
discriminator**, from the TS side, by reading the Python projector's source as text. It is good work
and it is not redundant with anything on our side:

- it pins the discriminator's *prose* so the explanation cannot be quietly deleted -- `:411`
  asserts the projector still contains `"an undefined method KEEPS ITS ROW"`, plus
  `"two sources of the same fact on the wire"` and a two-fragment assertion that survives a comment
  wrap;
- it has a **control before the claims** (`:419-422`): the extracted tuple must have more than five
  fields and must contain `verdict` *read by the same regex*, so an extractor that silently returns
  `[]` cannot make every later assertion vacuous -- their note says this file was written after
  exactly that failure;
- it asserts `suppliers_above_threshold` is absent **against the tuple, never against the comment**
  (`:430`);
- and its second case asserts count == row count on a real 2026-09-19 capture while stating in caps
  that **passing proves nothing about redundancy**, because a consumer deriving the count reproduces
  the same equality on a *truncated* payload -- your discriminator, argued from an artifact.

**What it does not do, and this is where ruling 1's seal earns its place:**

1. **It is keyed BY NAME, and says so.** `:423` -- *"The three completeness-bearing counts travel,
   BY NAME"* -- then three `toContain` calls. A **fourth** completeness count added to
   `COMPETING_MEASURES` is invisible to it. That is the per-member-predicate defect this dialogue
   already reproduced in two codebases, and this is the **third instance, on the exact surface
   ruling 1 governs**. A floor by name covers exactly the names in it.
2. **There is no tag anywhere.** The words "completeness-bearing" exist only in that test's comment.
   Nothing in `_PROJECTED_ARCHETYPES` marks a key as completeness-bearing, so "the seal reds on an
   untagged count" has nothing to read yet. The tag really does have to be created -- but section 1
   says its *vocabulary* should be the SDK's, not a new one.
3. **It is on the far side of the boundary from its subject.** A TS test greps Python source; the
   Python side has no seal of its own. So ruling 1's seal is **the missing half of a join**, not a
   duplicate -- the shape where every endpoint is verified and the invariant between them is not.

**Consequence: ruling 1's seal should be scoped as the Python half of a two-sided parity, and its
first job is to make the population derivable rather than named.** I will not touch their file --
another seat's territory, and the name-keying is theirs to fix -- but it goes to them as a check to
run, the way the emptying hazard did, since they have now been handed the same shape three times.

# 5. What I did not do

- **The seal is not written.** It is blocked on §3 only in its *tag*; if you do not answer, I will
  build it on the SDK vocabulary with the field-availability premise and say so in the seal.
- **I did not read the whole SDK.** The claim "exactly one type" rests on a name grep over
  `iagent_mesh/**.py` for both field names, which finds declarations and would miss a field
  introduced under a different spelling or built dynamically. I did not audit for either.
- **The TS side IS checked** -- the caveat that stood here is resolved, and resolving it produced
  section 4b. Neither `completeness` nor `total_available`/`totalAvailable` exists in the SDK's TS
  surface or in `cortex-ui/src`, so section 2's conclusion holds on both sides of the boundary: there
  is no field to migrate `methods_compared` to, in either language.
- **I did not read `projectedTupleParity.test.ts` whole** -- I read `:405-450`. There may be a
  population-derived arm elsewhere in it that makes point 1 of section 4b wrong, and the honest form
  of that claim is "the arm I read is name-keyed", not "the file has no derived arm".
