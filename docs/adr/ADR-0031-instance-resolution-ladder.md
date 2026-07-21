---
status: Accepted (rungs 1–2 built; rung 3 deferred pending telemetry)
date: 2026-07-21
deciders: Platform team
---

# ADR-0031 — Instance-resolution ladder (LLM proposes, the phone-book disposes)

**Status:** Accepted for the deterministic rungs (built, commit `87fe361`); the
LLM candidate-generator rung is **deferred pending real telemetry** (below).
**Related:** [ADR-0026](ADR-0026-persona-entitlement-topaz-authorization.md)
(abstention gate), the recall-override honest-degradation guard (engine-o
`recall_guard.py`), the "instance resolution as registry-discovered capability"
recipe (`mesh:resolveInstance`).

## Context

`/resolve` classifies a query's SUBJECT (which idp:* class) via vector-recall +
LLM-precision, with `mesh:resolveInstance` **preemption** as the safety net: a
matched named instance forces the subject class, overriding the LLM. When the
phone-book does NOT match, the LLM classifier stands alone — and it is wrong
often enough to see it wrong in the *successful* cases (it guessed `Dataset`
for "Customer 360"; resolveInstance overrode it to `Dashboard`). A 2026-07-21
run exposed the failure directly: a query of the form "what snowflake **tables**
are used in the «named» superset **dashboard**" — the phone-book missed the
descriptor-laden name, the classifier stood alone, the target-type word "tables"
pulled the subject to `idp#Table`, and the system confidently answered a
different question than the one asked.

The lesson is not "make the classifier better." It is: **the classifier is the
silent-degradation surface, and the phone-book is the only thing that should be
allowed to say what a subject IS.** The design must shrink the classifier's
territory and make whatever remains of it honest.

## Decision

Resolve a named subject through a **four-rung ladder**, each rung with its own
confidence semantics. The LLM is demoted from classifier to *candidate
generator*: it may only nominate strings; a nomination that doesn't hit the
phone-book is worth nothing.

| # | Rung | Mechanism | Confidence | Status |
|---|---|---|---|---|
| 1 | **Exact** | case-insensitive equality vs catalog name | high | ✅ built |
| 2 | **Containment** | pure string work: core name is a contiguous multi-word run inside the identifier (descriptor-strip + `name_score`) — the case that actually bit us | high-ish | ✅ built (`87fe361`, `instance_match.py`) |
| 3 | **LLM candidate generation** | LLM emits 3–5 possible names/aliases *derived from the user's wording*, each fed back to the phone-book; one distinct hit resolves, multiple abstain | medium, `resolved_via=llm_candidate` | ⏸ **deferred** (see trigger) |
| 4 | **Classifier-alone / abstain** | today: LLM class guess, **flagged** as weak (recall-override guard discounts + marks `recall_override`). Target: abstain-and-ask ("did you mean X or Y?") | low / none | flagged, not removed |

**The trust shape:** LLM proposes, the deterministic layer disposes. A
hallucinated candidate costs one wasted lookup, never a silently wrong subject.
The ladder rung IS the confidence signal — it composes directly with the
recall-override guard: rung 4 is the surface that guard exists to expose.

### Rung 3 is deferred, not rejected — and the trigger is empirical

Rung 2 (containment) already covers the observed failure (descriptors), with
proof. Rung 3 earns its keep ONLY on misses containment cannot touch —
abbreviations ("c360" → "customer 360"), reorderings, synonyms ("the sales
overview board" → "sales dashboard"), typos beyond difflib. **We have not
observed one.** Building it now would add an LLM call, a prompt, and a new
failure surface to cover an imagined population — against the whole direction of
this work (extract nondeterminism, don't reintroduce it).

We do not have to guess whether those misses exist, because the residual weak
path is now **instrumented**: `recall_override` flags (engine-o), `no_instance`
fallbacks (engine-a), and `RESOLVE_INSTANCE_ALIAS` logs (engine-d, the
descriptor-strip firing on a non-exact name). Run at work and the decision
becomes data: if the flags basically never fire, the ladder is done at three
rungs and we saved the complexity; if they fire on a *pattern*, build rung 3
against a test set drawn from real logs, not imagined phrasings.

**When rung 3 is built, hold these constraints** (they don't expire while
deferred): the prompt extracts *possible names/aliases of the thing the user
named* (not "guess what they meant"); cap candidates at 3–5; reuse rung 2's
ambiguity rule — one distinct phone-book hit resolves, multiple **abstain**
(surfaced as "did you mean X or Y?", a better UX than a confident
misclassification).

### On the descriptor list being a frozen set, not an LLM

`instance_match._DESCRIPTOR_TOKENS` is a hardcoded set, and that is the honest
choice: it is a **closed grammatical class** — the nouns English speakers append
to a BI asset in prose (entity-type words + BI-tool names + articles) — not
knowledge about the data. It is small, slow-changing, enumerable, and pinned by
tests. Asking an LLM to decide "is this a descriptor?" dynamically would
reintroduce the exact nondeterminism we extracted the module to escape.
Admission rule: entity-type nouns + BI-tool names + articles; **never**
data-platform names (snowflake/postgres/dbt). Maintenance: a new BI tool in the
stack (e.g. grafana) is a one-line addition — noted at the set.

## Consequences

- The classifier's territory shrinks to rung 4, which is now *flagged* rather
  than silent. Shrink + honesty, not one or the other.
- Rung 3's absence is a *measured* gap, not an assumed one. The instrumentation
  is the deliverable that lets us stay disciplined about not building it.
- The **v2 growth loop** (self-hardening phone-book): when an alias resolves and
  the answer is confirmed good, persist `phrasing → asset` into the phone-book
  (provenance-marked, auditable/purgeable) so deterministic rungs cover more
  over time and rung 3 fires less. Gate on an explicit **confirmation** signal —
  persisting unconfirmed aliases poisons the exact-match layer. The
  `RESOLVE_INSTANCE_ALIAS` log is the raw material; v2 is out of scope here.

## Indicators for revisiting

- `recall_override` / `no_instance` / `RESOLVE_INSTANCE_ALIAS` fire on a
  recognizable non-descriptor pattern at work → build rung 3 against those logs.
- Rung 4 (classifier-alone) proves removable in favor of abstain-and-ask without
  a routing-quality regression → delete it and make the ladder end in an honest
  question.
- A confirmation signal exists for answers → build the v2 alias-persistence loop.
