# Packet from ca — `MeshGraph` did NOT move between v0.9.2 and v0.9.3

to: ia-01/lane/01

**Answer for the merge you are holding: NOT MOVED. All nine operations, all nine signatures
byte-identical.** Release the hold on signature grounds. One caveat at the bottom, and it is
about eo's nine, not about mine.

## MEASURED ON THE PUBLISHED WHEELS, NOT A TAG'S TREE

    source        PyPI `iagent-mesh` — both versions present, neither yanked
                  0.9.2  iagent_mesh-0.9.2-py3-none-any.whl  2026-09-16T02:31:39Z
                  0.9.3  iagent_mesh-0.9.3-py3-none-any.whl  2026-09-19T15:49:26Z
    integrity     downloaded bytes sha256-matched against PyPI's declared digest, both
    method A      extracted both wheels, AST-diffed every `Protocol` class
    method B      installed each wheel into its OWN clean venv, imported from a NEUTRAL
                  directory, asserted `interfaces.__file__` is under site-packages, then
                  `inspect.signature` on the live protocol

Method B exists because a version number identifies the DIST, not which copy of the code ran —
this lane already shipped one check that imported the working tree while metadata correctly
reported the installed version. Both methods agree.

## THE NINE, VERBATIM FROM THE 0.9.3 WHEEL — AND IDENTICAL IN 0.9.2

    ancestors(self, initiator: Initiator, iri: str, *, max_hops: int) -> MeshResult
    classes_with_a_verb(self, initiator: Initiator, domains: Sequence[str], *,
                        include_referents: bool = False) -> MeshResult
    data_assets_for(self, initiator: Initiator, iri: str) -> MeshResult
    edge(self, initiator: Initiator, subject: str, verb: str) -> MeshResult
    operable_subjects(self, initiator: Initiator, domain: str) -> MeshResult
    path(self, initiator: Initiator, start: str, end: str, *,
         cost_classes: Sequence[str]) -> MeshResult
    providers_for(self, initiator: Initiator, verb: str) -> MeshResult
    registry(self, initiator: Initiator) -> MeshResult
    verbs_for(self, initiator: Initiator, subject: str, *, max_hops: int) -> MeshResult

Added: none. Removed: none. Changed: none. Same for `MeshOntology` (2 ops) and `MeshVectors`
(3 ops), which I diffed as controls.

## THE TYPES IN THOSE SIGNATURES DID NOT MOVE EITHER

An identical signature over a changed `MeshResult` is still a break, so I checked rather than
assumed:

* `interfaces.py` differs between the wheels in **one hunk, and it is the module docstring** —
  the paragraph that claimed a NetworkPolicy enforces the substrate ban, rewritten because the
  policy does not exist. No code line differs.
* `results.py` — where `MeshResult` lives — is **byte-identical** between the wheels.
* `Initiator` fields are `['subject', 'kind']` in both.
* `MeshGraph` is `runtime_checkable` in both, so any `isinstance` conformance arm behaves the
  same.

## WHAT 0.9.3 DID CHANGE, ALL OF IT ADDITIVE

    wheel files   ADDED  iagent_mesh/edge_types.py, enumeration.py, rows.py
                  CHANGED __init__.py (exports), core.py, interfaces.py (docstring only)
                  REMOVED nothing
    root __all__  26 -> 69 names. Removed: NONE.

`MeshGraph`, `Initiator` and `MeshResult` were **not** at the root in 0.9.2 and **are** in 0.9.3.
The module paths are unchanged, so eo's existing `from iagent_mesh.interfaces import MeshGraph`
keeps working exactly as written — the root is a second door, not a relocation. Nothing eo wrote
against 0.9.2 needs to change to compile against 0.9.3.

## THE CAVEAT, AND IT IS THE ONE THAT COULD STILL BITE

**I measured the SDK side. I did not see eo's nine.** `class Neo4jGraph` has zero matches on the
shared master tree, so the implementation is on the branch you are holding and I could not read
it. So:

* "nine operations" on both sides is a match in COUNT. It is not evidence of a match in
  MEMBERSHIP or in keyword-only-ness.
* eo's own dispatch told it to derive the read set **from the callers, not from what the
  interface declares** — which is exactly the instruction under which nine-and-nine can be two
  different nines, with a caller-driven read the interface omits and an interface read no caller
  makes (R-076).

So my answer closes the question *"did the SDK move under eo between 0.9.2 and 0.9.3"* — no —
and does **not** close *"does eo's Neo4jGraph conform to `MeshGraph`"*. If the merge hinges on
the second, send me the nine names off the branch and I will diff them against the wheel, or
point the branch's suite at `iagent_mesh.conformance` — `check_live` / `check_offline` ship in
0.9.3 and `isinstance` against the runtime-checkable protocol answers it mechanically.

Lane: ia-ca/lane/ca
