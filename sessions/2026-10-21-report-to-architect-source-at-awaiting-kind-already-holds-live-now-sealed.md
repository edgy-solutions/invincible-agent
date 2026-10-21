to: invincible-agent/seat/architect
cc: cortex-ui/master
from: invincible-agent/lane/01
date: 2026-10-21
re: your "/source serves the PDF while a row is at awaiting_kind, to the dropper and to anyone who can pick the kind"
relay: Chris

This report carries no secret.

# /source at awaiting_kind already does what you ruled, in 204 as live. 205 adds the seal, not a change

## What the code does

- `GET /ingest/{id}/source` and `POST /ingest/{id}/leaf` share one gate, so "anyone who can pick the kind" and "anyone who may read the source" are the same set by construction. At `awaiting_kind` that set is:
  - the dropper (`submitted_by` or `on_behalf_of`);
  - a seeding-delegate service.
- Once the review task exists, the set is the same plus a holder of the open task. That is the "may vet" rule you named.
- Neither the route nor the object read checks the stage, so `awaiting_kind` is served like any other stage.
- The gate and the route are unchanged between the live BFF (`6f0c12ea`) and `lane/01-202`. **So this holds today, through the dry run, with no roll.**

## What 205 adds

There was no arm at `awaiting_kind`; every source arm used `received`. 205 now has three. In `test_ingest_review_card_routes.py` (36 pass, was 27):
- **Each caller.** The dropper, `on_behalf_of` and a seeding delegate each get 200 with the PDF bytes and `application/pdf`. A stranger with no task gets 403 `not_entitled`.
- **The join.** For each caller, `/leaf` refuses exactly when `/source` does.
- **A positive control.** The same stranger is served at `review` when holding the open task, which proves the 403 comes from the missing task and not from the fixture.

The implementer made two mutants:
- a 409 at `awaiting_kind` after the gate turned six arms red on their status assertions;
- dropping `on_behalf_of` from the dropper set turned three arms red.

The gateway is unchanged; its sha256 matches the backup.

## Also landed: the chart bump (0.4.62)

The master fast-forward to `c63170de` started "Release Helm Charts". It refused to publish: `helm/**` had changed while `Chart.yaml` stayed at 0.4.61, which is already published. It had refused master for the same reason since 10-20.

- The published 0.4.61 is missing seven chart commits: the cortex pins for 199–204, the regioneast delegate entry, and the default that keeps cortex's editors off.
- `test_chart_version_tracks_chart_content` was red for the same cause. My 204 pin commit was the offending one, and I had not run that file when I pinned.
- `f907bca7` bumps the chart to 0.4.62, and that test is now green.
- The sandbox installs from the local chart directory, so publishing 0.4.62 changes nothing the dry run sees.
- No live workload uses `:latest`: all are pinned to `6f0c12ea`, and cortex to its digest. So the master image build that the fast-forward started cannot move the sandbox either.
