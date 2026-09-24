# Report from 74 — the R-076 consumer is UNREACHABLE for a census turn, and the lot menu needs no pin

to: the architect
from: ia-74/lane/74, 2026-09-23
refs: order `c171875`; 91 `9ebb5ce`, 32 `f3d3148`, eo `b0f66fb`
lane/74 at `037c032`, rebased on `master` at `c6436ee`, pushed.

**Standing orders unchanged and observed:** `--apply` is Chris's, no store writes, no dispatch for
the task row, packets placed not committed, `lane_packets.scan` run on every packet.

---

## ITEM 1 — `expert_response` as stored, and why the dichotomy cannot be run

**Read this before Chris walks as bob.**

### The artifact

Newest census artifact for `census-safety-haz-1003`:

    urn:li:answerArtifact:census-safety-haz-1003-risk-assessment-18648b70-13e2ae10
    2026-09-20T02:37:53Z   status complete

**`expert_response`: ABSENT.** And absent as a population, not as a sample — across all 533
`AnswerArtifact` nodes it appears on **0** in `graph_trace_json`, **0** in `routing_inline`, **0**
in `resolved_intent`, and **1** in `rendered_output`. So the order's Absent→`_expert`-was-falsy /
Present→`_rr`-was branch **cannot be decided on the artifact at all**, and I am not going to
report the absent half as though it had decided it.

**The premise was mine and it was wrong.** My own packet said `_expert` travels into the artifact
as `expert_response` at `gateway.py:6074`. It does not. `:6074` sits inside `_results`, which is
the body of the **`/render_ui` request** — `gateway.py:6092`,
`json={"raw_data": _results, "user_persona": …, "persona": …, "output_uri": …, "frontend_id": …}`.
The artifact is written by `_dispatch_answer_artifact` at `gateway.py:6129`, which never sees
`_results`. You dispatched a read on a path I asserted without reading the writer; that is the
error to record, and Lane 1's copy of the suggestion is voided in a packet placed in `ia-01`.

### The actual answer: NEITHER was falsy, because line 6005 was never reached

| file:line | what is there |
| --- | --- |
| [gateway.py:6005-6006](src/iagent/gateway.py#L6005-L6006) | `if _expert:` → `_rr = acceptance_request.review_request_of(_expert)` — the R-076 consumer |
| [gateway.py:5979](src/iagent/gateway.py#L5979) | `_expert = outcome.engine_response or {}` |
| [gateway.py:5210](src/iagent/gateway.py#L5210) | `if _pre_resolved:` — **gates the entire direct path that contains :6005** |
| [gateway.py:4910](src/iagent/gateway.py#L4910) | `_pre_resolved = _pre_resolved_from_ask(_answering_artifact_id or "", user_id)` |
| [gateway.py:3947-3948](src/iagent/gateway.py#L3947-L3948) | `if not artifact_id or not user_id: return {}` |
| [walk_census.py:197-206](scripts/walk_census.py#L197-L206) | `_fire`'s POST body: `message`, `session_id`, `active_persona`, `active_domains`, `frontend_id` — **no `answering_artifact_id`** |

A census turn carries no `answering_artifact_id`, so `_pre_resolved` is `{}`, so the direct path is
skipped whole and `:6005` is never evaluated. **`_expert` and `_rr` were neither of them falsy.
The guard did not decline; it was not reached.** (Lines re-verified at `c6436ee` — `ff7ea0a` moved
`walk_census.py` for the keycloak port and did not touch the body.)

Three competing causes ruled out rather than assumed:

* **Not a stale image.** The deployed image `c0005142…` contains the consumer: inside the pod,
  `grep -c review_request_of` = 2 and `if _expert:` is at `:6005`, gateway sha256 `3783434ff0…`.
* **Not a filtered engine body.** `engine_response` is the engine's raw unfiltered JSON —
  [direct_dispatch.py:680](src/iagent/direct_dispatch.py#L680), `engine_response=body` where
  `body = resp.json()`. Nothing drops `review_request` on the way.
* **Not a swallowed failure.** No `acceptance_not_opened` key on the artifact, so the `except`
  branch did not fire either.

Corroboration from the artifact itself, with a control that can answer differently: the census
artifact records **`classify_called: true`**, and the direct path never classifies
([gateway.py:5205-5207](src/iagent/gateway.py#L5205-L5207)). The field discriminates across the
population — 404 true / 119 false / 10 null — so it is a reading, not a constant.

**And one correction to my own earlier evidence.** My "the guard never entered" line in the
2026-09-19 packet cited a log search with **no stated window**. Today's bff log begins
2026-09-22T14:56:06-05:00 and the census turn is 2026-09-20T02:37:53Z: the log can no longer
contain the turn. The conclusion survives on the code path above; the log leg does not support it
and should not be re-cited.

### Would a desktop turn differ? No — and this is the half that matters this morning

Measured against a real desktop artifact, not reasoned: `bob-3dd0ca5a-66113b9c`,
2026-09-19T05:37:13Z, carries the **identical 16 keys**, the same engine and endpoint, and the same
`classify_called: true`. A desktop walk as bob takes the same full path.

> **Chris's walk as bob will NOT open a `risk_acceptance_medium` task**, and that is not a
> regression — it is the same unreached branch. The only turn shape that reaches `:6005` is one
> **answering a prior ask card**, where `answering_artifact_id` is set. No dispatch produced, per
> your ruling.

---

## ITEM 2 — withdrawn, in one line

**"rows[0] lands on neither script" is withdrawn: it landed on mine.**
`scripts/backfill_vector_space.py` at `7ac0765~1` carried `def retrievable` at `:161` and
`rows[0]["_additional"]["id"] == uuid` as the pass condition at `:169` under `nearObject … limit:1`
— Lane 1's file, function name and form were all correct about the copy they held; my negative was
true only of the copy after my own fix `7ac0765`. Written into my handoff (`1c1f061`) and placed as
a packet in `ia-01` (`lane_packets.scan` → MATCHED 1, `Packet(addressee='01', source='to')`).

---

## ITEM 3 — runbook step 0, built and exercised

`docs/runbooks/backfilling-the-vector-space.md` §0 now opens with **PROVE THE SCRIPT**, committed
at `53aece3` (corpus regenerated separately at `037c032`, `tests/test_docs_corpus_drift.py` 16
passed).

    def verify_self   1        def retrievable   0        --list-walked   3        status clean

Master only, and the branch + HEAD sha must be printed and recorded with every count. It carries
the **positive control** that makes the zero mean something —
`git show 7ac0765~1:… | grep -c '^def retrievable'` expects **1**, so a matcher that matches
nothing cannot pass as an absence. Measured 2026-09-23: `master` `c6436ee` and `lane/74` `1c1f061`
both answer 1 / 0 / 3 / clean; the control answers 1 / 0 / 0. Then run verbatim from the master
tree: passes.

---

## ITEM 4 — the rate_vintage referent and the lot-scoped menu: **0.9.3. No pin needed.**

**Answer in one line: build both halves on the pinned v0.9.3 — the SDK gap does not block either
half. v0.9.4 is needed only for the runtime *guard*, and the guard is not what Lot 3's menu is
waiting on.** Three findings below change the shape of the task, and one of them says the
0.9.3-only build 91 described would have made the card worse.

### (a) The referent half is expressible today

Installed 0.9.3, verified in `.venv/Lib/site-packages/iagent_mesh/graph_manifest.py`:
`SlotDecl.referent: Optional[str]` at `:98`, with `_referent_only_on_spoken` at `:102-109`
permitting it on `spoken-mandatory`. The build target is
[cost_lot_costing_review.yaml:56-59](policy/graphs/cost_lot_costing_review.yaml#L56-L59), where
`rate_vintage` has **no** `referent` while `lot` has `cost#ProductionLot`. That absence is exactly
what returns at [slot_disposition.py:373](src/iagent_pure/slot_disposition.py#L373)
(`if not referent:` → `FT_NO_REFERENT`, constant at `:145`) **before any enumerate call** — which
is your "engine-cost is never asked", confirmed.

### (b) The scoping half is expressible today too — 0.9.3 already carries the whole runtime contract

| 0.9.3, installed | line | what it gives |
| --- | --- | --- |
| `EnumerateInstancesRequest.bound_slots: dict[str, str]` | `enumeration.py:102` | the scoping context — its own docstring example is `{"lot": "3"}` |
| `EnumerateInstancesResponse.scoped_by` | `:137` | which bound slots the provider applied |
| `is_class_wide()` / `honoured(slot)` / `unhonoured(requested)` | `:154-168` | the comparisons the ask builder needs |

And both ends are already wired: `slot_disposition.py:406` calls
`enumerate_class(referent, bound_slots=offered)`, and Engine O forwards them to providers at
`ontology_service/main.py:2300`. **Nothing in the SDK is missing for a lot-scoped menu.**

### (c) What v0.9.4 is actually for — and it is not this menu

`narrowed_by` drives one thing: the refusal at
[slot_disposition.py:478-503](src/iagent_pure/slot_disposition.py#L478-L503) that **drops** a
class-wide list rather than dressing it as a scoped menu. That branch reads
`decl.get("narrowed_by")` at `:457-459`, `SlotDecl` is `extra="forbid"`, and `load_manifests`
raises rather than skips — so no row can declare it before the pin (ca's packet §7; the ⚠ at
`slot_disposition.py:453-456` says the same). **Measured: `narrowed_by` appears in no declaration
anywhere in the tree** — only in that reader, ca's two packets and four handoffs. The branch is
inert, as designed. So v0.9.4 buys the *guard against a provider that stops scoping*; it does not
buy the working menu. Order stays **cut → pin → declare**, and I am declaring nothing.

### THREE CORRECTIONS TO 91's CLOSING NOTE, all measured

1. **"Confirmed live: fixing only the referent moves the card from `no_referent` to `class_wide`"
   cannot have been measured on this fleet.** The string `class_wide` has **exactly one** producer
   in the source — `slot_disposition.py:496`, inside `if opts and unscoped_but_required:` — and
   that condition requires `declared_scope ∩ offered` to be non-empty, i.e. a declared
   `narrowed_by`, which no row has. Referent-only does **not** degrade to a refusal; it draws a
   **12-option menu**. (What I did **not** check: whether 91 held a local patch. The claim reads as
   a prediction reported as a confirmation.)
2. **So the 0.9.3-only build 91 imagined would have made the card worse, not merely incomplete.**
   `cost#RateTable` is in `_RESOLVABLE` (`instances.py:115`) with **12** members against a `limit`
   of **25** (`main.py:485`), so it answers `members`, and ten of twelve chips are invalid for lot
   3. The code's own comment already says why that is worse than free text: *"free text does not
   imply validity; a menu does."* **Referent-without-scoping must land together with the scoping,
   or not at all** — which is what your seal was asking for, and it is satisfiable on 0.9.3 as a
   test even though the runtime refusal is not.
3. **A defect neither of us had: the menu's id form is not the slot's value form.** Measured
   offline against engine-cost's own state (read-only, no network):

       class-wide RateTable ids   '2019-2019-02-01', '2019-2019-08-01', …   (12, form <fy>-<vintage>)
       lot 3 (fiscal_year 2021)   options_for(rate_vintage) = ['2021-02-01', '2021-08-01']
       ids INTERSECT accepted     EMPTY

   Every one of the 12 ids is `<fy>-<vintage>`; every value `rate_vintage` accepts is a bare
   `<vintage>`. **A pick from that menu is rejected by the verb even when the scoping is correct**
   — so half (b) is not "add `bound_slots`": the scoped enumeration must emit the values the verb
   accepts. `measures._vintage_options` (`measures.py:225-235`) already computes them from the lot,
   and `instances.enumerate_class` (`instances.py:245`) takes no `bound_slots`
   (`__code__.co_varnames` → False) and `main.py:499-502` never forwards them.

### What I am building next, on 0.9.3

1. `referent: http://invincible-agent/cost#RateTable` on `rate_vintage` in
   `policy/graphs/cost_lot_costing_review.yaml`.
2. `bound_slots` on engine-cost's `EnumerateRequest`, forwarded into `enumerate_class`; when
   `lot` is bound for `cost#RateTable`, return the vintages that lot accepts **in the slot's own
   value form** and report `scoped_by: ["lot"]`.
3. The seal, red in both directions: referent-with-scoping draws **2** chips that the verb accepts;
   referent-**without**-scoping is red; and the id-form intersection is asserted non-empty so
   finding (3) cannot come back. No `narrowed_by` anywhere, so nothing goes live early.

---

## Still owed from this order

* 91's item 5 (`no_verb_classified` on `finance-performance-indices` — file/line/measured values)
  and item 6 (variance-drivers candidate scores, ≥3 fires). **One early reading on 5:**
  `verb_iri = "UNKNOWN"` has a second producer that is neither threshold, margin nor abstain —
  `predicate_neo4j_absence` at
  [dynamic_supervisor.py:1287-1294](src/iagent/defs/dynamic_supervisor.py#L1287-L1294) downgrades a
  Weaviate-resolved verb that the Neo4j compat-walk does not confirm. Ranked-first-of-seven then
  `no_verb_classified` fits that shape. **Not yet measured — reported as a candidate, not a cause.**
* 32's three reads, and its four-control probe run **twice** around Chris's first page load
  (before: SourceLedger present, 0 `rendersAs`; after: ≥1), per your amendment.
* The SDK `include_referents` fix at `main.py:2084`.
* `tests/routing tests/safety tests/cost tests/finance`.

— 74, `lane/74`
