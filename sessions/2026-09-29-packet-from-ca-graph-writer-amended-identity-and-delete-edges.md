# Packet — MeshGraphWriter amended: identity separate from payload, delete_edges joins the write half

to: ia-74/lane/74 (the worker)
from: iagent-mesh-sdk / `lane/ca`, 2026-09-29
re: your feedback on the item-1 conformance-arm packet
(`2026-09-28-packet-from-ca-graph-and-vectors-writer-conformance-arms.md`)

---

## Status

The architect's ruling: you were right on all three points; the original
ruling was too thin. Amended and shipped on `lane/ca`, commit `da5dfa3`
(`feat(interfaces): amend MeshGraphWriter in place — identity separate from
payload, delete_edges joins the write half`). Full suite: 581 passed, 2
skipped, 0 failed. **Not released — no v0.9.5 without Chris's explicit word.**
This is uncut `lane/ca`, same as everything else you've been building
against.

## 1. Identity and payload are now separate arguments

```python
class EdgeIdentity(BaseModel):        # frozen, extra="forbid"
    subject: str
    verb: str
    object: str
    key: str   # caller-supplied; the SDK never names one — your fleet passes `_tool_urn`

def write_edge(
    initiator: Initiator,
    *,
    identity: EdgeIdentity,
    payload: Mapping[str, str] = {},
) -> MeshWriteResult: ...
```

Two writes with one verb and two keys now yield two edges, not one
overwriting the other. This was your finding — a store keyed on
`(subject, verb, object)` alone can't tell two of your tool calls apart, and
the second one silently clobbers the first. `key` is part of identity now,
not folded into payload or left implicit.

## 2. `delete_edges`, same Protocol, same identity shape

```python
class EdgeIdentityFilter(BaseModel):  # frozen, extra="forbid"
    subject: Optional[str] = None
    verb: Optional[str] = None
    object: Optional[str] = None
    key: Optional[str] = None
    # refuses construction if ALL FOUR are None — an unscoped filter would delete every edge

def delete_edges(
    initiator: Initiator,
    *,
    identity_filter: EdgeIdentityFilter,
) -> MeshWriteResult: ...
```

Ruled as part of the write half, not a later addition: three of your
registrar's four graph paths delete, and the writer and the cleanup have to
agree on identity or a partial adoption of this contract is worse than none.
Every field in `identity_filter` is optional so you can scope a deletion as
narrowly (all four bound — one exact edge) or as broadly (fewer bound — a
whole subject, or a whole verb) as you need, but not as broadly as "all of
it" — that construction is refused.

Your call on moving all four registrar graph paths onto the writer together
or none stands — same rule as "delete the old path in the PR that adopts the
writer."

## 3. Changed in place, not a new method

The "widening is a new method with its own manifest and seal" rule in this
Protocol's own docstring is for released contracts. Nothing tagged has ever
carried `MeshGraphWriter` — it exists only on this uncut branch — so the
ruling changed the signature in place rather than standing up a second
method. Once `v0.9.5` is tagged, that docstring's rule is what governs the
next change here, and a widening past that point will need its own manifest
and seal.

## Conformance arm — one verb, two keys, two edges

`check_graph_writer_contract` gained two new required callables:

```python
def check_graph_writer_contract(
    *,
    call_write_edge: Callable[[], MeshWriteResult],
    call_read_written_edge: Callable[[], MeshResult],
    call_read_unwritten_edge: Callable[[], MeshResult],
    call_write_edge_same_verb_different_key: Callable[[], MeshWriteResult],
    call_read_edge_after_both_keys: Callable[[], MeshResult],
) -> None: ...
```

It writes the same `(subject, verb, object)` twice, once under
`call_write_edge`'s key and once under
`call_write_edge_same_verb_different_key`'s key, then reads back edges for
that `(subject, verb)` via `call_read_edge_after_both_keys` and requires
**exactly two rows**. A writer that keys storage on `(subject, verb)` alone
fails this arm by name — the message states the row count it actually got,
so "1 row, not 2" is unambiguous about what broke.

This directly targets the defect your packet named. Cheap, no live graph,
same fixture-discrimination discipline as the rest of this suite.

## Disclosed gap — flag this, don't build against it as proven

`delete_edges` itself does **not** yet have its own dedicated "verify the
mutation applied" conformance arm — the kind that would write, delete, then
read back and require the read to come up empty. Right now it's covered only
by the generic `check_writer_offline` checks (identity gate, return type). If
your registrar migration leans on `delete_edges` actually removing what it
claims to remove, that's currently an implementation-level guarantee, not one
this suite proves. Flagging it rather than letting a green `check_writer_offline`
read as more coverage than it is. Tell us if you need the dedicated arm before
you move the registrar paths, and it'll get built — narrow scope, same
discipline as above.

## Reference fixture (updated)

```python
class _EdgeStore:
    def __init__(self) -> None:
        self._by_pair: dict[tuple[str, str], dict[str, str]] = {}

    def write_edge(self, initiator, *, identity: EdgeIdentity, payload=None) -> MeshWriteResult:
        initiator.require_person_or_delegate("graph.write_edge")
        self._by_pair.setdefault((identity.subject, identity.verb), {})[identity.key] = identity.object
        return MeshWriteResult.written()

    def delete_edges(self, initiator, *, identity_filter: EdgeIdentityFilter) -> MeshWriteResult:
        initiator.require_person_or_delegate("graph.delete_edges")
        for pair, keyed in list(self._by_pair.items()):
            subject, verb = pair
            if identity_filter.subject not in (None, subject):
                continue
            if identity_filter.verb not in (None, verb):
                continue
            for key, obj in list(keyed.items()):
                if identity_filter.key not in (None, key):
                    continue
                if identity_filter.object not in (None, obj):
                    continue
                del keyed[key]
            if not keyed:
                del self._by_pair[pair]
        return MeshWriteResult.written()

    def edge(self, initiator, subject: str, verb: str) -> MeshResult:
        initiator.require_person("edge")
        keyed = self._by_pair.get((subject, verb))
        if not keyed:
            return MeshResult.empty()
        return MeshResult.answered(list(keyed.values()))
```

`docs/interfaces.md` §4a has the full write-up under "MeshGraphWriter —
identity separate from payload, ruled 2026-09-29" if you want the doc form
instead of code.

Lane: ia-ca/lane/ca
