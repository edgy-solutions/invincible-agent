# Packet for lane 5f — two ADRs: data classes, and OpenDDIL ADR-0042

**Ruled by the architect, 2026-09-16. Relayed VERBATIM by Lane 1 (`ia-01/lane/01`) — the body
below is their text, not my summary of it.**

**Provenance matters here and this is why it is stated.** Twice tonight a ruling travelled badly:
one the architect believed they had sent never arrived, and one I summarised in the past tense
turned a ruled-and-pending rename into a name that did not exist — `invincible-agent-28` was a line
from compiling it. So: their words are quoted, not paraphrased, and if any of it reads oddly,
check with them rather than with me. A relayed ruling needs its verb and its assignee or it is a
claim about a state rather than an instruction.

**Delivered to the worktree/branch pair rather than to a session address**, per R-058.1 — a session
name predicts neither half.

---

## The ruling, as given

**Order:** engine-docs to its first artifact first — that's on the critical path for the card and
the walk. These ADRs are the next block; start reading now, write after the artifact lands.

**Read before writing, in this order** — all in
`C:\Users\cnogr\git\openddil\openddil-contracts\decisions\`, which is now an allowed directory:

- ADR-0040 offline sustainment and intent reconciliation — the edge write case; its "did not
  establish" section is the gap you're filling
- ADR-0031 with the 2026-09-08 addendum — the converged node; state-versus-knowledge; policy
  modules and subject namespace
- ADR-0035 — basis classes, including `asserted-locally-unconfirmed`
- ADR-0029 — releasability labelling
- ADR-0037 — verification evidence, VE-7 sanitization
- AUDIT-2026-08-08 severance-tolerance inventory
- On our side: ADR-0051 §6.1 (producers with different reproducibility do not share a graph), the
  prime's clearer invariant in `prime_databases.py`, ADR-0034, ADR-0047

### 1. `invincible-agent` — Data classes and the write interfaces (next ADR number)

Every write in the mesh carries a declared class with four fields: reproducibility (rebuildable /
stateful), authority location (here / upstream / external system of record), sync obligation (none
/ flush-up / mirror-down / write-back), releasability.

Name the three lifecycle shapes with their first consumers:

- **rebuildable** — ontology, vectors, registrations, `PARAMETERISED_BY`, markers; the prime may
  drop and re-land
- **stateful iagent-authored** — artifacts, lineage, `bound_slot_sources`, assessments and
  acceptances, checkpoints; preserved, retention as a rail row per kind, `valid_until` honoured
- **of-record-elsewhere** — FRACAS: Eagle events, CAPA records; OpenDDIL: any intent once accepted
  — a mirror with provenance and a write-back contract, never the authority; ADR-0040 §7's line
  verbatim

**Enforcement:** the class is declared per named graph, collection, and table; the prime's clearer
reads the class instead of a glob; the census refuses an unclassified store; the three write
interfaces carry the class in their signature — registrar writes rebuildable, trace writer writes
stateful, sync adapter alone writes across a location boundary — and nothing writes across.
Promote §6.1 from a safety rule to a platform one.

**Input:** the eo lane's fleet-wide write census; until it lands, derive from the four known write
paths (registration, artifact writer, human tasks/grants, doc-tools ingest) and mark the
population provisional.

### 2. `openddil-contracts` — ADR-0042, the answer to ADR-0040's registered gaps

**Custody:** where intent lives at a tier and in what form (an event on a local topic, typed by
composability per §5, carrying cached basis per §6, replicated by the existing tier rail — not a
second flush mechanism).

**Retention:** authority-pending intent never ages before it's accepted or rejected; reconciliation
outcomes persist on the intent permanently (§Limits already requires it); what happens when
severance outlasts retention is a declared degraded mode, not a default.

**Multi-tier:** intent reconciles via its parent, and a severed intermediate tier holds custody for
its children under the same rule.

**Sanitization** per VE-7. Cite ADR-0040 by section throughout; this ADR establishes only what that
one said it didn't.

### One finding to record in both, not resolve

The safety personas (`SAFETY_ENGINEER`, bob, carol) synced to Topaz this week are subjects in the
agent-side corpus only. ADR-0031 §2.3 requires one subject record carrying both attribute families
before the converged node exists. Register it in the policy rail's `GENERALIZATION-DEBT` equivalent
and in OpenDDIL's.

### Do not

Design the action vocabulary (ADR-0040 says it needs the operator conversation); invent a flush
channel (the tier rail is it); merge the policy corpora (modules compose, subjects merge); write
either ADR from this packet's summaries — **read the source and cite text**.

### Deliverable

Both drafts on `lane/5f` for review before ratification; the iagent one first, since its classes
are what the OpenDDIL one's custody rules attach to.

---

## Lane 1's additions — paths verified, not assumed

Every source named above was checked to exist before this packet was written, because a packet
that sends someone to a missing file costs them the hunt and teaches them to distrust the next one.

| cited | resolved to |
|---|---|
| ADR-0040 | `ADR-0040-offline-sustainment-and-intent-reconciliation.md` — `## What this ADR did not establish` at line 253 |
| ADR-0031 | `ADR-0031-converged-edge-node-reasoning-plane-seams.md` — contains the 2026-09-08 string |
| ADR-0035 | `ADR-0035-information-honesty-operator-surfaces.md` |
| ADR-0029 | `ADR-0029-coalition-releasability-abac-enforcement.md` |
| ADR-0037 | `ADR-0037-verification-evidence-is-a-deliverable.md` |
| AUDIT | `AUDIT-2026-08-08-severance-tolerance-inventory.md` |
| ADR-0051 §6.1 | `docs/adr/ADR-0051-*.md:636` — "*Where the instances land, and it is a RULE rather than a convention*" |

**ONE CORRECTION TO A PATH IN THE RULING:** `prime_databases.py` is at **`setup/prime_databases.py`**,
not `scripts/`. The clearer invariant the packet points at is real and is the comment at line 398:
*"THE DROP SET IS DERIVED FROM THIS FIELD. `clear_ontology_graphs()` computes…"*, restated at 453:
*"No change to `clear_ontology_graphs()` is needed: it derives its drop set from this list."* That
is the derive-the-population discipline the data-class ADR is asking you to generalise — the
clearer already reads a declaration instead of a glob for graphs, and the ruling extends that shape
to collections and tables.

**ADR NUMBER:** take "the next ADR number" from the directory at the moment you write, not from
this packet — other lanes are filing too, and a number chosen now may be taken by then. Same reason
ruling numbers are allocated by one lane.

**RELEVANT TO YOUR "rebuildable" LIST:** `PARAMETERISED_BY` is named in it, and as of tonight it is
live rather than hypothetical — ca's registrar writes those edges and the re-register hook backfills
them, which is precisely a rebuildable store the prime may drop and re-land. If you want a worked
example of the class in the wild, that is the freshest one:
`tests/routing/test_the_pool_reaches_parameterised_verbs.py` on master carries the edge contract and
the reason the identity is `(verb_iri, _tool_urn)` rather than the verb alone.

**Ask Lane 1 (`invincible-agent-65`) for anything the packet does not cover, but for the RULING
itself go to the architect — I relayed it and I can be wrong about it.**
