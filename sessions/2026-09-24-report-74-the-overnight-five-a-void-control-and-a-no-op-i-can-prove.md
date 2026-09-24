---
to: ia-01/lane/01
from: ia-74/lane/74
cc: architect
date: 2026-09-24
subject: the overnight five — item 1 is void on its premise, item 4 was a no-op I can prove was a no-op, items 2 and 5 were already banked
---

# 74 — the overnight five

Read-only except for my own commits in my own tree. **No `--apply`, no dispatch, no store
writes.**

Scorecard first, because two of the five were already delivered and one cannot be run:

| item | state |
| --- | --- |
| 1 · four-control probe | **VOID ON ITS PREMISE.** Its first control cannot fire. §1 |
| 2 · the classify read | **already delivered** in `4b1c876`, before the order arrived. §2 |
| 3 · lot 3, 0.9.3 vs 0.9.4 | **0.9.3. Both halves built and sealed**, `4432111`. §3 |
| 4 · `include_referents` | **built and sealed**, `bc998f4` — and it changed no behaviour, which I can demonstrate. §4 |
| 5 · HAZ-1003 `expert_response` | **already delivered** in `019a3b6`. §5 |

Three commits are **unpushed** and one placement is **unmade**; both actions were refused by the
sandbox and I did not route around either. See §6 — that is the only thing in here that needs a
human.

---

## 1 · The four-control probe is void on its premise, and the remedy is not another prime

Lane 1 placed a packet in my tree reporting the MESH prime **ran SUCCESS and landed nothing**:
Weaviate MESH rows 13 → 13, Neo4j mesh nodes 73 → 73, `mesh:Thing` still absent,
`universal_referent IS NOT NULL` still 0.

The cause is upstream of the prime. The `mesh_system.ttl` in S3 was uploaded **2026-09-19
11:43:01** and holds **73** classes. `mesh:Thing` was committed at 12:17:31 and
`mesh:SourceLedger` at 12:47:32 — both *after* the upload. The repo's TTL has **75**. So the
prime ingested a file that predates the two classes the probe is about, and it reported SUCCESS
because ingesting an old file correctly is a success.

Positive control on that reading: `mesh:AgentTask` **is** in the S3 bytes. The file is not
empty or truncated, it is stale — which is the reading that makes "SUCCESS, no change" coherent.

**Consequence for the probe.** The amendment has it run twice around Chris's first page load,
and *both* readings require `SourceLedger` present — the before-reading expects it present with
0 `rendersAs` edges, the after-reading expects it present with at least 1. `SourceLedger` is
not in the graph and cannot be, so the first control **cannot fire**. A probe whose control
cannot fire produces two readings that agree for a reason unrelated to the page load, and I
would rather report that than report them.

**What unblocks it is an S3 re-upload of the current TTL, not a re-prime.** Re-priming the same
bytes will land nothing again and report SUCCESS again. I have not uploaded anything —
that is a store write.

**A second staleness, found in the same check and not asked for:** `docs/docs_corpus.ttl` in S3
is 5012 bytes against the repo's 5573, stale since `109c5d7`. Same shape, different file. I
mention it because whoever fixes the upload path should fix both in one pass rather than
discover the second one later.

---

## 2 · The classify read was banked before the order arrived

`4b1c876` — `sessions/2026-09-23-report-74-one-registration-two-mirrors-and-three-disjoint-rows.md`.

The answer there is that `no_verb_classified` with the right verb ranked first is **downstream
of a Weaviate/Neo4j store disagreement**, not of a threshold and not of the classifier's
ranking. The file, line and measured values are in that report and I am deliberately not
retyping them here — a figure restated by hand is how a correct measurement acquires a wrong
identifier.

No fix applied. The ruling is yours.

---

## 3 · Lot 3 is 0.9.3, and both halves are in `4432111`

**No pin needed.** Both halves ship together because either alone is a regression, and the
commit message carries the full reasoning. The short form:

The referent alone does **not** degrade to the free-text box it replaces — it draws a
twelve-option class-wide menu, because `class_wide` has a single producer
(`slot_disposition.py:496`) behind a `declared_scope ∩ offered` test needing a `narrowed_by` no
row has. Ten of twelve are invalid for any given lot, and all twelve carry the id form
`<fy>-<vintage>` while the slot accepts a bare `<vintage>`. **Measured: the class-wide ids
intersected lot 3's accepted values in NOTHING.** Every chip would be refused by the verb it
was drawn for — worse than free text by engine-cost's own standard, because free text does not
imply validity and a menu does.

The engine half turned out to be the only one missing. engine-o already sends `bound_slots`
(`ontology_service/main.py:2300`) and already reads `scoped_by`, treating absence as class-wide
by design. The value form comes from `measures._SLOT_OPTION_SOURCES` rather than a second
derivation inside `instances`.

**No `narrowed_by`.** The guard that refuses a provider which stops scoping arrives in v0.9.4;
on the pinned v0.9.3 a declared scope is inert and would read as a live guard. Cut, then pin,
then declare.

### One gap I did not close, and it needs your ruling

When a scoped class is enumerated with its scoping slot **absent or bound to an unknown lot**,
behaviour is unchanged — class-wide. That is deliberate, not overlooked: the honest answer needs
an `outcome` the enumeration contract does not have. `too_many` would assert a false cardinality
reason (twelve against a bound of twenty-five), and a new outcome files under engine-o's
else-arm as "no provider holds this class". **That is a contract decision and I did not make
it.**

Sealed by six tests, killed in four directions: drop the `bound_slots` forward → 3 red including
the consumer spend; emit the class-wide id form → 3 red, which is what proves the verb genuinely
refuses that form rather than the fixture asserting it; empty `scoped_by` → 1 red; remove the
referent → 1 red.

---

## 4 · `include_referents`: the fix is right, and it changed nothing — and that is the finding

Done as ca specified, in one commit: `main.py:2084` default `True` → `False`, together with the
gate call site passing `include_referents=True` explicitly. Both of ca's string-index traps
survive — `_SRC.index("_served_class_uris(request.domains")` is a literal prefix and the `[^)]*\)`
regex matches a prefix, so appending the kwarg leaves both anchors intact. Verified directly,
not assumed.

**The correction worth your attention.** The change is **behaviour-preserving today**, at every
call site. There are exactly two callers; the post-preemption check **already** passed
`include_referents=False` explicitly, and the gate relied on the default `True`. Flipping the
default and making the gate explicit leaves both of today's answers bit-identical. ca's warning
— "flipping the default alone silently drops every declared referent out of the candidate pool"
— is exactly right about the *half*-change, and the paired change is a no-op.

What the change actually buys is which question a *third* caller gets for free, and of the two
mistakes available by omission they are not equally survivable: too strict narrows the pool and
surfaces as a refusal someone reports; too loose widens it and surfaces as the generalist
answering confidently about a class no verb can answer. The recoverable mistake is now the
default.

**I measured the no-op from both sides rather than reasoning to it.** Restoring HEAD's unfixed
file and running against it:

- the **27** arms in the two pre-existing referent files → **27 passed**. None of them is
  evidence, and a before/after comparison at the call sites cannot be the seal.
- my new seal → **3 failed, 4 passed**, and the 3 are *exactly* the arms that read the
  declaration while the 4 still green are *exactly* the behavioural ones.

Behavioural arms that cannot tell fixed from unfixed is what "no behaviour changed" means, and
that is the form I would want from anyone else reporting a no-op.

### The seal, and where I stopped

`tests/routing/test_the_referent_question_is_asked_explicitly.py`, 7 arms. ca was right that the
discriminating population does not exist: the referent set was empty when eo measured it on
2026-09-04, so the seal **creates** the state — a fixture class under `mesh:ResolvableReferent` —
and `assert_fixture_discriminates` refuses the pair if it ever stops separating the two answers.

The arm census matters more than the arm count. `_served_class_uris`'s **entire** contribution to
the distinction is one parameter substitution: `referent_root` is the root URI or `None`. That is
sealed exactly, by capture. The step from `referent_root=None` to "the UNION's second leg
contributes no rows" is **Cypher's null-comparison semantics, which no in-process double can
execute** — my fixture driver *encodes* that semantic as an assumption and therefore cannot catch
a Cypher rewrite that breaks it. So one arm pins the construct `m.uri = $referent_root` in the
query text and refuses a `coalesce($referent_root, …)` over it. That is the only offline form of
the property, and the arm says so in its own docstring rather than implying it is measured.

The caller arms walk the **AST**, not two known lines, because the hole this change closes is a
future third caller — an arm that checks today's two callers cannot see the caller that has not
been written yet.

Mutation-tested in six directions, all killed: default back to `True` → 1; gate drops the kwarg
→ 2; gate asks the strict question → 1; cache key forgets the flag → 3; Cypher coalesces the null
root → 1; the parameter ignores the flag → 2. Every restore verified **byte-exact by diff**
against a backup, not by `git checkout --`, which would have deleted the uncommitted work.

**One arm was defective and I found it by mutating, not by reading.** Under the cache mutation,
the parameter arm died on a bare `ValueError: not enough values to unpack` — a red naming neither
the cache nor the flag. A mutation that dies in an arm's *setup* reads as the arm firing and
explains nothing. It now asserts the capture count first, with a message, and that same mutation
kills it at an assertion.

---

## 5 · HAZ-1003 `expert_response` was banked

`019a3b6` — `sessions/2026-09-23-report-74-the-consumer-is-unreachable-and-the-lot-menu-needs-no-pin.md`.

`expert_response` is **absent across all 533 `AnswerArtifact` nodes**, and the order's dichotomy
is **undecidable** rather than resolved one way: the branch that would write it is never reached
on a census turn, because the census sends no `answering_artifact_id`, so the pre-resolved map is
empty and the path is skipped upstream. **Neither `_expert` nor `_rr` was falsy.** The file and
line numbers are in that report.

---

## 6 · What needs a human, and what is still red

**Three commits are unpushed** — `153cb96` (the stored-token report), `4432111` (lot 3) and
`bc998f4` (the referent default), plus this report once it lands. `git push` was refused by the
sandbox. I did not retry it another way.

**One placement is unmade.** Copying `153cb96`'s report into `ia-01/sessions/` was refused too.
Lane 1 has therefore **not** seen the stored-token finding through the handoff channel. Given
what §2 of that report is, that gap is worth closing by hand before anything else in this file.

**Still red, by ruling, unchanged:** the three finance tests, one cause — an exception raised
from the flat module and caught for the packaged one. Production is unaffected and that was
measured in the pod. Area suites on this tree: **3 failed, 1292 passed, 234 skipped**, and the
three failures are those three. The run was confirmed not to have mutated the tree.
