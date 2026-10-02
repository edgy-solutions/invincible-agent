# Measurement — the class-pool flag flipped on, by an in-process census of every walk row

**Date:** 2026-10-01 · **Lane:** `ia-74/lane/74` · **Subject:** `ONTOLOGY_CLASS_POOL_VIA_MESH`,
now DEFAULT ON (literal `"true"`) · **Seal:** `tests/test_the_flag_default_is_on_and_every_claim_about_it_agrees.py`

**Ordered, verbatim:** "Flip ONTOLOGY_CLASS_POOL_VIA_MESH default on; three-fire census; if any row
moves, flip back and report the diff."

## 0. The answer

No row moved, so the literal is flipped. 21 walk-census rows, both migrated routes, three fires per
arm. There were no errors and no fire unstable within an arm. The two arms agreed on ids, order,
scores and retrieval mode in every case.

## 1. Why this census, and not the 09-27 one

The 09-27 three-fire (`class-pool-flag-default-three-fire-2026-09-27.md`) fired the suite. Its
subject could not move: every test reader sets the flag explicitly, and the routing arms need a
cluster. Its §3 said the census that matters fires the deployed engine. That engine still carries
neither the migrated route nor the variable, and rolling it is Chris's.

So this census fires the code itself. It imports `main` from this branch and points its Weaviate
client and embedder at the sandbox's own stores, read-only (the coordinates stay out of the repo).
It then calls the two fork functions directly, with the module global set each way and read back
before every fire:

| route | function | arguments, both arms |
| --- | --- | --- |
| `/resolve` class pool | `class_pool_with_mode` | the row's question; `domains` = the row's domains, uppercased; `limit=10` |
| `/search_predicates` predicate pool | `predicate_hybrid_search` | the same question and domains; `limit=10`; no `verb_iris` |

Each row's subject is a non-blank census name derived from its `user`, because the mesh arm refuses
a blank one (§3). The script and its JSON stay in the session scratchpad and are not committed.

## 2. What was fired, and the controls that make the zero worth something

| | class pool | predicate pool |
| --- | --- | --- |
| rows x arms x fires | 21 x 2 x 3 | 21 x 2 x 3 |
| errors | 0 | 0 |
| fires unstable within an arm | 0 | 0 |
| rows whose ids, order or mode moved between arms | **0** | **0** |
| rows whose scores moved between arms | 0 | 0 |
| pool size, every fire | 10 | 10 |
| distinct pools across the 21 rows | 20 | 18 |
| mesh arm actually served (its own marker log line) | 63 of 63 on-fires | 63 of 63 on-fires |
| retrieval mode, both arms | `hybrid` | (not reported by this route) |

A zero is worth only what the census could have seen. Three things make this one real:

- **The mesh arm ran.** It logs a collection-marker line that only `WeaviateVectors` emits. That
  line appears exactly 63 times per route, which is 21 rows x 3 on-fires, and never on an off-fire.
- **The pools are full.** Every fire returned 10 rows, so the equality was not two empty lists agreeing.
- **The pools discriminate.** They differed across rows (20 of 21 distinct, and 18 of 21). An
  instrument that returned one fixed list would have shown 1.

## 3. What a row cannot show: identity

The mesh arm refuses a blank `user_email` with a 400, and the incumbent arm ignores identity. That
difference is by design and is not a row move. It applies to the person-less call only, so it was
enumerated rather than fired. Every in-repo caller of a flagged route threads the person when it
has one and omits the field when it does not:

- the supervisor's `/resolve` call (`dynamic_supervisor.py`, `if user_email:`);
- the supervisor's `/classify_predicate` call. It reaches the mesh arm only when the compatible-verb
  set is empty, because a scoped call stays on the incumbent whatever the flag says;
- `restate_analyst`'s `/resolve` call (`if user_email:`).

**Not measured:** how many person-less calls the deployed engine receives. The deployed engine
cannot answer that until the route is rolled, so the first post-roll walk census is where that
population shows up. A 400 there is the refusal working, not a regression.

**The dispatch's premise, checked.** "Identity is live (platform-registrar)" names the registrar's
graph-write owner (`meshRegistrar.onBehalfOfUser` in the sandbox values). That is not the `/resolve`
caller. What closed the 09-27 blocker is that the supervisor now threads the caller's
`user_email`. The conclusion holds; the stated cause was a different identity.

## 4. Gaps seen and not acted on

- Both collections lack a `MeshCollectionMeta` marker, so the mesh arm opens with the configured
  embedding model and logs that as a gap, not an agreement. Writing the marker is a write to the
  store, and this lane makes none.
- `MeshVectors.nominate` cannot restrict a field to a set, which is why a compat-scoped predicate
  call stays on the incumbent. Reported to ca.

## 5. What moved with the literal

The default seal red three arms and named ten prose homes. Each home was corrected: rewritten in
source and tests, and given a dated correction line in the three earlier measurement files. The seal
was renamed `..._is_on_...`, and its arms now hold the default ON in both the literal and its
evaluation.

## 6. Not claimed

- That the deployed engine behaves this way. It does not have the route yet, and it goes live only
  after Lane 1 merges and Chris rolls.
- That the person-less population at the deployed engine is empty (§3).
