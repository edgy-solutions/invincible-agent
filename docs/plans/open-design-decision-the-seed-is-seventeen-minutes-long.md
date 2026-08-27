# OPEN DESIGN DECISION — the seed's happy path is seventeen minutes long

**Date:** 2026-08-26 · **Raised by:** Lane 1 · **Owner:** whoever wires the phrase (eval agent)
**Status:** UNDECIDED. This is a design choice, not a workaround note — and the default is the
wrong one.

## The fact

A complete portfolio-canvas seed is **five governed asks, run sequentially**, measured at
**5/5 in 17.7 minutes**. That is not a pathological case. That is the happy path.

## The decision

Today `/canvas/seed` is a **synchronous POST** that holds the connection for the whole run and
returns slot-ordered artifact ids at the end. Cortex's shipped client (`client.ts`) calls it that
way. So the wired-up phrase path inherits the same shape unless somebody chooses otherwise.

**Two branches, and they are genuinely different systems:**

### Branch A — synchronous, as today

The call blocks ~17 minutes and returns the ids.

**What must be true, and none of it has been measured:**

* the **ingress** does not cut an idle-ish 17-minute request
* any **proxy** in front of the BFF does not cut it
* the **browser** does not abandon it (fetch has no default timeout, but a backgrounded tab, a
  sleeping laptop, or a network blip ends it)
* the BFF's own worker is content to hold a request for a quarter of an hour

**Nobody has run this end to end.** The 17.7-minute figure was measured; the *survival of a
17.7-minute HTTP request across every hop* was not.

### Branch B — asynchronous, ids arrive over Electric

The call returns immediately (accepted / seeding started). The five artifacts land the way every
other artifact lands — the writer persists, the projector projects, Electric delivers — and the
seed answer arrives as an artifact carrying the slot-ordered ids.

**What this costs:** the phrase's answer is not the HTTP response, so the client must recognise
the seed answer when it arrives. **Cortex has already built exactly that**
(`canvasSeedFromArtifact`, watching `rendered_output.components[]` for
`{archetype: "CANVAS_SEED", artifact_ids}`), and it is guarded against re-delivery and against
seeding from history.

**What this buys:** no hop has to hold a connection for seventeen minutes, and the seed becomes
an artifact like any other rather than the one answer in the system that arrives by a private
channel.

## Why this needs deciding rather than defaulting

**Branch A is what you get by not choosing.** It is simpler, it is what the route does today, and
it is what the existing client call assumes. Someone wiring the phrase will reach for it without
noticing they made a decision.

**And the failure mode of Branch A is the worst-shaped one available:** it does not fail fast, it
does not fail in testing, and it does not fail on a short seed. It fails at **minute fourteen**,
in front of a room, on the beat the whole demo opens with — and the server-side work keeps
running after the connection dies, so the artifacts may still appear minutes later with nothing
connecting them to the request that asked for them.

A shape whose defect only manifests at the far end of a quarter-hour is one nobody will encounter
during development.

## The recommendation, stated as input rather than a ruling

**Branch B**, for a reason that is not about timeouts: the seed answer *should be an artifact like
any other*. Verb → output class → `rendersAs` → hardened arm → component is the path every other
answer takes, and the chain to make the seed take it is made entirely of steps this project has
done six times. Branch A makes the seed the one answer that arrives through a private channel,
and that exception has to be maintained forever by everyone who touches the path.

The timeout question is then a consequence that disappears rather than a risk to mitigate.

**Not my ruling.** The route and the registration belong to the eval agent, and the client
contract to cortex. What is mine is making sure the choice is visible before it is made by
default.

## If Branch A is chosen anyway

Then these must be measured, not assumed, before the rehearsal:

1. the actual ingress/proxy idle and total-request timeouts on the path to `/canvas/seed`
2. behaviour when the connection dies mid-run — do the remaining asks complete, and do the
   artifacts still land?
3. what the operator sees at minute fourteen if it dies, and whether re-issuing the phrase is
   safe or produces a second board

Item 3 is the one that decides whether this is survivable live. A failure with a known,
practised recovery is a pause; a failure with an unknown one is the demo.
