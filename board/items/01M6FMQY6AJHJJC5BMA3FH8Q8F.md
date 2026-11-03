---
title: The already-filed path reads an open task's payload; a red test's fixture does not stub it
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: done
priority: next
blocked_on: []
pr: [invincible-agent#222]
ruling_ref: none; found by gov's consumer run for #210, triaged by Chris's 11-02 instruction
updated: 2026-11-03
---

Red on master at e0a2ab9b. Broken by c095be48 (2026-10-21): green at its parent with the same unset DSN, red at that commit, run in today's venv. So not environmental, although the error names an environment variable.

- tests/test_origin_write_route.py::test_q2_e_AN_ALREADY_FILED_TASK_IS_NOT_REFILED_BUT_THE_ROW_MOVES

The ALREADY_FILED path now calls `human_tasks.get_open_task_payload`. The test's `filing` fixture does not stub it, so `_pg_connect` raises `HumanTaskConfigError("PROJECTOR_POSTGRES_DSN is unset")`. It reads as a stale fixture. gov last touched this test at 00374662, before the break; the breaking commit is lane/01's, so the read is too.

Fix (lane/01-five-reds): the filing fixture now stubs get_open_task_payload (c095be48) to return the open task payload (the row's content_kind) when a task is already filed, else None; the test still proves no refile and that the row moves.
