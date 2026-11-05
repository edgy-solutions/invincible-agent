"""A flow decomposition: a signed amount split down a hierarchy into an edge table.

    flow_edges(root=..., paths=[((level_1, ..., level_n), amount), ...], other_threshold=...)

The module knows nothing about what the levels or the amount mean. Each input path is the tuple of
level values below the root, with the signed amount that sits at its end; the answer is the edges
of the tree those paths form.

NODES ARE PATHS. A node is `[root]`, then `[root, v1]`, then `[root, v1, v2]` and so on, so two
nodes that share a name under different parents stay two nodes. The signed value of a node is the
exact sum of the amounts beneath it.

EDGES. One per (parent, child): `{source, target, value, sign, level, node_kind}`. `source` and
`target` are the two paths (lists of strings), `value` is the ABSOLUTE signed sum of the child
(Decimal), `sign` is `"positive"`, `"negative"` or `"zero"` (the sign of the child's signed net),
`level` is the child's depth (1 for the root's children), and `node_kind` is `"other"` for the sink
edge the collapse emits and `"item"` for every other edge. One more edge carries the root: `source`
None, `target` `[root]`, `level` 0, and the root's net (ruled 2026-11-04), so the total is data and
every node, the root included, has exactly one incoming edge. The sink is marked by
`node_kind`, never recognised by its label; its path element is `OTHER_LABEL`, which is for display.
A child whose signed sum is exactly zero IS emitted (`value` 0, `sign` "zero", `node_kind`
"item") and its subtree is walked as usual, because its own children can be nonzero and offset; a
renderer draws no band for it. That keeps every level reconcilable.

CONSERVATION is the invariant: at every node, the signed children (the sink included) sum to the
node's signed value (a zero edge adds nothing, and is still there to be read).

THE COLLAPSE. A child's share is its absolute value over the sum of its siblings' absolute values
(a parent whose children sum to zero in absolute value collapses nothing). Zero-net siblings are
outside the collapse: they are not in that total, never fall below, and do not count toward the
two. When TWO OR MORE siblings fall below `other_threshold`, they are replaced by one
`[..parent, OTHER_LABEL]` child carrying their signed sum (emitted even when that sum is exactly
zero, with sign "zero"), and that child is terminal. A lone sibling below the threshold keeps its
name, because a sink of one only renames it. A threshold of 0 collapses nothing. A real child that
is itself named `OTHER_LABEL`, under a parent that also gets a sink, is refused: the two nodes
would share a path.

ORDER is deterministic: by level, then source, then value descending, then target.

PURE AND DECIMAL. Nothing is read or written, and the module imports nothing outside the standard
library (the measure-row loader refuses a module that does). `VERSION` is the string the row must
match and the string that travels beside the figure under ADR-0053 section 5.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Sequence

VERSION = "1.3.0"
OTHER_LABEL = "All other"


class SinkLabelClash(ValueError):
    """A real child is named `OTHER_LABEL` under a parent that also gets a sink."""


def flow_edges(
    *, root: str, paths: Sequence[tuple[tuple[str, ...], Decimal]], other_threshold: Decimal,
) -> list[dict[str, Any]]:
    """The edge table of `paths` under `root`; see the module docstring."""
    children: dict[tuple[str, ...], dict[tuple[str, ...], Decimal]] = {}
    for levels, amount in paths:
        node: tuple[str, ...] = (root,)
        for value in levels:
            child = node + (str(value),)
            bucket = children.setdefault(node, {})
            bucket[child] = bucket.get(child, Decimal(0)) + amount
            node = child

    edges: list[dict[str, Any]] = []

    def emit(source: tuple[str, ...] | None, target: tuple[str, ...], net: Decimal,
             node_kind: str) -> None:
        edges.append({
            "source": None if source is None else list(source), "target": list(target),
            "value": abs(net),
            "sign": "positive" if net > 0 else "negative" if net < 0 else "zero",
            "level": len(target) - 1, "node_kind": node_kind,
        })

    if (root,) in children:
        emit(None, (root,), sum(children[(root,)].values(), Decimal(0)), "item")
    stack: list[tuple[str, ...]] = [(root,)]
    while stack:
        parent = stack.pop()
        sums = children.get(parent, {})
        live = {c: v for c, v in sums.items() if v != 0}
        total = sum((abs(v) for v in live.values()), Decimal(0))
        below = {c for c, v in live.items() if abs(v) < other_threshold * total} if total else set()
        if len(below) < 2:
            below = set()
        elif any(c[-1] == OTHER_LABEL for c in sums):
            raise SinkLabelClash(
                f"a child of {list(parent)} is named {OTHER_LABEL!r}, which is the label of the "
                f"sink that collapses its siblings; the two would share a path")
        for child, net in sums.items():
            if child in below:
                continue
            emit(parent, child, net, "item")
            stack.append(child)
        if below:
            sink_net = sum((live[c] for c in below), Decimal(0))
            emit(parent, parent + (OTHER_LABEL,), sink_net, "other")

    edges.sort(key=lambda e: (e["level"], e["source"] or [], -e["value"], e["target"]))
    return edges
