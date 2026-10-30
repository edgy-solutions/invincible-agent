# policy/exports

Review-export profiles served by `GET /ingest/{id}/export?profile=<name>` and
`GET /ingest/export?profile=<name>&from=&to=` (the batch). One `<name>.yaml` per profile; the file
stem must equal `name`. The vocabulary is doc-tools 7f's `batch-column-map.md` (contract_version 1);
the loader and validator are `src/iagent/export_profiles.py`. A broken profile is logged and left
out of `GET /ingest/export/profiles`; it never breaks the others. `INGEST_EXPORT_PROFILE_DIR`
overrides this directory.
