"""Engine-o's `MeshVectors` implementation — the reader half of the marker contract.

**THIS MODULE IMPORTS NO DRIVER.** The Weaviate client and the filter factory are INJECTED, the
same shape `state_sparql` and `sustainment_instance_provider` already use here — which is why this
file can be exercised by a test where `main.py` needs a stub harness. The driver stays in
`main.py`, which is the one place engine-o is entitled to hold one.

WHAT THE CONTRACT ASKS FOR, and where each part lives:

    identity is an argument         every operation takes `Initiator` and REFUSES `kind="service"`
    the return says WHETHER         MeshResult: answered | empty | failed | unreachable
    the return says HOW             `mode`: "hybrid" when the vector was used, "bm25" when the
                                    embedding endpoint failed and we degraded — never silent
    the implementation owns embed   `embedding_model` is the SERVED identity from the response,
                                    never `DEFAULT_EMBED_MODEL`
    the marker is checked AT OPEN   once per collection, before the first search

**MOVED TO `marker_predates_collection` AT `v0.9.2`**, the release that renamed it. (The
fleet pin moved on past it — v0.9.3 on 2026-09-19 — so this line says WHERE THE RENAME
HAPPENED and no longer claims to name the current pin; the appositive was true when
written and the next pin falsified it without touching this file.) It was
`marker_is_stale` — a name asserting a CONCLUSION the predicate cannot reach, since what it
computes is *absent-or-older-than-the-oldest-object*. The old name survives as a deprecating alias
**only until this caller moved**, which is now: expand/contract with a live consumer, and this lane
was the consumer. The alias can contract in the next release.

**WHAT THIS READER CANNOT PROVE, stated because a populated field invites the opposite inference:**
a non-stale verdict is UNPROVEN, never freshness. doc-tools replaces objects on deterministic
UUIDs and Weaviate preserves `creationTimeUnix` across a replace — measured 2026-09-15, 132 of 132
`Predicate` rows carried an update later than their creation, the widest gap 81 days. So the
oldest-object proxy does not move while the vectors underneath are rewritten.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

from iagent_mesh.interfaces import (  # noqa: F401 — CollectionMarker is part of the surface
    CollectionMarker,
    CorruptCollectionMarker,
    Initiator,
    MESH_COLLECTION_META,
    ServiceIdentityRefused,
    marker_predates_collection,
    read_collection_marker,
)
from iagent_mesh.results import MeshResult

#: The vocabulary THIS interface declares. Conformance asserts an implementation emits only these,
#: which is why the pair lives here rather than in a central enum nobody owns.
MODES = ("hybrid", "bm25")


class MarkerMismatch(RuntimeError):
    """The collection was written by a different model than this reader embeds with.

    A REFUSAL NAMING BOTH, at open, before a single search. Opening anyway would search a space
    the query vector does not live in and return plausible neighbours — the failure this whole
    mechanism exists to end, and the one that looks like a working system.
    """


class WeaviateVectors:
    """`MeshVectors` over an injected Weaviate client."""

    MODES = MODES

    def __init__(
        self,
        *,
        client: Any,
        embed: Callable[[str], Any],
        filters: Any,
        fetch_marker: Optional[Callable[[str], Optional[dict]]] = None,
        oldest_object_unix_ms: Optional[Callable[[str], Optional[int]]] = None,
        report: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._client = client
        self._embed = embed
        self._filters = filters
        self._fetch_marker = fetch_marker
        self._oldest = oldest_object_unix_ms
        self._report = report or (lambda _m: None)
        self._opened: dict[str, None] = {}
        self._embedding_model: Optional[str] = None

    # ── identity ────────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _require_person(initiator: Initiator, operation: str) -> None:
        """A service identity is refused at the boundary.

        Not sniffed from the subject's spelling — `kind` is declared at the edge that minted the
        token, and parsing a subject is the rule this one exists beside, not a cheaper version
        of it.
        """
        if initiator.kind == "service":
            raise ServiceIdentityRefused(
                f"{operation}: a read attributed to a service records provenance no person can "
                f"be asked about (subject={initiator.subject!r})"
            )

    # ── the embedding contract ──────────────────────────────────────────────────────────────

    @property
    def embedding_model(self) -> str:
        """The model this implementation ACTUALLY embeds with, observed rather than declared.

        `None` until the first observation: a reader that answers before it has embedded anything
        would be reporting its constant, which is the whole defect.
        """
        return self._embedding_model or ""

    # ── open ────────────────────────────────────────────────────────────────────────────────

    def _ensure_opened(self, collection: str, observed_model: str, observed_dim: int) -> None:
        """Verify the marker ONCE per collection, before the first search.

        THREE STATES, and the third is the one that bites:

            matching      open
            mismatching   REFUSE, naming both
            absent        open, and REPORT THE GAP ONCE

        Absent must never be silently treated as matching. Readers land before writers, so absent
        is the normal early state — and a tolerance that says nothing is indistinguishable from a
        check that passed.
        """
        if collection in self._opened:
            return

        raw = self._fetch_marker(collection) if self._fetch_marker else None
        try:
            marker = read_collection_marker(raw)
        except CorruptCollectionMarker as exc:
            # OURS AND UNREADABLE is a FAILURE, not a gap. Nobody-wrote-one and
            # something-wrote-ours-badly want opposite behaviours.
            raise MarkerMismatch(
                f"{collection}: the collection marker is present and unreadable ({exc}). "
                f"A malformed marker is not an absent one."
            ) from exc

        if marker is None:
            self._report(
                f"{collection}: no {MESH_COLLECTION_META} marker — the collection cannot say which "
                f"model produced its vectors. Opening with model={observed_model!r}; this is a GAP, "
                f"not agreement."
            )
        else:
            if marker.model != observed_model:
                raise MarkerMismatch(
                    f"{collection}: written with model={marker.model!r} "
                    f"(version={marker.version!r}, by={marker.written_by!r}); this reader embeds "
                    f"with model={observed_model!r}. Refusing before the first search."
                )
            if marker.dimension != observed_dim:
                raise MarkerMismatch(
                    f"{collection}: marker declares dimension={marker.dimension}, this reader "
                    f"produced {observed_dim}. The vectors and the query do not share a space."
                )
            oldest = self._oldest(collection) if self._oldest else None
            if marker_predates_collection(marker, oldest):
                self._report(
                    f"{collection}: the marker predates the collection's oldest object — it may "
                    f"describe vectors that no longer exist. Treating as ABSENT."
                )
        self._opened[collection] = None

    # ── operations ──────────────────────────────────────────────────────────────────────────

    def collection_present(self, initiator: Initiator, *, collection: str) -> MeshResult:
        """Is the collection there at all — the guard that separates *nothing matched* from
        *nothing to match against*."""
        self._require_person(initiator, "collection_present")
        try:
            present = bool(self._client.collections.exists(collection))
        except Exception as exc:  # the substrate could not be asked
            return MeshResult.unreachable(f"collection_present({collection}): {exc}")
        return (
            MeshResult.answered([{"collection": collection, "present": True}])
            if present
            else MeshResult.empty()
        )

    def nominate(
        self,
        initiator: Initiator,
        *,
        collection: str,
        text: str,
        domains: Sequence[str] = (),
        limit: int = 10,
    ) -> MeshResult:
        """Candidate rows for a phrase, within one collection and across the given domains.

        `domains` IS A SEQUENCE and the singular form would be a regression: both live call sites
        scope by an entitlement LIST, and a per-domain loop would return separately-ranked results
        whose scores are not comparable across calls.
        """
        self._require_person(initiator, "nominate")

        try:
            if not self._client.collections.exists(collection):
                return MeshResult.empty()
        except Exception as exc:
            return MeshResult.unreachable(f"nominate({collection}): {exc}")

        # ── the embedding, and the identity that came with it ──
        mode = "hybrid"
        try:
            obs = self._embed(text)
            vector = list(obs.vector)
            self._embedding_model = obs.served or obs.requested
            observed_dim = obs.dimension
        except Exception as exc:
            # A DEGRADED RETRIEVAL IS A MARKED SUCCESS, NEVER AN UNMARKED ONE. The fleet ran
            # sixty-seven days BM25-only with nothing in any result saying so.
            mode, vector, observed_dim = "bm25", None, 0
            self._report(f"nominate({collection}): embedding failed, degrading to bm25 ({exc})")

        if vector is not None:
            try:
                self._ensure_opened(collection, self._embedding_model or "", observed_dim)
            except MarkerMismatch as exc:
                return MeshResult.failed(str(exc), mode=mode)

        try:
            rows = self._search(collection, text, vector, domains, limit)
        except Exception as exc:
            # A MID-QUERY FAILURE IS A REFUSAL, NEVER AN EMPTY SUCCESS — an empty list here means
            # "nothing matched", and a caller that cannot tell the two apart reads a substrate
            # outage as a confident zero.
            return MeshResult.failed(f"nominate({collection}): {exc}", mode=mode)

        return MeshResult.answered(rows, mode=mode) if rows else MeshResult.empty(mode=mode)

    # ── the query itself ────────────────────────────────────────────────────────────────────

    def _domain_filter(self, collection: str, domains: Sequence[str]) -> Any:
        """One rule, expressed per collection's own property shape.

        ADR-0009 keeps domain-agnostic predicates visible to scoped callers — the OR of
        `domains contains_any [entitled]` and `domains == []` — and that branch is load-bearing:
        27 of 129 predicates carry no domains (measured 2026-09-14), a fifth of the routing table.
        The class collection has no such branch and needs none: all 21,547 rows carry a domain.
        """
        scoped = [d.upper() for d in domains if d]
        if not scoped:
            return None
        if collection == "Predicate":
            return self._filters.any_of(
                [
                    self._filters.by_property("domains").contains_any(scoped),
                    self._filters.by_property("domains", length=True).equal(0),
                ]
            )
        prop = self._filters.by_property("domain")
        return prop.equal(scoped[0]) if len(scoped) == 1 else prop.contains_any(scoped)

    def _search(
        self,
        collection: str,
        text: str,
        vector: Optional[list],
        domains: Sequence[str],
        limit: int,
    ) -> list[dict]:
        handle = self._client.collections.get(collection)
        filters = self._domain_filter(collection, domains)
        if vector is None:
            resp = handle.query.bm25(query=text, limit=limit, filters=filters)
        else:
            resp = handle.query.hybrid(query=text, vector=vector, limit=limit, filters=filters)
        return [dict(getattr(o, "properties", {}) or {}) for o in getattr(resp, "objects", [])]
