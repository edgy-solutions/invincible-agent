# Lane 1 — the 2026-09-30 relay: roll #9 (rev 161), export, ingest, merges

Master: `09997efc` (merges) → `3f27c7cb` (export) → `e42cabde` (ingest) → `f0f9a185` (cortex packet).

## Item 6 — the worker's three branches (merged first; roll #9 carries them)

- Merged: `9fdbcc18` promotion, `67dff181` envelope-label, `8815f44d` canvas-export. They were said to merge clean; **they did not.**
  - envelope-label had one comment-only conflict in `provenance.py`: both sides added `USER_DROP` with a byte-identical code line.
  - canvas-export's test wrote into `dist/`. That was fixed in the merge.
- Gate: 45 failed / 5069 passed against `suite_row9b`. That is 44 common, **1 new**, 2 fixed.
  - The new red was `test_kind_hardcode_audit`: promotion added two `kind:document_promotion` sites with no disposition.
  - Both were dispositioned `excluded`, with checkable reasons (`09997efc`), and measured red then green.

## Item 1 — roll #9

- **My mistake:** the first fire went out without `--no-hooks`. Rev 160 failed at helm's timeout on the minio-bucket-init hook (quay.io `minio/mc` returns 401).
- The re-fire with `--no-hooks` gave **rev 161**: image `12d3ca6f`, 42 pods Running.
  - One stale rev-160 hook pod (`iagent-minio-bucket-init-*`, ImagePullBackOff) was **left in place**, not deleted.
- The mesh re-put was done once and round-tripped intact. Dagster run `1a3d863a` SUCCESS:
  - "Class labels: 78 authored (kept), 0 derived …"
  - "Retrievability seal green for domain 'MESH': …mesh#AgentTask retrieves itself by its own stored vector."
  - Weaviate: 17 accepted, 0 rejected, 17 with a vector; 17 + 61 excluded == 78.
- Read-back: Neo4j `mesh#` **78**, `universal_referent` **1**, Artifact tree `[Artifact, PDFArtifact, CADArtifact]`.
- Census, 3 fires, identical each time:

| row | r159 | r161 |
|---|---|---|
| docs-how-do-i-add-an-engine | FAIL (0 sections) | **PASS** |
| docs-what-is-an-archetype | FAIL (0 sections) | **PASS** |
| docs-how-do-i-add-a-canvas-template | FAIL no_verb_classified | FAIL, unchanged |
| safety-haz-1003-risk-assessment | FAIL disposition `drawn`, row accepts `task_requested` | FAIL, unchanged |

- Instrument note: `--only docs-how-do-i-roll-a-service-abstains` names no row, and the walker drops it silently. So "three docs rows" is three, not four.

## Item 2 — mirror `minio/mc` (PR #5, green, OPEN)

- A `mirror-util-images.yml` workflow builds mc from source for arm64 and amd64 and pushes to `ghcr.io/edgy-solutions/mirror/mc`.
- `values-sandbox.yaml` points `utilImages.mc` at it. That repo is deliberately outside `global.imagePrefix`, so its tag does not float to Chart.Version.
- Order: **merge → dispatch the workflow → confirm tag and pull access → roll.** Until the tag exists, the hook would ImagePullBackOff on ghcr instead of quay.

## Item 3 — export routes (`3f27c7cb`, rides roll #10)

- Routes: `GET /export/package/recipients`, `POST /export/package`, `GET /export/package/artifact/{filename}`.
- The recipient gate is on `authz_id` via `seed.readers_for_recipient`, the same source the engine uses. **Production is gated too**, because packages share one directory.
- The person's bearer is forwarded; there is no service identity.
- `artifact_uri` is the gateway path. `export_id` = the sha. Production is synchronous, so there is no GET-by-id.
- The naming rule is spelled once (`seed.artifact_filenames`).
- `answers` is a manifest resolved per id (404 when unknown, never dropped). There is **no** cross-engine composition.
- "BFF forwards both": `cortex_bff/main.py` re-exports `gateway.app`, and cortex-ui has no proxy (nginx serves `/` and `/assets/` only), so the routes *are* the BFF's. Consequence: the download must be fetched with the bearer; a bare `<a href>` gets a 401. That is in the packet.

## Item 4 — ingest (`e42cabde`, built on master, not `lane/01-ingest`)

- Built on master because the seam's first commit is already there, and the local `lane/01-ingest` holds bad-trailer commits that must not be pushed.
- **Found: two ingest-id spellings.** The seam minted bare hex, while promotion accepts only `sha256:<hex>`, so every seam-minted document would have been refused promotion. Both now use `promotion.ingest_id_for`.
- **Found: FORMAT IS NOT KIND.** The seam wrote `pdf`/`cad` into `manifest.metadata.content_kind`, which ADR-0021 rule 1 reserves for registered kinds, so every drop would HALT.
  - Now there is an optional `content_kind` field, and the format rides as `media_kind`.
  - The ADR-0021 amendment disables rule 2 under `ingress-user/`.
- The wire, stages, manifest and projection update follow ca's `b68926a` shapes. The details are in the commit message.
- A reject-without-comment fallback I added proved **unreachable**: the kind declaration 422s first. It was reverted and replaced by a seal on that 422.
- **Open, not mine to build:**
  - nothing writes `extracting`, `awaiting_disposition` or `failed` (the doc-tools driver);
  - nothing creates the `document_promotion` HumanTask;
  - the promotion store is unset (act → 503);
  - `GET /ingest/kinds` does not exist;
  - `envelope_label` has no production caller.
- Tests: the ingest, promotion, projection, provenance, export, manifest and audit files: 136 passed. The 29 `test_classify_route` reds are baseline (present in `suite_m74`). `test_citation_paths` is red on ca's untracked packet, citing `docs/interfaces.md`.

## Item 5 — HAZ-1003 Postgres check: NOT RUN

This waits on Chris's bob turn, and I have seen no evidence of it yet.

## Cortex packet (`f0f9a185`)

- Filed at `sessions/2026-09-30-packet-to-cortex-ui-the-built-export-and-ingest-wire.md`.
- The precedent `to: ia-cortex-60/lane/cortex-60  (cortex-ui :: master)` does **not** parse, because `_TO` anchors at end of line. So that earlier packet was never addressed.
- `test_THE_REPO_INBOX_IS_FULLY_ADDRESSED` is red on 23 pre-existing packets, not on this one.

## Roll #10 carries

`3f27c7cb` and `e42cabde`. It still needs `--no-hooks` until PR #5 is merged and the mirror tag exists.
