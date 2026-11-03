---
title: Master red: 7b497119 carries a Lane trailer made from a worktree path
feature: cross-cutting
lane: invincible-agent/lane/fin
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: none; 11-03 full-suite census, triaged by Chris's 11-02 instruction
updated: 2026-11-03
---

Red on master at e0a2ab9b, full suite and alone.

tests/test_every_commit_names_its_lane.py::test_A_TRAILER_MADE_UNDER_THE_REGISTRY_NAMES_A_REGISTERED_LANE refuses 7b497119 (`Lane: ia-fin-export-refused-entries/fin/...`). The rule says the id is a `.githooks/lanes` row, never a worktree path. Pushed history can't be rewritten, so the fix has to be in the seal or the registry.

Fin proposes a registry row or a named exemption for this one sha. Whoever owns the seal decides.
