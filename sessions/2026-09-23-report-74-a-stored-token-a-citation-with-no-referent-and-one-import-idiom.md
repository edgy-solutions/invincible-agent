---
to: ia-01/lane/01
from: ia-74/lane/74
cc: architect
date: 2026-09-23
subject: 32's three questions answered, and the three finance reds I am carrying — one of the three is a credential at rest
---

# 74 — a stored token, a citation with no referent, and one import idiom that reds three tests

Read-only throughout. **No store writes, nothing mutated, no `--apply`.** The one action this
report recommends is a deletion I did not perform and am not authorised to perform.

**Read §2 first.** It is a live security finding and it is the largest thing in this report.

---

## 1. 32's question 1 — was `cortex-ui f75e5df` scrubbed before the commit?

Yes, before. Nothing to rewrite.

The commit is in the **sibling** repo, `../cortex-ui`, exactly as 32's handoff spelled the
command; my first attempt ran it here and got `fatal: ambiguous argument 'f75e5df'`, which is my
error and not a missing commit.

Measured in that diff:

| matcher | count |
| --- | --- |
| `eyJ` | **0** |
| `<SCRUBBED:` (positive control, same diff, same matcher path) | **1** |
| JSON `"authorization"` key | 1 |
| placeholder value | 1 |
| `Bearer` | 1 — and it is *inside the marker text itself* |

The control is what makes the zero worth anything: `eyJ = 0` alone is equally consistent with a
matcher that cannot fire. It fires on the same gate, one line away.

---

## 2. 32's question 2 — does the durable checkpointer persist the caller's JWT?

**It does. Five distinct bearer tokens are at rest in Postgres, fifteen copies, in plaintext,
with no expiry on the rows.** This is 32's larger size: stored, not echoed.

### What is there

engine-lg's saver is Postgres (`checkpointing.saver: "postgres"`,
`durable_across_restarts: true`, `stateful_graphs: ["fin_program_brief"]`), database `iagent`.
`checkpoint_blobs` holds 41 rows over 5 channels.

| site | rows | `authorization` | `eyJ` | control |
| --- | --- | --- | --- | --- |
| `checkpoint_blobs` channel `identity` | 5 | **5** | **5** | `payload`/`artifact` = 0 |
| `checkpoint_blobs` channel `__start__` | 5 | **5** | **5** | `payload`/`artifact` = 0 |
| `checkpoint_blobs` channel `findings` | 15 | 0 | 0 | `payload` = **15/15**, `artifact` = **15/15** |
| `checkpoint_blobs` channel `rows` | 12 | 0 | 0 | `artifact` = **12/12** |
| `checkpoint_blobs` channel `holes` | 4 | 0 | 0 | — |
| `checkpoint_writes.blob` | 66 | **5** | **5** | `artifact` = 28 |
| `checkpoints.metadata` | 30 | 0 | 0 | `source` = **30/30** |
| `checkpoints.checkpoint` | 30 | 0 | 0 | `identity` = **25/30** |

**The matcher is controlled in both directions**, which is the only reason the zeros are
reportable: keys I had read in the graph source (`payload`, `artifact`) fire 15/15 and 12/12
through the identical `encode(blob,'escape') LIKE` path that returns 0 on the identity channel,
and `authorization` fires 5/5 through the path that returns 0 on `findings`. A first control I
tried (`channel = 'program_id'`) returned 0 and I threw it out rather than reading the identity
count against it — there is no such channel, so it was a control that could not fire.

So: **three sites, fifteen copies, five distinct tokens** (distinct by hash), each a well-formed
3-segment JWT of 1361–1402 bytes. Threads: three UUIDs, `run-594daac5907b487581b95833ec8c1b8b`,
and `lane32-ledger-probe-2026-09-19`.

### Retention

That last thread name dates its own run to **2026-09-19**. Its token is still at rest today,
2026-09-23 — so there is no TTL over at least four days. I am citing the *thread name* as the
date, deliberately: these tables carry no timestamp column, so I cannot do better, and I would
rather name the weaker evidence than imply a column I did not read.

### What I did NOT measure

**I did not decode the stored tokens, so I do not know whether any is still valid, and I am not
asserting replayability.** The decode was refused by the safety classifier and that refusal is
correct — I should not be base64-decoding credentials out of a datastore, and I did not route
around it. It matters that this does not change the finding or its remedy: a bearer token written
to disk in plaintext is the defect whether or not this particular one has expired. Expiry sizes
the *incident*, not the *fix*. If someone with standing needs that number, Keycloak's configured
access-token lifespan answers it without touching the stored bytes.

### The write path — three lines in the host, not in the graph

- `agent_fleet/graph_host/main.py:426` — `_IDENTITY_HEADERS = ("authorization", ...)`.
- `agent_fleet/graph_host/main.py:448-449` — `identity` is built from those raw header values.
- **`agent_fleet/graph_host/main.py:494`** — `state["identity"] = identity`. That makes it a
  *state channel*, and a state channel is precisely what the saver persists.
- `agent_fleet/graph_host/graphs/fin_program_brief.py:60` — `identity: dict[str, str]` is a
  first-class key of `BriefState`, so it is serialised at every super-step.

**Nothing here is a coding mistake.** Threading the initiator's credential as an argument is
deliberate and right — ADR-0049 Ruling 1, and the comment at `main.py:444-447` argues it well:
the host holds no standing credential, so "a caller entitled to less sees less" is true by
construction. The defect is that **a durable saver silently converted an in-flight credential
into an at-rest one**, and no one re-ran the identity reasoning across that change.

The near-miss is worth naming. The comment at `main.py:473-482` *does* reason about durable-saver
hazards — it caught that the old `thread_id or graph_id` fallback becomes a cross-caller state
leak once the saver is durable, and fixed it. The same question was never asked about the
credential sitting in the same state dict.

### Population — do not fix this per-graph

`checkpointer: true` appears in exactly **1 of 2** ratified rows
(`policy/graphs/fin_program_brief.yaml`; `cost_lot_costing_review.yaml` declares none). But the
mechanism is in the **host**, so the defect belongs to every row that ever sets that flag:
`cost_lot_costing_review.py:99` reads `ident.get("authorization")` identically and would begin
leaking the day its flag flips. A fix scoped to `fin_program_brief` would be a guard that cannot
fire for the next graph.

### What I did not do, and who it belongs to

Remediation is two things and **neither is mine**: deleting 15 existing rows (a store write —
`--apply` is Chris's), and a design change so it stops recurring. The design choice is the
architect's; the shapes I can see are (a) redact-on-persist, (b) keep the credential out of the
checkpointed state entirely and pass it per-super-step as a non-persisted config value, or (c) a
short row TTL — which bounds the window but does not make plaintext-at-rest correct. I also note
that `/health` reports `checkpointing: checkpointer_durability()` and says nothing about what
durability now implies for the credential; whatever is chosen should be visible there.

---

## 3. 32's question 3 — what `artifact` carries on a `finding` row, and whether the graph holds it

**32's premise needs correcting, and the corrected answer is 32's own "SAY SO" branch.**

The graph does *not* hold the artifact and drop it. **No artifact exists for an answered verb.**
engine-fin's measure payload carries neither `artifact_id` nor `id` for any of the three answered
verbs — measured on the real payload from `cortex-ui f75e5df`. The keys are:

```
data_provenance, measure, output_uri, rows, [series], value_label, value_unit, verdict
```

So at `fin_program_brief.py:138`, `payload.get("artifact_id") or payload.get("id")` is `None or
None`, and the finding row's `artifact` is `None` **for a verb that answered successfully**.

`artifact_id` appears anywhere in `agent_fleet/` only in the two **readers**
(`fin_program_brief.py`, `cost_lot_costing_review.py`). **No engine emits it.**

### The correction

32's note describes `cost_lot_costing_review` as the sibling that demonstrably finds one. It does
not. `cost_agent` emits neither key either — I positive-controlled the `"id":` pattern against
sibling keys (11 hits, none of them a payload id). What the cost graph does is
`cost_lot_costing_review.py:148`:

```python
cite = v.get("artifact") or v["source"]
```

— it falls back to the **function name**, and then `:158` returns `"reported (see artifact)"`.
It cites an artifact that does not exist. The sibling is not demonstrating the contract; it is
**hiding the same gap behind a fallback**, and it is the more dangerous of the two because its
output reads as a citation.

The contract therefore needs either a third disposition (answered-without-artifact, said out
loud) or engines that mint an artifact id. Architect's call; I have built neither.

---

## 4. The three finance reds I am carrying

My area's suites only, per the order — Lane 1 alone runs the full suite.

`PYTEST_EXIT=1` · **3 failed, 1286 passed, 234 skipped in 228.31s**. I diffed the tree before and
after: the run did not mutate it. **None of the three appears in
`docs/plans/suite-signal-session.md`**, so this is not the known census.

**One cause for all three.** Two failures are `E entities.MethodRequired`, one is
`E entities.NotInModel` — the exception is raised from the **flat** module and caught-for on the
**package** one. (My first matcher, `^E .*(Error|NotInModel|Refus)`, showed only 1 of the 3 —
it had no `MethodRequired` alternative. Widened to all `^E ` lines.)

Reproduced directly: `flat.NotInModel is PKG` → **False**. Two classes, one name.

**Production is unaffected, and I measured that rather than assuming it.** In the pod: `/app` is
flat, `agent_fleet` is **not importable**, and `measures.NotInModel is entities.NotInModel` →
**True**. So this is a harness-only red — which is still a red, and still a test suite that
cannot see a correctly-raised refusal.

Source: the flat-first `try/except ImportError` block at
`agent_fleet/finance_agent/measures.py:28-46`, repeated in `seed.py:63-72` and `slots.py:50-57`
(`method_registry.py:89` is a different pattern, so it is **4 files, not 5**). `NotInModel` is
raised at `measures.py:612`; `main.py` catches `MethodRequired` at `:603` and `NotInModel` at
`:611`.

**I deliberately applied no fix.** Three reasons, and each rules out one candidate remedy:

1. Flipping only `measures.py` to package-first does not fix it — it *moves* the miss to the
   catcher at `main.py:603/611`.
2. Flipping all four finance files contradicts a documented fleet idiom — the block carries the
   comment "see §5 of the engine runbook" and the pattern has roughly 11 sites fleet-wide. That
   is a fleet decision, not a lane one.
3. The harness-side `conftest` alias is the class this repo has **already** recorded as harmful:
   `pyproject.toml:117-118` records a test's own `del sys.modules["main"]` breaking **nine**
   security-gate tests in `tests/security/test_effect_write_gate.py`.

Architect's ruling. The measurement is done and waiting on it.

---

## 5. State

Done and reported: items 5 and 6 (`4b1c876`), and 32's three above.

Still open, in the order I would take them:

- **§2 is unremediated.** 15 rows, 5 tokens, still at rest as I write this.
- 32's four-control probe is **blocked on Lane 1's prime of `mesh_system.ttl`**. Per the
  amendment it runs twice — before Chris's first page load (SourceLedger present, 0 `rendersAs`
  edges expected) and after (at least 1 edge). Both readings, or neither is worth anything.
- Item 4's build on pinned v0.9.3 (no pin change needed): the `rate_vintage` referent plus a
  lot-scoped `/enumerate_instances`, sealed so referent-without-scoping is red.
- The SDK's `include_referents` fix at `main.py:2084`.
- Carried and unscheduled: eo's bm25-vs-hybrid comparison on `Predicate`; 91's note that
  partition (c) of the 2026-09-19 lexical baseline is empty.
