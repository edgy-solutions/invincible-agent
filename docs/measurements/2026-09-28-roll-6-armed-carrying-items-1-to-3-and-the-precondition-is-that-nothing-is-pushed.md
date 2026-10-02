# Lane 1, 2026-09-28 — roll #6 ARMED carrying items 1–3, and the open precondition is that NOTHING IS PUSHED

**Lane:** `invincible-agent/master` · **Item:** overnight dispatch 5 · **Status:** ARMED, **NOT FIRED**

The dispatch reads: *"Arm roll #6 with 1–3, fleet sha beside the payload, fleet-wide spec-vs-running
as leg 11a. Fire."* This arms it and records the one precondition that blocks the fire, which is not
a cluster fact at all.

---

## 0. The label is CHECKED, not assumed

Roll #5's arming document had to carry a section saying the order's "#4" had already fired, so the
label is the thing most likely to be wrong. Read rather than inferred:

| what | reading |
| --- | --- |
| helm release `iagent` | **revision 153, deployed**, chart `invincible-agent-0.4.10` |
| roll #5 | fired at **revision 153** (`6cd4c14a`) |

So #6 is the correct label and the next fire is **revision 154**.

---

## 1. The payload, with the fleet sha beside it

**Every `invincible-agent/*` workload currently specs and runs `55dc8614119b7bc5702f82aa5eeea8b40d6c5492`** —
roll #5's sha. That is the "fleet sha beside the payload" the dispatch asked for, and it is uniform:
**19** workloads, one sha, no drift.

⛔ **This said 18 when armed, and the re-read before the fire counted 19.** The uniformity claim
survives — every one of them is on the same sha — but the population figure did not, and I cannot now
say whether I miscounted at arming or a workload arrived in between. **An anchor count detects
population surprises, not only patch failures**, which is the whole reason to write the number down
rather than the word "all": had I written only "all", nothing would have disagreed with anything and
this line would not exist. The figure is corrected, not reconciled, and the difference is stated.

| item | engine(s) | change | commit |
| --- | --- | --- | --- |
| **1** | **engine-o** (`ontology_service`), **engine-f** (`presentation_agent`) | the docs defects: the seal arm's derivation repaired from a dict-literal key to all producers, table-driven included; the "not on the wire today" claim narrowed to the wrapper | `fadda10f` |
| **3** | **engine-o** (`ontology_service`) | MESH in `scope_domains` for the vector path | `fadda10f` |
| **2** | **cortex-bff** (`src/iagent/gateway.py`, `src/iagent_pure/lineage_claim.py`) | the lineage split: a prose turn naming a drawn artifact keeps its lineage and does **not** get the pre-resolved route | `d3944da8` |
| **4** | **none — tests only** | the stub harness. It changes `tests/` and `docs/` and **nothing the cluster runs** | `f17df904` |

**Item 4 is in the dispatch but not in the payload, and that is stated rather than left to be
inferred.** A tests-only item listed beside three deployable ones reads as deployed. It is not: no
file it touches is inside any image.

### ⛔ Item 2 moves TWO workloads, not one

`iagent-projector` runs the **cortex-bff image**, read from its own deployment spec rather than from
the chart's naming:

```
iagent-cortex-bff   invincible-agent/cortex-bff:55dc8614…
iagent-projector    invincible-agent/cortex-bff:55dc8614…
```

So item 2's gateway change lands on the projector too. Nothing in the item's name says so, and a
verification that reads only `iagent-cortex-bff` would call the roll landed while half of its blast
radius went unread.

### The new module reaches the image, and that is proven by the running fleet

Item 2 adds a **new** module, `src/iagent_pure/lineage_claim.py`, and a new file is the case where a
per-file `COPY` silently omits the payload. Three readings, not one:

1. `build-containers.yml` builds cortex-bff with `path: .`, so `Dockerfile.agent`'s
   `COPY ${AGENT_DIR}/ /app/` copies the whole repo, `src/` included.
2. `.dockerignore` excludes caches, venvs and `dist/` — **not** `src/`.
3. Decisively: `gateway.py` already imports `iagent_pure.primary_selection`,
   `iagent_pure.slot_acceptance` and `iagent_pure.acceptance_request`, and the deployed cortex-bff
   serves those paths today. **The import route is proven by the running system, not by my reading
   of the Dockerfile** — `lineage_claim` is one more module in a package that already arrives.

---

## 2a. THE PRECONDITION IS CLOSED — Chris pushed, and the payload is READ OUT OF THE REGISTRY

**Payload sha: `ec055c49da24cdbc39950a126321183c6974b668`** — `git rev-parse origin/master`, derived,
never typed. It is the pushed **tip**, which is the docs commit that armed this roll; the items' code
is in its ancestors. The tag therefore names a **tree**, not a change, and that is what
`build-containers.yml` tags (`:${{ github.sha }}`, line 162).

| gate | reading |
| --- | --- |
| commits on the remote | `git ls-remote origin refs/heads/master` → `ec055c49…` — the **remote**, not the local tracking ref |
| build | run `36429168118`, **success**, 12m36s, `headSha` = `ec055c49…` read from the run, not from its title |
| **registry** | `docker manifest inspect` resolves `ontology-service`, `presentation-agent`, `cortex-bff` at `ec055c49…` |
| helm release | `iagent` **revision 153, deployed** — so this fire is **154** |
| nodes | all 7 Ready, **worker6 included** (it pins the keycloak/weaviate/minio/restate PVs and blocks every upgrade at hook weight 2) |

### The registry read needed a positive control, and it earned one

My first attempt was `gh api .../packages/container/.../versions`, which returned **0 matches for the
payload — and 0 for roll #5's sha too**. The control is the only reason that did not get written down
as "the image is missing": the token carries `gist, read:org, repo, workflow` and **not
`read:packages`**, so the 403 was about my credentials. A payload-only query would have produced a
confident false negative, and the fix would have been to re-run a build that was already fine.

**The payload is a new image, not a re-tag.** All four manifest digests differ from roll #5's for each
of the three services — disjoint sets, no overlap. Worth checking because a re-tag would deploy
cleanly, report success, and carry none of items 1–3.

## 2b. What the precondition WAS, and why it was a decision rather than a step

This is not a registry problem or a build failure. It is upstream of both.

| reading | value |
| --- | --- |
| `git status -sb` | `master...origin/master` **[ahead 3]** |
| the three unpushed commits | `fadda10f` (items 1, 3), `d3944da8` (item 2), `f17df904` (item 4) |
| what builds an image | `.github/workflows/build-containers.yml`, `on: push: branches: [master, main]` |

**So the payload sha has no image, and cannot have one until the commits are pushed.** Both halves
are read rather than assumed: the trigger comes from the workflow file, the ahead-count from git.

**This roll therefore has no target sha yet.** Roll #5 could name `55dc8614` at arming because the
commit existed on the remote and only the *image* was pending. Here the commit itself is local, so
there is nothing to name — and a roll armed against a sha that does not exist on the remote is an
arm whose gate cannot be evaluated by anyone but me.

### Why this is a decision and not a step

Pushing three commits from local `master` to `origin/master` **is** the gated merge, performed
unilaterally. `AGENTS.md:133` makes merging to master the gated action and **names no merger**.
Recent `origin/master` history contains both shapes — explicit `Merge lane/NN into master` commits
*and* direct linear commits (`7da1f286`, `d4a00598`, `55dc8614`, and roll #5's three doc commits) —
so practice does not settle it either way.

The alternative is to replay the three onto `lane/01` and let the merge happen through the gate,
which is what `ia-01` ↔ `lane/01` exists for. **These commits were made directly on `master` in the
shared master tree by this window and the two before it**, which is itself the thing to flag: the
work is already on the branch the gate protects, just not pushed.

**Left for Chris. Not routed around, and not pushed on my own authority.** — and that is how it was
resolved: he authorized it, then pushed it himself. Recorded because the gate held rather than
because it was convenient.

---

## 3. The command — and ⛔ THE BARE COMMAND I FIRST WROTE HERE WOULD HAVE UNPINNED THE FLEET

```bash
scripts/upgrade-sandbox.sh --set global.imageTag="$(git rev-parse origin/master)"
```

**What this section said until I read the script: `scripts/upgrade-sandbox.sh` on its own, plus a
line saying a one-off `--set` must *not* be used here. Both halves were wrong, and the second was
wrong in a way that argued for the first.**

Read rather than summarised:

| reading | line |
| --- | --- |
| the script **never sets `global.imageTag`** — it only *validates* one if `"$@"` carries it | `upgrade-sandbox.sh:157-175` |
| it deliberately does **not** use `--reuse-values`; "every render is computed from the files as they are now" | `upgrade-sandbox.sh:19-22` |
| `values-sandbox.yaml` pins the engines to **`:latest`** | `values-sandbox.yaml:229` |
| the script's own refusal message spells the correct form | `upgrade-sandbox.sh:171` |

So the two facts compose into the opposite of what I wrote. Because no values file carries a sha and
nothing is reused from the previous release, **the payload sha can only arrive through `--set`** —
and firing the bare command would have rendered all 18 engines as `:latest`, discarding the explicit
sha pins that roll #5 put there and that section 4 measures.

### Why it would have looked like it worked

`build-containers.yml` tags `:latest` *beside* `:<git-sha>` on master (`build-containers.yml:162-165`),
so `:latest` currently resolves to the payload sha itself. The bare command would have **landed
items 1–3 correctly** and left the fleet unpinned — succeeding for a reason that has nothing to do
with being right, which is the only reason this defect is worth a section instead of a line:

1. **Leg 11a would go unreadable.** It compares spec against running. A spec of `:latest` against a
   running digest is not a match or a mismatch, and section 4 already records that an unreadable
   reading invites being treated as a matching one — I wrote that about the two digest workloads and
   then armed a command that would have done it to the other sixteen.
2. **`pullPolicy: Always` makes it persist.** `values-sandbox.yaml:23-24` sets Always precisely so a
   pod restart picks up a new `:latest`. Unpinned plus Always means any later restart silently moves
   an engine to whatever CI built most recently, with no chart change and no commit.

### ⛔ And the reason I gave was invented downstream

"`--reuse-values` makes a one-off permanent" is a true sentence about helm and **false about this
script**, which says at lines 19-22 that it does not use the flag. I reached for a rule I had
recorded, it fit the shape of the situation, and it produced a confident instruction to omit the one
argument the fire actually needs. The rule was right; I never checked that its premise held here.
**A justification invented downstream fits by construction** — and this one did not merely decorate
a correct command, it argued for a wrong one.

The sha is **derived, never typed** (`$(git rev-parse origin/master)`). The script refuses an
unresolvable tag because that exact discipline failed twice in one day in its author's hands, with
the first seven characters real both times.

---

## 4. Leg 11a — fleet-wide spec-vs-running, and its baseline is CLEAN

The dispatch adds leg 11a: compare what every workload **specs** against what it **runs**, fleet
wide, rather than reading one engine's image line.

```bash
# context comes from the operator's kubeconfig and is deliberately not recorded here
kubectl -n sandbox get deploy -o custom-columns='NAME:.metadata.name,IMAGE:.spec.template.spec.containers[0].image'
kubectl -n sandbox get pods  -o custom-columns='POD:.metadata.name,READY:.status.containerStatuses[0].ready,IMAGE:.status.containerStatuses[0].image'
```

**Baseline, RE-READ immediately before the fire: no drift anywhere.** All **19** `invincible-agent/*`
workloads spec `55dc8614…`, run `55dc8614…`, and report `Ready=true`. Saved to
`scratchpad/leg11a_pre.txt` so the after-reading compares against captured identities rather than
against my memory of this paragraph.

The arming baseline said 18. Re-reading rather than reusing it is what turned that into a visible
correction instead of a silent one — the reason gate item 3 exists.

**That clean baseline is what makes leg 11a able to say anything.** A leg that first runs *after* a
roll cannot distinguish drift the roll caused from drift that was already there — the reading would
be a claim about the fleet's whole history rather than about this fire. Recording it before the fire
is the control.

Two workloads run by **digest** rather than tag — `iagent-cortex-ui` and `iagent-central-gateway` —
and neither is in this payload. A spec-vs-running check that expects a tag everywhere would report
those two as unreadable and invite the reader to treat "unreadable" as "matching".

---

## 5. The gate before firing

1. The three commits are on `origin/master` **and** `build-containers.yml` has completed for that
   sha. A green build job is the producer's claim about the registry, not a read of it — roll #5
   already paid for that distinction, so the image is confirmed by reading the registry.
2. The payload sha is written into this document, replacing "does not exist yet".
3. Leg 11a re-read immediately before the fire, not reused from this arming — the baseline above is
   hours old by then, and the fleet is shared.

---

## 6. What I did **not** verify

- **Whether any of items 1–3 actually work on the cluster.** They are green in the suite; nothing
  here measures deployed behaviour. Item 3's "after" half — recall across MAINTENANCE, three fires
  before and after — is gated on this fire precisely because it needs the fix running.
- **Whether the chart at `invincible-agent-0.4.10` needs any change for this payload.** No item
  touches `helm/`, so I assumed none is needed. Assumed, not read.
- **The docs census and the HAZ-1003 row**, which the dispatch puts *after* the fire. Not run.
- **Whether `iagent-projector` exercises the changed gateway path at all.** I established that it
  runs the same image; I did not establish that it reaches `lineage_claim`. Sharing an image is not
  sharing a code path, and the blast radius I widened above is an upper bound, not a measurement.
