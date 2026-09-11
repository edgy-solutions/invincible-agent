# A host with nothing admitted is not ready

**The readiness law's first live instance, 2026-09-11**, and it arrived under a condition
nobody arranged.

The rule already existed — `docs/runbooks/adding-an-engine.md` §8.3: *"READINESS FAILS ON
'GAVE UP', NOT ON 'STILL TRYING'. Those are different states with different meanings to a
scheduler."* What it had never had was a day where the distinction was the only thing standing
between a green fleet and a silently unroutable one.

## What shipped

`engine-lg` reached production **serving zero graphs behind a green probe**:

    GET /health   200   {"status":"ok","engine":"engine-lg","graphs":[]}

Two defects, and the second is the one worth the entry.

**The cause** was a missing `COPY policy/graphs/` in the Dockerfile the CI workflow generates.
The ratified row never reached the image. That is the ordinary kind of bug — a hand-kept
per-file COPY list whose own comment, three lines above, read *"the per-file COPY is itself the
fragile part: the next shared-policy file will need…"*. `policy/graphs/` was that next file.

**The silence** was `load_graphs()` failing loud on a row it could not honour and **not failing
at all on no rows**. An absent policy directory globs to nothing, the host admits zero graphs,
registers zero verbs, and answers `status: ok` to every probe. Found by invincible-agent-32,
whose own summary is the sharpest form: *a host that boots healthy with nothing admitted.* The
missing COPY was the cause; the missing floor is why it was silent.

## The fix, and the two states it separates

1. The host **refuses to start** with zero admitted graphs — a graph host with no graphs is not
   a degraded graph host, it is an unroutable pod with a green light.
2. `/health` stops reporting `ok` when nothing is admitted.

**And the control, which is what makes it a floor rather than a refusal:** a fixture with one
admitted graph must still report ok. Without it, "refuses on zero rows" is indistinguishable
from "always refuses", and a floor that rejects everything passes its own negative test while
taking the engine down. Both directions were mutated and run, not described.

## The condition that proved it, which could not have been staged

On the roll that deployed the fix, the new pod came up **while Keycloak was itself restarting
under the same upgrade**. Registration mint failed five times with connection refused. The pod
then reported:

    ready  = FALSE     it gave up on registering — a scheduler must not send traffic here
    health = ok        it HAD genuinely admitted fin_program_brief

**That is the whole distinction, drawn live, by accident.** `ok` means *I admitted something*.
`ready` means *I registered it*. The old probe could express neither: it said `ok` with
`graphs: []` and nobody was the wiser. Readiness failed on **gave-up** rather than
**still-trying**, exactly as §8.3 requires, and the weight-20 reregister hook then restarted
the pod into a clean registration — the design working end to end under a condition neither
lane arranged.

## Why this is the argument for the same floor on every engine

Every registering engine has the same shape: a population it admits at startup (verbs, rows,
classes) and a registration it performs against the mesh. **Every one of them can currently
boot with an empty population and report healthy**, because the floor was written for
graph-host and nowhere else.

The failure has no symptom. The pod runs, the probe is green, the census says the sha is
current, and the only visible consequence is a question that routes somewhere else —
*confidently*, because the cold-start fallback answers from whatever ontology it does have.
That is the same class as the stale-router defect diagnosed the day before, where `/resolve`
returned `MaintenanceWorkOrderRecord` at 0.78 with no planning class in the candidate pool
while every engine reported healthy.

**So the floor generalises, and so does its control:**

* refuse to start on an empty admitted population;
* never report `ok` with nothing admitted;
* keep `ok` and `ready` as different claims — admitted versus registered;
* and seal both directions, because a floor that always refuses passes the same negative test
  as a floor that works.

## A probe whose only reachable value is healthy is not a probe

**The gateway's `/health` returned `{"status": "ok"}` unconditionally** — in the component that
reports on every other component. It had no expressible failure. That is the same defect
engine-lg shipped, in the one service best placed to notice it, and it survived because a probe
that always passes never looks broken.

**And fixing it surfaced a distinction that is easy to collapse and expensive to get wrong.**
Three service URLs carried hardcoded `getenv` fallbacks. Removing them meant deciding *when* the
value is read, and there are two different questions wearing one variable:

| question | when it must be read | who asks |
|---|---|---|
| **was this DECLARED at startup?** | fixed at **import** | readiness |
| **where is that service right now?** | read **live** | the fleet aggregation |

**One read cannot answer both.** Binding the aggregation to the import-time value broke the
fleet report for any caller setting the variable afterwards; leaving readiness to a lazy
per-request read meant an undeclared address was invisible until somebody happened to call the
route that needed it — **a deploy fault that only surfaces on the request that needs it is a
deploy fault nobody sees at deploy time.**

Both halves were found by tests rather than by reasoning: the boundary case (*two of three
declared must still refuse*) caught the first, and the existing fleet-report seal caught the
second within one suite run.

**The general form: when one value serves both a startup invariant and a runtime lookup, read
it twice on purpose and say why at each site.** A single read is a guess about which question
matters more, and the guess is invisible afterwards.

Related: [[a-registration-is-not-a-reachable-call]],
[[a-degradation-must-name-itself]],
[[nobody-tried-is-not-a-kind-of-no]],
[[a-green-seal-can-be-green-for-the-wrong-reason]].
