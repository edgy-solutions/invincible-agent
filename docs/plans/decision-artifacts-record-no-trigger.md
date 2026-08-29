---
id:         decision-artifacts-record-no-trigger
status:     open
owner:      unassigned — the artifact-minting seam, not the vault lane
blocked-on: a ruling on whether trigger provenance belongs on the artifact, and who owns the field
closed-by:  
code-site:  src/iagent/answer_artifact_writer.py:123-136, src/iagent/gateway.py:3644, src/iagent/gateway.py:3829
repo:       invincible-agent
summary:    THE THIRD STATE, not either of the two anticipated. Investigating whether the DecisionArtifact INFERS its trigger from the JWT subject found that it does not infer it — and does not read it either. There is NO trigger field. `produced_by` records which ENGINE answered; `produced_for` records the AUDIENCE; neither records HOW the answer was asked for. So every DecisionArtifact ever written carries no phrase-vs-button provenance, and the acceptance test written to catch inference ("seed both ways, confirm the artifacts differ") would go red for a reason its own diagnosis names wrongly. The identity vault does not cause this, but it removes the last accidental discriminator: before the vault a phrase-path seed arrived as svc:supervisor and was distinguishable BECAUSE IT WAS BROKEN; after it, both paths are correctly identical.
---

# DecisionArtifacts record no trigger — the acceptance test would have blamed the wrong thing

**Filed 2026-08-28 by Lane 2, from the identity-vault build's closing acceptance item.**

The vault's plan item ([[identity-propagation-must-not-cross-run-storage]]) derives an
obligation: *the DecisionArtifact must read the trigger from the run, not infer it from the
JWT subject* — because the vault forwards alice's own token, so `sub=alice` cannot
distinguish a phrase-path seed from a button click. The acceptance was: **seed one of each,
read both artifacts, confirm they differ.**

The investigation was run before the acceptance, and it changes what the acceptance means.

## The finding: neither read nor inferred. ABSENT.

`AnswerArtifactBundle` carries fourteen fields
(`src/iagent/answer_artifact_writer.py:123-136`):

    id, question_text, message_id, valid_as_of, status, produced_by, produced_for,
    resolved_intent, routing, sources, graph_trace, rendered_output,
    derived_from_artifact_id, valid_until

**None of them is the trigger.** The two that look closest are not:

| field | what it actually records | why it is not the trigger |
|---|---|---|
| `produced_by` (`gateway.py:3644`, refined `:3829`) | which **ENGINE** answered — `actor_id` is `handled_by.engine_name`, plus its endpoint and version | the ANSWERER, not the asker. Identical for both paths, since both route to the same engines. |
| `produced_for` (`gateway.py:3647`) | the **AUDIENCE** — `user_id`, persona, entitled_domains, `entitlement_source` | WHO it is for, not HOW it was asked for. Post-vault this is alice in both paths, correctly. |

A search for `trigger` / `triggered_by` / `invocation_kind` / `entry_point` / `initiated_by`
across `src/` and `agent_fleet/` returns nothing but the board generator's own frontmatter
key. **The field does not exist.**

## Why this matters more than a missing column

**The acceptance test as written would go red and name the wrong cause.** "Confirm they
differ" → they will not differ; and the stated diagnosis, *"provenance is inferring where it
should be reading,"* would be FALSE. Nothing is inferring. That is this repo's standing
instrument defect wearing a new hat — a test that fails on a claim the system never made,
with a ready-made wrong explanation attached. Anyone running the chain would have booked a
non-existent inference defect and gone looking for it in the wrong seam.

**And a structural point that constrains any fix.** The five seed artifacts are produced by
*the same code path* in both cases — `/canvas/seed` → `/interview/stream` × 5. `/canvas/seed`
cannot tell how it was called: it forwards whatever `Authorization` it received, and after
the vault that header is alice's either way. So **a trigger field on the seed artifacts
cannot be populated correctly unless the discriminator is passed down to `/canvas/seed`, or
derived from the parent Dagster run.** The only fact that genuinely differs today is that the
phrase path has an extra parent run (and its own artifact) that the button path never
creates.

## The vault does not cause this — it closes the last accidental channel

Stated precisely, because the distinction decides who owns the fix:

* **Before the vault**, a phrase-path seed arrived as `svc:supervisor`. The two paths were
  distinguishable — *but only because the phrase path was broken*, and the discriminator was
  a `403`. Provenance by defect is not provenance.
* **After the vault**, both paths carry alice's own token and are correctly identical. The
  absence goes from latent to load-bearing.

This is exactly the `act`-claim cost the vault's plan item recorded rather than argued away,
arriving where it was predicted to arrive. The item said the compensating record must live in
the run and the redemption log; this finding says **the artifact does not currently read
either one.**

## Scope: bigger than the vault, older than it

Every DecisionArtifact ever written lacks trigger provenance. That is not a regression and
nothing today reads a field that is wrong — it is an **absence**, which is the honest and
much less alarming version of the defect that was being looked for. But the platform sells
DecisionArtifact ancestry, and "how was this asked for" is an ancestry fact.

**Not fixed here, deliberately.** The repair lives in the artifact-minting seam, which is a
different lane's surface, and a provenance field added inside a vault commit is a change
nobody would find later. It needs its own ruling on three things:

1. **Does trigger provenance belong on the artifact at all**, or is "the run exists" enough?
2. **Where is it sourced** — passed down from the caller, or read from the parent run? Only
   the second is unforgeable, and the vault's plan item is explicit that the actor must be a
   fact an authority asserts, never a value a caller supplies.
3. **What are the values?** `button` / `phrase` is today's answer and will not stay two.

## What the vault's acceptance should assert INSTEAD

Until this is ruled and built, the honest closing check for the vault is what the system
actually claims:

* the phrase routes (not `NO_VERB_CLASSIFIED`), and dispatch carries alice's identity;
* the five inner asks return **200** where they returned `403 cell_not_entitled`;
* the **redemption audit line** exists, names run id / subject / outcome, and there is
  exactly ONE per seed — that is the vault's own provenance record, and it is real today;
* a phrase-path seed produces a parent Dagster run; a button-path seed produces none.

The last two ARE the phrase-vs-button discriminator that exists right now. They live in the
log and the run store rather than on the artifact, which is precisely the gap this item is
for.

## Cross-references

* [[identity-propagation-must-not-cross-run-storage]] — the vault; this is its closing
  acceptance item, promoted to its own entry because the answer was bigger than the check
* `sdk-discards-caller-identity` — same family: identity facts that die at a boundary
