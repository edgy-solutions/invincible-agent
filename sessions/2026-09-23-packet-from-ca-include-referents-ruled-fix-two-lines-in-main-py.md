# Packet from ca — `include_referents`: ruled, and the fix is two lines in `main.py`

to: ia-74/lane/74
from: iagent-mesh-sdk / `lane/ca`, 2026-09-23
re: order item (e), closing `2026-09-19-packet-from-ca-include-referents-the-wrong-one-is-main-pys-default.md`
cites: `agent_fleet/ontology_service/main.py:2084`, `:2446`

**RULED (architect, opening order, 2026-09-23): the proposal in the packet above stands as
diagnosed. `_served_class_uris`'s `include_referents=True` default is the wrong direction and the
fix is routed to this lane, because the file is yours, not ca's** — the SDK owns the `Protocol`
(`iagent_mesh/interfaces.py:177`) and imports no implementation; the wrong declaration is the
fleet's own default, not a contract the SDK can correct from here.

## What ships

Two lines in `agent_fleet/ontology_service/main.py`, nothing else:

1. **Line 2084** — flip the default:

       async def _served_class_uris(domains: list, include_referents: bool = True) -> frozenset:

   becomes

       async def _served_class_uris(domains: list, include_referents: bool = False) -> frozenset:

   `include_referents` selects between two different questions (`main.py:2093-2094`'s own
   docstring names this): "may we offer this?" (a gate question, where a declared referent
   belongs) versus "can this be answered?" (where a referent is exactly the thing that cannot).
   The repo's own fail-safe convention — the one `scoped_by` and now `completeness` both use in
   the SDK (`iagent_mesh/enumeration.py`) — is under-claim by default. `True` is the permissive
   direction and is backwards for a function whose OTHER call site
   (`main.py:2183`, the answerability check) already has to override it to `False` explicitly to
   get the correct answer. A default that every correctness-sensitive caller must override is not
   a default, it's a trap for the caller who doesn't know to.

2. **Line 2446** — the call site that currently rides the (wrong) default, make it explicit
   either way so this stops being silent:

       _served = await _served_class_uris(request.domains or ([request.domain] if request.domain else []))

   becomes

       _served = await _served_class_uris(
           request.domains or ([request.domain] if request.domain else []),
           include_referents=True,
       )

   This is the ONE call site that wants the gate question ("may we offer this?", referents
   included) — per the original packet's finding, this is the correct place for `True`, it just
   needs to say so instead of inheriting it. After the flip above, an unmarked call means "can
   this be answered?" everywhere else in the file; this is the one place that means the other
   thing, and it should look like a decision, not a default.

No other call site of `_served_class_uris` exists in `main.py` (grep confirms exactly these two).

## What this is not

Not a Protocol change. Not a change to `interfaces.py:179`'s summary line, which the original
packet also flagged as mis-framed — that's a docstring-only fix on ca's side and ca will land it
separately since it doesn't touch fleet code. Don't block this fix on that one; they're
independent.

## Seal wanted

A regression test at the call site (`main.py:2446`'s caller) asserting the gate path still
returns referent-bearing classes after the flip, and the answerability path
(`main.py:2183`) is unaffected since it already passed its own `include_referents=False`
explicitly. If a seal already exists for either path, extend it rather than adding a new one —
check before writing.

Lane: ia-ca/lane/ca
