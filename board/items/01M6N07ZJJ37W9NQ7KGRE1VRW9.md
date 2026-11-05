---
title: The agent image installs packaging, setuptools and wheel unversioned after its locked sync
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: Chris 11-05 board item, pin acryl-datahub in the lock, 0.4.79
updated: 2026-11-05
---

**Found by the 0.4.79 seal.** `tests/test_no_unversioned_install_after_a_locked_sync.py` reads every `Dockerfile*` under `.github/docker/`. Its census holds exactly one remainder:
- `.github/docker/Dockerfile.agent:16` and `:203` run `uv pip install packaging setuptools wheel` right after `uv sync --locked`, with no version.
- Every engine image is built from this Dockerfile, so each build takes whatever PyPI serves for the three at that moment.

The census records the three as `KNOWN_UNVERSIONED` and must equal it exactly. A new unversioned install fails, and so does fixing these without deleting their rows.

**Why it is not fixed in 0.4.79.** No reason was recorded for the install. It arrived in the commit that extracted the Dockerfiles from the workflow (`eac4b5328`, 09-18). Pinning or removing it changes every engine image, which is a decision for the release it rolls in, not a side effect of the acryl-datahub fix.

**Done when:**
1. It is known which engine needs any of the three at runtime. Read the images, not the pyproject files.
2. Each one that is needed comes from that engine's lock, or is pinned `==`. Each one that is not needed is removed.
3. Its rows are gone from `KNOWN_UNVERSIONED`, and the seal is green.

**Also unpinned, and not this item:** both builder stages copy `ghcr.io/astral-sh/uv:latest`.
