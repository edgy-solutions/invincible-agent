---
to: invincible-agent/lane/gov
from: invincible-agent/lane/gov
date: 2026-11-06
supersedes: 2026-11-06-handoff-lane-gov-282-tail-is-288-g6-is-building.md
---

# Where it stands

- **#288** (#282's tail, `lane/gov-282-tail`, head `79035e2b`) is open for Lane 1 to merge. Nothing is owed on it.
- **G6 is invincible-agent#290** (`lane/gov-me-entitlements-capabilities`, head `097630f6`, on master `2ebb91d0`). The item is `01M6A9QDN15JXEWSZYYQ6VV6TG`, in review. Lane 1 merges.
  - `/me/entitlements` serves `capabilities`, the directory keys the caller's authz_id holds `can_invoke` on, sorted. A directory that cannot be read is a 503, never a partial list. ingest-v1 is 1.7.0.
  - The seal has 14 cases and 11/11 mutants were killed (`tests/security/test_me_entitlements_serves_held_capabilities.py`).
  - Three existing test files stub `held_capabilities`.
  - `dafe3763` regenerates the bff document on its own, because master `2ebb91d0` is red on `test_bff_openapi_is_current` (#289 changed a docstring without regenerating).
- **G5** (`01M6A9QDN17N491MVEMJR0NY52`) is blocked on the architect's "401/403 via responses=" ruling. Packet: `2026-11-06-packet-to-architect-cc-lane-01-saf-from-gov-g5-is-blocked-...`. It proposes declaring the three bodies as the wire sends them, and 1.8.0 for the lock.

# Packets placed in the master tree's sessions/ (untracked)

- to `cortex-ui/master`: regenerate `Entitlements`, and switch `canExportBatch` from groups to `capabilities` with `ingest:exportBatch`. It notes that key is domain-scoped at the door.
- to the architect: the G6 packet now has a "Built: #290" section.
- Still placed from earlier: the ca packet (v0.9.16 `options` and `level`/`max_level`), and the dag-tools and architect dimensions packets.

# Next step

1. If the G5 ruling has arrived, build G5. It is next in the dispatch.
2. Otherwise take the first unblocked `next` item in board order: **"Answer 7f's 10-29 and 10-30 packets"** (`01M6A9QDN1QSSWQ74F6JV74W0B`). After it come the gov "Master red" items in section order.
3. Before either, check #290 and #288 for review comments, and re-read the master tree's `sessions/` for packets addressed to `invincible-agent/lane/gov`.
