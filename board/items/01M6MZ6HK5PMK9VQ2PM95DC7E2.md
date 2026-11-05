---
title: acryl-datahub is pinned by the lock in every image, with no unversioned install after the locked sync
feature: cross-cutting
lane: invincible-agent/lane/01
repo: invincible-agent
status: review
priority: now
blocked_on: []
pr: [invincible-agent#267]
ruling_ref: Chris 11-05 board item, pin acryl-datahub in the lock; architect via Chris 11-05: it cuts as 0.4.80
updated: 2026-11-05
---

**0.4.80 content** (0.4.79 was already released, so this cuts as 0.4.80). The control-plane image installs acryl-datahub outside the lock.
- The install is `.github/docker/Dockerfile.dagster:39`, `uv pip install --python /app/.venv/bin/python acryl-datahub`, with no version.
- It runs after `uv sync --locked`. Its version is whatever PyPI resolves at build time, so two builds of one sha can differ.

**The comment above it is stale.** It says acryl-datahub is kept out of the root deps to avoid bloat. The root `pyproject.toml:20` now declares `acryl-datahub>=1.7.0`, so the locked sync already installs it.

The extra install is redundant at best. At worst it moves the package and its transitive pins (botocore among them) off the lock.

**Done when:**
1. The unversioned install is gone, and the image's acryl-datahub version is the one `uv.lock` names.
2. A test reads every `Dockerfile*` under `.github/docker/` and fails on a `pip install` of a package name with no version after a `--locked` sync.
3. The engines that list bare `"acryl-datahub"` (`data_analyst`, `neo4j_expert`, `weaviate_expert`, `presentation_agent`, `mesh_registrar`, `restate_analyst`) are each confirmed to resolve it from their own `uv.lock`. The confirmation reads their images, not their pyproject files.

**Not checked:** which acryl-datahub version the live control-plane image carries, or what the root lock names. Reading `uv.lock` here was denied this session, so the PR reads the installed dist-info.
