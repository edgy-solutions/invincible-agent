---
id:         sandbox-document-objects-are-not-reproducible
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       invincible-agent
summary:    A recoverability audit (2026-09-10, during worker6's storage failure) found sandbox reproducible from the repo EXCEPT for MinIO document objects — the sample PDFs are seeded by nothing and exist only on one failing disk. The bucket-init job creates buckets and uploads nothing. Fix is a manifest of source URLs + sha256 and a fetch/upload script; the bytes must NOT be committed. Also: tests/fixtures/iads_40051_demo is in the repo but wired only to one test, not to any seed path.
---

# Sandbox is reproducible from the repo — except its document objects

**Audited 2026-09-10** while worker6's NVMe was failing and all four stateful singletons
(keycloak, weaviate, minio, restate) were unreachable on it. The question was the standing
claim that *"the entire sandbox deployment should be rebuildable from the repo using helm and
priming scripts, and if not that should be fixed."*

**The claim holds better than expected. One hole.**

| state | reproducible? | by what |
|---|---|---|
| Keycloak test users — `alice`, `bob`, `carol`, `agent-user` | ✅ | realm import in `templates/keycloak-configmap.yaml` |
| Ontology TTLs (13 of 14) | ✅ | prime uploads canonical TTLs to the `ontologies` bucket, then triggers doc-tools `ingest_ontology_job` |
| `mro_extension.ttl` | ✅ | the gated `ontology-seed` job — **not** in the prime ingest set, which is why that job exists; `ontologySeed.enabled: true` in `values-sandbox.yaml` |
| MinIO buckets | ✅ | `minio-bucket-init-job` |
| **MinIO document objects (sample PDFs)** | ❌ | **nothing** |
| `tests/fixtures/iads_40051_demo` | ⚠️ | in the repo, but referenced only by `tests/routing/test_b3a_ingest_helmet_40051.py` — no seed path uses it |

## The hole, precisely

`minio-bucket-init-job.yaml` runs `mc mb --ignore-existing` and **nothing else** — no `mc cp`,
no `mc mirror`, anywhere in the chart. There are no PDFs in the repo. So the sample documents
exist in exactly one place: the MinIO instance on worker6's disk, which spent 2026-09-09/10
dropping off the PCIe bus under load.

**This is the ordinary shape of bootstrap-state debt** and the repo already names the class —
`ADR-0016` records *"because the doc-tools content pipeline isn't seeded in sandbox"*, and the
`ontology-seed` job's own header calls itself a *"GATED reproducible ROUTING substrate
(bootstrap-state-debt)"*. Content that arrived by hand reads exactly like content the bootstrap
produced, right up to the day you rebuild.

## The fix

**A manifest, not the bytes.** The documents came from public sources on the internet; the repo
should hold the *recipe*, never the files.

1. **`setup/documents/manifest.yaml`** — one entry per document: source URL, **sha256**, target
   bucket + key, and a provenance/licence note.
2. **A fetch-and-upload script.** Default shape is **workstation → MinIO**, not an in-cluster
   job: the work cluster has no internet egress (which is why `scripts/mirror-to-artifactory.ps1`
   exists at all), so a job that fetches from the public internet cannot run there.
3. **Wire `iads_40051_demo` in from the repo** at the same time — it is already committed and
   only needs promoting from test fixture to seed input.

### Properties the script must have, and why each one

* **sha256 pinned per document.** A URL is not a guarantee of content. Without a checksum a
  source that changes, or silently serves a redirect page, seeds *different data* and reports
  success. See [[a-green-seal-can-be-green-for-the-wrong-reason]].
* **A partial fetch is a FAILURE.** No "3 of 5 uploaded, exit 0" — that is the exact defect
  fixed in `/canvas/seed`, where a run that seeded nothing returned 200 and made an ADR-0050
  seal report PASS in 2.48 seconds against a fifty-minute run.
* **Idempotent** — skip when the object is present and its checksum matches, so re-running is
  free and safe.
* **DO NOT COMMIT THE PDFs.** Explicit instruction, 2026-09-10. They are data. If they are ever
  needed offline, they belong in the same off-cluster store as the gya backup below.

## Related, different scope: gya has real data and no backup

The `gya-*` namespaces (Goat Yard Archive) hold MinIO objects and Weaviate vectors that are
**not** reproducible from any repo. Recoverable in principle by reloading sources and
re-vectoring, but that costs hours.

**Back up the source, not the index.** The Weaviate vectors are *derived* — expensive to
recompute, not irreplaceable. **The MinIO objects are the only genuinely unrecoverable data in
the cluster.** A `mc mirror` to an external disk on a *different power supply* is the whole
job. A Weaviate snapshot is an RTO convenience on top, worth doing only if it is cheap.

**Note the failure domain.** op4/op5/op6 shared one multiport supply, so replicating across
nodes would have put every copy in one power domain. That is why the answer here is an
off-cluster backup and **not** Longhorn, Ceph, or any replicated block layer — on these boards
those would have cost far more and protected against the wrong thing.

## Definition of done

* `setup/documents/manifest.yaml` exists with a checksum per document, and the script restores
  every sample document into a **fresh** MinIO from a cold start.
* `iads_40051_demo` reaches MinIO through the seed path, not only through a test.
* gya MinIO objects have a scheduled off-cluster copy, verified by a restore rather than by the
  backup job's exit code.
* The whole claim is settled the only way it can be: **install into a fresh namespace, prime,
  and diff the resulting Keycloak realm / MinIO keys / Weaviate classes / Neo4j label counts
  against sandbox.** Every difference is a gap to fix or a deliberate divergence to record. An
  untested recovery path reads as verified right up until it is needed.
