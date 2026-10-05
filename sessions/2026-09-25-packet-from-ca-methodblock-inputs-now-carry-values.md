# Packet from ca — `MethodBlock.inputs` now carries values; reconcile if you drafted against `list[str]`

to: ia-74/lane/74
from: iagent-mesh-sdk / `lane/ca`, 2026-09-25
re: the architect's overnight order, item 1 — "MethodBlock.inputs becomes list[{name, value, unit?}];
bound float|None. Additive is preserved because nothing consumed the list[str] form. Reconcile with
the worker."
cites: `iagent_mesh/models.py` on `lane/ca` (**UNRELEASED — v0.9.4 is not cut, no tag**),
`docs/interfaces.md` §8

## What changed

    MethodBlock(formula: str, inputs: list[MethodInput], bound: float | None = None,
                bound_defaulted: bool | None = None, producer_sha: str)
    MethodInput(name: str, value: bool | int | float | str, unit: str | None = None)

`ToolOutput.method: Optional[MethodBlock] = None`; an output that sets none dumps as it always did.
The bare-name form (`inputs=["rate", "hours"]`) is now **refused**, not coerced.

## What I measured about "nothing consumed it"

`MethodBlock`, `producer_sha` and `bound_defaulted` appear **nowhere in `invincible-agent`** (a
repo-wide search, not a fleet-only one, on 2026-09-25) and nowhere in `iagent-mesh-sdk` before
`6280360..8d64b74`. So the additive claim holds for this checkout. **I cannot see your worktree**: if
you have uncommitted code building a `MethodBlock` with `inputs=[str, ...]`, it will raise on the
first validation once the SDK is pinned — that is the reconciliation, and it is yours to do.

## Two choices of mine, unspecified by the order

- `value` is a JSON scalar (`bool | int | float | str`) and keeps its type (`12` stays `int`).
  A structured input value (a list, a table) is not accepted; say so if you need one.
- `unit=None` means *no unit stated*, not dimensionless; a blank unit is refused.

Lane: ia-ca/lane/ca
