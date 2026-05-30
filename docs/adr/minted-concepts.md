# Minted `mesh:` concepts

Per [ADR-0007 — Survey-before-mint](ADR-0007-survey-before-mint.md), every
new `mesh:` URI (verb or concept) gets a one-line record here justifying
why an existing standards-body ontology didn't cover it.

The survey order is:
1. **Apple App Intents** (intent / verb category vocabulary)
2. **Schema.org Actions** (action verbs and typed parameters)
3. **W3C Activity Streams 2.0** (SPO-shaped activity records)
4. **W3C SOSA** (sensor / observation / measurement)
5. **Broader Schema.org** (entities — Article, Dataset, HowTo, etc.)

First match wins; mint `mesh:` only when none fit cleanly.

| URI | Date | PR / commit | Surveyed (rejected) | Reason for mint |
|---|---|---|---|---|
| `mesh:analyzeWithCodeAgent` | 2026-05-29 | D.1 (Engine A self-registration) | App Intents `PerformIntent` too generic — captures "do something" but not "iterate with tool-use until convergence"; Schema.org `AssessAction` focuses on judgment outcome rather than the loop pattern; W3C Activity Streams has no Activity that captures multi-step tool-use; SOSA n/a; broader Schema.org n/a. | "Run a smolagents CodeAgent loop over a task" is a mesh-specific implementation pattern. The loop semantics (LLM proposes code → execute → observe → iterate) are how Engine A processes work, and no external ontology models that contract. Future engines using the same pattern (Engine E, DA) can reuse this verb. |
| `mesh:AgentTask` | 2026-05-29 | D.1 (Engine A self-registration) | Schema.org `Action` too abstract — has `agent`/`object`/`result` but no `task_description` / `dataset_id` shape; Schema.org `Question` too narrow (modeled for Q&A); App Intents `IntentParameter` close conceptually but tied to Apple's Swift type system; Activity Streams `Question` same issue as Schema.org's. | The BAML `AgentTask` class is the platform's contract for "a structured request to an analyst engine" — task_description + dataset_id + optional context. It is fundamentally a mesh-internal shape (lives in `baml_shared/baml_src/contracts.baml`); naming it `mesh:` is honest about its origin. If a future workflow standard captures the same shape, we can supersede via a new ADR. |
| `mesh:AgentResponse` | 2026-05-29 | D.1 (Engine A self-registration) | Schema.org `Answer` too narrow (single text response); Schema.org `Comment` similar; the result property of `Action` is generic but doesn't model the structured-data + execution-trace + status tuple Engine A returns. | Mirrors the BAML `AgentResponse` class: status + summary_text + structured_data + execution_trace. The execution_trace is what makes this mesh-specific — observability tied to the agentic loop is part of the contract, not a side-channel. No external vocabulary captures it. |

## Format guidance

- One row per new URI; never modify existing rows (immutable record).
- The `Surveyed (rejected)` column should list **which standards were checked and why they didn't fit**, in the survey order. "Considered Schema.org" without specifics is not acceptable.
- The `Reason for mint` column should say what about the concept is genuinely mesh-internal — usually "captures an implementation pattern" or "binds a platform-contract shape that doesn't exist outside the mesh."
- If you find a `mesh:` URI that should not have been minted (existing vocabulary covered it), don't delete the row — add a new entry that supersedes it and update routing to use the standard URI instead.
