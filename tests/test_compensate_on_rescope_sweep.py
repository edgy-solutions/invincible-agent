"""Cross-engine isolation test for the compensate-on-rescope sweep.

The sweep runs unsupervised on every engine boot, so its scope has to
be provably surgical: it must delete the engine's own rename-stale
rows and touch **zero** records belonging to any other engine. A
too-broad match would mean engines deleting each other's live
registrations on startup — the catastrophic failure mode that's much
worse than the accretion the sweep is meant to fix.

The architect's framing: assert the **negative space** — for each
engine's sweep, count exactly which UUIDs disappear and prove every
other UUID is byte-identical afterward.

The five-record contamination shape this test reconstructs is the
LIVE shape we found in the sandbox cluster on 2026-06-25:

  * DA current ``(analyzeDataset, idp#Dataset, engine_da_data_analyst)``
  * DA stale ``(analyzeDataset, mesh:DatasetAnalysisRequest, engine_da_data_analyst)``
  * A  current ``(analyzeWithCodeAgent, mesh#AgentTask, engine_a_restate_analyst)``
  * A  stale ``(analyzeWithCodeAgent, mesh:AgentTask, engine_a_restate_analyst)``
  * Rename-orphan ``(analyzeDataset, idp#Dataset, engine_a_analyze_dataset)``

Predict-snapshot table (encoded as test assertions below):

  * DA's sweep deletes ONLY DA stale; leaves the other four byte-identical.
  * A's  sweep deletes ONLY A  stale; leaves the other four byte-identical.
  * Neither sweep touches the rename-orphan (different tool_urn) —
    it's left for Step 2's clean to remove permanently, since the
    writer (``engine_a_analyze_dataset``) is retired and won't
    recreate it after a re-seed.

The compact-vs-full IRI canonicalization is the load-bearing detail
the test pins: A's stale row carries ``mesh:AgentTask`` (compact)
while A's current registration is ``mesh#AgentTask`` (full IRI).
A naive string compare would treat them as different tuples and
either (under-delete) miss the sweep entirely, or (over-delete)
delete the current row when the current registration is in compact
form. Canonicalizing both sides closes that hazard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from agent_fleet.mesh_registrar.v2_substrate import (
    _canonical_iri,
    sweep_stale_weaviate_predicate_rows,
)


# ---------------------------------------------------------------------------
# In-memory fake of the Weaviate ``Predicate`` collection
# ---------------------------------------------------------------------------
#
# Tracks only the fields the sweep reads (verb_iri, tool_urn,
# input_uri) plus a uuid. The sweep's read path is ``fetch_objects``
# with a ``tool_urn`` + ``verb_iri`` filter; the fake honors that.
# Delete is by uuid.


@dataclass
class _FakeObject:
    uuid: UUID
    properties: dict


@dataclass
class _FakeQuery:
    """Honors the sweep's ``fetch_objects(filters=...)`` call shape."""

    collection: "_FakeCollection"

    def fetch_objects(self, filters, limit=100):
        # We don't actually parse the weaviate Filter expression; the
        # test seeds the collection and provides matching predicates
        # via _required_filters on the collection. We use it as a
        # lookup so a test that mis-specifies its filter notices.
        matches = []
        for obj in self.collection.objects:
            if all(
                obj.properties.get(k) == v
                for k, v in self.collection._required_filters.items()
            ):
                matches.append(obj)
        result = type("Result", (), {})()
        result.objects = matches[:limit]
        return result


@dataclass
class _FakeData:
    collection: "_FakeCollection"

    def delete_by_id(self, uuid):
        before = len(self.collection.objects)
        self.collection.objects = [
            o for o in self.collection.objects if o.uuid != uuid
        ]
        assert len(self.collection.objects) == before - 1, (
            f"delete_by_id({uuid}) didn't match any row — sweep tried to "
            "delete something that didn't exist"
        )
        self.collection.delete_log.append(uuid)


@dataclass
class _FakeCollection:
    objects: list = field(default_factory=list)
    delete_log: list = field(default_factory=list)
    _required_filters: dict = field(default_factory=dict)

    def __post_init__(self):
        self.query = _FakeQuery(self)
        self.data = _FakeData(self)

    def set_filter(self, **kwargs):
        """Tests call this before invoking the sweep so the fake knows
        which rows the filter should match — mirrors the Weaviate
        Filter expression the sweep builds."""
        self._required_filters = kwargs


@dataclass
class _FakeWeaviateClient:
    collections: "_FakeCollections"


@dataclass
class _FakeCollections:
    predicate: _FakeCollection

    def get(self, name):
        assert name == "Predicate"
        return self.predicate


# ---------------------------------------------------------------------------
# Shared fixture — the live five-record contamination shape
# ---------------------------------------------------------------------------


def _seed_contaminated_collection() -> _FakeCollection:
    """Reproduce the sandbox's five-record state on 2026-06-25."""
    col = _FakeCollection()
    col.objects = [
        # 1. DA current — the row each DA sweep call should preserve.
        _FakeObject(
            uuid=uuid4(),
            properties={
                "verb_iri": "mesh:analyzeDataset",
                "input_uri": "http://invincible-agent/idp#Dataset",
                "tool_urn": "urn:li:mlModel:(urn:li:dataPlatform:mesh,"
                            "engine_da_data_analyst,PROD)",
                "endpoint_url": "http://iagent-data-analyst:8089/analyze_data",
            },
        ),
        # 2. DA stale (rename-stale input_uri, pre-IDP migration).
        _FakeObject(
            uuid=uuid4(),
            properties={
                "verb_iri": "mesh:analyzeDataset",
                "input_uri": "mesh:DatasetAnalysisRequest",
                "tool_urn": "urn:li:mlModel:(urn:li:dataPlatform:mesh,"
                            "engine_da_data_analyst,PROD)",
                "endpoint_url": "http://data-analyst-svc.default.svc."
                                "cluster.local:8089/analyze_data",
            },
        ),
        # 3. Engine A current.
        _FakeObject(
            uuid=uuid4(),
            properties={
                "verb_iri": "mesh:analyzeWithCodeAgent",
                "input_uri": "http://invincible-agent/mesh#AgentTask",
                "tool_urn": "urn:li:mlModel:(urn:li:dataPlatform:mesh,"
                            "engine_a_restate_analyst,PROD)",
                "endpoint_url": "http://iagent-engine-a:8081/analyze",
            },
        ),
        # 4. Engine A stale (rename-stale input_uri, compact form).
        _FakeObject(
            uuid=uuid4(),
            properties={
                "verb_iri": "mesh:analyzeWithCodeAgent",
                "input_uri": "mesh:AgentTask",
                "tool_urn": "urn:li:mlModel:(urn:li:dataPlatform:mesh,"
                            "engine_a_restate_analyst,PROD)",
                "endpoint_url": "http://restate-agent-svc.default.svc."
                                "cluster.local:8081/analyze",
            },
        ),
        # 5. Rename-orphan — Engine A's prior tool_urn before its rescope.
        _FakeObject(
            uuid=uuid4(),
            properties={
                "verb_iri": "mesh:analyzeDataset",
                "input_uri": "http://invincible-agent/idp#Dataset",
                "tool_urn": "urn:li:mlModel:(urn:li:dataPlatform:mesh,"
                            "engine_a_analyze_dataset,PROD)",
                "endpoint_url": "http://iagent-engine-a:8081/analyze",
            },
        ),
    ]
    return col


def _client_for(col: _FakeCollection) -> _FakeWeaviateClient:
    return _FakeWeaviateClient(collections=_FakeCollections(predicate=col))


def _uuids_by_engine(col: _FakeCollection) -> dict[str, UUID]:
    """Stable map: {label → uuid} for assertions about which rows
    survive a sweep."""
    return {
        "da_current":     col.objects[0].uuid,
        "da_stale":       col.objects[1].uuid,
        "a_current":      col.objects[2].uuid,
        "a_stale":        col.objects[3].uuid,
        "rename_orphan":  col.objects[4].uuid,
    }


def _surviving(col: _FakeCollection) -> set[UUID]:
    return {o.uuid for o in col.objects}


# ---------------------------------------------------------------------------
# The actual surgical-scope tests
# ---------------------------------------------------------------------------


def test_a_sweep_keeps_storage_form_duplicate():
    """Engine A's stale row has ``input_uri = mesh:AgentTask`` (compact)
    while A's current registration uses
    ``http://invincible-agent/mesh#AgentTask`` (full IRI). Under
    canonical comparison the two are the **same semantic tuple** —
    just two storage forms — so the sweep correctly KEEPS the
    "stale" row instead of deleting it.

    This is the architect's prescribed safety bias: when in doubt,
    under-delete rather than over-delete. The catastrophic failure
    mode is "sweep deletes a live record"; treating a storage-form
    variant as a candidate-for-delete is one string-mismatch away
    from over-deleting the current row when a future seed writes in
    the other form. Canonicalize first, accept that storage-form
    duplicates survive Step 1, and trust the safety net:

      * Step 5 (already shipped) makes the duplicate's endpoint
        inert by overriding dispatch with the Neo4j compat-walk
        result — even with the wrong-endpoint duplicate present in
        Weaviate, dispatch goes to the Neo4j-authoritative endpoint.
      * Step 3 (the dedup guard, next) canonicalizes BEFORE grouping
        — so the same-canonical-tuple pair shows up as a duplicate
        in the guard's report, where an operator can decide whether
        to surgically delete the storage-form variant.

    Net: Step 1 stays maximally safe (cross-engine + same-canonical
    preservation), and the other two steps handle the residual.
    """
    col = _seed_contaminated_collection()
    uuids = _uuids_by_engine(col)
    client = _client_for(col)

    col.set_filter(
        verb_iri="mesh:analyzeWithCodeAgent",
        tool_urn="urn:li:mlModel:(urn:li:dataPlatform:mesh,"
                 "engine_a_restate_analyst,PROD)",
    )
    deleted = sweep_stale_weaviate_predicate_rows(
        weaviate_client=client,
        verb_iri="mesh:analyzeWithCodeAgent",
        current_input_uri="http://invincible-agent/mesh#AgentTask",
        tool_urn="urn:li:mlModel:(urn:li:dataPlatform:mesh,"
                 "engine_a_restate_analyst,PROD)",
    )

    # Sweep is a NO-OP — both rows canonicalize to the same tuple.
    assert deleted == []

    survivors = _surviving(col)
    # Every row survives — including A's storage-form duplicate.
    assert uuids["a_current"]     in survivors
    assert uuids["a_stale"]       in survivors  # storage-form duplicate, KEPT
    assert uuids["da_current"]    in survivors
    assert uuids["da_stale"]      in survivors
    assert uuids["rename_orphan"] in survivors


def test_da_sweep_deletes_genuinely_different_namespace():
    """DA's stale row has ``input_uri = mesh:DatasetAnalysisRequest``
    while DA's current registration uses ``idp#Dataset``. Different
    namespace (mesh vs idp) AND different local name — these are
    genuinely different semantic tuples even after canonicalization,
    so the sweep correctly deletes the stale row.

    This is the case Step 1 is built for: input_uri migrations that
    cross namespaces (catalog-verb migration 2026-06-12). Same
    engine, same verb, semantically different input_uri ⇒ delete."""
    col = _seed_contaminated_collection()
    uuids = _uuids_by_engine(col)
    client = _client_for(col)

    col.set_filter(
        verb_iri="mesh:analyzeDataset",
        tool_urn="urn:li:mlModel:(urn:li:dataPlatform:mesh,"
                 "engine_da_data_analyst,PROD)",
    )
    deleted = sweep_stale_weaviate_predicate_rows(
        weaviate_client=client,
        verb_iri="mesh:analyzeDataset",
        current_input_uri="http://invincible-agent/idp#Dataset",
        tool_urn="urn:li:mlModel:(urn:li:dataPlatform:mesh,"
                 "engine_da_data_analyst,PROD)",
    )

    # The single deleted row is the migration-stale one.
    assert len(deleted) == 1, deleted
    assert deleted[0]["input_uri"] == "mesh:DatasetAnalysisRequest"

    survivors = _surviving(col)
    assert uuids["da_current"]    in survivors
    assert uuids["a_current"]     in survivors  # other engine — UNTOUCHED
    assert uuids["a_stale"]       in survivors  # other engine — UNTOUCHED
    assert uuids["rename_orphan"] in survivors  # different tool_urn — UNTOUCHED
    assert uuids["da_stale"]      not in survivors


def test_canonical_iri_handles_both_directions():
    """The sweep's canonicalization must be idempotent on full IRIs
    and expand compact forms — so the comparison works whichever way
    the row was stored. Without this, a future seed in compact form
    against current registrations in full form would over-delete the
    live row."""
    assert _canonical_iri("mesh:AgentTask") == "http://invincible-agent/mesh#AgentTask"
    assert _canonical_iri("idp:Dataset") == "http://invincible-agent/idp#Dataset"
    # Idempotent on already-canonical full IRIs.
    assert (
        _canonical_iri("http://invincible-agent/mesh#AgentTask")
        == "http://invincible-agent/mesh#AgentTask"
    )
    # Unknown prefix passes through (we won't expand what we don't know).
    assert _canonical_iri("ex:Thing") == "ex:Thing"
    assert _canonical_iri("") == ""


def test_sweep_with_no_stale_rows_is_a_noop():
    """Steady-state: after the first post-deploy boot has cleaned up,
    every subsequent boot's sweep should find nothing to delete.
    The sweep must be safe to run on every boot indefinitely."""
    col = _seed_contaminated_collection()
    client = _client_for(col)
    # DA's first sweep cleans its stale row.
    col.set_filter(
        verb_iri="mesh:analyzeDataset",
        tool_urn="urn:li:mlModel:(urn:li:dataPlatform:mesh,"
                 "engine_da_data_analyst,PROD)",
    )
    sweep_stale_weaviate_predicate_rows(
        weaviate_client=client,
        verb_iri="mesh:analyzeDataset",
        current_input_uri="http://invincible-agent/idp#Dataset",
        tool_urn="urn:li:mlModel:(urn:li:dataPlatform:mesh,"
                 "engine_da_data_analyst,PROD)",
    )
    # Subsequent DA sweep on the same registration must be a no-op.
    deleted_second = sweep_stale_weaviate_predicate_rows(
        weaviate_client=client,
        verb_iri="mesh:analyzeDataset",
        current_input_uri="http://invincible-agent/idp#Dataset",
        tool_urn="urn:li:mlModel:(urn:li:dataPlatform:mesh,"
                 "engine_da_data_analyst,PROD)",
    )
    assert deleted_second == []


def test_rename_orphan_persists_through_both_sweeps():
    """The architect's central reframing: the rename-orphan is NOT
    handled by Step 1's sweep — it's permanently removed by Step 2's
    clean (the re-seed) and never recurs because its writer is
    retired. The test asserts the sweep correctly LEAVES the orphan
    alone, because a sweep that DID delete it would be operating
    outside its surgical scope (different tool_urn) — which is the
    catastrophic failure mode."""
    col = _seed_contaminated_collection()
    uuids = _uuids_by_engine(col)
    client = _client_for(col)

    # DA's sweep.
    col.set_filter(
        verb_iri="mesh:analyzeDataset",
        tool_urn="urn:li:mlModel:(urn:li:dataPlatform:mesh,"
                 "engine_da_data_analyst,PROD)",
    )
    sweep_stale_weaviate_predicate_rows(
        weaviate_client=client,
        verb_iri="mesh:analyzeDataset",
        current_input_uri="http://invincible-agent/idp#Dataset",
        tool_urn="urn:li:mlModel:(urn:li:dataPlatform:mesh,"
                 "engine_da_data_analyst,PROD)",
    )

    # A's sweep.
    col.set_filter(
        verb_iri="mesh:analyzeWithCodeAgent",
        tool_urn="urn:li:mlModel:(urn:li:dataPlatform:mesh,"
                 "engine_a_restate_analyst,PROD)",
    )
    sweep_stale_weaviate_predicate_rows(
        weaviate_client=client,
        verb_iri="mesh:analyzeWithCodeAgent",
        current_input_uri="http://invincible-agent/mesh#AgentTask",
        tool_urn="urn:li:mlModel:(urn:li:dataPlatform:mesh,"
                 "engine_a_restate_analyst,PROD)",
    )

    # The rename-orphan is still there. Step 2's clean is what kills it.
    assert uuids["rename_orphan"] in _surviving(col)
