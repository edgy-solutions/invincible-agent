"""Substrate dedup guard for the Weaviate ``Predicate`` collection.

Runtime invariant: no two rows in the Predicate collection share the
same canonical ``(verb_iri, input_uri)`` pair. The guard runs in CI
against a test-seeded Predicate collection AND in post-deploy against
the cluster's live Weaviate, so any registration churn that re-
accretes a duplicate is caught structurally, not by waiting for a
mis-routed query to surface it.

Two distinct contamination shapes the guard catches — they share the
"duplicate logical verb" failure mode but take different remediation:

  * **Stale-tuple residue.** A row whose canonical pair collides with
    a current registration but whose ``tool_urn`` is no longer any
    engine's current tool_urn. The rename-orphan from the live
    sandbox investigation
    (``engine_a_analyze_dataset`` claiming ``mesh:analyzeDataset`` after
    A had been rescoped to ``engine_a_restate_analyst``) is this shape.
    Remediation: substrate clean (the Step 2 re-seed) or manual
    delete by uuid; cannot recur because the writer is retired.

  * **Storage-form duplicates.** Two rows with the SAME canonical pair
    stored in DIFFERENT string-form spellings — e.g. one stored as
    ``mesh:AgentTask`` and one as ``http://invincible-agent/mesh#AgentTask``.
    Step 1's per-call sweep correctly *keeps* both (under canonical
    comparison they ARE the current registration, just in alternate
    namespace forms). The guard catches them here so an operator can
    decide whether to normalize to one form. **Safety claim** —
    these are benign at routing time only if the resolution path is
    canonical-clean end-to-end: if ``classify_predicate`` and the
    supervisor compare canonical forms, then both spellings resolve
    identically and a storage-form duplicate cannot misroute. The
    phrasing-independence integration test (Step 4) is what proves
    that safety claim by exercising both spellings against the same
    resolution path. Without Step 4, storage-form duplicates remain
    a *potential* second contamination mechanism.

Source vs substrate sibling discipline. The source side
(``seed_sandbox_predicates.py``, ``register_engine_to_mesh``) already
canonicalizes to full-IRI form — that's the source-clean half.
This guard is the **substrate sibling**: it catches accretion that
the source side can't see, including:

  * rename-orphans created by writers that no longer exist,
  * legacy compact-form rows that predate the canonical-form discipline,
  * any future writer that drifts off canonical form (a regression).

Source-clean ≠ runtime-clean. Both layers need their own guard.

The architect's through-line behind this work: duplicate-record
contamination has multiple surface forms (endpoint divergence,
namespace-spelling divergence) and the durable defense is canonical-
form resolution end-to-end — not cleaning each duplicate, because
you'll never clean faster than registrations accrete, but a canonical-
resolution path makes accretion harmless. Step 5 (supervisor reads
endpoint from Neo4j, not Weaviate) closed the endpoint-divergence
seam; this guard plus Step 4's phrasing-independence test close the
spelling-divergence seam.

Skips if the Weaviate client isn't installed or the configured host
isn't reachable. CI sets ``WEAVIATE_HTTP_HOST`` / port via env;
local-dev defaults to a port-forwarded sandbox Weaviate.
"""

from __future__ import annotations

import os
from collections import defaultdict

import pytest

try:
    import weaviate
except ImportError:
    pytest.skip("weaviate-client not installed", allow_module_level=True)


_PREDICATE_COLLECTION = "Predicate"

_WEAVIATE_HTTP_HOST = os.getenv("WEAVIATE_HTTP_HOST", "localhost")
_WEAVIATE_HTTP_PORT = int(os.getenv("WEAVIATE_HTTP_PORT", "8080"))
_WEAVIATE_GRPC_HOST = os.getenv("WEAVIATE_GRPC_HOST", "localhost")
_WEAVIATE_GRPC_PORT = int(os.getenv("WEAVIATE_GRPC_PORT", "50051"))


# Mirrors the canonicalization in ``agent_fleet/mesh_registrar/v2_substrate.py``.
# Kept inline rather than imported so this guard can run against an
# isolated test environment without pulling in the registrar module.
# When a new namespace prefix is added there, mirror it here — a CI
# job that imports both modules can assert they stay in lockstep.
_IRI_PREFIXES = {
    "mesh:": "http://invincible-agent/mesh#",
    "idp:": "http://invincible-agent/idp#",
}


def _canonical_iri(iri: str) -> str:
    """Expand a compact-form CURIE to its full IRI. Idempotent."""
    if not iri:
        return ""
    for prefix, expansion in _IRI_PREFIXES.items():
        if iri.startswith(prefix):
            return expansion + iri[len(prefix):]
    return iri


@pytest.fixture(scope="module")
def weaviate_client():
    """Connect to Weaviate; skip the module if the host isn't reachable.

    Honors WEAVIATE_HTTP_* / WEAVIATE_GRPC_* env vars so CI and
    post-deploy can target different clusters without code edits.
    """
    try:
        client = weaviate.connect_to_custom(
            http_host=_WEAVIATE_HTTP_HOST,
            http_port=_WEAVIATE_HTTP_PORT,
            http_secure=False,
            grpc_host=_WEAVIATE_GRPC_HOST,
            grpc_port=_WEAVIATE_GRPC_PORT,
            grpc_secure=False,
        )
    except Exception as exc:
        pytest.skip(f"Weaviate unreachable at {_WEAVIATE_HTTP_HOST}: {exc}")
    try:
        if not client.is_ready():
            pytest.skip(f"Weaviate not ready at {_WEAVIATE_HTTP_HOST}")
        if not client.collections.exists(_PREDICATE_COLLECTION):
            pytest.skip(f"Predicate collection missing — substrate uninitialized")
        yield client
    finally:
        client.close()


def _fetch_all_predicate_rows(client) -> list[dict]:
    """Pull every Predicate row's identity-and-disambiguation fields.

    The fields here are what the guard's collision report needs:
    canonical comparison (verb_iri + input_uri), storage-form (the
    raw stored strings), provenance (tool_urn), and the field that
    made this whole investigation matter — endpoint_url.
    """
    collection = client.collections.get(_PREDICATE_COLLECTION)
    objects = []
    # Weaviate's iterator paginates; 1000-row chunks are plenty for the
    # current Predicate-collection size (~50 rows) but the iterator
    # protects against silent truncation if the collection grows.
    for obj in collection.iterator(include_vector=False):
        props = obj.properties or {}
        objects.append({
            "uuid": str(obj.uuid),
            "verb_iri": props.get("verb_iri") or "",
            "input_uri": props.get("input_uri") or "",
            "tool_urn": props.get("tool_urn") or "",
            "endpoint_url": props.get("endpoint_url") or "",
            "owner_persona": props.get("owner_persona") or "",
        })
    return objects


# Verbs that legitimately have multiple providers serving the same
# canonical (verb_iri, input_uri) pair under DIFFERENT tool_urns. This
# is the [[recipe-v2-landed]] multi-provider pattern: mesh:resolveInstance
# is served by Engine D (DataHub) and Engine E (DMC capability) with
# distinct endpoints. The dispatch path discriminates by provider via
# instance-shape hints — cross-tool_urn co-existence is intended.
#
# Add a verb here ONLY when the registration is genuinely multi-
# provider (multiple LIVE engines serving the verb intentionally).
# Adding an entry to silence a rename-orphan failure is the wrong
# move — the orphan's writer should be retired and the substrate
# re-seeded, not allowlisted into the substrate.
#
# Format: ``(canonical_verb_iri, canonical_input_uri)``.
_MULTI_PROVIDER_ALLOWLIST: frozenset[tuple[str, str]] = frozenset({
    (
        "http://invincible-agent/mesh#resolveInstance",
        "http://invincible-agent/mesh#InstanceIdentifier",
    ),
})


def _classify_within_tool_urn(rows: list[dict]) -> str:
    """For a collision group with rows that ALL share the same tool_urn,
    tag the shape:

    * ``"exact_tuple"`` — rows share the same raw stored input_uri.
      Likely cause: a migration script updated input_uri in-place but
      kept the OLD uuid; a subsequent registration generated a NEW
      uuid via uuid5(verb, new_input_uri) and both rows coexist.
    * ``"storage_form"`` — rows share canonical input_uri but differ
      in raw stored string (e.g. ``mesh:AgentTask`` vs
      ``mesh#AgentTask``). Step 1's sweep keeps these; remediation is
      to normalize to one form, OR accept once Step 4 proves the
      resolution path is canonical-clean end-to-end.
    """
    raw_input_uris = {r["input_uri"] for r in rows}
    if len(raw_input_uris) == 1:
        return "exact_tuple"
    return "storage_form"


def test_predicate_collection_has_no_within_tool_urn_duplicates(weaviate_client):
    """**Strict invariant.** No two rows share the same
    ``(canonical_verb_iri, canonical_input_uri, tool_urn)`` triple.

    Same-tool_urn duplicates can't be made safe by Step 5's
    Neo4j-authoritative dispatch (both rows point at the same engine —
    field drift between them, even just in ``description`` or
    ``synonyms`` text used by Weaviate's vector search, could still
    nudge the wrong one to win). This guard fails red the moment the
    next registration churn re-accretes one.
    """
    rows = _fetch_all_predicate_rows(weaviate_client)
    by_triple: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in rows:
        key = (
            _canonical_iri(r["verb_iri"]),
            _canonical_iri(r["input_uri"]),
            r["tool_urn"],
        )
        by_triple[key].append(r)

    collisions = {k: v for k, v in by_triple.items() if len(v) > 1}
    if not collisions:
        return

    lines = [
        f"\nWithin-tool_urn dedup guard found {len(collisions)} collision "
        f"group(s) ({sum(len(v) for v in collisions.values())} rows total):",
    ]
    for (canon_verb, canon_input, tool_urn), group in collisions.items():
        shape = _classify_within_tool_urn(group)
        lines.append("")
        lines.append(
            f"  canonical=({canon_verb!r}, {canon_input!r}) "
            f"tool_urn={tool_urn} shape={shape} count={len(group)}"
        )
        for r in group:
            lines.append(
                f"    uuid={r['uuid'][:8]} endpoint={r['endpoint_url']}"
            )
            lines.append(
                f"      stored_verb_iri={r['verb_iri']!r} "
                f"stored_input_uri={r['input_uri']!r}"
            )
    lines.append("")
    lines.append("Remediation:")
    lines.append(
        "  * exact_tuple — almost certainly a migration script that "
        "updated input_uri in place but kept the old uuid. Re-running "
        "seed_sandbox_predicates.py (drops + recreates the collection) "
        "is the durable fix; identify and patch the offending in-place "
        "update so the next migration writes a new uuid AND deletes "
        "the old one."
    )
    lines.append(
        "  * storage_form — normalize the stored input_uri to canonical "
        "full-IRI form. Until then, the same tuple is split across two "
        "rows that classify_predicate can pick non-deterministically."
    )
    pytest.fail("\n".join(lines))


def test_predicate_collection_cross_tool_urn_collisions_are_allowlisted(
    weaviate_client,
):
    """**Allowlisted invariant.** When two rows share canonical
    ``(verb_iri, input_uri)`` but under DIFFERENT tool_urns, that's
    either:

    * the legitimate multi-provider pattern (one verb served by N live
      engines, dispatch discriminated by provider) — allowlisted in
      ``_MULTI_PROVIDER_ALLOWLIST``, OR
    * a rename-orphan (the original writer was rescoped/renamed and
      the row from the old tool_urn was never compensated). Step 1's
      sweep can't see these (different tool_urn from any current
      registration). Step 5 prevents the rename-orphan from misrouting
      via Neo4j-authoritative dispatch, but it's still substrate
      residue that should be cleaned.

    The guard distinguishes them by allowlist. Failing this test
    means: either the verb is genuinely multi-provider (add it to
    ``_MULTI_PROVIDER_ALLOWLIST`` after confirming all listed
    tool_urns map to LIVE engines), or you've found a rename-orphan
    that needs re-seeding to clean.
    """
    rows = _fetch_all_predicate_rows(weaviate_client)
    by_canonical: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        key = (_canonical_iri(r["verb_iri"]), _canonical_iri(r["input_uri"]))
        by_canonical[key].append(r)

    # Same canonical pair under DIFFERENT tool_urns. Within-tool_urn
    # collisions are the other guard's responsibility — don't double-
    # report them here.
    unallowlisted = []
    for key, group in by_canonical.items():
        distinct_tool_urns = {r["tool_urn"] for r in group}
        if len(distinct_tool_urns) <= 1:
            continue
        if key in _MULTI_PROVIDER_ALLOWLIST:
            continue
        unallowlisted.append((key, group))

    if not unallowlisted:
        return

    lines = [
        f"\nCross-tool_urn dedup guard found {len(unallowlisted)} "
        "unallowlisted collision group(s):",
    ]
    for (canon_verb, canon_input), group in unallowlisted:
        lines.append("")
        lines.append(
            f"  canonical=({canon_verb!r}, {canon_input!r}) "
            f"count={len(group)}"
        )
        for r in group:
            lines.append(
                f"    uuid={r['uuid'][:8]} tool_urn={r['tool_urn']} "
                f"endpoint={r['endpoint_url']}"
            )
    lines.append("")
    lines.append(
        "Remediation: confirm each colliding tool_urn maps to a LIVE "
        "engine. If yes, this is a legitimate multi-provider pattern — "
        "add ``(canonical_verb_iri, canonical_input_uri)`` to "
        "``_MULTI_PROVIDER_ALLOWLIST`` with a comment naming the live "
        "providers. If any tool_urn is retired, it's a rename-orphan "
        "— re-run seed_sandbox_predicates.py to drop+recreate the "
        "Predicate collection and remove the orphan permanently."
    )
    pytest.fail("\n".join(lines))


def test_canonical_iri_helper_is_idempotent():
    """A tiny unit test that pins the canonicalization rule the guard
    depends on. Mirrors the assertion in the Step 1 sweep test — kept
    here too so this file is self-contained when run in isolation.
    """
    assert _canonical_iri("mesh:AgentTask") == "http://invincible-agent/mesh#AgentTask"
    assert _canonical_iri("idp:Dataset") == "http://invincible-agent/idp#Dataset"
    assert (
        _canonical_iri("http://invincible-agent/mesh#AgentTask")
        == "http://invincible-agent/mesh#AgentTask"
    )
    assert _canonical_iri("ex:Thing") == "ex:Thing"
    assert _canonical_iri("") == ""
