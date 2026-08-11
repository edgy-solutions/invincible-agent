---
id:         silence-closure-arc
status:     parked
owner:      agent
blocked-on: inventory review
closed-by:
repo:       invincible-agent
summary:    Inventory of failure modes presenting as silence rather than error; instances checked against the repo.
---

# Silence-closure arc

Standing inventory of paths where failure is indistinguishable from healthy quiet.

> **Provenance note.** Drafted from conversation, then **checked against the repo**. Two claims
> were corrected in that pass, and the corrections are shown rather than silently applied — a
> packet that quietly absorbs its own corrections teaches nothing about how it was wrong.

## Witnessed instances

### The lexicographic cursor — *verified*

`tests/test_sensor_cursor_contract.py:66-77`. The sensor's cursor sorted keys
**lexicographically** while "new" means **arrival order**. An object whose key sorted *below* the
cursor (`'g' < 'o'`) was therefore invisible **forever**, and the sensor logged nothing unusual.
The record states it *"silently lost two real notices."*

> **Corrected from the draft.** The draft described an ISO-timestamp-vs-bare-key comparison
> (`'2' < 's'`) and "nine artifacts accumulated". The repo supports neither the comparison nor
> the count: the mechanism is lexicographic-vs-arrival ordering, and the loss was two notices.
> The family was right; the specifics were reconstruction — which is exactly what a conversation
> source produces, and why this pass ran.

### The silent gauge — *verified first-hand, 2026-08-08*

`transport_auth` logged caller posture at INFO; no engine configured logging, so records fell
through to `logging.lastResort` (WARNING) and were **discarded**. Twelve services announced
`OBSERVE` at startup and observed nothing — while the function's own docstring claimed it *"turns
the migration into a gauge instead of a claim."* It was still a claim. Fixed in SDK v0.2.1
(`ensure_gauge_visible`), which is additive and deferential so a configured host is left alone.

The sharp edge: the contract flip's precondition is "the unverified count reads zero", and **a
silent gauge satisfies that perfectly and falsely.** Zero-because-silent and zero-because-clean
are the two states the instrument exists to separate.

### Langfuse credential absence — *reported, then RETRACTED*

The audit that raised it had been rendered **without the secret overlay**, so the credentials
were present all along. Kept here as a **mechanism, not an incident**: the telemetry leaf no-ops
when keys are missing, so a genuinely credential-less deploy emits zero telemetry, silently. The
retraction is itself the entry's value — the false positive came from a positive control that
exercised every *stage* but not every *input*.

### dag-tools Restate dispatch — *read-verified 2026-08-10, and a SHARPER shape*

`restate_dlt_sync/component.py:154` and `restate_api_sync/component.py:159` both `await
client.post(...)` inside a `try`, catch `Exception`, log at **`warning`**, and **continue the
loop**. A condition that refuses every request drops every chunk / every record — and the Dagster
asset **materializes GREEN**.

This is not the arc's usual shape. The entries above are *failure presenting as silence*; this is
**failure presenting as success**. A green materialization is a positive assertion that the work
happened, and here it is emitted by the path that just discarded the work. Silence invites a
question; a green asset forecloses one.

### dag-tools broker re-register — *read-verified 2026-08-10, a mitigation relied on past its class*

`domain_broker/main.py:247`, caught at both call sites → logged → loop continues. The gateway
holds `mesh_route:*` on a **300s TTL** and the broker re-pushes every **120s**, which the code's
own comment justifies as surviving a missed push. **It is a hiccup mitigation, and nothing marks
it as one.** Against a persistent refusal the table empties one TTL later and every asset answers
**404 "No active domain broker found"** — a total outage wearing a not-found. See
`[[dag-tools-broker-register-unauthenticated]]`.

**The general lesson both add:** retry-with-TTL and catch-log-continue are the two most common
fail-soft idioms, and each hides a *persistent* failure behind machinery designed for a
*transient* one. Ask of any retry: what does this look like when the condition never clears?

### A NEW SPECIES — a flag whose absence of effect is indistinguishable from its effect

Found 2026-08-11 while building the `central_gateway` subject-source gauge, and it is not a
variant of the entries above.

Every instance so far is a *mechanism* that goes quiet. This one is a **control that was never
wired**: `dag-tools/central_gateway` had no enforcement of any kind, so an operator setting
`REQUIRE_GATEWAY_AUTH=true` — a flag name the whole fleet uses — would see the service start
cleanly, serve traffic, log nothing unusual, and **reasonably conclude the gateway was
enforcing.** Requests would be served exactly as before.

**The two states are observationally identical from outside:**

| | what the operator sees |
|---|---|
| flag set, enforcement working, all callers compliant | starts clean, serves everything, no refusals |
| flag set, enforcement **does not exist** | starts clean, serves everything, no refusals |

The earlier entries produce a *missing* signal. This produces a **positive false one** — the
operator does not merely fail to learn something, they acquire a specific wrong belief, and it is
the belief that stops them looking. **A false belief in enforcement is worse than known-absent
enforcement**, because the second gets scheduled and the first gets relied upon.

**The repair is one line and it is loud:** an unimplemented control that is *set* must announce
that it is being IGNORED, naming what is not happening. Silence on a set flag is consent to the
operator's inference.

> **The general rule: a flag's absence of effect must be observable. If setting it and not setting
> it look the same from outside, the flag is a lie with a config schema.**

Guarded by `test_a_REQUIRE_flag_is_loudly_IGNORED_not_silently`. Related:
`[[naming-a-class-is-not-a-guard]]` — naming this class in a doc would not have prevented the next
one; the announcement is the guard.

## The general shape

A fail-safe path that is also **fail-silent** is only safe until something depends on it. The
repair is always the same: make the softness loud *inside its own seal* — count it
(`emit_misses()`), announce it at startup, or fail the build. **Fail-soft is honest only when it
is countable.**

## Status

Parked. The inventory is stable; closure work is unscheduled and unowned. New entries should
carry their verification state inline, as above.
