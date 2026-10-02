# Lane 1, 2026-09-26 — roll #4: the corrected arm fired, revision 151, and the pin is retired

**Status: FIRED, GREEN, and the purpose roll #3 could not deliver is delivered.** Both
`dagster-server` deployments are now at `b5eeb408`, the tag pin is gone from the release, exactly
two pods moved, and the specific failure `b95ce005` was authored to fix is checked by its own name.

This closes
`docs/measurements/2026-09-26-roll-3-fired-revision-150-and-the-dagster-server-tag-is-pinned-past-global-imagetag.md`.

## 1. Two corrections to the arm as that report wrote it, both found before firing

**(a) The `--set` pair became a tracked values file.** Per the ruling that *a component override
that must expire goes in a tracked values file with the reason and the sha that retires it, never a
bare `--set`, so the next reader of `helm get values` isn't guessing* — and per R-034, which
`values-roll-frontend-digest.yaml` already records as "never a bare `--set` for the pin". The file is
`helm/invincible-agent/values-retire-dagster-server-pin.yaml`: two keys, and the reason, the
consumer, the retiring sha and the redundancy condition in its header.

**(b) The arm's word order was wrong for the permission matcher.** The rule that was added is
`Bash(helm upgrade:*)` — a **prefix** matcher. The arm as previously written began
`helm --kube-context <ctx> upgrade …`, whose prefix is `helm --kube-context`, and would not have
matched. Reordered to `helm upgrade iagent … --kube-context <ctx>`. This is the same shape as the
recorded hazard that a matcher's reach must cover what the shipping command is forced to spell; here
the two were written by different hands a day apart and neither was wrong on its own.

**And one claim of mine that had to be re-measured rather than carried forward.** Roll #3's report
asserted that emptying the tags "makes them behave like every other component". The chart annotates
both keys `# defaults to .Chart.AppVersion`, which would have made emptying deploy the *chart
version* and the arm useless again. **That annotation is wrong.** `_helpers.tpl:112` is the consumer:

```
$tag := .tag | default (ternary global.imageTag "" $ours) | default global.defaultImageTag | default $floor
```

`$ours` is `hasPrefix "<global.imagePrefix>/"` on the repository, the repository is
`<imagePrefix>/dagster-server`, so `$ours` is **true** and an empty tag falls through to
`global.imageTag`. `Chart.Version` is only `$floor`, four steps later. The claim was right; it was
right for a reason the values file states incorrectly.

**A second thing the re-read found:** `values-sandbox.yaml:497,517` **already declares `tag: ""`**
for both. So the pin was never a tracked decision anywhere — the tracked declaration and the release
disagreed, and `--reuse-values` kept the release's side. The new overlay is not a new opinion; it is
the existing declaration carried into a command that cannot see it.

## 2. The gate before firing — a full-manifest diff, not an image-line diff

Two dry-runs at the same sha, differing only in whether the retire overlay is passed:

| | measured |
|---|---|
| release values before | `dagster.webserver.image.tag` and `dagster.daemon.image.tag` = `c0005142a610bc…` |
| diff A (no overlay) → B (overlay) | **12 lines: the `LAST DEPLOYED` timestamp and exactly two image references** |
| both rendered refs in B | `…/dagster-server:b5eeb408e5658530193b05e1b503d9ec03dbe95a` |

Whether an empty string in a `-f` overlay displaces a non-empty value that `--reuse-values`
preserved is a claim about helm's merge. The manifest answered it; the values file only asked.

## 3. The fire

```
helm upgrade iagent helm/invincible-agent -n sandbox --kube-context <ctx> \
  --reuse-values \
  -f helm/invincible-agent/values-roll-frontend-digest.yaml \
  -f helm/invincible-agent/values-retire-dagster-server-pin.yaml \
  --set global.imageTag=b5eeb408e5658530193b05e1b503d9ec03dbe95a \
  --no-hooks
```

| | measured |
|---|---|
| helm exit | `0` |
| release | `iagent`, `sandbox`, **REVISION 151**, `STATUS: deployed` |
| release values after | both keys now `tag: ""` — **the pin is out of the release** |

## 4. What moved, and what did not

| pod | image | startTime | ready | restarts |
|---|---|---|---|---|
| `iagent-dagster-webserver-…-csv22` | `dagster-server:b5eeb408…` | `02:55:19Z` | true | 0 |
| `iagent-dagster-daemon-…-7pf7j` | `dagster-server:b5eeb408…` | `02:55:19Z` | true | 0 |

**Exactly two pods have a `startTime` in the roll's window.** Nothing else restarted — which is what
the 2-line manifest diff predicted, now confirmed on the cluster rather than inferred from it.

**Leg 11a: 33 deployments, `readyReplicas == spec.replicas == updatedReplicas` on every one.** Read
after the pods had moved, not seconds after helm returned — roll #3's recorded lesson that a
deployment reports Ready *throughout* a rolling update. `tika` now passes this leg where roll #3
flagged it, and **it passes vacuously**: its `spec.replicas` is 0, so the equality is `0 == 0 == 0`.

## 5. Leg 11b, and a behavioural check that is stronger than leg 11b

Whole log per pod, not a 60-second window — the correction recorded earlier today, that
`status.startTime` is the kubelet's admission and not the process's first output.

| pod | log lines | `Traceback` | `ERROR`/`CRITICAL` |
|---|---|---|---|
| webserver | 1 | 0 | 0 |
| daemon | 23 | 0 | 0 |

**The webserver's negative is weak and is recorded as weak:** an absence assertion over one line is
nearly vacuous. What makes it a real green is that its one line is
`Serving dagster-webserver on http://0.0.0.0:3000 in process 1` **and** its readiness probe is a real
`httpGet /server_info` that the kubelet reports passing — so `ready: true` is an answer here, not a
label.

**The daemon's green is behavioural.** All seven daemons configured; four sensors evaluated against
real cursors carried over from before the roll; and `QueuedRunCoordinatorDaemon — Launched 1 runs.`
Every one of those lines is a read or a write against the Postgres run storage.

**And that is the exact subject of `b95ce005`.** The failure it fixed was not a version cosmetic: on
`:03ee440` a bare `postgresql://` URL began resolving to psycopg3 under SQLAlchemy 2.1 and
`create_engine` died on `ModuleNotFoundError: No module named 'psycopg'` — the control plane could
not open its storage at all. Checked by its own name rather than by the absence of generic errors:

| check | measured |
|---|---|
| `No module named 'psycopg'` in either pod's log | **0** |
| storage-dependent work actually done | sensor cursors read, **1 run launched** |
| the pinned versions **in the running image** | `sqlalchemy 2.0.54`, `psycopg2 2.9.13` — exactly the pins |

The versions were read out of the pod, not inferred from the fact that it works.

## 6. The roll demonstrates the class `b95ce005` left open

`b95ce005`'s own comment says so in advance: the four dagster distributions are **still unpinned**, so
"this image is still not reproducible from its own tag". Measured here: the image that was measured
working carried **dagster 1.13.23**, and the image this roll deployed carries **1.13.24**. A patch
version of the orchestrator changed with no chart change, no repo change, and nothing naming it —
the dice roll the comment describes, which this time came up fine. **Recorded as a demonstration of
the open class, not as a defect of this roll.**

## 7. The overlay's own retirement condition is ALREADY met

The file says it becomes redundant once `helm get values` shows `tag: ""` for both keys. §3 measures
exactly that, as of revision 151. So the overlay now asserts nothing the release does not hold, and
the next hand should **delete it** rather than pass it on habit. It is committed anyway, this once,
because it is the only tracked record of the retirement at the moment the retirement happened — and
that record is what the ruling was about.

## 8. What I did not verify

- **That `dagster-server:b5eeb408…` is the image CI built**, first-hand. This account's token has no
  `read:packages`, so the claim still rests on job `Docker · dagster-server` succeeding at that sha
  plus `--push .` in the workflow. Unchanged from roll #3, and not a registry read.
- **Why `c0005142` was pinned.** Still unknown. §1 shows it was never a tracked decision, which is a
  different fact from knowing the intent. If it had a reason beyond "the last good one", this roll
  is wrong and the overlay's header says where the reason should go.
- **The dagster webserver's UI, or any job run end to end.** The daemon launched a run; I did not
  follow that run to completion, and "launched" is not "succeeded".
- **Anything about the eighteen services roll #3 moved.** They did not move here and were not
  re-examined.
