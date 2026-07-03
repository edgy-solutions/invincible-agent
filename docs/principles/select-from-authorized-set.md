# Principle: the LLM selects from a symbolically-authorized set — it never authors the logic

**Status:** Governing principle. New ADRs cite this the way they cite
banked rules. Arrived at through failure-driven iteration, stated here
once so it governs future decisions rather than being re-derived per ADR.

## The tenet

**The LLM's output is constrained to a set the symbolic layer
authorized — never checked after the fact.**

Concretely: a symbolic layer (the ontology graph, the verb registry,
the Topaz policy store, a deterministic classifier) computes the
*legal set* — the compatible verbs, the valid classes, the permitted
cells. The LLM's job is to **extract intent and select from that
set**. It does not generate the formal object (the query plan, the
routing decision, the access grant, the logic program) and hand it to
an engine to execute or verify.

This is stricter and safer than "LLM authors, engine verifies." An
author-then-verify pipeline still lets the LLM produce a
wrong-but-syntactically-valid object that the engine faithfully
executes — garbage-in, dutifully-computed-out. Select-from-an-
authorized-set cannot produce anything outside the whitelist **by
construction**. There is no wrong-but-valid output to catch, because
the set of possible outputs was authorized before the LLM saw it.

The canonical mechanical form is the **conjunctive-read invariant**:
a verb is eligible only if it appears in *both* Neo4j and Weaviate;
the LLM selects among the intersection, it cannot mint a verb that
lives in neither. Generalize that shape and you have the principle:
the symbolic layer computes membership; the LLM picks a member.

## Where it is already load-bearing

Each of these was decided on its own merits, in its own ADR or
bug-fix. The through-line was implicit until now:

- **Three-leg routing** (Neo4j ∩ Weaviate ∩ registry) — the canonical
  instance. LLM selects among symbolically-compatible verbs.
- **entity_type threading** — the deterministic class→entity_type
  mapping is computed and threaded so the LLM can't re-derive
  (guess) it. See `project_engine_a_entity_type_hint_gap`.
- **PROV-contamination fix** — the ontology corpus is filtered at
  ingest so the LLM selects from a clean class set, rather than
  reasoning around contamination at query time.
- **Deterministic content-kind selection** (ADR-0021) — content_kind
  is computed at ingest, not LLM-chosen at render.
- **Image placement is structural, not LLM-decided** — figure
  placement derives from the data module structure.
- **Classification is deterministic; the LLM extracts only** (ADR-0009
  persona split) — persona comes from identity claims / policy, not
  from the LLM classifying the query text.
- **ADR-0025 — access is provenance, LLM extracts but does not
  decide access.** The symbolic policy layer decides; the LLM never
  authors an authorization.
- **ADR-0026 — `can_assume` is a symbolic permission check.** The
  picker offers only the cells the policy store authorized; the user
  (and the LLM downstream) selects from that set, cannot mint a cell.

The pattern behind these — "a deterministic fact exists, the LLM
re-derives (and sometimes fabricates) it, the fix threads the fact so
the model can't re-derive it" — is banked as the recurring bug shape.
This doc elevates its *inverse* (the design that prevents it) to a
stated tenet.

## Prior art (one paragraph, on record — not the framing)

This principle corresponds to what the literature calls
**neurosymbolic grounding / autoformalization** — the LLM as a
translator into a symbolic engine that does the deduction. We arrived
at it through failure-driven iteration, not from the literature, and
we enforce it **more strictly** than the standard autoformalization
pipeline: there, the LLM *generates formal code* (Z3 formulas,
Datalog programs) that a solver runs — the LLM authors the logic and
the solver checks it. We do not let the LLM author logic at all; the
symbolic layer computes the legal set and the LLM selects from it.
LLM-authors-then-solver-verifies still admits wrong-but-valid logic
the solver faithfully executes; LLM-selects-from-a-computed-set cannot
by construction. Noted so the correspondence is on record and future
work can draw on that body of work where useful — but the system is
simpler and stricter than the literature, and should be understood in
its own terms, not through the papers.

## Forward application

### Multihop (when its ADR opens)

The multihop plan is a **symbolically-derived object** — a deductive
chain over the ontology, Datalog-shaped — **not an LLM-generated
plan**. The LLM extracts intent and selects among *legal* chains; it
does not invent the chain. This is the principle extended from routing
(select a verb) to orchestration (select a chain). Do not let the LLM
author the chain and then verify it; have the symbolic layer compute
legal chains and let the LLM select. **Select-from-authorized, never
author-then-check** — the same rule, one layer up. The literature's
autoformalization pipelines (LLM-poses-question, deductive-engine-
derives-chain) are the reference for that decision.

### Authorization conflict (when the policy model grows prohibitions)

ADR-0026's policy is currently monotonic-permissive: `∃ group granting
the cell → permitted`, no prohibition primitive, so no two authorities
can conflict. The moment the policy language grows a **deny** (instance-
plane enforcement per ADR-0025 will likely need classification-based
prohibitions that override group grants), conflicting authorities
become possible. When that happens, adopt an **explicit conflict rule
— deny-overrides-allow unless explicitly prioritized** — rather than
letting evaluation order decide which policy wins. "Which authority
wins," decided by accident of evaluation order, is the authz version
of the assumed-contract bug. This is the deontic-logic prior art
(permission / prohibition / obligation; explicit priority ordering)
reached for at the point it becomes load-bearing, not before. Note
also that the system currently models only "may" (`can_assume`); real
policy also has "must" / "must not" (e.g. "a DATA_STEWARD *must*
review before publish") — an *obligation* the publish-HITL flow will
eventually need to express, distinct from permission.

## Scope discipline

This doc names what we already do and points one step forward. It is
**not** a survey of the neurosymbolic literature mapped onto the
architecture — that produces a beautiful document that governs
nothing. If writing this turned into reading papers, it overshot. The
job is to state the tenet so future ADRs inherit it as a first-class
principle, and to mark the two places (multihop, authz-conflict) where
the corresponding literature becomes live design input rather than
retrospective vocabulary.
