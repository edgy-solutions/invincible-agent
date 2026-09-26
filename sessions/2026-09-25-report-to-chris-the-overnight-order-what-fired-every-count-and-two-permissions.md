---
to: Chris
from: ia-01/lane/01
re: the overnight order — steps 1–5
---

# Morning report — what fired, every count, what's red

**Headline.** Step 1 **fired and verified**. Step 2 was already green and is **re-verified, not
re-put**. Step 3 is **blocked on a permission, and nothing was deleted**. Step 4 is **step 0 green,
the rest gated** by step 1's one red. Step 5 is running last, on a clean committed tree.

**Two things need you, and only you.** Both are named precisely in §6. Neither was worked around.

---

## 1. What fired

`helm upgrade` at `03ee440dc4118fd78ec8a789fd6c2d83815bf974`, chart `0.4.10`:
**rc=0, revision 148, status `deployed`.** Fired `2026-09-26T02:36:27Z`.

Verified two ways, both after the fact:

| check | result |
|---|---|
| post-deploy manifest vs the gated render | **byte-identical** but for the 1 line already partitioned as an extraction artefact |
| frontend digest, read from `imageID` (running bytes) not `.spec` | requested == running == `sha256:28f752f2111b760c…` |
| `/version.json` | `cortex-ui`, `git_sha a6950b25…`, built `2026-09-24T02:25:27Z` |

The manifest coming back identical retroactively validates that partition entry rather than
excusing it. The digest is read from `imageID` on purpose: `.spec` says what was *asked for*.

## 2. Every count

**The gate — 9 legs + 2 controls, all green.**

| | |
|---|---|
| CI `Build & Push Container Images` @ arming sha | success, run `36090025176` |
| CI `Release Helm Charts` @ arming sha | did not run, **correctly** — 0 files under `helm/` |
| ⤶ its positive control (`ca23e9e`, 4 helm files) | ran, succeeded, published `0.4.10` |
| built images resolving with `linux/arm64` | **19 / 19** |
| ⤶ bogus-sha negative control | **19 / 19 correctly MISSING**, 0 control failures |
| byte-equality, on-disk sha256 == git blob sha256, under `helm/` | **43 tracked, 0 mismatched** |
| CR bytes in the raw render | **0** (was 2342 before normalisation) |
| `--dry-run` | rc=0, empty stderr, 335877 bytes |
| full-manifest diff | **289 lines, partitioned to 0 unaccounted** |
| sibling digests re-read immediately before firing | **4 / 4** arm64; bogus-digest control → `manifest unknown` |
| nodes | **7 / 7 Ready** |

**The 289-line diff, every line in exactly one bucket:** `IAGENT_IMAGE_TAG` 2 · engine `image:`
lines 38 (19 occurrences × 2) · `helm.sh/chart` `0.4.6`→`0.4.10` 236 (118 × 2, uniform) ·
cross-repo `:latest`→`@sha256:` 12 · extraction boundary 1 · **unaccounted 0**. Symmetry: 19 engine
occurrences live, 19 new — every one moves, none appears or disappears.

**Populations:** 19 built, 17 deployed. `langgraph-support` and `swarms-scraper` are built and not
rendered. `dagster-server` and `cortex-bff` carry 2 occurrences each, which is why 17 services give
19 lines.

**Step 2, the ontology prime (already sealed, re-verified not re-put):** `mesh#` OntologyClass in
Neo4j **75** · Weaviate `OntologyClass` domain=MESH **14** of **26240** all-domains, negative
control `NO_SUCH_DOMAIN` **0** · classes carrying `universal_referent` fleet-wide **1**, TRUE **1**
(`mesh#Thing`) · `mesh:DocPage` instances in Jena **9**, all nine named, negative control **0** ·
named graph `DOCS` **81** triples, `MESH` **333** · file-side independent witness: **75** `owl:Class`
in `mesh_system.ttl`, **75** distinct subjects, control **0**.

**Step 3, the checkpoint tables — these are *current* counts, because the delete never ran:**

| table | rows | disposition |
|---|---|---|
| `public.checkpoints` | **30** | to clear |
| `public.checkpoint_blobs` | **41** | to clear |
| `public.checkpoint_writes` | **66** | to clear |
| `public.checkpoint_migrations` | **10** | **KEEP** — and it is the positive control |

**Step 4, step 0 — the script proved in this tree at `03ee440d`:** `verify_self` **1** ·
`retrievable` **0** · `--list-walked` **3** · `git status --porcelain` empty. The runbook's positive
control discriminates: at `7ac0765~1` the same patterns answer **1 / 0**, inverted — so the zero is
a real absence, not a broken matcher.

**Fleet:** **41 of 43 pods ready.**

## 3. What's red

**The Dagster control plane is down.** `iagent-dagster-daemon` and the new
`iagent-dagster-webserver` pod, both CrashLoopBackOff, 6 restarts, both on
`dagster-server:03ee440…`. The old webserver replica on `dagster-server:c0005142…` still serves,
so the old image is a live control.

```
sqlalchemy/dialects/postgresql/psycopg.py:497 in import_dbapi
  import psycopg
ModuleNotFoundError: No module named 'psycopg'
```

**It is not a code change and not a bad gate leg. It is an unpinned image.**

| package | old, works | new, crashes |
|---|---|---|
| `dagster` / `dagster-postgres` | 1.13.23 / 0.29.23 | 1.13.24 / 0.29.24 |
| `psycopg2-binary` | 2.9.13 | **2.9.13 — unchanged, still present** |
| `SQLAlchemy` | **2.0.54** | **2.1.0** |

`psycopg2-binary` is in **both**, so nothing was dropped — the obvious story is wrong. SQLAlchemy
2.1 changed which DBAPI a bare `postgresql://` URL resolves to, psycopg2 → psycopg3. The frame
naming `dialects/postgresql/psycopg.py` is what makes that measured rather than plausible.
`Dockerfile.dagster-server` and `build-containers.yml` are **byte-identical** between the two shas.

**The finding worth keeping:** the Dockerfile stays unpinned on a comment saying it "MUST match" the
user-code image, "which doesn't pin dagster". **It does.** User code builds `uv sync --locked`,
pinned at dagster **1.12.20**. The unpinning never produced a match — the *working* pair was already
a minor apart — so that comment is a stale justification that reads as a considered decision because
it explains itself, and it has been turning every rebuild into a dice roll. Generally: **an image
does not belong to a sha when its dependencies are unpinned.** Same Dockerfile, same commit, two
builds, two artefacts.

**And why nine green legs missed it:** every leg asked whether the right *bytes* would deploy. **Not
one started a container.** A cheap eleventh leg closes most of it — import-check each moved image,
or require the previous roll's pods to reach Ready before calling the next arm green.

## 4. What's blocked, and what I refused to do about it

**Step 3, the purge.** You authorized it in writing; the auto-mode classifier refused the `DELETE`
as `[Cloud Storage Mass Delete]`. The transaction never ran. **I did not split the delete into
smaller batches to get under the classifier** — that is routing around the denial's intent, not a
safer method. Same distinction that kept `scripts/upgrade-sandbox.sh` out of the fire earlier:
it would have deployed, but it bakes in every values file and runs hooks, making it a *larger*
action, not a safer road to the same one.

Two things were established before the attempt and survive the block:

- **the premise** — `iagent-engine-lg` runs `graph-host:03ee440…` and is ready, so the writer
  carrying `identity_scrub.py` is live and a cleared table will not refill with tokens;
- **the scope** — the four tables exist in exactly **one** database (`iagent.public`); `postgres`
  and `datahub` hold none. This matters because a purge verified in the wrong database returns 0
  for the wrong reason, and `checkpoint_migrations` holding at 10 is what tells "the three are
  empty" apart from "I am querying nothing".

Counts only were read. **No blob contents were selected** — the standing refusal to reproduce the
stored bearer tokens stands, and I did not route around it.

**Step 4, the backfill.** Step 0 is green. The rest is gated by the runbook's own stop condition —
*"Is a roll in progress? If yes, stop"*, tested by listing pods that are not `1/1` — which prints
the two crashlooping dagster pods. So §3 is step 4's precondition, not a side quest. The backfill
itself needs no Dagster: it pipes `scripts/backfill_vector_space.py` into the cortex-bff pod.

**Remedies for §3 that I did *not* fire:**

1. **Surgical, no rebuild** — pin the two components back through the chart's own documented escape
   hatch (`values.yaml:16`, "a hotfix under test"). Precedence read rather than assumed:
   `$tag := .tag | default (global.imageTag …)`, so a component tag **wins**, leaving the other 17
   images at `03ee440`. `--set dagster.webserver.image.tag=c0005142… --set dagster.daemon.image.tag=c0005142…`
2. **Durable** — add `psycopg[binary]`, or pin `sqlalchemy<2.1`, or best, pin the ecosystem to what
   `uv.lock` resolves, which is what the comment was trying to achieve. Needs a CI rebuild, a new
   sha, and a second fleet roll.
3. **`helm rollback` — wrong.** Named so nobody reaches for it: it would undo `graph_host`'s JWT
   fix, which is live and is precisely what step 3's purge depends on.

(1) is another `helm upgrade`, not covered by the authorization you gave for *this* arm; (2) moves
the fleet off the sha you named. So both stop here.

**Side effect you should know about:** with the daemon down, **`ontology_sensor` cannot fire, and
neither can any schedule or sensor in the fleet.** That makes step 2's re-put hazard inert for now.
It is a reason to fix §3 before anything expects Dagster to act — not a reason to relax the
no-re-put rule, which holds the moment the daemon returns.

## 5. Step 5

Run last, once, alone, on a clean committed tree, after re-measuring memory — reported separately
when it finishes. The reboot precondition is met (LastBoot `2026-09-24T22:31:30`, previously 08/28
with 27.4 days' uptime).

## 6. What I need from you

1. **Permission for the purge `DELETE`** on `public.checkpoints`, `public.checkpoint_blobs`,
   `public.checkpoint_writes` in `iagent` — 137 rows, `checkpoint_migrations` untouched. Everything
   else is ready; verification and its control are written.
2. **A decision on the Dagster fix**, remedy 1 or 2 above. 1 restores the control plane in one
   command and unblocks step 4 tonight; 2 is the real fix and costs a rebuild plus a second roll.
   My recommendation is **1 now, 2 as the next roll's payload**, because remedy 2's own value is
   mostly in removing the unpinned `pip install`, and that deserves its own gate rather than being
   rushed behind a broken control plane.

## 7. Not mine, left alone

Four untracked inbound `2026-09-23…`/`2026-09-24-packet-from-ca-*` packets are still in the tree.
They are not this seat's and were not committed.
