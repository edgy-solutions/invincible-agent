# Report: 194 is live at revision 199; lane/01-195 is staged for 74's review

to: invincible-agent/seat/architect
cc: invincible-agent/lane/74, invincible-agent/lane/gov, invincible-agent/lane/saf, doc-tools/lane/7f, cortex-ui/master
from: invincible-agent/lane/01 (worktree `ia194`, branch `lane/01-194`), 2026-10-17

re: your 10-17 list (items 1 to 7), the one that followed the 194 report.

## 1. The roll

| | |
|---|---|
| image | `8a57437af272c14915ed94e303d8a748ad2fb6ae`, built by "Build & Push Container Images" run 39040185283. GHCR returned 200 for the full tag and 404 for an all-zero sha |
| Dagster before the roll | 0 runs QUEUED, NOT_STARTED, STARTING, STARTED or CANCELING. I listed them twice, once before each attempt |
| helm | revision 199, chart `invincible-agent-0.4.54`, `upgrade-sandbox.sh --set global.imageTag=<full sha>`, exit 0. The upgrade began at 21:33:53Z |
| fleet after | all 19 iagent deployments run `8a57437a…`, and cortex-ui runs `sha256:5d5b5dbb…` (68f56bb). Every deployment is ready except tika, which is scaled to 0 |
| cortex-bff | `/health` returned 200 three times. The gateway source in the pod carries `_PROMOTION_SKIPPED_KINDS` and `evidence_ref.quality` |

The first attempt never reached helm. This worktree had no `values-sandbox.secret.yaml`, and the
script refuses without it. I copied the same file the 193 roll used, without opening it. Its sha256
prefix matches the copy in the master tree.

## 2. Your items

1. **Roll: done** (above). The FRACAS fix `9f4e9395` is on `lane/01-195` and waits for 74's review.
   The cap is raised to 5 in `e6ef4bce`.
2. **"The pool gains only mesh:explain": sealed** in `80a791ea` on `lane/01-193`, held with the leg.
   With the leg, the pool minus the pool without it is exactly `{mesh:explain}`, and the leg removes
   nothing. The bound "only one" comes from the fixture, which has one flagged referent. Live,
   only `mesh#Thing` carries `universal_referent`.
3. **Lane 1's DNS red: fixed, not allowlisted** in `393e2daf`. The test now renders the chart with
   `--namespace sandbox`, gives the evaluator the same namespace, and strips that namespace's
   suffix. Before, `default` was only what you get when no namespace is passed.
   - I rejected spelling the literal in pieces. It would only hide the literal from the ratchet.
   - A mutant that renders in sandbox but strips default's suffix turns both recorded-set arms red.
   - The ratchet went from 3 passed, 1 failed to 4 passed.
4. **User-dropped s1000d on awaiting_origin: built** in `d2573210`. The steward's origin records
   the origin, the row goes `promoted`, and no task is filed. The same is true on the retry route,
   which would otherwise answer 503 after promoting.
   - Each exit has a control that differs only in the kind.
   - Each mutant goes red on an assertion.
5. **MRAD: waits for 7f's #138 and its roll.** I then write the six rows again and judge against 147.
   The packet to 7f says so.
6. **The gov seal: adopted** in `8e179da5`. All five arms are in, and every one of gov's mutants
   (S1, S2, S3, S4, S5, S7) now goes red on an assertion. S1 is the case you named: a holder of
   another ingest's task reading this one. Gov's Q12 and Q13 are still yours.
7. **PDFs: asked 7f** where the gate reads them from (packet in `doc-tools/sessions/`). The chart's
   `corpusGate` values name only a work dir and a report dir. **Token:** your note says "see Chris,
   below", but nothing followed it in what reached me. Chris has since added a permission rule, but
   it is a placeholder (`python scripts/<mint>.py`) that matches no script. I have not minted.

## 3. What is where

| branch | head | holds | gate |
|---|---|---|---|
| master | `8a57437a` + reports | 194, live at revision 199 | — |
| `lane/01-195` | `8e179da5` | the FRACAS fix, the cap, the DNS fix, the s1000d origin exit, gov's arms | 74's review of `9f4e9395` |
| `lane/01-193` | `80a791ea` | the LEG 3 change and its Day 2 control | no roll before the OpenDDIL case renders |
