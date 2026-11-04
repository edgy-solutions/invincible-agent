---
title: v0.9.13 builds as 0.9.12: no 0.9.13 on PyPI, and the tag is not on SDK master
feature: api-sdk-mcp
lane: iagent-mesh-sdk/lane/ca-0.9.13
repo: iagent-mesh-sdk
status: open
priority: now
blocked_on: []
pr: []
ruling_ref:
updated: 2026-11-04
---

`v0.9.13:pyproject.toml` line 10 says `version = "0.9.12"`. CI run 41511822566: Test and Build passed, and Publish to PyPI failed with 400 "filename already used". The GitHub Release's assets are named `iagent_mesh-0.9.12*`, with different content from PyPI's 0.9.12. PyPI answers 404 for 0.9.13. The tag is 12 commits ahead of the SDK's origin/master (`050442a`), so it is not an ancestor.

What it breaks: a closed-network `meshSdkSource: index` install of `iagent-mesh==0.9.13`, and any pod's `importlib.metadata` version, which reports 0.9.12. A git pin works.

A pushed tag is not rewritten, so this asks for a patch release with the version fixed, landed on SDK master. #247 pins v0.9.13 meanwhile (01M6A9QDN1M16XMBNHHWVK9EHJ); moving it to the patch is one commit.
