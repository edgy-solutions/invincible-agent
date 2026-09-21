# Packet from ca — `limit`: the response has no way to say it truncated

to: the architect
from: iagent-mesh-sdk / `lane/ca`, 2026-09-19 overnight
re: order item (d) — *"`limit`: how a truncated enumeration says it is truncated. Read the real
model first. Give two options and a recommendation."*

**PROPOSAL ONLY. Nothing is built. No code was written for this, on any branch.**

---

## 1. WHAT THE REAL MODEL SAYS — read, not remembered

`iagent_mesh/enumeration.py`, at `lane/ca` head.

    EnumerateInstancesRequest    class_uri: str            (required, non-empty)
                                 bound_slots: dict = {}
                                 limit: int = 25           <- DEFAULT_ENUMERATE_LIMIT

    EnumerateInstancesResponse   instances: Sequence[InstanceOption] = ()
                                 scoped_by: Sequence[str] = ()

**`limit` is on the REQUEST. There is no field on the RESPONSE that mentions it.** The response
object does not hold the request, so nothing in the SDK can compare the two. The contract can
state a limit and cannot hear an answer about it.

The module's own docstring already names this, and names it as unruled:

> ⚠ **THE SAME RULE APPLIES TO `limit` AND IS NOT IMPLEMENTED HERE.** A truncated list wearing a
> complete menu is the same defect as a class-wide list wearing a scoped one […] The ruling
> covered scoping, so this model covers scoping — the symmetry is recorded rather than invented,
> and it wants its own ruling.

So this packet is not discovering the gap. It is answering the question the gap was left open on.

### The measured population this has to survive

From the same docstring, measured 2026-09-17 by AST across the fleet:

    cost_agent         limit = 25
    finance_agent      limit = 8
    safety_agent       limit = 25
    ontology_service   no limit at all
    planning_agent     no limit at all

**Three different truncation behaviours across five providers, and the ask builder cannot tell
which one answered it.** Adopting `DEFAULT_ENUMERATE_LIMIT = 25` fixes what the caller ASKS for.
It does nothing about what the provider DID, which is the half this packet is about.

### The shape the answer has to match

`scoped_by` is the precedent and it made three choices worth copying deliberately rather than by
reflex:

1. **It reports NAMES, not a boolean** — because "scoped" is not one state. A provider handed
   two slots that honours one has not produced a scoped list or a class-wide one.
2. **Its default is the UNDER-claiming direction** (`()` = class-wide = menu refused). A
   forgetful provider is reported as less capable than it is, never more. The docstring calls
   this "the only asymmetry in the model and it is deliberate."
3. **The comparison is a free function, not a model validator** — `unhonoured_scoping(declared,
   bound, response)` — because the two halves of the invariant live in different objects.

---

## 2. TWO OPTIONS

### Option A — one boolean claim: `complete: bool = False`

The provider asserts completeness; silence means it did not.

    class EnumerateInstancesResponse(BaseModel):
        complete: bool = False
        """True only if this list is EVERY member. Default False: a provider that does not
        say has not claimed it."""

**For.** One field. Exact mirror of `scoped_by`'s fail-safe asymmetry — forgetting under-claims.
Cheap for every provider: one that fetched fewer rows than its limit already knows.

**Against, and it is the same defect this fleet keeps paying for.** `complete=False` means two
unrelated things that call for opposite repairs:

    "I truncated at 25 and there is more"        -> raise the limit, or narrow the question
    "I have never heard of this field"           -> fix the provider

Those are indistinguishable, and during the migration interval the second is the common case —
five providers, none of them emitting this yet. So the ask builder would refuse or degrade every
menu in the fleet, and no instrument would say which providers still needed work. That is
[same-observation-opposite-reasons] arriving by construction rather than by accident.

It also cannot separate 25-of-26 from 25-of-4000, and those are different products: the first is
a menu with a "more" affordance, the second is a question that should never have been drawn as a
menu at all.

### Option B — name the state, and report the population when it is known

    completeness: Literal["complete", "truncated", "unknown"] = "unknown"
    total_available: Optional[int] = None

    complete    every member is in `instances`
    truncated   the provider cut the list, deliberately
    unknown     the provider did not determine or did not say   <- the default

`total_available` is the optional refinement: present when the provider can count cheaply, `None`
when it cannot. Truncation is never DERIVED from it — a provider that knows it truncated says so
whether or not it can count.

**For.** The three states are the three states, named. `unknown` is the un-migrated population
and is countable, so "how far through the migration are we" is a query rather than a guess.
`truncated` is a real answer a provider gives on purpose, and it is distinguishable from silence.
The under-claim asymmetry is preserved exactly: `unknown` and `truncated` are both "do not draw
this as the complete menu", and only an explicit `complete` licenses that.

**Against.** Two fields instead of one, and a `Literal` is a closed vocabulary in the SDK — which
this repo deliberately avoided for `MeshResult.mode`, where the vocabulary is per-interface. The
counter-argument is that `mode`'s vocabulary is open because each PROTOCOL owns its own modes;
completeness has exactly one owner and exactly three states, so closing it costs nothing it would
otherwise buy.

---

## 3. RECOMMENDATION — Option B

Because of the migration interval, which is a measured fact and not a forecast: **five providers,
zero of them emitting this field on the day it ships.** Under Option A every one of them reports
`complete=False`, which is the same value a provider emits when it genuinely truncated. The
field would arrive already unable to distinguish its two readings, in a fleet that has paid for
that shape repeatedly, and the migration would have no instrument.

Under Option B the same five providers report `unknown`, `truncated` means what it says from the
first day, and the ask builder's rule is a one-liner that does not change as providers migrate:

    draw the complete menu only on completeness == "complete"

## 4. TWO THINGS TO CARRY WITH IT, WHICHEVER OPTION IS RULED

**(i) `len(instances) <= limit` is an invariant nobody checks.** A provider returning MORE rows
than the caller asked for is as much a contract break as one that truncates silently, and the
SDK cannot catch it inside either model — the limit is on the request, the rows are on the
response. It wants the `unhonoured_scoping` treatment: a free function taking both halves.

    def over_limit(request, response) -> int:
        """Rows returned beyond what was asked for. Non-zero is a provider defect."""

Same design as the existing helper, same reason: the invariant spans two objects, so it cannot
live in either.

**(ii) `complete` / `completeness` must not be derivable from `len(instances) < limit`.** It is
tempting and it is wrong in both directions: a provider that found exactly 25 of 25 looks
truncated, and a provider that fetched 25, filtered 3 for visibility and returned 22 looks
complete while having cut the list for a reason the caller cannot see. The claim has to be the
provider's, asserted, not computed by the consumer from the shape of the answer.

## 5. COST

SDK side, if ruled: two fields on `EnumerateInstancesResponse` (additive, defaults preserve every
existing caller), one free function, one docstring section replacing the ⚠ paragraph that
currently records the gap. It is a v0.9.x-additive change and rides the same pin as anything
else — it does not need its own.

Fleet side: not ca's, and it is the real work — five providers, three current behaviours.

**The SDK half is worth nothing on its own.** A field five providers do not set is a field that
reports `unknown` forever, which is honest and useless. If this is ruled, it wants a named owner
for the provider half in the same order, or it lands as documentation.

Lane: ia-ca/lane/ca
