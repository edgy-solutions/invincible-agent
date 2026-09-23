# Packet — the doc-tools precondition for the mesh_system.ttl prime is MET (verified independently)

to: ia-01/lane/01
from: ia-01/lane/01 · cc the architect
read-by:
**M** = measured by me. **P** = the peer's claim, unverified by me.

Supersedes one line of `2026-09-21-handoff-lane-01-four-lanes-merged-and-roll-2-must-be-re-armed.md`
(`fc12b28`): its NEXT TASK listed **the doc-tools chain, then the `mesh_system.ttl` prime** as one
waiting item. The chain half is now done. **The prime itself still waits on Chris** — nothing in
this packet is a go, and I did not fire it.

`doc-tools-56` (a peer session, not Chris) reported sandbox doc-tools at `0279d83`. I did not take
it on the claim. Measured 2026-09-22 against context `edge`, ns `sandbox`:

    pod        doc-tools-6675ccd5b-s8x7t   Running 1/1, ready, sole replica (deploy 1/1/1)   M
    image      ghcr.io/edgy-solutions/doc-tools:0279d836a57de0f2c4ae00f9e51b3c74009499e7     M
    imageID    sha256:71a662f0f41a3cbc1484f0b465c83871b3cf3ec09b2487b0a8cc6aea72606046       M
    registry   the TAG's index digest == that imageID, and it has arm64                      M
    release    helm doc-tools revision 11, deployed, updated 2026-09-22 21:36 CDT            M

The registry leg is the one the peer did not run, and it is the one that catches a tag moved after
the node pulled. It agrees. **Both legs read the digest, never the tag** — this workload is
`dagster api grpc` and has no `/version` to ask (P, and consistent with the image).

## Two corrections to the peer's note, neither material
* Its filename is dated **2026-09-23**. The release stamp says the roll happened **2026-09-22** (M).
  A forward-dated record reads as newer than the thing it describes; cite the release, not the file.
* The claim that the digest is what build-and-push emitted for `0279d83` (run 35804122987) is **P** —
  I confirmed the registry tag and the running pod agree, which is a different assertion. Nobody has
  tied either to that workflow run, so do not repeat "the CI artifact" as measured.

## Carried forward from the peer, unverified (P), so that it is not read as a regression later
* `seal_a_written_row_is_RETRIEVABLE` stays **red on any ontology ingest** until the ledger backfill
  lands. Expect it red when the prime runs; that is not the prime failing.
* The blank-node filter fix rides in this same image because it was already on `main`.
* Open on their side, blocking nothing here: the 9-notice extractor baseline, and `VISION_MAX_TOKENS`.

## What this does NOT change
Roll #2 is still armed at the **stale** `8952b11` and must be **re-armed, not edited** — doc-tools
is a different chart and a different release. The census still owes a third fire. Master is
`816bbee`; `lane/01` is `fc12b28`, 2 ahead, unmerged.
