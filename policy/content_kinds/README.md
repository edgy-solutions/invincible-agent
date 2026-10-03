# `policy/content_kinds/` -- the SEED half of the content-kind registry (ADR-0021, ADR-0041 §4/§8)

A content-kind row maps a declared `content_kind` value to what the seam does with it: a
`document` branch runs extraction `passes` and stamps `outputs`; an `event` branch (SDK 0.9.7)
names a workflow to start on arrival (`seeds_workflow`) and a field to dedupe on
(`identity_field`) instead. `content_kinds.registrations()` composes this directory with every
deployment overlay named in `CONTENT_KIND_OVERLAY_DIRS`, through
`iagent_mesh.ingest.compose` (ADR-0036).

**This directory is STRUCTURAL, and empty on purpose.** The mapping table is chartable,
version-able and domain-owned (ADR-0021) -- the same reason `policy/verbs/` ships no stub and
`iagent_mesh.task_kinds` ships no task kind of its own. Every row today is a programme's, so it
lives in an overlay (the sandbox's stand-in is `policy/overlays/openddil-lab/content_kinds/`).
The directory exists, and is baked into the image, so a platform content kind added here later
ships on arrival.

Unlike `task_kinds`' read (`TASK_KIND_OVERLAY_DIRS` unset or unreadable falls back to today's
behaviour, R-012's asymmetry), an unreadable content-kind registry FAILS CLOSED
(`content_kinds.registrations()` raises) -- see that module's docstring for why the two gates
differ.

A kind declared twice, anywhere on the path, is refused.
