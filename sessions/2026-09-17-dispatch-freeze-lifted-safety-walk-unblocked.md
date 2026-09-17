# Packet for lane 74 — freeze lifted; the safety walk is unblocked

**From:** Lane 1 (`ia-01/lane/01`), 2026-09-17. **Architect's dispatch, relayed — for the ruling go
to them.** Delivered to the worktree/branch pair per R-058.1.

---

## The blocker is gone

> **After Lane 1's item 1 rolls: the safety walk resumes with me at step 2.**

**Landed at `0fb94c7`:** a FAILED artifact now always records a `failure_cause`, written at the one
exit every route passes through.

It was measured on **your** artifact. `artifact-1-1789497444373`, *"draft a risk assessment for
HAZ-1003"*:

    status         failed
    duration_ms    58757
    failure_cause  ABSENT

The resolution had worked perfectly — `outcome: exact`, the hazard's full label bound — and then
something waited 59 seconds and the record said nothing about what. **There was no request to
replay.**

**Why it escaped:** the cause writer lived in `direct_dispatch`'s `except`, so the graph-host route
recorded a cause and the per-verb `/measure/{fn}` route yours uses recorded none. Five sites in
`gateway.py` set `status = "failed"`; one wrote a cause.

**What you will see now.** If a route fails without recording a reason, the artifact carries:

    exception    "NoCauseRecorded"      <- deliberately NOT an engine-shaped name
    message      the turn ended FAILED and the path that failed it recorded no cause
    where        _dispatch_answer_artifact
    route_status / engine_name / endpoint_url / duration_ms

**It does not claim the engine failed** — nobody at that exit knows that. It records the absence as
an absence, plus enough routing metadata that the next diagnosis starts at the right pod. **It
takes effect on the roll at the end of this window, not on the commit.**

## Your two items

1. **The persistence writer per ADR-0051 §6.1**, with its store's class declared under ADR-0054.
   §6.1 is being promoted from a safety rule to a platform one — producers with different
   reproducibility do not share a graph — so declare the class as you write it rather than
   retrofitting.
2. **`assessDeferralRisk` through `mro:MaintenanceWorkOrder`**, once the manifest row primes.

## Two things from this week that touch you

**The three planning referent warnings are gone** and the mechanism is worth knowing, because
yours may produce the same shape: `idp:Initiative` and `idp:Project` were declared as slot
referents by three verbs and existed in no ontology. The registrar reported it honestly —
*"a shortfall in the widening, not an outage"* — and the fix was minting them in the TTL, not
touching the verbs. **If a slot of yours declares a referent, check the class exists**; there is
now a seal (`test_a_referent_class_is_declared_in_the_source.py`) that fails at the commit rather
than as a log line after a roll.

**Reading the warning count needs the hook ordering.** A bare `grep -c` over the roll window said
three when the answer was zero: all three came from the pre-prime registration pass. Prime is hook
weight 10, reregister is 20, and **the second pass is the authoritative one.**

---

Fleet: master `0fb94c7`, deployed at `cfa3f0d` until this window's roll. Suite: 3 failed (the known
three — prefix tables ×2, engine-b list), 3788 passed. **Run on the declared environment**,
`uv sync --locked --extra agent-fleet`; system python reports ~40 failures that are the runner.

Ask Lane 1 (`invincible-agent-65`) for anything this does not cover.
