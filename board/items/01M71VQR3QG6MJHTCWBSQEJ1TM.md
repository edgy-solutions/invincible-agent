---
title: A declared or dataset-kind panel in a package is a 503 from the builder
feature: finance
lane: invincible-agent/lane/fin
repo: invincible-agent
status: open
priority: next
blocked_on: []
pr: []
ruling_ref: Chris 2026-11-09 (fin source ruling) — a board item, not a blocker
updated: 2026-11-09
---

`/package_export` refuses a canvas carrying a declared (overlay row) or dataset-kind panel with a
503 from `scripts/build_fin_package.py`, naming the panel, and writes nothing. The page recomputes
every panel in the browser with its embedded `measures.py`, which holds only the built-ins, so it
cannot reproduce a declared or dataset-kind panel and the builder's `page.verify` refuses.

Done when such a panel can ride in a package, which needs the page to carry what recomputes it (the
row's module, or the dataset rows it reads), and the 503 is gone for it. With the flag unset a
dataset-kind panel was a 409 and is now this same 503.
