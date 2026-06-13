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

1. Parse root element name → look up `mil:*` content kind via
   `classify_40051_work_package(root_tag)` (analog of B2's
   `classify_data_module(info_code)` for S1000D).
2. Read `wpno` attribute → that's the canonical instance identifier.
   Goes into the `mil:DataModule.wpno` property (or the same `.dmc`
   property if the architect decides to unify the identifier slot).
3. Read `<wpidinfo><title>` for the human-readable label.
4. Read `<tools-setup-item><name>` (M-type WPs) for tool cross-links.
   Note: 40051 doesn't have a clean equivalent of S1000D's
   `<spareDescr>` — parts are referenced via `<xref>` to RPSTL
   modules. The composition cross-links (`mil:hasPart`,
   `mil:requiresTool`) edges should be written when those refs are
   present, same shape as B2's S1000D path.
5. Each `<symptom>`/`<malfunc>`/`<action>` triple in a `<tswp>` could
   eventually become its own structure if the docs phase decides to
   surface fault-trees as graph data. B2-level minimum: ingest as a
   single instance with the full text as a chunk.

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
