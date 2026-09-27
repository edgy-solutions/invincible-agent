# Route migration pilot — `/resolve`'s class pool through `WeaviateVectors`

**Date:** 2026-09-27 · **Lane:** `ia-74/lane/74` · **Flag:** `ONTOLOGY_CLASS_POOL_VIA_MESH`, **default
off, and it stays off** · **Seal:** `tests/test_the_migrated_route_returns_the_same_rows.py` (39 arms)

One route moved, behind a flag, to make the diff between the hand-rolled query and the shared
implementation *measurable*. This file is the diff. Nothing here proposes flipping the default.

---

## 1. What was measured

`class_pool_with_mode()` is the fork and the only one: both arms return `(rows, mode)`. The seal runs
each arm over **the 20 rows of `docs/measurements/walk-census.yaml`** — the questions the fleet
actually asks, derived from the file, not typed — against one scripted store, and compares the pools
row for row and key for key.

| arm | assertion | result |
| --- | --- | --- |
| 20 census questions × flag off/on | pools identical | **identical, all 20** |
| filter shape (1 domain, 2 domains, none) | both arms issue the same query | **identical** |
| embedding fails | `mode == "bm25"`, rows still returned | **both arms** |
| embedding succeeds | `mode == "hybrid"` | **both arms** |
| collection absent | `([], None)` — no retrieval, so no retrieval mode | **both arms** |
| mid-query exception | HTTPException **503** | **both arms** |
| store answers zero objects | `([], "hybrid")` — cold start, *not* a refusal | **both arms** |

The last two are the pair that matters most and they are deliberately not collapsed: RULED
2026-09-14, an empty pool sends `/resolve` down the cold-start path, which answers from the
**maintenance ontology**. A substrate failure returning `[]` therefore produces a confident
wrong-domain answer under a banner naming a false diagnosis. Both arms separate failure from
emptiness, and the seal holds each to it.

## 2. The differences that remain — the actual deliverable

### 2.1 A blank `user_email` is refused with the flag on, and served with it off

`ResolveRequest.user_email` defaults to `""`, and the incumbent has never read it. `nominate` refuses
a service initiator, and this call site refuses a *blank* subject rather than minting
`Initiator(subject="", kind="person")` — which would pass the interface's check while being exactly
what that check exists to stop: a read whose provenance no person can be asked about, wearing the
right label.

**Consequence:** any caller reaching `/resolve` without threading identity gets a **400** with the
flag on. This is the one behavioural change in the pilot, it is sealed as a difference rather than
smoothed over, and **it is the item that has to be settled before any default moves.**

### 2.2 A `uri`-less row raises on the incumbent and passes through on the mesh arm

Incumbent: `obj.properties["uri"]` → KeyError → its own `except` → **503**. Mesh arm: `.get("uri")` →
a candidate with `uri: None`. Neither is obviously right and a `uri`-less `OntologyClass` row has
never been observed, so the behaviour is **pinned** by an arm rather than aligned by guess: whichever
way it is settled, that arm reds and names the decision.

### 2.3 A stored-null `definition` reaches the wire as `None` on **both** arms — a pool-builder defect

The incumbent's `.get("definition", "")` returns `None` for a property stored as null, and `None`
reaching an f-string renders `"None: None"` in a BAML enum description. The mesh projection was
aligned to match it, *including this*, because row identity is what the flag's seal asserts and the
arms must agree even where both are arguably wrong.

**Reported, not repaired here.** Fixing it inside a migration that was supposed to change nothing
would be the one change no seal in this file could see.

A draft of the projection wrote `r.get("definition", "") or ""`, which agrees with the incumbent on a
present definition *and* on an empty-string one. It differs **only** on a stored null. That is why
the fixture carries one.

### 2.4 The mesh arm is stricter about the collection marker

`nominate` checks the embedding-model marker at open and refuses a mismatch; the incumbent has no
such check and would search a space its query vector does not live in. Strictly one-directional: it
can turn an answer into a refusal, never a refusal into an answer. On a **markerless** collection it
warns rather than refusing.

### 2.5 `score` had to be added to `WeaviateVectors._search`

The implementation never requested `MetadataQuery(score=True)`, so every row came back scoreless —
not a pool the incumbent's can be compared against, and the decision-path panel would have lost the
losing candidates' scores again. The metadata-query factory is now a **required** constructor
keyword: a default would have been invisible at construction, invisible in the row shape, and visible
only as an empty column in a panel.

## 3. Mutation results — 11 mutants, 11 dead at the named arm

Runner restores in `finally` and re-digests; `AFTER-RESTORE` green on every pass.

| mutant | verdict | arm that caught it |
| --- | --- | --- |
| flag branch never taken | DIED | `FLAG_SELECTS_A_DIFFERENT_CODE_PATH` |
| `definition` gains `or ""` | DIED (20 red) | census parity |
| `score` dropped | DIED (21 red) | census parity |
| `.get("uri")` → `["uri"]` | DIED | the pinned `uri` diff |
| failure returns `[]` | DIED | 503 parity `[mesh]` |
| empty treated as failure | DIED | empty-store + no-retrieval |
| blank subject allowed | DIED | the 400 diff |
| domain scope dropped | DIED | **same-query only** |
| incumbent mode always `hybrid` | DIED | bm25 `[incumbent]` |
| mesh mode always `hybrid` | DIED | bm25 `[mesh]` |
| answered → empty | DIED (23 red) | census parity |

**The entry worth reading is `domain scope dropped`.** It reds the same-query arm and **leaves all 20
row-equality arms green** — because a scripted store ignores the filter it is handed. So *row identity
against a double cannot detect an entitlement widening*, and the same-query arm is the only thing in
this file standing between the flag and a silent scope change. It exists because of this measurement,
not because of an argument.

Two anchors that mattered: a multi-line mutant anchor matched **zero** times (main.py is CRLF) and was
reported as `SKIP` rather than passing as quiet; and a mutant first scored `WRONG-ARM` only because
`-x` stopped at whichever equally-correct arm came first in file order — a verdict selected by
position.

## 4. Suite state — and two of master's 38 routing reds are not real

Measured with the invocation set held fixed:

- `tests/routing/` **alone, with my changes**: 38 failed / 700 passed / 116 skipped.
- `tests/routing/` **alone, with my four paths stashed to HEAD**: 38 failed / 700 passed / 116
  skipped — **the same 38 identities**, `comm` empty in both directions.

So the pilot adds **no routing regression**. The first control I ran said otherwise (40 vs 38) and was
wrong: it changed my paths *and* the set of collected files at the same time.

Chasing that confound produced a finding worth keeping. Run alone:

| file | alone | inside `tests/routing/` |
| --- | --- | --- |
| `test_classify_route.py` | 29 failed | 29 |
| `test_phrasing_independence.py` | 7 failed | 7 |
| `test_adr0019_engine_o_contract_a.py` | **2 passed** | **2 failed** |

29 + 7 = **36 genuine**; the remaining **2 are order-dependent contamination**, and the arithmetic
closes exactly (no other routing file fails). For `docs/plans/suite-signal-session.md`.

### The mechanism, and a class rather than an instance

`tests/test_predicate_hybrid_search.py` installs 10 `sys.modules` stubs and removes none. Co-collected
with `tests/routing/test_a_vector_is_written_where_the_search_looks.py` it reds two of that file's
arms (`test_the_config_helper_returns_kwargs_not_a_value`,
`test_the_fallback_form_is_reachable_on_the_pinned_range`) — both green when it runs alone. This is a
defect at HEAD; it was found because the new seal *reuses that harness* and reproduced it exactly.

The new seal now **undoes its own install**: the footprint is derived by diffing `sys.modules` across
`_install_stubs()` (never a typed list), restored in `finally`, and two arms assert it. Both
collection orders are now clean, 53 passed.

Census of the class: **38 test files install `sys.modules` stubs; 21 of the 38 carry no restore
marker at all** (counted as files containing `sys.modules[` against files containing
`monkeypatch.setitem` / `sys.modules.pop` / `del sys.modules` — a *text* proxy, so a file restoring
some other way would be miscounted as leaking; the two measured offenders below were confirmed by
running them, not by the grep). Worst
offenders `test_predicate_hybrid_search.py` (10/0) and
`tests/routing/test_adr0019_engine_o_contract_a.py` (9/0) — which is, not coincidentally, the file
whose 2 failures are order-dependent. Not fixed here: each is another arm's committed harness, and the
shape of the fix is the ~6 lines used above. Available on a word.

## 5. What is *not* claimed

- Nothing about live cluster behaviour. Every arm above runs against a scripted store.
- No claim that the arms agree on a **real** Weaviate. They agree on what they *ask* it, which is the
  strongest thing a double can support.
- The default is not flipped and no recommendation to flip it is made here. §2.1 is the blocker.
