# PROPOSED headers for the six unheadered packets — verified, not transcribed

**Prepared 2026-08-19. NOTHING APPLIED.** Each proposal below carries the evidence that
produced it. Apply with a glance, or reject a row — the point is that no row rests on the
packet's own prose.

## The finding that changes how these should be read

**Four of six prose statuses are STALE, and three of those understate completion** — they say
not-done about work that is landed AND sealed. Transcribing them would have written four wrong
headers onto the board and made the board *less* accurate than no header at all. This is
exactly the two-homes defect ADR-0040's header-as-single-authority rule exists to end.

Also worth recording: **cited shas span SIX repositories** (`invincible-agent`, `doc-tools`,
`cortex-ui`, `iagent-mesh-sdk`, and by inspection `dag-tools`/`pub-tools`), and no packet says
which repo its shas belong to. Two shas read as "not a commit" until the sibling repos were
searched. **A cross-repo sha without its repo is not a citation.**

| packet | prose says | VERIFIED state | proposed status |
|---|---|---|---|
| `triage-card-archetype` | "RULED, not built (2026-07-31)" | **BUILT + SEALED.** `906cf64` (2026-07-30, task verbs per species) + cortex-ui `e55d308` (TRIAGE_TASK archetype). 11 tests green today, incl. `test_a_triage_task_refuses_approve_and_reject`, `test_acknowledge_without_a_reason_is_refused`. **Stale from the day it was written** — the build predates the status line by one day. | **closed**, `closed-by: 906cf64` |
| `fingerprint-input-normalization` | "Must land BEFORE the first real promotion" | **LANDED.** `025c8ba` (2026-08-06) "canonical vendors, attested doc_type, both segments guarded". `canonical_vendor`, `_normalise`, `load_vendor_aliases` all present in `agent_fleet/utils/format_fingerprint.py`. | **closed**, `closed-by: 025c8ba` |
| `phase-1-3-consumer-derive-packet` | "READY TO RUN, fresh window" | **BUILT + SEALED.** `f8837bf` (2026-08-06) "DERIVE the trust key from the artifact — the caller supplies a pointer, nothing more". 29 tests green; `test_artifact_provenance_derive.py` pins BOTH halves server-derived (`format_fingerprint`, `pipeline_version`) plus refuse-loudly and supervised-floor arms. The packet's own worry — a half-derived conjunction — does not apply: both halves derive. | **closed**, `closed-by: f8837bf` |
| `sdk-transport-auth-handoff` | "complete and green" | **TRUE, and CONSUMED.** `iagent-mesh-sdk@68e28c0` is an ancestor of tag `v0.3.0`, and `pyproject.toml` pins `iagent-mesh-sdk.git@v0.3.0` (two places). Claim verified at the consumer, not just at the producer. | **closed**, `closed-by: 68e28c0` *(iagent-mesh-sdk)* |
| `unminted-caller-enumeration` | "5 of 5 REPOS SWEPT" | **SWEEP DONE, FIX NOT CONSUMED.** The cited `a934c61` ("bind the SDK's OWN consumer") is in **v0.3.1 ONLY**; this repo still pins **v0.3.0**. The sweep's own remedy is sitting one tag away, unadopted. [[consolidation-completes-at-the-last-consumer]] — the last consumer has not moved. | **open**, `blocked-on: bump iagent-mesh-sdk pin v0.3.0 -> v0.3.1 (a934c61); the fix this packet produced is not consumed here` |
| `pcn-extraction-sort` | "decided, waiting for its window" | **ACCURATE.** A decided sort for milestone M2, not itself a build. No `three-pile` implementation exists; the cited `0cc406e` (2026-07-24) is the review-state tripwire, a different artifact. Nothing to close. | **open** (prose correct) |

## Proposed header blocks

```yaml
# triage-card-archetype.md
id:         triage-card-archetype
status:     closed
owner:      agent
blocked-on:
closed-by:  906cf64
repo:       invincible-agent
summary:    A triage task is a THIRD species, not an approval. Offering Approve/Reject on "this notice could not be prepared for review" records a decision the schema cannot represent, which ADR-0034 would then archive as evidence. Verbs are now per-species and a wrong verb is REFUSED, not stored; UI ships TRIAGE_TASK (cortex-ui e55d308). 11 tests green.
```

```yaml
# fingerprint-input-normalization.md
id:         fingerprint-input-normalization
status:     closed
owner:      agent
blocked-on:
closed-by:  025c8ba
repo:       invincible-agent
summary:    format_fingerprint stopped being a recording device and became half the trust key that routes supervised vs autonomous, so untidy inputs became trust-key material. Normalization (canonical vendors, attested doc_type, both segments guarded) landed BEFORE any real promotion, which was the whole ordering requirement — a pre-normalization key would have been orphaned by normalization later.
```

```yaml
# phase-1-3-consumer-derive-packet.md
id:         phase-1-3-consumer-derive-packet
status:     closed
owner:      agent
blocked-on:
closed-by:  f8837bf
repo:       invincible-agent
summary:    The consumer half of the 1.3 trust key: the starter DERIVES (format_fingerprint, pipeline_version) from the fetched artifact and the caller supplies only a pointer. Held together rather than staged because a half-derived conjunction inherits the weaker component's trust. Sealed by test_artifact_provenance_derive.py incl. refuse-loudly and supervised-floor arms.
```

```yaml
# sdk-transport-auth-handoff.md
id:         sdk-transport-auth-handoff
status:     closed
owner:      agent
blocked-on:
closed-by:  68e28c0
repo:       iagent-mesh-sdk
summary:    One authenticated registration transport in the SDK app factory. Verified CONSUMED, not merely shipped: 68e28c0 is an ancestor of tag v0.3.0 and invincible-agent pins v0.3.0.
```

```yaml
# unminted-caller-enumeration.md
id:         unminted-caller-enumeration
status:     open
owner:      unassigned
blocked-on: The remedy is NOT consumed. a934c61 ("bind the SDK's OWN consumer") exists only in iagent-mesh-sdk v0.3.1; invincible-agent still pins v0.3.0 in pyproject.toml (two places). The sweep is complete; the fix it produced has not reached this repo.
closed-by:
repo:       invincible-agent
summary:    Five-repo sweep for callers that reach mesh routes without a minted identity. Sweep COMPLETE (5 of 5). Closing requires bumping the SDK pin to v0.3.1 so the binding fix is actually consumed here.
```

```yaml
# pcn-extraction-sort.md
id:         pcn-extraction-sort
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       invincible-agent
summary:    The decided three-pile sort (RENAME-AND-PROMOTE / keep-domain-specific / delete) so the M2 extraction milestone is a mechanical execution rather than a fresh analysis. Pairs with the generic-at-birth rule. DECIDED, not executed — M2 has not run.
```

## What I did NOT do

Apply any of these. Two rows are judgement calls a human should make: whether
`unminted-caller-enumeration` closes on "sweep complete" or stays open until the SDK pin moves
(I propose OPEN, because a sweep whose remedy is unconsumed has not changed the system), and
whether `triage-card-archetype`'s deferred escalation-lane WAKE keeps it open (I propose
CLOSED — the packet itself says "Acknowledge-with-reason covers the case honestly" until the
wake fires).
