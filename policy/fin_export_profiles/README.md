# `policy/fin_export_profiles/` -- a CDRL is an export profile

A row here declares a finance EXPORT: a deliverable (a CDRL) laid out in an xlsx template and
filled with values a verb returned. The proposal is
[`docs/proposals/a-measure-is-an-overlay-row-and-a-cdrl-is-an-export-profile.md`](../../docs/proposals/a-measure-is-an-overlay-row-and-a-cdrl-is-an-export-profile.md)
(Part 2); the loader is `agent_fleet/finance_agent/export_profiles.py` and the producer is
`agent_fleet/finance_agent/cdrl.py`.

**Kind:** `fin_export_profiles`, key `name`. **The platform seeds none** (this README only). A
deployment adds rows, each with its xlsx template beside it, in an overlay:

    FIN_EXPORT_PROFILE_OVERLAY_DIRS=/app/policy/overlays/sample/fin_export_profiles

(`os.pathsep`-separated, default empty). `FIN_EXPORT_PROFILE_POLICY_DIR` moves the seed. An overlay
row replaces a row of the same `name` whole; `deleted: true` tombstones one. A malformed row set
refuses to boot the engine, naming the file and the reason.

**The shared header.** The first four keys of every row -- `name, format, scope, label` -- are the
header offered to lane/01's `policy/exports/` (the ingest-review export), so one picker can list
both kinds. This kind is kept out of `policy/exports/` on purpose.

**A profile computes nothing.** Every number in the file is a value a verb returned, joined on
`table.key`; a `formula`, `compute` or `expression` key is refused, as is a column naming a field
its source does not return, and a template whose sha256 differs from `template.sha256`.
