"""Write canonical product-structure assertions — provenance-blocked, canonical-only.

ADR-0035 packet 2 step 3. Two boundaries are enforced here, and both are structural rather
than conventional:

1. THE WRITER NEVER SEES SOURCE COLUMNS. It accepts CANONICAL assertions only; mappings feed
   it. A writer that accepted `{"MFG_PN": ...}` would grow a per-source branch the first time a
   source disagreed with another, and then the mapping would live half in a declared contract
   and half in code — which is the state the mapping contract exists to prevent. Sources
   declare; the writer writes.

2. NO ASSERTION LANDS WITHOUT A COMPLETE PROVENANCE BLOCK. Refused at write, loudly. The claim
   that cannot say where it came from doesn't get written.

BUILT BEHIND THE CONTRACT, NOT AHEAD OF IT. The real mappings live where the data lives and do
not cross into this repo. So this module is sealed against a SYNTHETIC mapping that exercises
every degradation the template permits — cannot-populate entries, `unknown` vintage, the
truth-vs-annotation split, and a deliberate disagreeing pair. When a real mapping is filled in
elsewhere, it meets a writer already proven against every shape of lossiness the template can
express, rather than one built around guesses about a source nobody here has seen.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

from .provenance import validate_provenance

# The canonical field surface. A key outside this set is REFUSED rather than passed through:
# an unrecognized field is either a source column that leaked past the mapping (boundary 1
# broken) or a vocabulary addition nobody declared — both worth stopping for.
CANONICAL_FIELDS = {
    "Part": {"partNumber", "revision"},
    "PartUsage": {"parent", "child", "quantity", "referenceDesignator", "applicability"},
    "ManufacturerPart": {"mpn"},
    "ApprovedSourceRelationship": {"forPart", "forManufacturerPart", "qualificationStatus"},
}

PRODUCT_GRAPH_SUFFIX = "_PRODUCT"


class CanonicalAssertionInvalid(ValueError):
    """The assertion is not writable — wrong shape, unknown field, or missing provenance."""


def product_graph(domain: str = "SUSTAINMENT") -> str:
    """A DEDICATED runtime graph, never the vocabulary graphs and never prime.

    Product assertions are non-reproducible runtime output with a different reproducibility
    class than the ontologies that describe them. Mixing producers of different reproducibility
    into one graph is the mistake the collision incident already charged for once.
    """
    return f"http://internal/{(domain or 'SUSTAINMENT').strip().upper()}{PRODUCT_GRAPH_SUFFIX}"


def validate_canonical(assertion: dict) -> None:
    """PURE. Refuse anything that is not a well-formed canonical assertion with provenance."""
    if not isinstance(assertion, dict):
        raise CanonicalAssertionInvalid("assertion must be a dict")
    kind = assertion.get("kind")
    if kind not in CANONICAL_FIELDS:
        raise CanonicalAssertionInvalid(
            f"unknown canonical kind {kind!r} — expected one of {sorted(CANONICAL_FIELDS)}")
    fields = assertion.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise CanonicalAssertionInvalid(f"{kind}: fields must be a non-empty dict")
    unknown = set(fields) - CANONICAL_FIELDS[kind]
    if unknown:
        raise CanonicalAssertionInvalid(
            f"{kind}: {sorted(unknown)} are not canonical fields. Either a SOURCE COLUMN leaked "
            f"past the mapping — the writer must never see one — or the vocabulary grew without "
            f"the mapping template being updated. Both are worth stopping for")
    try:
        validate_provenance(assertion.get("provenance"))
    except Exception as exc:  # noqa: BLE001
        raise CanonicalAssertionInvalid(
            f"{kind}: {exc}. An assertion without complete provenance is refused at WRITE — "
            f"discovering it at query time means the graph already holds claims nobody can place")


def write_assertions(assertions: Iterable[dict], *, writer: Callable[[dict], Any],
                     domain: str = "SUSTAINMENT") -> dict:
    """Validate every assertion, then hand each to `writer`. ALL-OR-NOTHING on validation.

    Validation runs over the WHOLE batch before anything is written, so a malformed assertion
    halfway through cannot leave a half-ingested source in the graph — a partial product
    structure is worse than none, because the missing rows are indistinguishable from parts
    that genuinely have no usage.
    """
    batch = list(assertions)
    for a in batch:
        validate_canonical(a)                      # raises before any write
    graph = product_graph(domain)
    written = 0
    for a in batch:
        writer({**a, "graph": graph})
        written += 1
    return {"ok": True, "written": written, "graph": graph}


def unmappable_report(mapping: dict) -> list:
    """What this source CANNOT say, read straight off its declared contract.

    Exists so the degradation is queryable from the mapping alone, before a single row is
    ingested — you can tell what a source will be unable to tell you without running it.
    """
    return [
        {"field": e.get("field", ""), "reason": e.get("reason", "")}
        for e in (mapping.get("cannot_populate") or [])
    ]


def as_of_for(mapping: dict, *, row_value: Optional[str] = None) -> str:
    """The truth-date this source can honestly claim for a row.

    Returns the `unknown` SENTINEL rather than a blank or a guess. In particular it refuses the
    tempting fallback of using ingest time as truth time unless the mapping explicitly declares
    that they are the same — which is true only for a direct read. For any export or copy,
    substituting ingest time would make a stale mirror look live, and that is the single most
    consequential lie this model can tell.
    """
    from .provenance import AS_OF_UNKNOWN

    strategy = (mapping.get("as_of") or {}).get("strategy") or "unknown"
    if strategy == "unknown":
        return AS_OF_UNKNOWN
    if strategy == "ingest-time-is-truth-time":
        if not (mapping.get("as_of") or {}).get("ingest_time_is_truth_time"):
            return AS_OF_UNKNOWN
        return row_value or AS_OF_UNKNOWN
    return row_value or AS_OF_UNKNOWN
