"""``WeaviateVectorsWriter`` + ``FleetEmbedder`` — this fleet's ``MeshVectorsWriter``.

── WHAT THIS EXISTS TO MAKE UNEXPRESSIBLE ───────────────────────────────────────────────────
Three measured defects of this fleet's vector writes, each one now a call this class's surface
cannot make:

1. **The unnamed vector space.** A bare ``collections.create`` emits a space called ``default``
   that a POSITIONAL ``vector=[...]`` never writes to, so every row reads back as vectorised while
   no vector search can find one (``agent_fleet/utils/weaviate_utils.py``, ``VECTOR_SPACE``). This
   writer addresses the space BY NAME through ``named_vector()`` on every write, and declares it
   through ``named_vector_config()`` on every create. Neither is optional, and neither is spelled
   here — a second spelling of the space name is the defect wearing a new hat.

2. **The silent BM25 degrade.** A vector that fails to embed and is written anyway leaves a row
   that is present, countable, reported accepted, and unretrievable by the search that matters —
   which is how sixty-seven days of hybrid search ran on keywords alone. ``vector_required``
   therefore defaults **True**, and an embed failure with no waiver is ``refused``. The waiver is
   possible (the registrar legitimately writes vectorless rows so a registration is not blocked on
   the LLM stack) but it must be ASKED FOR, and it comes back as the named state
   ``written_without_vector`` rather than as a success.

3. **A constant stamped and a constant compared.** The marker beside a collection records the model
   that produced its vectors. A writer stamping its own module constant and a reader comparing its
   own module constant agree with each other while both disagree with the vectors on disk. So
   ``model`` is taken from the endpoint's SERVED identity, never from ``DEFAULT_EMBED_MODEL``.

── WHY `relocate` IS A SECOND METHOD AND NOT A `vector=` PARAMETER ──────────────────────────
Ruled 2026-09-27. ``write`` embeds through the writer's own injected ``Embedder``; ``relocate`` is
the ONE door for a caller-supplied precomputed vector. A single ``write(..., vector=None)`` would
make "supply your own vector" look like an ordinary optional argument, and the split exists exactly
to stop that from being the easy call. ``relocate`` also refuses a vector of the wrong length rather
than storing one no query could retrieve — a wrong-dimension vector is the unnamed-space defect
again, reached by a different road.

── `Embedder`, AND WHY `identity()` PROBES RATHER THAN REPLAYING THE LAST WRITE ─────────────
``FleetEmbedder`` adapts ``agent_fleet.utils.embed``, which is the only module permitted to POST to
``/embeddings`` (its own guard test forbids a direct POST anywhere else), so this writer never talks
to the embedding endpoint itself.

``embed()`` uses ``embed_document`` — NOT ``embed_query``. nomic-embed-text is task-prefixed, and a
corpus row written with the query prefix lands in a different region of the space than the queries
that will look for it; retrieval scores collapse without anything failing.

``identity()`` runs its own probe through ``observe_query_embedding`` rather than reporting what the
last ``embed()`` served. Two reasons, and the first is the Protocol's: ``embed`` and ``identity`` are
separate methods on ``Embedder``, whose docstring asks for an identity "probed fresh from the
endpoint". The second is that the served model is only reachable through ``embed``'s module-level
``_LAST_SERVED``, so reading it after a document embed would pair a vector from one call with a name
from whichever call landed last — the two-moments problem ``EmbeddingObservation`` was built to
close, reopened. The probe's prefix does not matter for what ``identity()`` returns: the task prefix
changes where a vector lands, not which model served it nor how many dimensions it has
(``probe_embedding_dim``: "EXPECTED_EMBED_DIM is independent of task prefix").

⚠ Scope of that claim: ``observe_query_embedding`` itself reads ``_LAST_SERVED`` after its own call
returns, so the race is narrowed to one call rather than removed, and it is a property of the shared
module that predates this writer. Routed, not fixed here — the fix belongs with ``_post_embedding``
returning its envelope's ``model`` instead of recording it in a global, which is a change to a
module with three in-module callers and a seal that monkeypatches the global by name.

── `version` IS ABSENT, WHICH IS A STATE ────────────────────────────────────────────────────
Measured 2026-09-15 against the configured endpoint: the response carries ``"model":
"nomic-embed-text"``, unversioned. ``identity()`` therefore returns ``None`` for the version, which
``CollectionMarker`` treats as a state rather than as a value to invent.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional, Sequence

from iagent_mesh.interfaces import (
    MESH_COLLECTION_META,
    Initiator,
    collection_marker,
)
from iagent_mesh.write_results import MeshWriteResult

try:  # container flat layout
    from utils.embed import embed_document, observe_query_embedding
    from utils.weaviate_utils import named_vector, named_vector_config
except ImportError:  # pragma: no cover — import path differs by runtime
    from agent_fleet.utils.embed import embed_document, observe_query_embedding
    from agent_fleet.utils.weaviate_utils import named_vector, named_vector_config

__all__ = ["FleetEmbedder", "WeaviateVectorsWriter"]

#: THE MARKER DOES NOT LIVE IN THE COLLECTION IT DESCRIBES, and the first draft of this module had
#: it there. Two reasons it moved, the second worse than the first:
#:
#: 1. The reader looks elsewhere. ``iagent_mesh`` names the carrier ``MeshCollectionMeta``, and the
#:    fleet's reader (``ontology_service/mesh_vectors.py``) resolves a marker through an injected
#:    ``fetch_marker(collection) -> Optional[dict]``. A marker stamped as a row inside the described
#:    collection is a marker in a place nothing reads — present, correct and invisible.
#: 2. A marker row inside a searched collection IS A SEARCH RESULT. It would carry ``text=""`` and
#:    sit in the same BM25 and vector index as the content, so hybrid search could return it as an
#:    answer chunk. Writing metadata into the corpus makes the metadata retrievable as corpus.
#:
#: ⚠ MEASURED 2026-09-28: ``fetch_marker`` is supplied at NO production construction site — the two
#: occurrences in the tree are lambdas in ``tests/test_mesh_vectors_conforms.py``. The reader
#: therefore takes its ``absent`` branch for every collection today and opens with a reported gap.
#: So this writer's marker has no live reader yet; it is written to the carrier the CONTRACT names,
#: not to the carrier a running consumer proves, and that distinction is routed rather than hidden.
#: Wiring the reader's fetcher is a separate item and does not belong in a writer.

#: What `written_by` records when the caller does not say. A marker whose author is unknown cannot
#: be traced back to the code that stamped it, so this is a value, not an empty string.
_DEFAULT_WRITTEN_BY = "agent_fleet.utils.mesh_writers.weaviate_vectors.WeaviateVectorsWriter"

#: ``weaviate.exceptions`` names that mean WE NEVER GOT TO ASK — the ``unreachable`` half. Module
#: level so a test can resolve each against the real module: a misspelled entry is a guard that never
#: fires, and it fails in the direction that sends an operator to the code while the store is down.
_TRANSPORT = frozenset({
    "WeaviateConnectionError",
    "WeaviateGRPCUnavailableError",
    "WeaviateTimeoutError",
    "WeaviateStartUpError",
    "WeaviateClosedClientError",
})


def _row_uuid(collection: str, id: str) -> uuid.UUID:
    """The deterministic object id for a caller-supplied logical ``id``.

    Weaviate addresses objects by UUID, and the ruling is that the CALLER supplies the id. The two
    are reconciled the way the registrar already does it — ``uuid5`` over a known name string — so
    the same logical id always maps to the same object and a re-write REPLACES rather than
    duplicating. The collection is part of the name so the same logical id in two collections does
    not collide into one uuid.
    """
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"{collection}/{id}")


class FleetEmbedder:
    """``Embedder`` over ``agent_fleet.utils.embed``. Constructed once, held by the writer."""

    def __init__(self, *, timeout: float = 30.0, probe_text: str = "iagent embed probe") -> None:
        self._timeout = timeout
        self._probe_text = probe_text

    def embed(self, text: str) -> Sequence[float]:
        """The DOCUMENT-prefixed vector for this text. See the module docstring on prefixes."""
        return embed_document(text, timeout=self._timeout)

    def identity(self) -> tuple[str, Optional[str], int]:
        """``(model, version, dimension)``, probed fresh. ``version`` is ``None``: unversioned."""
        observation = observe_query_embedding(self._probe_text, timeout=self._timeout)
        # `served` is what the endpoint said it served; `requested` is what we asked for. Falling
        # back to `requested` when the response omitted the model would report an INTENT as an
        # observation, so an omission is reported as the endpoint's own answer being absent.
        model = observation.served
        if model is None:
            raise RuntimeError(
                "the embedding endpoint returned no `model` in its response, so there is no served "
                "identity to stamp a collection marker with. Refusing to substitute the REQUESTED "
                f"model ({observation.requested!r}), which would record an intent as a measurement."
            )
        return (model, None, observation.dimension)


class WeaviateVectorsWriter:
    """Concrete ``MeshVectorsWriter``. By-name vector space, marker stamped at creation.

    Structurally satisfies ``iagent_mesh.interfaces.MeshVectorsWriter``; no inheritance.
    """

    def __init__(
        self,
        *,
        client: Any,
        embedder: Any,
        written_by: str = _DEFAULT_WRITTEN_BY,
    ) -> None:
        if client is None:
            raise ValueError("client is None — a writer with nowhere to write is not a writer")
        if embedder is None:
            raise ValueError(
                "embedder is None — embedding is the WRITER's job (ruled 2026-09-27) and it is "
                "injected so exactly one place in a running system probes what the endpoint served"
            )
        if not (written_by or "").strip():
            raise ValueError("written_by is empty — a marker whose author is blank is untraceable")
        self._client = client
        self._embedder = embedder
        self._written_by = written_by
        #: The dimension as OBSERVED from a vector this writer actually stored, not as CLAIMED by a
        #: probe. Set from ``len(vector)`` after a successful embed, and read by :meth:`relocate` so
        #: that moving a vector does not require the embed endpoint to be reachable. Starts unknown
        #: rather than at a constant: a number invented here would become this fleet's next
        #: independently-invented dimension, which is a defect already measured on this codebase.
        self._observed_dimension: Optional[int] = None

    # ── the two doors ───────────────────────────────────────────────────────────────────────

    def write(
        self,
        initiator: Initiator,
        *,
        collection: str,
        id: str,
        text: str,
        domains: Sequence[str] = (),
        vector_required: bool = True,
    ) -> MeshWriteResult:
        """Embed ``text`` here and store it addressed to the named vector space.

        THE IDENTITY GATE RAISES; IT DOES NOT RETURN `refused`. The first draft caught
        ``ServiceIdentityRefused`` and turned it into a refused result, on the reasoning that a
        writer returns a result rather than raising at its caller — and ``check_writer_offline``
        rejected that immediately, which is the contract answering a question I had decided for it.
        The distinction it is protecting: ``refused`` is a value a caller can ignore, and
        ``MeshWriteResult`` raises on ``bool()`` precisely because ignoring one is the failure mode.
        An unauthorized write is not an outcome to weigh, it is a call that may not be made — so it
        propagates. ``refused`` stays for what this writer declines on the MERITS, with an authorized
        caller: an empty argument, a wrong-dimension vector, an embed that failed with no waiver.
        """
        initiator.require_person_or_delegate("vectors.write")

        for label, value in (("collection", collection), ("id", id), ("text", text)):
            if not (value or "").strip():
                return MeshWriteResult.refused(f"{label} is empty")

        vector: Optional[list[float]] = None
        embed_detail: Optional[str] = None
        try:
            vector = list(self._embedder.embed(text))
        except Exception as exc:  # noqa: BLE001 — the waiver decision is made on it, below
            embed_detail = f"{type(exc).__name__}: {exc}"

        if vector is None or not vector:
            if vector_required:
                return MeshWriteResult.refused(
                    f"could not embed and vector_required=True, so nothing was written: "
                    f"{embed_detail or 'the embedder returned an empty vector'}. A row stored "
                    f"without its vector is present, countable and unretrievable by vector search "
                    f"— pass vector_required=False to accept that state deliberately."
                )
            return self._store(
                collection=collection,
                id=id,
                text=text,
                domains=domains,
                embedding=None,
                degraded_detail=(
                    f"stored without a vector by waiver (vector_required=False): "
                    f"{embed_detail or 'the embedder returned an empty vector'}. This row needs a "
                    f"RE-EMBED, not a relocate — a vectorless row is the one case the backfill "
                    f"cannot repair."
                ),
            )

        # Observed, not claimed: this is the length of a vector that is about to be stored in this
        # collection, which is the only number a later relocate actually has to match.
        self._observed_dimension = len(vector)

        return self._store(
            collection=collection, id=id, text=text, domains=domains, embedding=vector,
            degraded_detail=None,
        )

    def relocate(
        self, initiator: Initiator, *, collection: str, id: str, vector: Sequence[float]
    ) -> MeshWriteResult:
        """Replace an existing row's vector with a caller-supplied one. The ONLY such door.

        The gate raises rather than returning ``refused`` — see :meth:`write`.
        """
        initiator.require_person_or_delegate("vectors.relocate")

        for label, value in (("collection", collection), ("id", id)):
            if not (value or "").strip():
                return MeshWriteResult.refused(f"{label} is empty")

        supplied = list(vector or ())
        if not supplied:
            return MeshWriteResult.refused(
                "vector is empty — relocate() moves a vector, it does not remove one; a row that "
                "should lose its vector needs a re-embed, which is write()'s job"
            )

        # RELOCATE DOES NOT CALL THE EMBEDDER IF IT CAN AVOID IT, AND THAT IS NOT AN OPTIMISATION.
        # The first draft always called `identity()` here, for the dimension to check against. On
        # `FleetEmbedder` that method is a LIVE request to the embed endpoint, so a relocate — an
        # operation that needs no embedding whatever, taking a precomputed vector — could not
        # complete while the endpoint was down, and reported `unreachable` about a service it had no
        # business needing. Worse, it is a round trip per relocate for a number that does not move.
        #
        # So: prefer the dimension this writer OBSERVED when it last stored a vector, and probe only
        # when nothing has been stored yet and there is no other way to learn it. A relocate after a
        # write now touches the embedder zero times.
        dimension = self._observed_dimension
        if dimension is None:
            try:
                _model, _version, dimension = self._embedder.identity()
            except Exception as exc:  # noqa: BLE001
                return MeshWriteResult.unreachable(
                    f"this writer has stored no vector yet, so its dimension is not known from "
                    f"observation, and the embedder could not be asked either — a supplied vector "
                    f"cannot be checked against anything: {type(exc).__name__}: {exc}"
                )

        if len(supplied) != dimension:
            return MeshWriteResult.refused(
                f"vector has {len(supplied)} dimensions and this writer's embedder serves "
                f"{dimension}. Storing it would put a row in the collection that no query can "
                f"retrieve — the same unretrievability as writing to an unnamed space, reached by "
                f"a different road."
            )

        row_id = _row_uuid(collection, id)
        try:
            handle = self._client.collections.get(collection)
            if not handle.data.exists(uuid=row_id):
                return MeshWriteResult.failed(
                    f"no row {id!r} in {collection!r} to relocate — relocate() moves the vector of "
                    f"an existing row; creating one is write()'s job, which would also embed it"
                )
            handle.data.update(uuid=row_id, vector=named_vector(supplied))
        except Exception as exc:  # noqa: BLE001 — classified in _classify
            return self._classify(exc)
        return MeshWriteResult.written()

    # ── the store, and the marker written in the same act that creates the collection ───────

    def _store(
        self,
        *,
        collection: str,
        id: str,
        text: str,
        domains: Sequence[str],
        # NAMED `embedding`, NOT `vector`, AND THE SEAL IS WHY. `tests/routing/
        # test_a_vector_is_written_where_the_search_looks.py` collects every `vector=` expression in
        # a module and requires each to be `named_vector(...)`; an internal keyword called `vector`
        # is indistinguishable from a store write to that matcher, and it went red here naming a
        # real expression that was never going to reach Weaviate unaddressed. Renaming the plumbing
        # keeps the matcher's population exactly the writes, rather than teaching the matcher about
        # this module's internals.
        embedding: Optional[Sequence[float]],
        degraded_detail: Optional[str],
    ) -> MeshWriteResult:
        try:
            created = self._ensure_collection(collection)
            handle = self._client.collections.get(collection)
            row_id = _row_uuid(collection, id)
            write_kwargs: dict[str, Any] = {
                "uuid": row_id,
                "properties": {"mesh_id": id, "text": text, "domains": list(domains)},
            }
            # The key is OMITTED rather than set to None in the waived case: `named_vector(None)`
            # returns None by design, and passing `vector=None` into the client would be a third
            # state next to "addressed" and "absent" for no one's benefit. The call is written
            # inline so the only vector expression in this module is the addressed one.
            if embedding is not None:
                write_kwargs["vector"] = named_vector(embedding)
            # Both branches need the addressed vector, and the replace branch is the one that gets
            # missed: insert runs once on a cold store, replace runs on every re-write.
            if handle.data.exists(uuid=row_id):
                handle.data.replace(**write_kwargs)
            else:
                handle.data.insert(**write_kwargs)
            if created:
                self._stamp_marker(collection)
        except Exception as exc:  # noqa: BLE001 — classified in _classify
            return self._classify(exc)

        if degraded_detail is not None:
            return MeshWriteResult.written_without_vector(degraded_detail)
        return MeshWriteResult.written()

    def _ensure_collection(self, collection: str) -> bool:
        """Create the collection with the vector space DECLARED. ``True`` if this call created it.

        Auto-schema is the hazard: a bare ``collections.get()`` followed by ``insert()`` lets
        Weaviate create the collection with default config — no named space, no length index — and
        whichever writer touches a wiped substrate first decides that shape for everyone.
        """
        import weaviate.classes as wvc

        if self._client.collections.exists(collection):
            return False
        self._client.collections.create(
            name=collection,
            # engine-o's `/classify_predicate` ORs a `domains length == 0` clause into its
            # domain-scope filter, and Weaviate REJECTS that clause unless property length is
            # indexed — at which point hybrid search returns empty and routing degrades to the
            # generalist for every entitled-domain caller, silently.
            inverted_index_config=wvc.config.Configure.inverted_index(
                index_property_length=True,
            ),
            **named_vector_config(),
        )
        return True

    def _stamp_marker(self, collection: str) -> None:
        """Write the marker IN THE SAME ACT that created the collection.

        Fold, not hand-run: a marker written by a separate step is a marker that can be forgotten,
        and a forgotten marker reads as ABSENT while the collection is perfectly real. Raising here
        is deliberate — it propagates into ``_classify`` and the write reports ``failed`` rather
        than returning ``written`` over a collection with no marker.
        """
        import weaviate.classes as wvc

        model, version, dimension = self._embedder.identity()
        marker = collection_marker(
            collection=collection,
            model=model,
            dimension=dimension,
            written_by=self._written_by,
            collection_created_unix_ms=int(time.time() * 1000),
            version=version,
        )

        if not self._client.collections.exists(MESH_COLLECTION_META):
            self._client.collections.create(
                name=MESH_COLLECTION_META,
                # `named_vector_config()` HERE TOO, on a collection that holds no vectors, and not
                # by copy-paste: what it declares is `self_provided` / `none`, i.e. NOBODY
                # vectorizes this. A bare create leaves the vectorizer to the client's default, and
                # a default that ever becomes a real vectorizer would make every marker write call
                # out to an embedding module this collection has no business needing — failing the
                # stamp, and with it the write it rides on.
                **named_vector_config(),
                properties=[
                    # `collection` is the logical key: one marker per described collection.
                    wvc.config.Property(name="collection", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="model", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="version", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="dimension", data_type=wvc.config.DataType.INT),
                    wvc.config.Property(name="written_by", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(
                        name="collection_created_unix_ms", data_type=wvc.config.DataType.INT
                    ),
                ],
            )

        meta = self._client.collections.get(MESH_COLLECTION_META)
        meta_id = _row_uuid(MESH_COLLECTION_META, collection)
        # `version` is None against this endpoint (the model is unversioned), and a None property is
        # dropped rather than stored as the string "None" — which would read back as a VERSION, and
        # `read_collection_marker` would then compare a literal "None" against a real version and
        # refuse a collection that is fine.
        properties = {k: v for k, v in marker.items() if v is not None}
        if meta.data.exists(uuid=meta_id):
            meta.data.replace(uuid=meta_id, properties=properties)
        else:
            meta.data.insert(uuid=meta_id, properties=properties)

    @staticmethod
    def _classify(exc: BaseException) -> MeshWriteResult:
        """The refused/failed/unreachable split, on the store's own exception names.

        Matched by NAME rather than by importing ``weaviate.exceptions``, so this module stays
        importable where the client library is absent — the offline conformance arms construct the
        writer with a stub and never open a socket.
        """
        detail = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, OSError) or type(exc).__name__ in _TRANSPORT:
            return MeshWriteResult.unreachable(detail)
        return MeshWriteResult.failed(detail)
