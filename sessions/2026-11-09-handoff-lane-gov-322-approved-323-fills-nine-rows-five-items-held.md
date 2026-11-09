to: invincible-agent/lane/gov
from: invincible-agent/lane/gov
date: 2026-11-09
re: the 503-seal dispatch after the architect's 11-09 answers
supersedes: 2026-11-08-handoff-lane-gov-322-carries-the-503-seals-7f-is-answered-the-pin-waits-on-ca.md

## Next step

Read CI on #322 (head `04e656ea`) and #323 (head `23fd13f2`). CI on #322 was still running when this was written. If either is red, fix it on its own branch. If both are green, they wait for the merger, which is not gov. Then check for the v0.9.17 tag:

`git -C C:/Users/cnogr/git/iagent-mesh-sdk ls-remote --tags origin 'v0.9.1*'`

## The dispatches, verbatim

"gov: 503 seal finds routes by what they call, not a fixed list (74's packet); "Answer 7f's 10-29/10-30 packets" item; v0.9.17 pin PR when ca tags it (nine-field ImpactRow)."

"gov (#322): approved — a code defect is a 500, an outage is a 503; the seal finding routes by form is the right shape. EvidenceRef: the 10-31 rule stands (no null note, bbox exactly four numbers in 0..1); gov fills the remaining kind rows from 7f's table."

## Item 1: #322, approved, waits for the merger

Worktree `C:\Users\cnogr\git\wt\gov\503-seal-by-form`, branch `lane/gov-503-seal-by-form`. Master is merged in, with #315 landed. Both seals: 332 passed at `04e656ea`. When it merges, remove the worktree: `git cherry origin/master <head>` shows no `+`, status is clean, `is-ancestor` holds.

## Item 2: 7f and the kind rows

- `EvidenceRef`: 10-31 stands. `src/iagent/ingest_api.py` already matches, so no code change. Its docstring cites 10-28 for the wire shape, but its next paragraph names 10-31 as the authority, so I left it. 7f relaxes its stricter arm and re-takes the pin.
- #323 (worktree `C:\Users\cnogr\git\wt\gov\kind-rows`, branch `lane/gov-kind-rows`) adds `arrives_as` and `label` to nine rows. Nothing reads those fields yet, so it changes no behaviour.
- Tests on #323: 70 kind-related files, 1652 passed, 2 failed, 3 xfailed. The 2 failures are in `tests/test_a_finished_run_with_no_leaf_waits_for_a_kind.py` and fail identically on `1691a290` without the change. Reported to Lane 1, not diagnosed.
- Packet placed untracked in the master tree's `sessions/`, dated 11-09, to the architect and 7f.
- Board item `01M6A9QDN1QSSWQ74F6JV74W0B` is `blocked` on the architect's call on what is held. That change rides #322.

## Held for the architect's call

The four new rows and `review_shape: document` on `work-instruction`. Reasons and what each needs are in the 11-09 packet. No seal was edited to admit them.

If they are ruled in, the rows come from 7f's 10-30 table in doc-tools `sessions/`. All are `passes` / `outputs` as shown:

| kind | domain | arrives_as | review_shape | label | passes | outputs |
| --- | --- | --- | --- | --- | --- | --- |
| document | document | [pdf] | document | General document | identity.document_identity, document.document_outline | mesh:GeneralDocumentArtifact |
| dxf | null | [dxf] | | DXF drawing | cad.dxf_identity | mesh:DxfArtifact |
| step-ap242 | null | [step] | | STEP AP242 model | cad.step_ap242_identity | mesh:StepAp242Artifact |
| cad | null | | | CAD artifact | cad.cad_document_identity | mesh:CADArtifact |

## Item 3: v0.9.17 pin PR, not started

ca had not tagged it at 2026-11-09 (newest is v0.9.16). Lane 1's pin procedure and the `chris:rule who moves the iagent-mesh pin` board row for v0.9.16 are the precedent to read first.
