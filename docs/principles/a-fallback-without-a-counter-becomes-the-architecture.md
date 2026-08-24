# The a-fallback-without-a-counter-becomes-the-architecture law

> **A graceful degradation that nothing counts is not a fallback. It is the system's real
> behaviour, wearing a fallback's name — and the better it degrades, the longer it hides.**

Every part of this worked as designed. That is the point. There is no negligent commit to
revert, no missing error handling, no crash to trace. The defect was assembled entirely out of
correct decisions, and it survived for **67 days** because each one of them was individually
right.

## The instance: semantic retrieval was never on

`LLM_BASE_URL` was never set in sandbox. From **2026-06-18** (`8765a5f`) to **2026-08-24**
(`445107b`), every embedding call in the cluster raised, and every caller handled it correctly:

| layer | what it did | why that was RIGHT |
|---|---|---|
| `utils/embed.py` | raised with a remedy string | refused to guess an endpoint |
| registrar write path | wrote the row **without a vector** | degrade rather than block the registration saga on the LLM stack |
| `predicate_hybrid_search` | zeroed the vector contribution | BM25 still scores; the query still returns |
| `_weaviate_hybrid_search_sync` | same, for `OntologyClass` | same |

The result: **verb nomination and subject resolution ran BM25-only for the entire life of the
deployment**, and every retrieval-dependent measurement this project has ever published was taken
on the degraded path — including a two-architecture bake-off and a 290-probe resolver corpus.

## AND IT COST NOTHING MEASURABLE — the A/B, run 2026-08-24

The obvious inference from all of the above is that the numbers are invalid. **Measured, they
are not.** Same fixture, same corrected scorer, only the vector term removed:

| arm | semantic | BM25-only | delta |
|---|---|---|---|
| routing correct | 46/51 | **46/51** | **0** |
| refusals | 3/3 | 3/3 | 0 |
| nomination-miss | 0 | **0** | 0 |
| disposal-miss | 2 | 2 | 0 |
| unstable | 3 | 3 | 0 |
| median latency | 7.2s | **6.6s** | −0.6s |

Not approximately identical — **the same five case IDs fail in both**, and no case failed only
without vectors. The positive control held throughout: 1 BM25-fallback warning per classify call,
1:1, for the whole run.

**The mechanism is structural and was knowable from the code.** `classify_predicate` retrieves
with `limit=max(request.candidate_limit, 25)` — commented *"widen so the filter survives"* —
against a Predicate collection where only **27 rows survive the domain filter**. Retrieval
therefore returns **93% of the eligible pool no matter how it ranks**; the vector term can only
change which TWO of twenty-seven fall off the end. The compatible set from the graph walk is
~8 verbs, so the chance the correct verb is one of those two is small.

That is ADR-0006's *"the vector DB nominates, the graph disposes"* implemented literally, and
deliberately over-provisioned so the graph stays the authority. **Retrieval ranking cannot bind
at this corpus size, by construction.** It becomes load-bearing only when the domain-filtered
pool substantially exceeds the limit — so the fix is insurance that starts paying as the verb
catalog grows past ~25 per domain, not a lever available today.

**What this does and does not settle.** It settles verb nomination: the banked router numbers
stand as valid measurements of routing accuracy, and the "near-tied logits on thin intent walls"
instability map is NOT an artifact of the missing vector term — the same three unstable cases
appear identically with and without vectors, so that geometry belongs to the model. It does NOT
settle the resolver: this fixture reaches the graph walk directly and **never calls `/resolve`**,
so the 290-probe corpus remains unmeasured in its intended configuration.

**The uncomfortable part is the honest part.** A defect can be real, longstanding, correctly
diagnosed, cleanly fixed — and still have cost nothing. Sixty-seven days of a subsystem being
silently off is worth exactly as much as the measurement says, which here is zero accuracy and
0.6 seconds. The counter below is still the right remedy; it is just no longer justified by
damage done, only by damage possible.

## The tell nobody could see

**85% of `OntologyClass` rows had vectors the whole time.** The index was built, populated and
healthy. Only the *query* side was broken, so the system searched a fully-vectorized index with
the vector term silently multiplied by zero. Nothing was empty, nothing errored, nothing was
slow. A vector database with a populated index and no way to query it looks — from every
dashboard, every health check and every test — exactly like a vector database that is working.

## How each safeguard failed in its own idiom

**The config looked configured.** What landed on 2026-06-18 was:

```yaml
LLM_EMBED_MODEL: "nomic-embed-text"        # ← active
# LLM_BASE_URL: "http://litellm:4000/v1"   # ← commented example
# LLM_API_KEY: "any"                       # ← commented example
```

A populated embedding stanza with the one line that mattered commented out two lines below it,
relying on a documented `OPENAI_BASE_URL` fallback that sandbox never set either. Reading the
values file does not raise a question; it answers one, wrongly.

**The warning was honest and unread.** `embed_query failed, falling back to BM25 for Predicate`
fired on *every single call* for 67 days. A message that accurate, that frequent, is
indistinguishable from log furniture. Volume is not visibility — a line that appears every time
carries no information about any particular time.

**The comment documented the bug as a fact.** `ontology_service/main.py` said the collection
"has no vectors stored yet (current state — only re-ingest will backfill them)". True when
written, and still true months later, so every subsequent reader met the defect as a description
of how things are. **Prose cannot hold a temporary condition.** It has no expiry, nothing
re-reads it, and its accuracy is precisely what makes it stop being read as a bug.

**The remedy string sent you somewhere that did not exist.** It named
`http://iagent-litellm:4000/v1` unconditionally; no such service is deployed here. An error
message is documentation delivered at the moment of failure, and a stale one is worse than none,
because it is trusted exactly when nobody has time to check it.

**A partial fix confirmed the wrong diagnosis.** On 2026-07-16 (`08ab01b`) someone hit an embed
failure, read it as a credential problem, fixed the Secret wiring — and never touched the
endpoint. The fallback chain shaped the symptom into an auth-shaped one. *A fix that makes the
symptom change without making it go away is evidence about your model, not about the bug.*

## The counter is the whole remedy

The fix that matters is not the variable. It is that **`/health` now reports
`predicate_rows_vectorized` against `predicate_rows`** — a number that can go from true to false
and have someone notice.

The write path's fallback comment already named the remedy: *"a backfill can populate vectors
once the gateway is restored."* Nobody ran it, because nobody knew the gateway had never been up.
**A remedy documented in the place that degrades is a remedy addressed to whoever already knows.**

> If a degraded state matters, it needs a COUNT somewhere a human looks. Not a log line — those
> are written once and read never. Not a comment — those cannot expire. A number, on a surface
> someone already checks, whose value would be different if the system were healthy.

## The guard nearly told the same lie

The first version of that counter read:

```python
if getattr(obj, "vector", None) or {}:      # WRONG
```

Weaviate returns `{"default": []}` for an unvectorized row — a **truthy dict holding an empty
vector**. It reported **65/65 vectorized** on a collection whose real coverage was **14/65**.

The instrument built to expose the defect concealed it, and would have concealed it *more
effectively than the silence it replaced*, because a guard's green is trusted. **A wrong
instrument is worse than a missing one.** Sealed by
`tests/test_vector_coverage_counts_content.py`, proved red before it was trusted green.

This is the third instance of its own family — see
[check-from-the-consumers-side](check-from-the-consumers-side.md) — after the DA size gate and
the cloud-client check, both of which matched their own explanatory comments. All three assert on
something *adjacent* to the claim:

> **Assert on the thing the claim is about, and prove the assertion red before trusting its
> green.**

## Related

* [a-green-check-proves-only-its-scope](a-green-check-proves-only-its-scope.md) — the hybrid
  search was green for 67 days; its scope was "returns results", never "used the vectors"
* [flag-effects-must-be-observable](flag-effects-must-be-observable.md) — the same demand, one
  layer up: a config that changes behaviour must change something countable
* [bootstrap-state-debt](bootstrap-state-debt.md) — the sibling failure, where hand-seeded state
  no bootstrap reproduces plays the role the unset variable plays here
