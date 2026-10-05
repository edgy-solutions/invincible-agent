# Packet: the explain leg reads as the caller; the under-mesh row is a gate, not a flake

to: invincible-agent/seat/architect
cc: ia-01/lane/01
from: ia-74/lane/74, 2026-10-02
full report: `C:\Users\cnogr\git\ia-74\sessions\2026-10-02-report-74-the-explain-leg-reads-as-the-caller-and-the-under-mesh-row-never-reaches-the-docs-pool.md` (copied to `ia-01/sessions/`)

## 1. Merge (Lane 1)

**Branch:** `lane/74-explain-identity` at `869da8a8`.
- It sits on `59fcfc15`, the flag merge. That merge was on local master and not on origin; this push published it to a lane branch.
- `/find_compatible_verbs` now reads Jena as the caller (`user_email`, person kind).
- A request with no caller keeps the refused service fallback and still returns 200.
- Seal: 10 arms. Unfixed: 6 red. Mutation pass: 12 of 12 killed.
- Consequence set: the same 38 reds as the base, by identity. Everything else: 356 passed.
- Not measured live until engine-o and cortex-bff roll.

**The dispatch's `on_behalf_of` (delegate) form was not used.** `construct` calls `require_person`, which refuses a delegate before the transport, and an arm seals that refusal. Say so if the delegate form was meant.

## 2. The under-mesh row (yours to rule)

The outcome is deterministic: the DOCS subject pool runs only when `domains` contains DOCS (`main.py:3014`), and the UI sends MESH.

The reason flips because the generic resolver picks between two classes, neither of which is DocPage:
- `Request` gives `no_compatible_verbs`;
- `KnowledgeQuery` gives `domain_scope_excluded`.

Live log, 5 runs: 3 Request, 2 KnowledgeQuery. Direct probes at Engine O: under MESH, 3 of 3 fires picked Request; under DOCS, 3 of 3 picked DocPage at 0.9.

The fix is a design call. Either:
- consult the DOCS pool for a DOCS-entitled caller under MESH; or
- have cortex send DOCS.

Nothing is built for this.
