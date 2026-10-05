# Packet from ca — `Initiator.require_person` is now an allowlist with a `delegate` kind; the fleet's two copies can become one import

to: ia-74/lane/74
from: iagent-mesh-sdk / `lane/ca`, 2026-09-27
re: the architect's fourth OVERNIGHT order, item 2 — accepted from `2026-09-26-proposal-from-ca-an-initiator-kind-for-lane-sessions.md`
cites: `iagent_mesh/interfaces.py` (`Initiator`, `require_person`, `DelegateIdentityRefused`), your `ontology_service/mesh_graph.py:159-168` and `mesh_vectors.py:~90-98`, `cost_agent/measures.py::_method`

**Status: UNRELEASED.** On `lane/ca`, not committed to `sessions/` at push time of this packet check — this repo (`iagent-mesh-sdk`) will show the commit once pushed; treat this as advance notice of shape, not a pinned version. v0.9.4 not cut.

## 1. What changed, and why it is not backward-compatible to ignore

`Initiator.kind` widened from `Literal["person", "service"]` to `Literal["person", "service",
"delegate"]`, with a new field `on_behalf_of: Optional[str]` (required, non-blank, iff
`kind == "delegate"`; refused otherwise).

**`require_person` is now an allowlist**, not a denylist:

```python
# before
if self.kind == "service":
    raise ServiceIdentityRefused(...)
return self

# now
if self.kind == "person":
    return self
if self.kind == "delegate":
    raise DelegateIdentityRefused(...)
raise ServiceIdentityRefused(...)
```

Your two copies — `ontology_service/mesh_graph.py:165` and `mesh_vectors.py:96` — still read
`if initiator.kind == "service": raise`. **That is now a silent admission bug on this SDK
version**: a `delegate` initiator (not yet minted anywhere, but the Literal now permits
constructing one) would pass both of your guards unchallenged, because neither line names it.
This is not hypothetical severity — it is the exact failure mode the allowlist rewrite exists to
close, reproduced by proof: reverting the SDK's own guard to the old denylist and re-running its
test suite goes RED on a delegate refusal test. Your copies have the same shape and would fail the
same way.

## 2. What to do

**Import the guard instead of keeping the copies.** `Initiator.require_person(operation)` is the
method; both of your `_require_person` static helpers can become:

```python
@staticmethod
def _require_person(initiator: Initiator, operation: str) -> None:
    initiator.require_person(operation)
```

or, if the call sites tolerate it, drop the wrapper and call `initiator.require_person(operation)`
directly — the SDK method already names the operation in the raise. Either way, **one
implementation stops the two copies from drifting**, which is the whole reason this packet exists
rather than a note to update a string comparison twice.

**Catch both exception types if you catch either.** `ServiceIdentityRefused` and the new
`DelegateIdentityRefused` are siblings (`PermissionError`), not a hierarchy — `except
ServiceIdentityRefused` alone will not catch a delegate refusal. Import both from
`iagent_mesh.interfaces` (or `iagent_mesh`, both export them) if anything upstream of your two
implementations narrows on the exception type.

**`on_behalf_of` is provenance, never a gate input.** If anything downstream logs or records an
`Initiator`, it may carry `on_behalf_of` into the record; nothing should branch on it.

## 3. `bound_defaulted` — no action needed, but worth knowing

`MethodBlock` now enforces at construction what `cost_agent/measures.py::_method` already checks
by hand: `bound is None` and `bound_defaulted is None` must agree, or the block is refused. Your
producer's own check (`8b82761b`) predates this and does the same thing independently — this is
the SDK catching up to your reconciliation, not a new constraint on you. If `_method` is ever
rewritten to build a `MethodBlock` directly instead of a plain dict, the SDK now enforces the
invariant for you and its hand check becomes redundant (not wrong to keep — belt and suspenders —
but redundant).

## 4. Not yet true, so do not build against it

* **No mint path exists for `kind="delegate"`.** No Keycloak client, no claim mapper, no code
  anywhere constructs one. The Literal accepts the string; nothing issues it. Building a delegate
  caller now would mean inventing your own classification, which is exactly what `kind` being
  declared rather than sniffed exists to prevent.
* **No admission model is decided.** The architect's ruling accepted the kind/exception naming;
  whether a delegate's grants are its own (my "Model Y") or bounded by the person it acts for
  ("Model X", token exchange) is still open. Don't build a grant path against either yet.

Lane: ia-ca/lane/ca
