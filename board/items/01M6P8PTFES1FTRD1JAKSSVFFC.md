---
title: The chart serves policy/classification/levels.yaml to dag-tools as a ConfigMap (ADR-0064 ruling a)
feature: cross-cutting
lane: invincible-agent/lane/gov
repo: invincible-agent
status: blocked
priority: later
blocked_on: [chris:name the chart version for the 0.4.79/0.4.80 split (#267)]
pr: []
ruling_ref: architect via Chris 11-05 (a) one levels file, owned by policy; dag-tools reads the deployment's copy (ConfigMap from the chart)
updated: 2026-11-05
---

Ruling (a): "dag-tools never ships its own — it reads the deployment's copy (ConfigMap from the chart), so code reads what the server serves." The file is `policy/classification/levels.yaml` (01M6N17JBZK14V4MTTEQQ3HYWZ, #268).

Today policy files reach pods only baked in the image at `/app/policy`. No ConfigMap carries one, and `.Files.Get` cannot read outside the chart directory. So the file is copied into `helm/invincible-agent/files/` with a drift seal, as the sql and broker files are, and a ConfigMap serves it to whatever runs dag-tools. That is a `helm/**` change, so it waits on the chart version for #267's 0.4.79/0.4.80 split. Which pod mounts it, and at what path, is dag-tools' to say when step 5 has a reader.
