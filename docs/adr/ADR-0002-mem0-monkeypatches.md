# ADR-0002 — Carry two upstream-mem0 monkey-patches in `utils/mem0_utils.py`

**Status:** Accepted
**Date:** 2026-05-29
**Deciders:** Platform team
**Related:** [ADR-0001](ADR-0001-mem0-llm-decouple.md)

## Context

End-to-end validation of Engine A's `/analyze` flow surfaced two
distinct bugs in `mem0` 0.1.x that prevented mem0 from being usable for
us out of the box:

**Bug 1 — `score_and_rank` None-comparison crash.**
At `mem0/utils/scoring.py:102`:

```python
semantic_score = result.get("score", 0.0)
if semantic_score < threshold:
    continue
```

`dict.get(key, default)` returns the *stored value* when the key exists
— so a stored `None` becomes `None`, not `0.0`. The default never
fires, and the subsequent `<` raises `TypeError: '<' not supported
between instances of 'NoneType' and 'float'`. Every `m.search()`
crashes when any result has a `None` score in its dict.

**Bug 2 — `Langchain` provider `_parse_output` discards scores.**
At `mem0/vector_stores/langchain.py` line 36:

```python
entry = OutputData(
    id=getattr(doc, "id", None),
    score=None,                            # ← hardcoded
    payload=getattr(doc, "metadata", {}),
)
```

With a comment claiming *"Document objects typically don't include
scores"*. That assumption is false for our adapter:
`Mem0CompatibleWeaviate.similarity_search_by_vector` explicitly writes
a real similarity score into `doc.metadata["score"]`. mem0 throws it
away. Downstream, every result lands with `score=None`, the threshold
filter discards everything, and `m.search()` returns empty even when
Weaviate matched.

Together these two bugs make mem0 unusable against any LangChain-backed
vector store that returns Documents (which is the documented integration
pattern): you either crash on the first search, or get empty results
forever.

Both bugs were found, characterized, and reproduced cleanly during the
Step 2 round-trip e2e validation. We need to ship working memory to the
dev cluster *now*, not when upstream merges fixes.

## Decision

`agent_fleet/utils/mem0_utils.py` installs two monkey-patches at module
load time, **before** `from mem0 import Memory`:

1. `_install_mem0_none_guards()` rebinds `mem0.utils.scoring.score_and_rank`
   to a wrapper that normalizes `None` scores to `0.0` in the input list
   before delegating. Because `mem0.memory.main` does
   `from mem0.utils.scoring import score_and_rank` at module load, it
   binds the *original* function name in its own namespace before our
   patch runs — so we also sweep `sys.modules` and rebind every module
   that already imported the name. Idempotent via the
   `_NONE_GUARD_INSTALLED` sentinel.

2. `_install_mem0_score_propagation_patch()` rebinds
   `mem0.vector_stores.langchain.Langchain._parse_output` to read
   `score` from `doc.metadata` when the input is a list of Documents,
   instead of hardcoding `None`. Method-level patch, so all `Langchain`
   instances pick it up. Idempotent via `_SCORE_PROPAGATION_PATCHED`.

Both patches are documented inline with the upstream file:line, the
specific anti-pattern, and the symptom they prevent.

## Consequences

**Wins:**
- mem0 search returns the right results with the default threshold (no
  callers have to pass `threshold=0.0` as a workaround).
- No fork burden — we track upstream mem0 releases freely.
- The patches are scoped to one file we already own (`mem0_utils.py`).
  No other module in the fleet knows mem0 is patched.
- Removal is safe and detectable: when upstream lands fixes, we delete
  the two `_install_*` functions and the `_NONE_GUARD_INSTALLED` /
  `_SCORE_PROPAGATION_PATCHED` flags. The
  `tests/test_engine_mem0_roundtrip.py` `PATCHES_VERIFIED` assertion
  will start failing — that's the signal to update the test.

**Costs:**
- Monkey-patching is fragile to upstream refactors. If mem0 renames
  `score_and_rank`, changes its signature, splits `Langchain._parse_output`,
  or restructures the import chain, the patches stop applying silently
  (canonical site stays patched; bound names in other modules diverge).
  Mitigation: the round-trip test verifies *both* patches are live in
  the running image (`_main.score_and_rank is _scoring.score_and_rank`
  + `_lc._SCORE_PROPAGATION_PATCHED`), and the test skips with a clear
  "patches missing" message rather than producing confusing failures.
- We pay the patch cost on every cold start, not just once per host
  (each pod re-runs `_install_mem0_none_guards()`). Cheap — a couple of
  attribute lookups — but worth noting.

## Alternatives considered

- **Fork mem0.** Rejected. mem0 is actively developed and the surface
  area is large; carrying a fork means constant rebase work for two
  bugs whose root causes are five lines each.

- **Pin mem0 to an older version that doesn't have these bugs.**
  Investigated. The score-handling code path predates 0.1 and the
  Langchain provider's hardcoded `None` has been there since the
  provider was introduced. There's no "good" version to pin to.

- **Wait for upstream PRs.** Rejected as a blocker. We may also submit
  PRs, but production work can't wait on upstream review cycles.

- **Patch the call sites in our adapter instead.** Investigated.
  Our `Mem0CompatibleWeaviate` is the input to mem0's vector store
  pipeline — we already write `metadata["score"]` correctly. The bugs
  are downstream of where our code runs. Patching from inside the
  adapter would require duplicating mem0's full result-handling logic.

- **Wrap `Memory.search` at our API boundary.** Possible but adds an
  abstraction layer in front of mem0 that hides the real interface
  from engine code. The monkey-patch is invisible to callers.

## Indicators for revisiting

- mem0 ships releases that fix `score_and_rank` (the
  `dict.get(k, default)` → `dict.get(k) or default` correction) **and**
  the Langchain provider score propagation (reading from
  `doc.metadata`). When both land, drop the patches and remove the
  `assert _NONE_GUARD_INSTALLED` / `assert _SCORE_PROPAGATION_PATCHED`
  lines from `tests/test_engine_mem0_roundtrip.py`.
- We switch the mem0 vector store provider from `langchain` to a native
  Weaviate one (mem0 0.1.x has a stalled native Weaviate provider; if
  it lands and stabilizes, Bug 2 becomes irrelevant for us).
- An upstream refactor renames or relocates one of the patched
  functions. At that point either the patch silently no-ops (caught
  by the round-trip test's `PATCHES_VERIFIED` assertion) or starts
  applying incorrectly — either way the test fails loudly and we
  update.
