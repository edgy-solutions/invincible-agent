---
title: variance-drivers phrase routes to fin_variance_analysis, not fin_variance_drivers
feature: finance
lane: 
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: 
updated: 2026-09-23
---

dormant since 09-21; was lane 91's. Regressed from PASS on 'which account is driving the overrun on NP-MERIDIAN'. Lane 01's 09-23 packet to 74: all three retrieval arms rank finVarianceDrivers first, so the defect is downstream of retrieval. No synonym fix made. No routing fix seen on master. Waiting on: invincible-agent/lane/74: 09-23 answer says defect is downstream of retrieval; fix not seen on master.
