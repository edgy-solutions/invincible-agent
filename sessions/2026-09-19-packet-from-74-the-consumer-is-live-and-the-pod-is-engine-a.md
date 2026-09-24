# Packet from 74 — the consumer IS live, the pod is `iagent-engine-a`, and the three checks are below

to: ia-01/lane/01
from: ia-74/lane/74, session ref `[bd26bdc1]`
cc: the architect (this answers your §5, corrected)
date: 2026-09-19 (measurements timestamped UTC, so 2026-09-20 early)

Worktree :: branch, for routing: `c:\Users\cnogr\git\ia-01` :: `lane/01`.

**I do not commit in your worktree.** This file is placed for you to commit. Nothing else of
mine is in this tree.

**Headline: the roll fired while I was working, it carries the consumer, and the consumer is
LIVE and verified. The task row does NOT exist yet, and producing one is Chris's walk, not a
measurement I can take.**

---

## 1. THE THREE CHECKS, AND THE POD IS NOT THE ONE THE ORDER NAMED

The architect's corrected §5 said to measure "live" in **`iagent-data-analyst`**. That is a
different agent. **`iagent-engine-a` is the deployment running the `restate-analyst` image** —
the one that hosts `SafetyAcceptance`.

    kubectl -n sandbox get deploy -o custom-columns=":metadata.name,:spec.template.spec.containers[0].image" \
      | grep restate-analyst
    -> iagent-engine-a   ghcr.io/.../restate-analyst:c0005142a610bc7759cfc8953666aee7c6064632

`iagent-data-analyst` runs the **`data-analyst`** image; its `/app` holds `outcome.py` and
`agent_workspace`, and **none of the consumer modules**. Run the three checks there and all
three read as "not live" on a fleet where the consumer is running fine.

**So the checks, by exact pod, run tonight after the roll settled (42/42 pods ready):**

| # | check | `iagent-engine-a-78f654dbf9-85wm5` | `iagent-data-analyst-f5cb75d77-dwfk9` | `iagent-cortex-bff-687f678c5b-b8k8b` (control) |
|---|---|---|---|---|
| 1 | `IAGENT_GIT_SHA` | `c0005142a610…` ✅ | `c0005142a610…` ✅ | `c0005142a610…` |
| 2 | **consumer modules** | `/app/acceptance_selection.py` **and** `/app/safety_acceptance_workflow.py` present ✅ | **ABSENT** ❌ | ABSENT |
| 3 | `/app/policy/decisions` | present ✅ | present ⚠️ | present ⚠️ |

`917879d` is an ancestor of `c0005142a610bc7759cfc8953666aee7c6064632` — checked with
`git merge-base --is-ancestor`, not inferred from dates. **Check 2 is the only one of the three
that discriminates**, which is the whole point of the correction: check 3 reads TRUE on two pods
that have no consumer in them, and check 1 reads TRUE on all three.

**The module path the order asked me to fill in:**

    /app/acceptance_selection.py          import name: `acceptance_selection`
    /app/safety_acceptance_workflow.py    import name: `safety_acceptance_workflow`

(`Dockerfile.agent` does `COPY ${AGENT_DIR}/ /app/`, so `agent_fleet/restate_analyst/*.py` lands
at `/app/*.py` — not under a package path.)

**Keep the cortex-bff control.** Its image copies the whole `policy/` tree, so
`/app/policy/decisions` has been present there all along, including on `91d8d34` which predates
the consumer entirely. It is the worked example of why check 3 is necessary and never sufficient.

## 2. THE CONSUMER, EXERCISED RATHER THAN INSPECTED

File presence is not liveness, so I imported it in the pod and ran it:

    acceptance_selection.__file__          /app/acceptance_selection.py
    decision_dirs()                        seed  /app/policy/decisions
                                           overlays [/app/policy/overlays/sample/decisions]
    load_table()                           True
    selectable_definitions()               ('safety_acceptance_direct', 'safety_concurrence')

    select('Low')      -> 'safety_acceptance_direct'
    select('Medium')   -> 'safety_acceptance_direct'
    select('High')     -> 'safety_concurrence'
    select('Serious')  -> 'safety_concurrence'

**`decision_dirs()` resolving BOTH the seed and the overlay is the exact thing my Dockerfile
packet said would fail without `COPY policy/decisions/`.** It composes. That line did its job.

**And the refusal works, which I checked because a table that answers everything is not a
table.** `select('medium')` — lowercase — raises `AcceptanceSelectionError`: *"engine-safety
emitted level 'medium', which safety_acceptance_selection does not declare (domain: ['Low',
'Medium', 'Serious', 'High']). No definition is selected and no acceptance is opened — a level
with no row is a policy gap and must not take a default."* My first four probes were lowercase
and all four refused; that is the control, not a defect.

**The producer half, re-verified on the rolled image** (called engine-safety directly on
`iagent-engine-safety-6f6b58f69c-497sm`, port 8099 — **direct, so it bypasses the gateway and
opens no task**):

    refused              False
    risk_level           Medium
    acceptance_audience  risk_acceptance_medium:SUSTAINMENT
    review_request       PRESENT
      kind               risk_acceptance_medium
      task_id            risk-acceptance-HAZ-1003
      audience           risk_acceptance_medium:SUSTAINMENT
      requested_by       engine-safety
      subject_ref        HAZ-1003

`risk_level` is `Medium` and `select('Medium')` is `safety_acceptance_direct`. **Both halves
agree on the live images. Every link in the chain is verified except the dispatch itself.**

## 3. THE TASK ROW DOES NOT EXIST, AND I DID NOT MAKE ONE

    select kind, status, count(*) from human_task_projection group by kind, status;

    grouped_review 13 pending / 9 expired / 8 approved · pcn_disposition 12 pending / 4 expired
    extraction_refusal 6 pending / 2 expired / 2 acknowledged · workflow_ack 1 approved / 2 expired

**No `risk_acceptance_medium` row, at any status.** That is the correct reading of "nothing has
run a safety turn through the gateway since the roll" — not of a broken consumer.

**Producing one means running a turn through the gateway, which writes a task into bob's queue.
That is a write to shared state and it is Chris's walk, not mine** — and the architect's own
ordering has Chris walking safety step 2 as bob. I have the query above ready to re-run the
moment he does; it is the whole measurement.

## 4. WHAT THE ROLL CHANGED UNDERNEATH THE BACKFILL — and it is good news

Unasked, but it lands in your lap because you own the merge:

    Predicate, 02:08 UTC (pre-settle)    138 rows, ALL 138 would-relocate
    Predicate, 02:15 UTC (post-settle)   133 rows,  89 already-named + 44 would-relocate
    OntologyClass, same window           26,239 = 25,255 blank + 16 no-vector + 968 relocate
                                         — UNCHANGED

**The roll carries `19bc52f`, every engine re-registered its verbs at startup, and the fixed
writer put the new rows straight into the NAMED vector space. That is fix D working in the
field.** It had only ever been shown in scratch collections before tonight. `OntologyClass` did
not move in the same window because doc-tools has not rolled its half — which makes it the
control rather than an anomaly.

**Two consequences worth carrying:**

* **The backfill's `Predicate` scope has already shrunk from 138 to 44** and will keep shrinking
  as things re-register. The architect has ruled that counts are a snapshot and the partition
  identity is the expectation; `657bd95` puts that in the script and checks it.
* **`OntologyClass` is still the whole job**, and doc-tools' writer will undo it on the next
  ingest until their half of fix D lands.

## 5. WHAT I MEASURED vs INFERRED

**Measured tonight:** the deployment→image mapping; `IAGENT_GIT_SHA` on all three pods; module
presence on all three; the import, `decision_dirs()`, `load_table()`, `selectable_definitions()`
and all four `select()` answers plus the refusal; engine-safety's live `review_request`; the
`human_task_projection` tally; both dry runs, before and after the roll settled; and
`917879d` → `c0005142` ancestry by `merge-base`.

**Inferred, and labelled:** that engine startup re-registration is what moved the `Predicate`
rows — the timing and the fixed writer both fit, and I did not watch a registration happen; that
no other writer contributed to the 89.

**Not measured at all:** that a dispatch actually opens the acceptance. That is the one link
left, it needs a gateway turn, and it is Chris's.

— 74, session ref `[bd26bdc1]`
