# MIL-STD-40051E Demo Work Packages (publicly redistributable)

**Source:** IADS 4.0 Demo Dataset (`helmet.iads`), Army TM 1-1680-TNG-13P,
PubDate 12 May 2014, Watermark `DEMO`. Two work-package XML files
extracted from the public demo package for use as exemplars when
authoring the MIL-STD-40051 reader (the 40051 sibling path to
`mil_info_code_map.classify_data_module` for S1000D).

This is **demo content distributed for IADS viewer/tooling demonstration
purposes**, watermarked DEMO and identified as "TNG" (training) variant.
It is not restricted Army content. Safe to commit indefinitely as a
reference exemplar.

## Files

| File | Bytes | Root | wpno | Maps to |
|---|---|---|---|---|
| `M0004.xml` | 2623 | `<maintwp>` | `m0004-1-1680-TNG` | `mil:ProcedureDataModule` |
| `T0003.xml` | 2638 | `<tswp>` | `t0003-1-1680-TNG` | `mil:FaultIsolationDataModule` |
| `40051E_5_0.dtd` | 132855 | (DTD — schema) | n/a | The authoritative WP-root enumeration |

The `.dtd` file is the MIL-STD-40051E REV E 5.0 DTD (USA-DOD), public
spec. It is the source the classifier's `WP_ROOT_TO_KIND` map is
derived from — per the architect's Step 0: "build the classifier
map from the DTD, not the samples." Committed alongside the
exemplars so the map's provenance is self-contained in the fixture.

## Why these two specifically

Per the architect's call: "the DTD tells me the value space; one real
WP tells me where in the document those values live." This pair is the
minimum exemplar for authoring the 40051 reader:

- **`<maintwp>`** with full procedure structure (`<maintsk>` →
  `<remove>`/`<install>` → `<proc>` → `<step1>` chain) — tells the
  reader where to find procedure steps, tool refs (`<tools-setup-item>`),
  and cross-WP references (`<xref wpid=...>`).
- **`<tswp>`** with full diagnostic structure (`<tsproc>` →
  `<faultproc>` → `<symptom>`/`<malfunc>`/`<action>`) — the
  fault-isolation vocabulary. Different element set from S1000D's
  fault-isolation work; the reader needs both.

## What the 40051 reader does with these

Shipped 2026-06-13. Three layers:

- `doc_tools.parsers.iads_extract.iter_iads_xml_entries(path)` — the
  IADS-container-specific layer. Unpacks the manifest + concatenated
  gzip blobs into `(relative_path, xml_bytes)`. An EAGLE adapter
  later would be a sibling module feeding into the same downstream
  reader.
- `doc_tools.parsers.mil_40051_ingest.read_40051_wp(xml_bytes)` — the
  format-general WP reader. Returns `WP40051Facts` (root_tag, wpno,
  maintlvl, title, tools, xrefs, kind_iri) or None for non-WP
  front-matter.
- `doc_tools.parsers.mil_40051_classifier.classify_40051_work_package(root_tag)`
  — the DTD-derived classifier. 80 WP root types enumerated from
  `40051E_5_0.dtd`; 65 map to existing `mil:*` kinds, 15 (reference/
  index/admin cluster) fall through to `mil:DataModule` and
  increment `FALLTHROUGH_COUNT[root_tag]` (positive control on the
  "no silent absorption" rule). Banked as a morning TBox decision:
  is `mil:ReferenceDataModule` or `mil:IndexDataModule` worth
  declaring?

The B3a end-to-end test (`tests/routing/test_b3a_ingest_helmet_40051.py`)
ingests the helmet TM via this stack and asserts: classification
matches the coverage table (11 rows), G1 stays green (positive
control on substrate OntologyClass count), G2 (every instance gets
INSTANCE_OF), G3 (idempotent re-ingest), composition (REQUIRES_TOOL
+ REFERENCES edges materialize), pool-hold, negative-boundary
(the helmet TM identifier `1-1680-tng` is in the substrate but
ABSENT from every deploy-path artifact).

## Boundary rule

This fixture is **categorically separate** from the SANDBOXRTX
synthetic corpus:

- SANDBOXRTX is the **unit-level negative-boundary fixture** —
  detectable marker (the MIC), guard asserts absent from deploy paths.
- IADS demo content is **public real-shape exemplar** — has no
  fabrication marker; the boundary against it is "it's only 2 files,
  doesn't go into any production manifest, lives in tests/fixtures/
  for reader-authoring reference."

The negative-boundary guard in `test_b2_ingest_sandboxrtx.py`
intentionally only checks for `SANDBOXRTX` — these files are not
its concern. A separate ingestion-time check (when the 40051 reader
lands) should refuse to ingest TM 1-1680-TNG-13P into the work
cluster's substrate the same way SANDBOXRTX is refused into deploy
paths.
