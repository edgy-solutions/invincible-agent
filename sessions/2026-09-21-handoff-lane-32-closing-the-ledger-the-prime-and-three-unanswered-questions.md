# Lane 32 closing — the ledger row landed, the prime has not, three questions never reached me

to: ia-74/lane/74 — from ia-32/lane/32, 2026-09-21. Lane 32 closes; lane/74 inherits the open
items. Claims marked **M** = measured, **I** = inferred; all M today unless dated.

## Current state

    worktree/branch  ia-32 / lane/32                                              M
    lane tip         33e97b4   0 ahead / 0 behind origin/lane/32 — pushed         M
    working tree     CLEAN (git status --porcelain empty)                         M
    vs master        0 ahead, 14 behind — lane/32 is FULLY MERGED, at ae356e5     M
    master           70541a0 == origin/master (0/0, pushed)                       M
    cortex-ui        92c195a                                                      M

## Decisions and rulings received

1. **`33e97b4` is ACCEPTED as reported** (the architect, 2026-09-21, placed by Chris). Runbook
   sites 2, 5, 6 and the `cost:LotCostingReview` binding stand.
2. **A packet's author PLACES the file and does not COMMIT it** into another repo's checkout.
   My `f75e5df` in cortex-ui shipped once, on Chris's word. **Do not repeat it.**
3. **The prime is Chris's.** Nothing on any lane substitutes for it.

### ⚠ CORRECTION — the two-mirrors seal is GREEN, not red

The order closing this lane says master's seal is red until cortex adds the
`LotCostingReview -> SOURCE_LEDGER` row. **Cortex has added it.** Do not carry the red forward.
* **M** — committed in cortex-ui at **`ea060f3`**, present at `92c195a`;
  `src/registry/assembleCapabilities.ts:669` = `"http://invincible-agent/cost#LotCostingReview"`.
* **M** — `uv run pytest tests/finance/test_the_wire_carries_what_the_engine_declares.py -k MIRRORS -q`
  → **1 passed**, 15 deselected. Run in `ia-32` at `33e97b4` against cortex-ui `92c195a`.
* **I** — that master agrees: I ran it at the lane tip, and `git diff --stat lane/32..master`
  touches neither `presentation_agent/capabilities.py` nor `tests/finance/`. **Re-run on master
  before quoting it as master's state** — a green belongs to a sha, not a directory.

## The prime still owed — `mesh:SourceLedger` is ABSENT from the live graph

**M 2026-09-19** on the rolled sandbox; **NOT re-measured today.**

    mesh:SourceLedger                         ABSENT   0 canonical, 0 compact
      control+ mesh:KnowledgeDocument         present  1
      control+ mesh:StatefulSupportResponse   present  1
      control- a fabricated class             absent   0
    StatefulSupportResponse -[rendersAs]-> *  0 edges
      control+ cost#LotCostBreakdown          2 edges
      floor:   the rendersAs relationship TYPE exists in the graph

It needs a prime of `mesh_system.ttl`. **That prime is Chris's, and it must wait for doc-tools
to roll its fixed writer.** Sites 1–6 all go green on commit because every one of those seals
reads a FILE; the class resolving in the graph is a different claim, and no seal here makes it.

### The probe, to re-run AFTER the prime

Runner: the line already tracked at `scripts/probes/baseline.sh:18` (`kubectl exec` →
`cypher-shell --format plain`). Use it; do not retype credentials into a session file.

    # 1 — the CLASS, BOTH spellings, with both controls in the same breath
    UNWIND [{l:'SUBJECT  SourceLedger',        c:'http://invincible-agent/mesh#SourceLedger',            k:'mesh:SourceLedger'},
            {l:'CONTROL+ KnowledgeDocument',   c:'http://invincible-agent/mesh#KnowledgeDocument',       k:'mesh:KnowledgeDocument'},
            {l:'CONTROL+ StatefulSupportResp', c:'http://invincible-agent/mesh#StatefulSupportResponse', k:'mesh:StatefulSupportResponse'},
            {l:'CONTROL- Fabricated',          c:'http://invincible-agent/mesh#NotAnArchetypeXyz',       k:'mesh:NotAnArchetypeXyz'}] AS p
    OPTIONAL MATCH (a:OntologyClass) WHERE a.uri = p.c
    OPTIONAL MATCH (b:OntologyClass) WHERE b.uri = p.k
    RETURN p.l AS probe, count(DISTINCT a) AS canonical_nodes, count(DISTINCT b) AS compact_nodes ORDER BY probe;
    # 2 — the BINDING, count form (prints a row even at zero)
    MATCH (s:OntologyClass) WHERE s.uri = 'http://invincible-agent/mesh#StatefulSupportResponse'
    OPTIONAL MATCH (s)-[r:rendersAs]->(o)
    RETURN s.uri AS subject, count(r) AS rendersAs_edges, collect(DISTINCT o.uri) AS objects;
    # 3 — POSITIVE CONTROL, identical query shape, a subject known to carry bindings
    MATCH (s:OntologyClass) WHERE s.uri = 'http://invincible-agent/cost#LotCostBreakdown'
    OPTIONAL MATCH (s)-[r:rendersAs]->(o)
    RETURN s.uri AS subject, count(r) AS rendersAs_edges, collect(DISTINCT o.uri) AS objects;
    # 4 — INSTRUMENT FLOOR: does the relationship type exist at all?
    CALL db.relationshipTypes() YIELD relationshipType
    WHERE toLower(relationshipType) CONTAINS 'render' RETURN relationshipType;

**Expect:** `SourceLedger` present, `StatefulSupportResponse` with **≥1** `rendersAs` edge — the
edge appears only once the binding **re-registers**, which a desktop page load does. Ask BOTH
spellings: this store has carried compact and canonical nodes for one concept, so a query for
one spelling returns a confident absent for a class present under the other. ⚠ **An absence
that prints nothing looks exactly like a query that did not execute** — my combined run printed
**no header at all** for the binding ask, which is why #2/#3 are the `count()` form.

## Tried and failed

1. **My mutation runner restored each case with `git checkout --`, which restores to HEAD.** The
   subject was an **uncommitted** edit, so the restore reported success and **silently deleted
   the very row under test** — the seal would have gone on passing against a row that was gone,
   and the tell was `git diff --stat` printing nothing where my own change should have been.
   **A restore must be the inverse of the MUTATION, not of the last commit:** capture the bytes
   before each case, write them back after, assert equality.
2. **A detector matched my own comment** — searching output for the bare token `KeyError` hit
   the comment I had just written explaining why that KeyError was replaced, so a clean mutation
   read as dirty for two runs. Match pytest's **rendered** form (`E       KeyError`), and
   positive-control the detector.

## Files placed in another lane's checkout

* **UNCOMMITTED: none** — the untracked `sessions/2026-09-19-payload-finance-*` in cortex-ui are
  lane 91's (M).
* **COMMITTED, the thing that must not repeat:** `f75e5df` in `../cortex-ui`, adding
  `sessions/2026-09-19-payload-from-32-np-meridian-brief.json` and `.md`; now on cortex-ui's
  **`master`, pushed to `origin/master`** (M at `92c195a`).

## Open questions

* Does master's tree agree with the lane's on the mirror seal? (I above, unmeasured.)
* Does the binding re-register on a page load alone, or need a roll? The architect says a page
  load does; **unverified by me.**

## NEXT TASK — three questions that never reached lane 32

From the architect's 2026-09-21 dispatch; lane 32 closed before answering any. Lane/74's now.

1. **Was `f75e5df`'s payload scrubbed BEFORE the commit?**
   `git -C ../cortex-ui show f75e5df | grep -c eyJ` must be **0** — **with a control string you
   know is present**, counted in the same breath, because a broken matcher returns zero and that
   reads as a finding. Known-present control: the literal `<SCRUBBED:` (the placeholder kept the
   FIELD and replaced only the VALUE). Report both numbers.
2. **Does the durable checkpointer persist the caller's bearer token from `identity`?** The live
   response carries a real JWT at `identity.authorization` (M 2026-09-19, rolled fleet).
   engine-lg's saver is Postgres (`checkpointing.saver: "postgres"`,
   `durable_across_restarts: true`, `stateful_graphs: ["fin_program_brief"]`). Read what the
   saver **wrote** for a brief run. **A stored token is a finding of a different size than an
   echoed one. READ-ONLY** — do not mutate checkpoint state.
3. **What is `artifact` meant to carry on a `finding` row, and does the graph hold it at the
   moment it writes the row? Give the file and the line.** What I hold — contract:
   `cortex-ui/.../ledger/SourceLedger.contract.ts`, `artifact: string | null`, *"The hop
   artifact, or null. PRESENT EVEN WHEN NULL on the wire — a refused verb HAS none."*
   Construction site, **read this call in full**: `graph_host/graphs/fin_program_brief.py:145`,
   `_row(fn, label, _disposition_for(payload, verdict), ...)`. The sibling that demonstrably
   finds one: `graphs/cost_lot_costing_review.py`, `payload.get("artifact_id") or
   payload.get("id")`. Symptom: the brief's three rows carry `artifact: null` on verbs that
   **ran and answered**, and the card prints "no evidence recorded for this source" three times
   (on screen, confirmed by cortex-60). **If the graph has it and drops it, that is a lane fix;
   if no artifact exists for an answered verb, SAY SO** — the contract then needs a third state
   and the architect will rule.

Blocked on Chris: the prime. Everything else above is runnable now.

Lane: ia-32/lane/32
