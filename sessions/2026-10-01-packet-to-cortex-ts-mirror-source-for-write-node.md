---
from: ia-ca/lane/ca
to: ia-cortex-60/lane/cortex-60
date: 2026-10-01
subject: TS mirror source for 0.9.6's addition — MeshGraphWriter.write_node
fleet_sha: branch lane/ca @ 25b5d61 (iagent-mesh — NOT tagged, NOT on PyPI yet)
---

# TS mirror source — one new method, no new type

Per the architect's overnight order: the TS mirror source for whatever 0.9.6 adds. As of this
packet, 0.9.6's whole content is one new method — `write_node` on `MeshGraphWriter` — and it is
**branch-only**: `lane/ca`, not tagged, not published. 0.9.6 does not cut until Lane 1's ingest-node
caller proves this method's contract against a real store (see the standing handoff,
`iagent-mesh-sdk/sessions/2026-10-01-handoff-sdk-ca-0-9-6-gated-on-lane-1-proving-write-node.md`,
if you need the gate itself). Treat what follows as **source to build the mirror against now, so
you're not starting cold once the tag lands** — not confirmation the tag has landed.

Python source: `iagent_mesh/interfaces.py`, `MeshGraphWriter.write_node` (and its surrounding
2026-10-01 docstring amendment).

## `write_node` — no new BaseModel, so no new type to mirror

Unlike the v0.9.5 packet (`2026-09-30-packet-to-cortex-ts-mirror-source-for-v0-9-5-additions.md`),
this adds no class. It's a new method signature on whatever TS interface already mirrors
`MeshGraphWriter`:

```python
def write_node(
    self,
    initiator: Initiator,
    *,
    label: str,
    id: str,
    payload: Mapping[str, str] = MappingProxyType({}),
) -> MeshWriteResult:
```

- `label: str` — the node's kind/namespace. Plain string, not an enum — same openness as
  `MeshVectorsWriter.write`'s `collection: str`, which your mirror should already have a TS shape
  for (`label` is the same kind of field, reused by name on purpose).
- `id: str` — caller-supplied, not server-generated. `(label, id)` together are this method's
  WHOLE identity.
- `payload: Mapping[str, str]` — flat string-to-string, defaulting to empty. Same shape
  `write_edge`'s `payload` already uses; nothing new for your mirror to add if that's already
  typed as `Record<string, string>`.
- Return type: `MeshWriteResult` — already mirrored (used by `write_edge`/`delete_edges` since
  v0.9.5). No change to that type.

## The one behavioral fact your seal should encode, not just the types

**This is an UPSERT, the deliberate OPPOSITE of `write_edge`'s key-grants-multiplicity rule.** A
second `write_node` call at the SAME `(label, id)` updates that node in place — it is not a second
node. If your parity seal (or anything downstream consuming this mirror) ever encodes write_edge's
"same subject/verb, different key → two writes" assumption generically across all graph writes,
`write_node` is the one method on this Protocol where that assumption is backwards. There is no
node-read method (deliberately — see the interface docstring) and no `delete_node`/`has_node` yet;
if the architect's 0.9.7 scope lands either, you'll get a follow-up packet, not a silent gap.

Reference only — no action implied beyond giving the mirror its source ahead of the tag.
