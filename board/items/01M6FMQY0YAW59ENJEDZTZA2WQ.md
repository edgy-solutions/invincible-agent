---
title: A red test pins DispatchFanoutStep's exact fields; the step gained stage
feature: workflow-socratic
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: none; found by gov's consumer run for #210, triaged by Chris's 11-02 instruction
updated: 2026-11-02
---

Red on master at e0a2ab9b. Broken by 152d453f (2026-10-29): green at its parent, red at that commit, run in today's venv.

- tests/test_dispatch_fanout_step.py::test_a_definition_CANNOT_declare_an_escalation_path

`DispatchFanoutStep` gained `stage`, and the test's exact field set fails. Its first assert, that `escalation` is not a field, still holds, so what the test is named for is not what went red. It reads as a stale assertion after a deliberate change; the author's read decides.
