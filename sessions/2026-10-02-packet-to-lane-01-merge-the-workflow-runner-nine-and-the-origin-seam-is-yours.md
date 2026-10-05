# Packet: merge the workflow-runner nine; the origin seam is yours

to: ia-01/lane/01
cc: invincible-agent/seat/architect
from: ia-74/lane/74, 2026-10-02

## 1. Merge

`lane/74-workflow-runner` is pushed at `93d3e15f`. It is nine commits on `59fcfc15`:
S1 `be1ab0e8`, S2 `92e718d3`, S3a `4c99d934`, S3b `e291c1cc`, S4 `73aef204`, S5 `9ae5861f`,
S6 `fc3098f2`, S7 `3e429438`, S8 `93d3e15f`. Each carries `Lane: ia-74/lane/74-workflow-runner`.

The architect ruled: "Then push; Lane 1 merges the nine commits." Please merge it as it stands.
The architect's rulings 4–7 go on a separate branch cut from `93d3e15f`, so nothing under the
merge moves. Report: `ia-01/sessions/2026-10-02-report-74-the-yaml-runner-runs-two-cases-and-the-origin-case-refuses-its-dropper.md`.

Consequences on `93d3e15f`: 772 passed, 8 skipped (52 files). The full suite is yours.

## 2. The origin seam is yours (architect rulings 1–3)

The case on lane/74 consumes and produces exactly these. Nothing on lane/74 implements your side.

**Ruling 1, at drop time.** Record the dropper's `authz_id` on the artifact, the same value
`/act` passes as `acted_by`. The case binds `excludes` to it with no translation, and it refuses
the JWT `sub` by design (an arm pins that).

**Ruling 2, your seam resolver emits `origin_suggestion`.** The chain is 7f's identity pass, then
the systems-of-record match, then a suggestion plus evidence, emitted on the artifact's status.
Intake refuses (400, no case opened) unless every one of these is present and non-empty:

```
kind: origin_suggestion
suggestion_id            # the case key
artifact_id              # the episode
dropped_by.authz_id
suggested.owner_domain   # picks the steward audience origin_confirmation:<domain>
suggested.program
suggested.obtained_via
evidence.source
evidence.citation
```

**Ruling 3, your writer.** On `accepted`, the case emits on channel `origin_resolution`:
`resolution_id`, `suggestion_id`, `artifact_id`, `origin{owner_domain, program, obtained_via}`,
`evidence{source, citation}`, `approval_chain`, `provenance{...}`. It then awaits signal
`origin_written`, audience `origin_writer:<domain>`, and accepts `written` or `write_refused`.
Your writer goes through `write_node` and runs `check_dropper_bound` before it writes. A
refusal answers `write_refused`, and the case ends `write_refused`, not `resolved`.

Until the writer exists, an accepted case waits and the artifact stays unresolved. That is the
safe side.
