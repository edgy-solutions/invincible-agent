# policy/exports

Review-export profiles served by `GET /ingest/{id}/export?profile=<name>` and
`GET /ingest/export?profile=<name>&from=&to=` (the batch). One `<name>.yaml` per profile; the file
stem must equal `name`. The vocabulary is doc-tools 7f's `batch-column-map.md` (contract_version 1);
the loader and validator are `src/iagent/export_profiles.py`. A broken profile is logged and left
out of `GET /ingest/export/profiles`; it never breaks the others. `INGEST_EXPORT_PROFILE_DIR`
overrides this directory.

## Server fields and the overlay

Each profile also declares `version` (required positive integer; an export records the version it
used), `grain` (`per_notice` | `per_part`; the same thing as 7f's `granularity`, `notice` |
`notice_part`, and a row that names both must agree), and optionally `accepts` (a list of content
kind names, shape-checked only; absent = any kind) and `dedupe` (a list of output columns; the
first row per joint value is kept), and `exportable_states` (a list of notice states, named AS
SERVED: the `stage` `GET /ingest/{id}/status` returns, and the loader refuses a name that is not
one; absent = `[promoted]`, and the shipped profiles say so). A notice in a state the profile does
not list is refused naming that state; an export from a state before promotion serves the
extraction's uncorrected values. The listing serves only the profiles the caller holds
`can_export:<profile>` for, and `POST /ingest/export/notices` takes notice ids, a profile and an
optional destination; it lists unexportable notices with reasons and builds no file if any exist.

`INGEST_EXPORT_PROFILE_OVERLAY_DIRS` (os.pathsep-separated, optional) layers directories over this
one under ADR-0036: add a profile, replace one by name (a whole replacement), or delete one with a
tombstone (`name:` + `deleted: true`; a tombstone for a name nothing ships is an error).
`policy/overlays/sample/exports/` carries the generic `part-list` sample and `part-list-reviewed`, the same list for a notice in `review` or `promoted`.
