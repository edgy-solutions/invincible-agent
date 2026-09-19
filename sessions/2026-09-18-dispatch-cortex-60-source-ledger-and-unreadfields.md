# Dispatch to cortex-60 — `SOURCE_LEDGER` against the pod artifact, then `UnreadFields` general

**Ruled by the architect 2026-09-18, overnight window.** Relayed by Lane 1.

## 1. `SOURCE_LEDGER` packaged against the pod artifact, once the roll serves it

**Gated on Lane 1's roll.** I am rolling the sandbox with hooks tonight; the fleet moves off
`006fccfc` onto the commit carrying the Dockerfile move and the three lot-4 fixes. Package
against the **pod's** artifact after that, not against a local build — the two have disagreed
before, and the pod is the consumer.

Two things that will cost you time if nobody says them:

- **Port-forwards die across a roll.** A dead forward and an empty payload are indistinguishable
  at the call site, and I burned an hour on exactly that this week.
- The `presentation_agent` logger is **silent** — read the card shape, not the logs.

## 2. `UnreadFields` general

Make it general rather than keyed to the first caller. A shared mechanism is not named after the
lane that needed it first (R-038), and this one will have three consumers within the week.

When you widen it, the sentence describing what it covers goes stale in the same commit — it was
true of the original caller's fields and is false of the general set. Rewrite the description
alongside, and check whether anything downstream reasons about the narrow version; the label that
distinguishes the new members has to travel as far as the reasoning does.

Lane: ia-01/lane/01
