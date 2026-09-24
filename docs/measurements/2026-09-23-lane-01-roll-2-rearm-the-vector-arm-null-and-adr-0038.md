# Lane 1, 2026-09-23 — roll #2 re-armed twice, the vector arm changes everything but the answer, and ADR-0038 measured

**Seat:** `ia-01/lane/01` on `invincible-agent/master`. **Order:** the architect's consolidated
OPENING ORDER, plus the mid-session supersession of the frontend digest.
**Nothing was fired.** Every cluster read below is read-only; the roll is armed and waiting on Chris.

> Kube contexts, node addresses and the Langfuse credentials seen while measuring are deliberately
> absent from this file — they belong in the out-of-repo handoff log. The Langfuse keys are named
> here only by the Secret that holds them (`iagent-secrets`), never by value.

---

## 1. Roll #2 — the arming sha, and the digest that moved under it

The frontend digest was re-armed **twice today**. Both armings are recorded, because the first one
is the control that makes the second one a measurement rather than a copy.

| | digest | state |
|---|---|---|
| running on the cluster | `sha256:c8d6553f…` (cortex-ui `8a13dd6`) | what pod `iagent-cortex-ui-5c7c784464-7g5xl` reports, re-measured at both armings |
| first arming | `sha256:38cda6c8…` (tag `ea060f3…`) | **armed and never fired** — superseded before Chris said go, so it deployed nothing and there is no intermediate state to unwind |
| current arming | `sha256:28f752f2…` (tag `a6950b2500b369456680b23f29db7189524bf4c0`) | armed at `6484717`, chart `0.4.8` |

So the frontend line of this roll is **one step, `c8d6553f` -> `28f752f2`**, not two.

### The tag is the full 40-character sha, and the short form fails *ambiguously*

The order carried the tag as `a6950b25`. That tag does not exist:

    imagetools inspect …/cortex-ui/frontend:a6950b25   ->   not found

A 404 there is indistinguishable from **"not built yet"** and from **"no anonymous pull access"** —
three different states, one message. The same trap as the abbreviated *digest* in the previous
order. Both were resolved against the registry rather than completed by hand.

### Verified in this seat, both directions

cortex-60's packet asserts all of these; they were re-run here rather than quoted, because two
independent readings of a digest are worth more than one relayed one.

* `…/frontend@sha256:28f752f2…` resolves as an OCI image index
  (`application/vnd.oci.image.index.v1+json`), with **linux/arm64 beside linux/amd64** — the nodes
  are arm64.
* **tag -> digest**: the full tag resolves to exactly `sha256:28f752f2…`. A digest that merely
  *exists* is not the digest that tag ships, and only this direction rules that out.
* **control, in the same breath**: the superseded `sha256:38cda6c8…` **still resolves**. Nothing was
  deleted; it was overtaken. An absence assertion here would have been wrong.
* `:latest` now resolves to `28f752f2`.

### `:latest` moving off an accepted digest is a pipeline property, not an accident

This is the **second** time a cortex-ui push has moved `:latest` off a digest the architect had
already accepted (cortex-60 reports the same shape at `4c0375b`/`8a13dd6`). The previous version of
the pin's comment predicted exactly this and it happened within the day. The pin is **by digest**,
so `:latest` cannot change what the roll deploys — which is the whole reason the pin is a digest and
not a tag.

**What changed between the two digests is cortex-60's measurement, not mine, and is marked as
theirs:** six commits, of which the only two touching `src/` are comment-only, and `sessions/`-only
commits do not reach the image. Digests differ regardless — build metadata and layer timestamps
guarantee that — so **a differing digest is not evidence of a differing application.** The roll's
gate does not depend on this either way, because the pin is exact.

---

## 2. "17 images" and "19 images" are both right — different populations

The order says 17; the build matrix declares 19. Neither is stale:

* **19 built**: the `build-containers.yml` matrix.
* **17 deployed**: what this chart actually renders. `langgraph-support` and `swarms-scraper` are
  **built but not deployed** by the chart at this tag.

Derived by asking the rendered manifest for each matrix service, not by reading either list. A
census of one population answering for the other is how a correct number becomes a wrong one.

---

## 3. The full-manifest diff — the leg that earns its name

Rendered dry-run vs the live manifest at the arming sha `6484717`, **5883 lines each**, **280 changed
lines**. Every changed line was normalised and tallied — enumerated, not sampled — and falls in
exactly four categories:

| lines | category | what |
|---|---|---|
| 236 | chart label | `helm.sh/chart: invincible-agent-0.4.6` -> `-0.4.8` (118 before/after pairs) |
| 40 | engine images | `…/invincible-agent/<svc>:c0005142…` -> `:6484717…`, across **17 deployed services** (`dagster-server` and `cortex-bff` carry two occurrences each) |
| 2 | frontend | `…/cortex-ui/frontend@sha256:c8d6553f…` -> `@sha256:28f752f2…` |
| 2 | `IAGENT_IMAGE_TAG` | `"c0005142…"` -> `"6484717…"` |
| 2 | `checksum/broker-code` | the annotation hash |

The set difference outside those four categories is **empty**. The chart goes `0.4.6` -> `0.4.8`,
skipping `0.4.7`, because that arming was never fired either — the live release is still chart
`0.4.6` at image tag `c0005142…`, which is roll #1's state.

**`DATAHUB_TOKEN` stays populated and no other key drifts** — which is the entire reason this check
is the manifest and not the image lines. The scoped one-key overlay
(`values-roll-frontend-digest.yaml`, verified to carry exactly `cortexUi.image.digest` and nothing
else) is what keeps it that way; passing the whole `values-sandbox.yaml` would blank the token.

---

## 4. Sibling digests re-read — converged, and that has a shelf life

Three siblings are pinned to `:latest` with `imagePullPolicy: Always`, so a roll re-pulls whatever
`:latest` means **at fire time**. This leg was run **twice, ~40 minutes apart**, and the second
reading is why it is a gate leg and not a formality.

| image | first read | re-read at arming | running pod | verdict |
|---|---|---|---|---|
| `dag-tools/central-gateway:latest` | `c05e0131…` | `c05e0131…` | `c05e0131…` | converged |
| `dag-tools/user-deployment:latest` | `70092098…` | `70092098…` | `70092098…` | converged (2 pods) |
| **`pub-tools:latest`** | `ed93f7b1…` | **`1555b341…`** | **`ed93f7b1…`** | ⚠️ **MOVED** |

### ⚠️ `pub-tools:latest` moved during the arming window

Between the two readings — inside this one session — `pub-tools:latest` moved from `ed93f7b1` to
`1555b341`. Both `pub-tools` workloads (`iagent-pub-tools`, `iagent-pub-tools-broker`) are still
running `ed93f7b1`, and both carry `imagePullPolicy: Always`.

**So firing the roll as armed would silently replace `pub-tools` on both pods** — a component the
architect's order lists as **held**. The roll's own diff cannot show this: the manifest line is the
unchanged string `pub-tools:latest` in both the live and dry-run renders. **A full-manifest diff is
blind to a floating tag by construction** — the text is identical; only the *referent* moved. That
is precisely the gap this leg exists to cover, and it caught one on its second firing.

Control, in the same breath: `ed93f7b1` **still resolves**, so it moved rather than being deleted,
and pinning it is available as a remedy. Two shapes, the architect's call:

* **pin it** by digest in the same scoped-overlay pattern the frontend uses, making the roll's
  effect on `pub-tools` exactly nothing; or
* **accept the re-pull** deliberately, recording `ed93f7b1 -> 1555b341` as part of this roll rather
  than discovering it afterwards.

What this lane will not do is fire a roll whose effect on a held component is unstated. Note also
that doc-tools rolled earlier today (helm rev 12, image `0279d83`), which is the likeliest source of
the push that moved the tag — stated as a lead, not a measurement; the tag's movement is measured,
its cause is not.

**Re-read all three immediately before firing regardless of what this table says.** A converged
reading taken 40 minutes earlier is a stale claim wearing a gate's authority — demonstrated here
rather than argued.

---

## 5. Item 3 — the vector arm changes the ranking on every row and the answer on none

### a. Predicate three-bucket census, fire #3

Byte-identical to fires 1 and 2: **89 reachable / 44 legacy / 0 no-vector**, and the 44 failing rows
are the **same 44 uuids** — compared by identity, not by count, after a first attempt matched all 133
uuids instead of the failing block. The three-fires ruling is satisfied.

### b. bm25 vs hybrid on the 89 reachable rows

Instrument: `scripts/bm25_vs_hybrid_arm.py`, mirroring `mesh_vectors.py` (same ADR-0009 domain
branch, same handle, same limit) with **three** arms — `bm25`, `hybrid`, and `near_vector` as a
control, so that "hybrid equals bm25" cannot silently mean "the vector leg never ran".

| measure | result |
|---|---|
| ranking changed by the vector arm | **89 / 89 rows** |
| candidate set changed | 88 / 89 |
| **top-1 winner changed** | **0 / 89** |

So the vector arm reorders the tail of every result and **never changes the answer**.

### c. The discriminator for `finance-variance-drivers` PASS -> FAIL

On the regressing phrase — *"which account is driving the overrun on NP-MERIDIAN"*, scoped to
`PROGRAM_FINANCE` — **all three arms rank `finVarianceDrivers` first, across three fires.**

**The vector arm is therefore not the cause of that regression at the retrieval step.** Retrieval
hands the right predicate to whatever runs next, so the defect is downstream of retrieval — which
is where the run log already points (`verb […] lacks 'fin_variance_drivers'`). eo's larger question
is answered too: the vector leg contributes nothing decisive **even where the index can reach the
rows**.

### Two defects of my own instrument, found before it published a number

Recorded because both would have *reported as findings*:

* `_arm()` passed a bookkeeping key into the client call. Every arm would have raised, every row
  counted unreachable, and the comparison run over an **empty population** — which prints as "no
  arm changes the ranking", a null indistinguishable from the measured one.
* A first version read each row's vector slot and reported the 44 census failures as `named=44`,
  contradicting the census's `legacy=44`. The cause is the client, not the store: the v4 client
  surfaces any vector under the key `default`. The census's REST read is the authority; the script
  now asserts presence only, rather than publishing a weaker second figure that would age into a
  contradiction.

---

## 6. ADR-0038 stage "helper + env on Langfuse v2" — measured, not read off the ADR

The order calls this stage 1; the ADR's rollout calls it **item 2** (item 1 is the ADR itself).
Reported by content to avoid arguing about the number.

| stage component | measured state |
|---|---|
| `set_trace_standard` helper | **DONE.** Exported by the leaf, imported at `baml_shared/telemetry.py:31`, called at the real boundary (`agent_fleet/restate_analyst/main.py:1386`) |
| `provenance-telemetry` leaf | **DONE.** `==0.1.0` pinned in 7 `pyproject.toml`s + root; **installed** in the master venv *and* in the running engine-o pod |
| re-export shim + removal marker | **DONE.** The marker names its condition (all three repos importing the leaf directly) |
| shape-schema refuses an unknown slot | **DONE and sealed.** Exercised both directions with a positive control: a valid slot accepted, an unknown slot and a bad score encoding each `ValidationError` |
| mesh truth-check reddens on a mapped-but-nonexistent field | **DONE and sealed.** `tests/test_telemetry.py::test_mesh_mapping_truth_check`, **mutation-proven in both directions** (dangling field -> red; produced-but-unmapped field -> red), and it *ran* rather than skipped |
| `LANGFUSE_RELEASE` + environment wired per-deployment | **PARTIAL — see below** |
| fail-soft proven (Langfuse down -> work still starts, the miss is **counted**) | **NOT SEALED — see below** |

### The env leg: one of three inputs is wired

`build_trace_values` sources three fields from the deploy environment. Measured in two running pods,
with a wired variable as the control that the read works:

| field | source | in-pod |
|---|---|---|
| `environment` | `DEPLOY_ENV` | **`sandbox`** — wired |
| `build_sha` | `LANGFUSE_RELEASE` | **UNSET** |
| `chart_version` | `CHART_VERSION`, or a caller argument | **UNSET**, and the production boundary call passes no `chart_version` argument either |

`LANGFUSE_RELEASE` appears **zero times** in the chart templates and zero times in the rendered
manifest. The mapping declares `release: build_sha` with the comment *"CI-baked LANGFUSE_RELEASE"* —
so **the `release` slot is declared, sealed, and fed nothing.** Both seals above are honest: they
check that the mapping's names match the code's names, which they do. Neither can see that an input
is absent — a mapping can be perfectly truthful about a field that is always `None`.

The keys that *do* reach pods (`LANGFUSE_HOST`, and the public/secret pair from `iagent-secrets` via
`envFrom`) are present in all the engine pods checked, so `LANGFUSE_ENABLED` is **true** in the
fleet. Coverage is **symmetric**: parsed as YAML, all **21** containers carrying an `envFrom` take
both the ConfigMap and the Secret — **zero asymmetric containers**, so there is no workload silently
running without the keys.

> That symmetry took two instruments to establish, and the first one lied. A
> `grep -A6 'envFrom:' | grep name:` tally reported **21 configMapRef against 20 secretRef**, which I
> started writing up as an odd-one-out worth naming. The gap was entirely the fixed `-A6` window
> clipping one block's second `name:`. A context window is a sample; the object graph is the
> population. Re-derived by loading the manifest as YAML and walking containers, where the asymmetric
> set is empty — and the lesson is that the count which *invited* a finding is exactly the one to
> re-derive before publishing it.

> A manifest read alone would have got this wrong. The rendered manifest names
> `LANGFUSE_PUBLIC_KEY` exactly once (in the Secret), which I first read as "no deployment
> references it" — i.e. telemetry off fleet-wide. The in-pod read refuted that: `envFrom: secretRef`
> carries it. The env read in the pod is the authority; the manifest count was the wrong instrument.

### Why fail-soft is not sealed

Four tests cover the **disabled** configuration (no keys) — the one configuration in which emission
**cannot fail, because nothing is attempted**. That is presence, not resilience. There is no test
where the keys are set and the host is unreachable, and `emit_misses()` is referenced nowhere in
this repo's code or tests — only in `docs/plans/silence-closure-arc.md:97`, which says the quiet part
itself: **"Fail-soft is honest only when it is countable."**

Worse, the two failure modes are **indistinguishable from outside**. The shim's leaf-import guard is
`except Exception:` -> silent no-ops; `_LEAF_AVAILABLE` is never logged, counted, or exported. So a
service whose venv lacks the leaf emits nothing and looks exactly like a service whose Langfuse is
down — and both look like a healthy service on a quiet day.

---

## 7. The exact command, and the gate ledger

**Armed at `6484717b9648d21064898a1ab8d4f3a585368029`, chart `0.4.8`. NOT FIRED — Chris says go.**

```bash
helm --kube-context <ctx> upgrade iagent helm/invincible-agent -n sandbox \
  --reuse-values \
  -f helm/invincible-agent/values-roll-frontend-digest.yaml \
  --set global.imageTag=6484717b9648d21064898a1ab8d4f3a585368029 \
  --no-hooks
```

This is byte-for-byte the command that was dry-run, minus `--dry-run`. The context is in the
out-of-repo log. `--reuse-values` is why the overlay must be passed with `-f`, and why the overlay
carries exactly one key.

| leg | result |
|---|---|
| CI: `Release Helm Charts` at the arming sha | **green** |
| CI: `Build & Push Container Images` at the arming sha | **green** |
| 19 built images resolve with `arm64` | **19/19**, 4 platform entries each (amd64, arm64, 2 attestations) |
| bogus-sha negative control | **19/19 correctly MISSING, 0 control failures** — the instrument can report absence |
| `--dry-run` renders | **green**, 5883 lines against a 5883-line live manifest |
| full-manifest diff | **green** — 280 lines, all four categories, nothing outside them, `DATAHUB_TOKEN` intact |
| sibling digests re-read | ⚠️ **`pub-tools:latest` MOVED** (§4) — needs a ruling before firing |

**Every leg is green except the sibling re-read, and that one is a decision rather than a failure**
(§4): the roll as armed would silently re-pull `pub-tools` on two pods. Pin it or accept it — but
firing without choosing means the roll changes a held component by accident.

The chart bump is a gate leg in its own right, learned the hard way today: an earlier `helm/**`
commit without a `Chart.yaml` bump **failed `Release Helm Charts`**, and an unbumped chart publishes
nothing *while reporting green* on the other workflow. `invincible-agent-0.4.8` was confirmed free
before use, with `0.4.3`–`0.4.7` listed as the control that the tag query can see tags at all.

---

## 8. Two things the next hand needs to know

* **Item 5's suite has not been run at head.** The run in hand measured `60b512e`, and head is now
  `6484717`. It must be re-run, once, alone. It also **mutates a tracked file** (`docs/BOARD.md`) —
  diff the tree after the run and do not stage that on a green.
* **cortex-60's packet is not in this repo's inbox.** It is in the **cortex-ui** repo's `sessions/`
  (held unpushed there, because a `sessions/`-only push would build another image and move `:latest`
  again — the exact fault the packet reports). The inbox derivation reads only this tree, so a packet
  that lives in a sibling repo is invisible to it. Found by searching the sibling repo after this
  tree's search came back empty — with a positive control proving the empty result was real.
