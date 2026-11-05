---
title: validate_policy's other no-SDK forks, content kinds and review shapes (fork 13)
feature: api-sdk-mcp
lane: invincible-agent/lane/gov
repo: invincible-agent
status: open
priority: later
blocked_on: []
pr: []
ruling_ref: Chris 11-04 (the two other validate_policy.py spots are a board item, gov's, after #262 merges)
updated: 2026-11-05
---

#262 retired one fork in `policy/sync/validate_policy.py` that rested on "this gate runs where the SDK is not importable". Two more rest on the same premise:

- `known_content_kinds` reads the content-kind directories itself, "because this gate runs where src/iagent and the SDK are not importable".
- `REVIEW_SHAPE_REQUIRED`, `REVIEW_SHAPE_COVERAGE` and `_read_review_shapes` restate `iagent_mesh` `ReviewShapeRow`'s shape "because this gate runs without the SDK". `tests/test_review_shapes_are_one_registry.py` holds the copy equal to the model.

The premise as #262 read it: both documented run sites use the cortex-bff image, whose `python` is the venv that carries iagent-mesh (the seed CronJob, and `docker run <image> python policy/sync/validate_policy.py` in `policy/README.md`). That was read, not run. Measure it before relying on it, then replace each copy with the SDK's own reader or model.
