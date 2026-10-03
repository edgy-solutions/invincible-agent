# `policy/systems_of_record/` -- the SEED half of the origin resolver (architect ruling
2026-10-02, "ORIGIN, not audience", item 2; SDK 0.9.7 `iagent_mesh.systems_of_record`)

A system-of-record row names one external system the origin resolver can match an artifact's
declared metadata against (`identity`), look up through a named connector (`lookup`), and read
an `owner_domain`/`program` from. `origin_resolver.systems()` composes this directory with every
deployment overlay named in `SYSTEMS_OF_RECORD_OVERLAY_DIRS`, through
`iagent_mesh.systems_of_record.compose` (ADR-0036).

**This directory is STRUCTURAL, and empty on purpose.** The SDK ships no rows of its own (same
discipline as `iagent_mesh.ingest` and `iagent_mesh.task_kinds`), and neither does this seed --
every real system of record belongs to the deployment that operates it, and names a connector
registered in `origin_resolver.CONNECTORS`, which only that deployment's code can supply. The
sandbox's stand-in overlay (`policy/overlays/sample/systems_of_record/`) ships an EMPTY list,
same reason and same mechanism as `policy/overlays/sample/graphs/`'s own empty `.gitkeep`: an
existing empty directory is the CLAIM "this deployment names no systems of record", a different
fact from an unset overlay variable ("nobody said where to look").

A row's connector name is validated against `origin_resolver.CONNECTORS` at the first
`origin_resolver.systems()` call -- an unknown connector raises `UnknownConnector` rather than
silently never matching (the SDK's own "prefix-registry failure class").

A row declared twice, anywhere on the path, is refused.
