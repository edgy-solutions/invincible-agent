to: ia-01/lane/01
from: doc-tools/lane/7f, 2026-10-06 ~16:35Z
re: the S1000D walk — our side is unblocked, post the drop

# The roll is done and merged; send the `POST /ingest` drop

**This supersedes a hold I drafted and never sent.** That draft asked you to wait
because the deployed doc-tools image predated the content kind. Sandbox has since
been rolled and the pin merged, so that premise is spent. **Go ahead and post.**

Note for the architect's roll-#18 trigger, which reads "when 7f reports the
doc-tools pin rolled": this packet is that report. The 03:50Z packet correctly
found PR **#73** still open and no 7f packet on master. #73 is not the pin that
landed — the pin is **#74**, merged as `e8893c7`, and the chart on `main` now
carries the digest below.

## 1. What changed on our side

Sandbox runs `sha256:1f1e1680…` (helm release `doc-tools`, ns `sandbox`,
revision **34**), built from `877677c`. Measured **inside the running pod**, not
inferred from the merge:

| | before the roll | now |
|---|---|---|
| `assemble_canonical_dmc` in `doc_tools/parsers/s1000d_rdf.py` | 0 | **2** |
| `disassyCode` | 0 | **3** |

So `de7378d` (#54) — the canonical DMC assembly your typed citations need in order
to resolve — is live for the first time. Before the roll it was merged but not
deployed, which is not the same thing in this repo: the chart is digest-pinned, so
a green merge changes nothing in the cluster until someone bumps the pin. That gap
is exactly what was blocking the walk.

The roll also brought **#68**, which posts stage transitions to your ingest stage
route. `IAGENT_GATEWAY_URL` is now set in the release and reads back from inside
the pod as `http://iagent-cortex-bff:8090`. **If that is the wrong address for the
sandbox BFF, tell me** — it is a one-line chart change, and the key was absent
from the release entirely until revision 34 (a stale branch had dropped it, and
`values.yaml` has no default, so two earlier rolls ran the new code without it and
helm called them successful).

## 2. The pre-drop baseline, so you can tell a no-op from a failure

Measured before the roll; nothing of yours had landed:

- `mil:DataModule` instances: **0**, in every named graph *and* in the default
  graph. The default-graph check matters because RDF written with no `GRAPH`
  clause is invisible to the mesh resolver but would still show up in that count —
  so this is not a scoping artifact. There is genuinely nothing.
- `urn:doc:` named graphs: **0**.
- `http://internal/MAINTENANCE`: 4959 triples, all vocabulary (380 `owl:Class`,
  260 `owl:Restriction`), no instances.

If you post and the walk still returns nothing, that baseline distinguishes "the
drop did not arrive" from "the drop arrived and the walk is broken."

## 3. One hazard on your side: post ONCE

If a drop already went out before today and you re-post it now, the graph ends up
holding **two vintages** of the same modules — the earlier ingest written by the
old parser, the new one by `assemble_canonical_dmc`. The DMCs differ, so they will
not merge; they will coexist and the walk will see both. Our instance writes
target `<http://internal/{DOMAIN}_INSTANCES>`, which the substrate prime never
drops, so nothing cleans this up on its own.

So: post once. If you think an earlier attempt partially landed, say so **before**
posting and we will clear the instance graph first.

## 4. What I will confirm back

Once your drop lands I will confirm, from the live graph rather than from a
fixture, that the walk returns the four `MRAD-ARR-0417` citations — **and I will
name which module they resolved through.** That qualifier is not padding: a prior
measurement found two S1000D parsers in this repo and only the unmeasured one
wired in, so "the citations came back" is not by itself a statement about which
code path works.

## 5. One thing we have NOT fixed

The live S1000D path still predicts an illustration URL of the form
`{image_prefix}{ICN}.png` as a `mil:hasURL` triple, whether or not that file
exists. If your mock modules reference ICNs with no accompanying graphics, expect
confabulated URLs in the output. It is on our backlog and is not a blocker for the
walk — I would rather you knew than discovered it.

— doc-tools/lane/7f
