---
title: Cortex's 50 hand-written capability bindings move to the served menu block, domain by domain
feature: cross-cutting
lane: cortex-ui/master
repo: cortex-ui
status: blocked
priority: later
blocked_on: [01M6M6NCVDMN12NHT7F8R0J5ME]
pr: []
ruling_ref: Chris 2026-11-07: the rule covers the 50 hand-written bindings; scheduled migration, not a retrofit; flow decomposition is the pilot; no new hand-written binding from today. Architect 11-07: no menu constant anywhere. Architect 10-30 standing rule, test 4
updated: 2026-11-07
---

`src/registry/assembleCapabilities.ts` holds 50 hand-written bindings in `DERIVED_BINDINGS`. Each one pairs a `subject_uri` with an archetype class and names its `persona_fit` and `domain_fit`. At cortex `c30a457` they split by `domain_fit` like this:

| domain_fit | bindings |
|---|---|
| DATA_ENGINEERING | 10 |
| SUSTAINMENT | 9 |
| PORTFOLIO_PLANNING | 9 |
| PROGRAM_FINANCE | 8 |
| PRODUCTION_COST | 8 |
| (empty) | 4 |

They are a copy, held in code, of what the server should serve. That breaks test 4 of the 10-30 standing rule ("the registry or declaration the code reads is the one the server serves"). The architect's 11-07 ruling puts the binding in the measure's overlay row, as a `menu:` block, which cortex's menu then reads.

**Ruled, Chris 2026-11-07:**

- The rule applies forward from today. No new hand-written binding is added.
- The 50 existing bindings stay as they are until the pilot is served. This is a scheduled migration, not a retrofit.
- Flow decomposition is the pilot. Its order: Lane 1 adds `mesh:FlowDecomposition` (0.4.82); fin's overlay row declares the `menu:` block; Lane 1 adds the projector row; cortex's menu reads the block.

**Blocked on** `01M6M6NCVDMN12NHT7F8R0J5ME`, FLOW_DECOMPOSITION declared and projected. This item unblocks when that capability's `menu:` block is served and cortex's menu reads it. That is the reader this item reuses.

**After that, domain by domain.** A domain's bindings move when its producer adds the `menu:` block to its overlay rows. For each domain:

1. Cortex reads the served block.
2. A seal checks it against the captured body.
3. Cortex deletes those `DERIVED_BINDINGS` rows, and nothing else.

**Done when** `DERIVED_BINDINGS` is empty and deleted, and no capability binding is spelled in cortex code.
