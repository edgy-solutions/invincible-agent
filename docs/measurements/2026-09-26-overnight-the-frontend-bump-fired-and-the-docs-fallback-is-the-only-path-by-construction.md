# Lane 1, 2026-09-26 — overnight: the frontend bump fired, and the docs fallback is the only path *by construction*

**Dispatch:** the overnight order to `ia-01/lane/01`, items 1–6. This report covers **1, 2, 3, 4**.
Item 5 was delivered in the previous window
(`2026-09-26-program-finance-cannot-seed-the-409-is-unconditional-and-there-are-two-gates-behind-it.md`).
Item 6 is armed separately and **not fired**, per order.

    repo   7da1f286 (+ this working tree)
    fleet  b5eeb408e5658530193b05e1b503d9ec03dbe95a
    helm   revision 151 -> 152 (frontend only)

---

## 1. Item 1 — the frontend digest bump: FIRED, verified by `imageID`, leg 11 green

### 1.1 ⚠ The order's digest was abbreviated, and a digest cannot be expanded the way a tag can

The order named `sha256:6e2fc31d…`. A short *tag* has a git object behind it to `rev-parse`; a short
*digest* has nothing in this repo to derive it from — `grep 6e2fc31d` over the whole tree returns
**zero hits**. So it was not typed out and it was not guessed. It was read from the producer's packet
in the sibling repo:

    cortex-ui/sessions/2026-09-26-packet-to-lane-1-digest-6e2fc31d-for-roll-3-and-the-producer-pin-moved.md:12
    sha256:6e2fc31db21f718b1aebc73d1cb5fcc2bc72361c0494c03512ce3e0093e3bbd0

and then **re-resolved here rather than copied on trust**. Recorded because the next order will
abbreviate too, and the answer is "read it from the producer's packet", never "complete the tail".

### 1.2 The instrument was positive-controlled before any of its answers were believed

A 404 from `imagetools inspect` means at least four different things (not built, not pullable, wrong
reference, typo). So the negative was fired first:

| measurement | result |
| --- | --- |
| ⊕ `frontend:092b0bab` — **abbreviated** tag | `not found` ✅ *the instrument discriminates* |
| forward: `frontend:092b0bab7eb…` (full 40) | `-> sha256:6e2fc31d…` ✅ both directions bound |
| reverse: `frontend@sha256:6e2fc31d…` | `application/vnd.oci.image.index.v1+json` ✅ |
| arch coverage | `linux/amd64` **and `linux/arm64`** ✅ the nodes are arm64 |
| control: superseded `sha256:28f752f2…` | **still resolves** — overtaken, not deleted |

Without the first row a `found` would have been an absence of evidence rather than evidence.

### 1.3 ⛔ `:latest` had ALREADY moved off the ordered digest, and the packet says otherwise

cortex-60's packet states "`:latest` resolves to this same digest". **True when written, false when
armed.** Measured here:

    :latest  ->  sha256:f3b363332fd21d70c6163e6dafd5e3a484a540fafa2d061a38a46daffcaecd75

A *third* image. Two more cortex-ui commits landed behind it (`c3a7ac44` fix(elicitation),
`15552d03` fix(picker)). This is the **third consecutive arming** at which a cortex-ui push moved
`:latest` off a digest the architect had already accepted — a property of the pipeline, not an
accident. It changes nothing about what this roll deployed, because the pin is *by digest*, which is
the entire reason the pin is a digest. It is written down because a stale claim about `:latest` is
pre-authenticated: measured once, reads as current, and only a re-measurement separates the two.

⚠ **Possibly relevant to tonight's routing, unverified:** `c3a7ac44` fix(elicitation) — *"a pick with
no question behind it locked the card and was never sent"* — may be cortex's half of the **lot 3
elicitation defect** the packet routed to "the NEXT digest". If so it is in `:latest` and **not** in
what was just deployed. Not verified here, because naming a fix from its commit subject is the same
"a name is not a measurement" defect this report opens with. Flagged for the next arming to settle by
reading the diff.

### 1.4 The gate: exactly ONE manifest line moved

`--set global.imageTag` was **deliberately omitted** — a frontend-only bump must not move the fleet.
Full-manifest diff, live release manifest (rev 151) against the dry-run, asserted mechanically rather
than eyeballed:

    removed: 1   image: …/cortex-ui/frontend@sha256:28f752f2…
    added:   1   image: …/cortex-ui/frontend@sha256:6e2fc31d…
    DATAHUB_TOKEN absent from the diff   <- the blanking this check exists to catch

The file's header explains why the check is the **manifest** and not the image lines: adding
`-f values-sandbox.yaml` would re-assert `DATAHUB_TOKEN: ""` over the live token, and an image-line
diff cannot see that. Nothing else in 5883 lines moved.

### 1.5 Fired, and verified by `imageID` — not by `.spec.image`

    helm upgrade … --reuse-values -f values-roll-frontend-digest.yaml --no-hooks --timeout 20m
    STATUS: deployed   REVISION: 152

    pod       iagent-cortex-ui-6fc8b76f56-lmjng   restarts=0  ready=true
    spec      …/frontend@sha256:6e2fc31db21f718b1aebc73d1cb5fcc2bc72361c0494c03512ce3e0093e3bbd0
    imageID   …/frontend@sha256:6e2fc31db21f718b1aebc73d1cb5fcc2bc72361c0494c03512ce3e0093e3bbd0

Old pod gone, one pod in the selector. `imageID` is the claim, because `.spec.image` only says what
was *asked for*.

**The before-side is worth one line:** unlike the previous two armings, this one's predecessor *was*
fired — the running `imageID` and the pinned digest agreed exactly at rev 151. The pin is being
honoured and there was no drift to unwind.

### 1.6 Leg 11 — 11a green, 11b CLEAN, and ⛔ 11b CANNOT FAIL ON THIS POD CLASS

> **Leg 11.** Every deployment reaches Ready, **and** the first 60 seconds of each pod's log carry no
> `Traceback`. CLEAN / TRACEBACK / EMPTY-UNDECIDED, undecided never folded into the pass, matcher
> controlled in the same run.

**11a — green.** All 32 deployments at `DESIRED == READY == UPDATED`. One row is not a pass and is
not folded in: `tika` is `DESIRED 0`, deliberately scaled to zero, and **this roll provably did not
touch it** — the one-line manifest diff is the proof, which is a stronger statement than re-reading
its status.

**11b — CLEAN, with both controls fired in the same run:**

    matcher='Traceback'   positive control=HIT   negative control=MISS
    window: 21 line(s), t0=2026-09-27T04:34:14.759Z, span=0.078s
    VERDICT: CLEAN

**⛔ And the green is nearly vacuous, which I would rather say than bank.** Two reasons:

1. **`Traceback` is a Python construct; `cortex-ui` is nginx serving a static bundle.** It cannot
   emit one. Leg 11b on this pod class is a guard that cannot fire — it verifies the container
   started, and nothing whatsoever about the application.
2. **The window is 78 milliseconds, not 60 seconds.** The pod writes its runtime config and goes
   quiet. 21 lines is not EMPTY-UNDECIDED, so the verdict stands as specified — but "no traceback in
   60s" over 78ms of nginx startup is a much weaker claim than the same words mean on an engine.

**A real frontend regression from this bump would appear as a JS error in a browser, which leg 11
does not and cannot reach.** Roll #3's report left 11b open across eighteen pods on a classifier
denial; that is still open and this does not close it — one narrow pod read is not that census.

**Scope, stated rather than silently narrowed:** 11b was run on the one pod this roll replaced. The
other 31 deployments' "first 60 seconds" belong to roll #3's fire, not this one; re-reading them
would be re-measuring a state this roll did not touch.

---

## 2. Item 2 — the docs pool fix, both halves, sealed

Built, sealed, mutation-proven. The failure chain and its nine links are in
`2026-09-26-docs-walk-no-compatible-verbs-is-not-registration-…md`; this section records only what
the fix is and what was measured about it.

### 2.1 Two independent halves, and each alone leaves the walk dead

| half | change | without it |
| --- | --- | --- |
| **A** — the fallback spans MESH | `cold_start_fallback_domains()` appends `MESH` to the caller's own domains | pool is the DOCS graph's one class, which is a response shape → `NO_COMPATIBLE_VERBS` |
| **B** — response shapes are never subjects | `FILTER NOT EXISTS { ?cls rdfs:subClassOf+ ?root }` over **two** roots, `mesh#Response` *and* `mesh#Archetype` | `mesh:DocPage` arrives but `docs:DocExplanation` is still offered as a subject |

**The loop this closes:** doc-tools *deliberately* excludes response shapes from the Weaviate index,
so the DOCS index being empty is by design. The defect was never the empty index — it was that the
**fallback applied a different rule than the index did**. B makes the fallback agree with the index;
A makes the agreed-on pool non-empty.

### 2.2 The load-bearing check that could have made the fix defeat itself

`mesh:DocPage` must survive the new filter, or B kills the very class A goes to fetch.
`setup/ontologies/mesh_system.ttl:739-742`: it carries the `rdfs:label` the query requires and is
`rdfs:subClassOf prov:Entity` — **not** under either shape root. Measured, not assumed. Had `DocPage`
been modelled under `mesh:Archetype`, this fix would have been a no-op with a green seal.

### 2.3 ⛔ MUTANT B SURVIVED, and the fix for that is in the engine, not the test

The implementer's seal called `_fallback_domains_like_resolve` — a **mirror** of three inline lines
in `/resolve`. Disabling production's `MESH` append left
`test_the_fallback_query_RUN_yields_DocPage_and_NO_response_shape` **GREEN**. The MESH half was
uncovered by construction: a mirror in a test asserts the mirror.

Fix: extracted `cold_start_fallback_domains()` as a **module-level function in the engine**, pointed
`/resolve` at it, and reduced the test's helper to a thin delegating wrapper. Mutant B then killed
two arms. The survival is recorded in the function's own docstring, where the next reader of that
function will hit it.

### 2.4 The seal that shipped the original defect, and why two arms were added

`test_response_shapes_are_not_groundable.py` was **declaration-only over the exclusion** — and a
declaration seal over a filter cannot distinguish a working exclusion from one that matches nothing.
That is precisely the shape that let this defect ship under a green. Added:

* a **behavioural** arm that RUNs the real wrapped query against a dataset shaped like the deployed
  graphs and asserts `DocPage` in, `DocExplanation` out, `KnowledgeDocument` out;
* an arm pinning the **single-graph** limitation (below).

### 2.5 A limitation found, measured, and pinned open rather than left latent

`execute_sparql` textually wraps the query in `GRAPH ?__mesh_g { … }`, and `GRAPH ?g` binds one graph
for its whole pattern. So `rdfs:subClassOf+` inside the wrap is **single-graph transitive and cannot
cross named graphs**. A crafted cross-graph shape leaks past the filter (probed, confirmed).

It is harmless today, and that is a **measurement, not a hope**: the whole 82-member response-shape
population is direct-to-root *within its own domain's file*. doc-tools has no such limit because it
computes over a merged graph. An arm now **passes while the leak exists** and instructs its own
deletion if someone closes it — so the gap cannot be re-derived as though it had been checked.

### 2.6 The gate records when it stands down

`_gate_excluded` now carries a disposition on both arms, so "the gate removed a candidate" and "the
gate would have emptied the pool so it kept one" stop being the same silence:

    if _productive and _unproductive:   disposal="removed"   reason="no_verb_in_scope"
    elif not _productive:               disposal="retained"  reason="no_verb_in_scope_but_pool_would_empty"

Consumers at `:2774 :2791 :2817 :2837 :2861`; `tests/routing/test_eligibility_trace.py:300` counts
those call sites and is unaffected.

### 2.7 ⛔ WHY THE COLD-START FALLBACK WAS THE ONLY PATH RUNNING POST-BACKFILL — as ordered

**Not "the index is empty."** The backfill (968 rows) and the prime (12 MESH classes *with vectors*)
both worked. The answer is in the filter, `ontology_service/main.py:~1189`:

```python
scope_domains = [d.upper() for d in domains if d]     # or [domain.upper()]
elif len(scope_domains) == 1:
    filters = wvc.query.Filter.by_property("domain").equal(scope_domains[0])
else:
    filters = wvc.query.Filter.by_property("domain").contains_any(scope_domains)
```

**`_weaviate_hybrid_search_sync` never adds MESH.** A DOCS caller's filter is therefore literally
`domain == "DOCS"` → 0 rows → cold start, **every time, deterministically**. The 12 primed MESH
classes are indexed, carry vectors, and are **structurally unreachable through the vector path for
every caller in the fleet** — not just DOCS.

So the honest statement about this fix: **it makes the docs walk answer, and it makes it answer via
the fallback permanently.** That is the risk the dispatch flagged ("the fallback fix ships while the
real path stays dead"), and it is real.

**The parallel Weaviate fix was NOT built, deliberately.** Adding MESH to `scope_domains` changes
recall *and ranking* for every domain in the fleet, including 13k MAINTENANCE rows, and the order
named the fallback. Reported, not built — with its blast radius, so the decision is available rather
than rediscovered.

---

## 3. Item 3 — the refusal menu producer half, sealed

### 3.1 The order named one function; the property had two

The dispatch named `_render_refusal_menu`. The property is "a producer that puts `options` on the
wire", and there were **two** — `_render_abstain_menu` has identical exposure and was absent from the
lot 3 report. Both now carry `**_reroute_fields(raw_data)`. A seal's subject is a population, not a
line number, so `test_every_option_bearing_producer_is_covered` **AST-derives** the population from
the module: a third producer reds on the count instead of quietly inheriting the defect.

> ⚠️ **Corrected 2026-09-27** (roll #5). That last sentence was false when written, and this is the
> harder home to find because it was written in the same act as §3.2 — fixing one reads as handling
> the class. The third producer **already existed** (`_project_flat_archetype`, the one that serves
> production) and the arm was **green over it**: the derivation keys on a dict literal carrying an
> `"options"` key, and a table-driven producer reading `_FLAT_ARCHETYPES` never spells that shape.
> Derived-not-listed is not the same as complete — a derivation still hard-codes a code *shape*.
> Repaired 2026-09-27: two shapes, a *checkable* forwarder excuse, third producer covered, 5/5
> mutants killed by their named arms.

### 3.2 `sub_query` is on the WRAPPER; `accepted_slots` is not on the WRAPPER

> ⚠️ **Corrected 2026-09-27** (roll #5 — `2026-09-27-roll-5-fired-revision-153-…`, §5.1). The
> heading here read *"not on the wire at all"*. That was wrong in scope, not in measurement: what
> was measured was the **wrapper**, and `accepted_slots` **is** on the wire, one level down, inside
> `expert_response` — `src/iagent_pure/slot_disposition.py:634` emits
> `"accepted_slots": dict(accepted or {})` on **every** ask. The live ELICITATION cards carry it,
> because `_project_flat_archetype` reads the envelope and not the wrapper. A `{}` from :634 is the
> *informed* report that nothing was bound yet; §3.3's forbidden `{}` is the *uninformed* default
> from a producer that cannot know. The rule is about a producer's knowledge, not about the value.

Measured: `/render_ui`'s two callers (`gateway.py`'s `_results` wrapper, `dynamic_supervisor.py`'s
POST body) both send `sub_query`; **neither sends `accepted_slots` in the wrapper**. The accepted
set exists in `direct_dispatch` only as a Dagster materialization.

### 3.3 ⛔ The seal DELIBERATELY does not require `accepted_slots` present-and-empty

A seal demanding the key would be satisfied by `accepted_slots: {}` — and `{}` is not a weaker
version of the right answer, it is a **false** one. `answer_ask` computes:

    Reroute(BIND, {**accepted, slot: value})

With `accepted == {}` that re-routes having **silently dropped every slot the first turn bound** —
manufacturing the exact failure the field exists to prevent, with no error anywhere. So
`_reroute_fields` omits rather than defaults (`_wrapper_field` returns `None`, not `""`, so callers
can tell "absent from the wire" from "empty on the wire"), and there are three arms:

| arm | what it holds down |
| --- | --- |
| `…carries_sub_query` | unconditional, both producers |
| `…carried_WHEN_the_wire_has_it` | the conditional half, for the day a caller sends it |
| `…is_ABSENT_rather_than_EMPTY…` | **forbids the easy fix** |
| `…PINNED_to_the_wrapper_that_feeds_it` | reds when the wire gap closes, naming the arms to delete |

### 3.4 Two defects in my own instrument, both fixed, both recorded

**`pytest.importorskip` produced `1 skipped`, exit 5.** A skipped seal asserts nothing — the exact
shape of guard this suite exists to refuse. Replaced with a stub whose failure **ERRORS loudly**.

**⛔ And the stub then poisoned two sibling files — a sample read as a population.** The stub was
installed at **module level**, i.e. during *collection*. pytest imports every test module before
running any test, so `test_response_shapes_are_not_groundable.py` and the cold-start file both died
at import with `'baml_client' is not a package`. **Each of the three files passed ALONE; the trio
failed together.**

`tests/conftest.py`'s `_restore_globally_stubbed_modules` exists for exactly this class — and could
not help, because it is `scope="module"` and its snapshot is taken *after* collection. Fixed by
importing **lazily, from inside the tests**, which puts the mutation back inside that fixture's
window, plus `__path__ = []` so this stub is not the sixth instance of the bare-ModuleType shape the
conftest names. Verified in **both collection orders**: 18 passed, 18 passed.

---

## 4. Item 4 — three fires on both finance rows: `classify_called` is True, and there is no reason code

**The premise does not reproduce at this sha.** Both rows PASS, 3/3, byte-identical:

    WALK CENSUS  repo=7da1f286  fleet=b5eeb40
      PASS  finance-variance-drivers     PROGRAM_FINANCE_ANALYST
      PASS  finance-performance-indices  PROGRAM_FINANCE_ANALYST
      2 pass, 0 fail, 0 blocked

Because a PASS says the card *drew* and not that the classifier *ran* — the docs walk resolved at
0.99 off a one-member enum — the routing fields were harvested from the `/orchestrate` stream
directly, 3 fires per row, 6 total:

| field | value, all 6 fires |
| --- | --- |
| `classify_called` | **`True`** (on `route_decision`) |
| `route_status` | `matched` |
| `fallback` | `False` |
| **`reason_code`** | **NOT PRESENT ANYWHERE IN THE STREAM** |
| `reason` | `no_verb_in_scope`, plus a live-view prose string |

**Both answers to the order, plainly:**

* **`classify_called` is `True`**, deterministically, on every fire of both rows. This is not the
  docs-walk shape.
* **There is no `reason_code` field** under that name anywhere in the stream. The stream carries
  `reason`. On a PASS there is no refusal to code, so the question has no value to report — which is
  itself the answer.

`reason: no_verb_in_scope` appears **on `route_decision`, which is also where the gate's `excluded`
entries live** — i.e. it is consistent with candidates being correctly removed for having no verb,
not with the route's own verdict, which is `matched` / `fallback=False`.

### 4.1 ⛔ My probe read a neighbour, and I am not reporting it as a finding

The probe recorded `archetype = KNOWLEDGE_DOCUMENT` on `final_payload`, while the census rows expect
`CONTRIBUTION_RANKING` and `MULTI_SERIES`. That looks like a contradiction and **is not one**: the
judge scores each **component's** `archetype` (`src/iagent_pure/walk_census.py:463-468`), not the
wrapper's top-level field. My harvest also skipped `expect_verb` entirely because it only collected
scalar values and the verbs arrive as a list.

So the census is the better instrument here on both fields, it checks **both** `expect_verb` and
`expect_archetype`, and it passes. `KNOWLEDGE_DOCUMENT` is my probe reading the wrong field — it is
**not** evidence of a defect and must not be quoted as one.

Also worth recording: the census's own `_fire` comments that without `frontend_id` "the fleet
correctly refuses a live view (`live_view_requires_registration`) and every archetype assertion
scores a default menu the walk sheet never describes" — and the live-view prose string in my `reason`
harvest is that same refusal shape. A probe that does not match the sheet's caller produces correct
refusals indistinguishable from regressions.

---

## 5. What I did not verify

* **That the deployed frontend behaves correctly.** Leg 11 cannot see a browser-side error, and no
  UI walk was run. Ready + zero restarts + the right `imageID` is the whole claim.
* **Whether `c3a7ac44` fix(elicitation) is the lot 3 defect's cortex half.** Named from its commit
  subject only; not read as a diff. §1.3.
* **Leg 11b across the fleet.** Still open from roll #3's classifier denial. One pod is not that
  census.
* **That the docs fix works on the cluster.** ⚠ Nothing has been rolled — the fleet is still
  `b5eeb408`. **A docs census fired now still exercises the OLD code, and a still-red result must not
  be read as the fix failing.** It rides roll #4.
* **The cross-graph exclusion leak beyond today's population.** §2.5: measured for the current 82
  shapes, pinned as an arm, not closed.
