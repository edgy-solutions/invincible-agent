"""Merge each compact-form OntologyClass node into its canonical
full-IRI counterpart, redirecting all edges with property updates.

Sibling of `migrate_compact_to_full_iri.py`. That script handles
"compact exists, canonical does NOT" — it CREATEs the canonical from
the compact's props and copies edges. This script handles the
inverse case (`migrate_compact_to_full_iri.py:73-75` aborts on it):
"compact exists AND canonical ALSO exists" — the seed-script
regression class (2026-06-13 finding). The canonical was already
materialized by `sync_jena_ontologies_to_neo4j` from
`mesh_system.ttl` / `mro_extension.ttl`; the compact was created by
re-runnable seeds (seed_sandbox_predicates.py etc.) writing the
compact-prefix form. Result: TWO :OntologyClass nodes per concept,
edges split between them.

Approach per compact node:

  1. Verify both compact AND canonical exist (this script's
     precondition; abort if compact-only — that's the other
     script's job).
  2. Capture all incoming and outgoing edges on the compact node.
  3. For each edge: rebuild an equivalent edge anchored at the
     canonical node (same type, same props, with _input_uri /
     _output_uri remapped if they reference a URI in URI_MAP).
  4. DETACH DELETE the compact node (drops the original edges).
  5. Report the per-node delta.

Architect-approved scope (2026-06-13 late session):

  IN scope: the 27 compact-form nodes that have known canonical
  full-IRI counterparts in the substrate. Enumerated via the
  widened test_no_compact_form_ontology_classes guard's
  CLEANUP-ABLE list.

  OUT of scope: the 3 banked TBox-decision items (data:Dashboard,
  data:Dataset, mesh:Thing). These don't have canonical full-IRI
  declarations yet; deleting them WITHOUT a redirect target would
  orphan 548+ edges (mesh:Thing alone). The widened guard correctly
  stays RED on them until their canonicals are declared.

Predictions BEFORE running (written 2026-06-13 late, snapshot
captured separately):

  - 27 compact-form OntologyClass nodes will be deleted.
  - 580+ edges will be moved from compact → canonical, preserving
    type + properties. (Snapshot below shows the per-node counts.)
  - mesh:Thing edge count (548) is preserved on the compact node;
    it's not in scope and won't be touched.
  - test_no_compact_form_ontology_classes: 30 violations → 3 (the
    banked TBox items).
  - test_no_compact_form_for_migrated_subjects (the focused
    sibling guard): currently red on 4 names → 0 (clean).
  - User-visible base matrix: 18/18 UNCHANGED. Pool-hold +
    conjunctive invariant should mean the routing layer doesn't
    notice the compact-form duplicates being gone — verbs route by
    `iri` property on edges (compact-form, substrate-canonical for
    verbs) and edge-property `_input_uri`/`_output_uri` are
    string-matched against the resolved subject's full-IRI, which
    is already the canonical. If the matrix moves, that's a real
    finding: some path depends on a compact OntologyClass node we
    thought inert.

Run via port-forwards:
    kubectl -n sandbox port-forward svc/iagent-neo4j 7687:7687 &
    py scripts/merge_compact_into_canonical.py
"""

from __future__ import annotations

import os
import sys

try:
    from neo4j import GraphDatabase
except ImportError:
    print("ERROR: install neo4j: pip install neo4j", file=sys.stderr)
    sys.exit(1)


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USERNAME", os.getenv("NEO4J_USER", "neo4j"))
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "changeme-neo4j-sandbox")


# Compact → canonical full-IRI mapping for the 27 in-scope nodes.
# Derived by running test_no_compact_form_ontology_classes and reading
# the structured "CLEANUP-ABLE" list (2026-06-13 snapshot).
URI_MAP: dict[str, str] = {
    # mesh:* (22 entries) → http://invincible-agent/mesh#*
    "mesh:AgentResponse":               "http://invincible-agent/mesh#AgentResponse",
    "mesh:AgentTask":                   "http://invincible-agent/mesh#AgentTask",
    "mesh:AssetProfile":                "http://invincible-agent/mesh#AssetProfile",
    "mesh:CatalogAssetQuery":           "http://invincible-agent/mesh#CatalogAssetQuery",
    "mesh:CatalogListing":              "http://invincible-agent/mesh#CatalogListing",
    "mesh:CatalogScopeQuery":           "http://invincible-agent/mesh#CatalogScopeQuery",
    "mesh:DatasetAnalysisReport":       "http://invincible-agent/mesh#DatasetAnalysisReport",
    "mesh:DatasetAnalysisRequest":      "http://invincible-agent/mesh#DatasetAnalysisRequest",
    "mesh:FreshnessReport":             "http://invincible-agent/mesh#FreshnessReport",
    "mesh:GraphExpertResponse":         "http://invincible-agent/mesh#GraphExpertResponse",
    "mesh:GraphQuery":                  "http://invincible-agent/mesh#GraphQuery",
    "mesh:ImpactSet":                   "http://invincible-agent/mesh#ImpactSet",
    "mesh:InstanceIdentifier":          "http://invincible-agent/mesh#InstanceIdentifier",
    "mesh:InstanceResolution":          "http://invincible-agent/mesh#InstanceResolution",
    "mesh:KnowledgeQuery":              "http://invincible-agent/mesh#KnowledgeQuery",
    "mesh:KnowledgeRetrievalResponse":  "http://invincible-agent/mesh#KnowledgeRetrievalResponse",
    "mesh:LineageTopology":             "http://invincible-agent/mesh#LineageTopology",
    "mesh:OwnershipFact":               "http://invincible-agent/mesh#OwnershipFact",
    "mesh:Request":                     "http://invincible-agent/mesh#Request",
    "mesh:Response":                    "http://invincible-agent/mesh#Response",
    "mesh:SchemaDescription":           "http://invincible-agent/mesh#SchemaDescription",
    "mesh:TagFilterResult":             "http://invincible-agent/mesh#TagFilterResult",
    # mro:* (5 entries) → spec.industrialontologies.org canonical
    "mro:Diagram":        "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/Diagram",
    "mro:Equipment":      "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/Equipment",
    "mro:Procedure":      "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/Procedure",
    "mro:ProcedureStep":  "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/ProcedureStep",
    "mro:Symptom":        "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/Symptom",
}

# Edge property names that may contain URI references that need
# remapping (compact → canonical) when edges are recreated.
URI_PROP_NAMES = ("_input_uri", "_output_uri", "input_uri", "output_uri")


def _remap_props(props: dict, uri_map: dict) -> dict:
    """Return a new props dict with URI-valued props remapped via uri_map."""
    out = dict(props)
    for k in URI_PROP_NAMES:
        if k in out and out[k] in uri_map:
            out[k] = uri_map[out[k]]
    return out


def migrate_one(session, compact: str, canonical: str, dry_run: bool) -> dict:
    """Migrate edges from the compact node into the canonical node,
    then delete the compact. Returns a small per-node delta dict.
    """
    pre = session.run(
        """
        OPTIONAL MATCH (c:OntologyClass {uri: $compact})
        OPTIONAL MATCH (f:OntologyClass {uri: $canonical})
        RETURN c IS NOT NULL AS compact_exists,
               f IS NOT NULL AS canonical_exists
        """,
        compact=compact, canonical=canonical,
    ).single()
    if not pre["compact_exists"]:
        return {"compact": compact, "skipped": "compact_missing", "edges_moved": 0}
    if not pre["canonical_exists"]:
        return {"compact": compact, "skipped": "canonical_missing", "edges_moved": 0}

    in_edges = list(session.run(
        """
        MATCH (other)-[r]->(c:OntologyClass {uri: $compact})
        RETURN type(r) AS rel_type, properties(r) AS props,
               other.uri AS other_uri, labels(other) AS other_labels
        """,
        compact=compact,
    ))
    out_edges = list(session.run(
        """
        MATCH (c:OntologyClass {uri: $compact})-[r]->(other)
        RETURN type(r) AS rel_type, properties(r) AS props,
               other.uri AS other_uri, labels(other) AS other_labels
        """,
        compact=compact,
    ))

    delta = {
        "compact": compact,
        "canonical": canonical,
        "in_edges": len(in_edges),
        "out_edges": len(out_edges),
        "edges_moved": 0,
    }

    if dry_run:
        return delta

    # IDEMPOTENT EDGE CREATION (apoc.merge.relationship). The
    # match key distinguishes verb edges (keyed by iri) from
    # subClassOf-style edges (keyed by endpoints only). 851 existing
    # canonical→canonical subClassOf edges already exist in the
    # substrate (canonical pipeline creates them); without this
    # match-key discipline, every migration of a parent class would
    # duplicate its child classes' subClassOf edges.
    for e in in_edges:
        props = _remap_props(dict(e["props"]), URI_MAP)
        source_uri = URI_MAP.get(e["other_uri"], e["other_uri"])
        # match-key: iri if present (verb edges), empty otherwise
        match_props = {"iri": props["iri"]} if "iri" in props else {}
        session.run(
            """
            MATCH (s {uri: $src})
            MATCH (o:OntologyClass {uri: $tgt})
            CALL apoc.merge.relationship(s, $rel_type, $match_props, $props, o, $props)
                YIELD rel
            RETURN type(rel) AS t
            """,
            src=source_uri, tgt=canonical,
            rel_type=e["rel_type"], match_props=match_props, props=props,
        )
        delta["edges_moved"] += 1

    for e in out_edges:
        props = _remap_props(dict(e["props"]), URI_MAP)
        target_uri = URI_MAP.get(e["other_uri"], e["other_uri"])
        match_props = {"iri": props["iri"]} if "iri" in props else {}
        session.run(
            """
            MATCH (s:OntologyClass {uri: $src})
            MATCH (o {uri: $tgt})
            CALL apoc.merge.relationship(s, $rel_type, $match_props, $props, o, $props)
                YIELD rel
            RETURN type(rel) AS t
            """,
            src=canonical, tgt=target_uri,
            rel_type=e["rel_type"], match_props=match_props, props=props,
        )
        delta["edges_moved"] += 1

    session.run(
        "MATCH (c:OntologyClass {uri: $compact}) DETACH DELETE c",
        compact=compact,
    )
    return delta


def run(dry_run: bool = True) -> list[dict]:
    drv = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    drv.verify_connectivity()
    results = []
    try:
        with drv.session() as session:
            for compact, canonical in URI_MAP.items():
                d = migrate_one(session, compact, canonical, dry_run=dry_run)
                results.append(d)
                tag = "[DRY]" if dry_run else "[EXEC]"
                if d.get("skipped"):
                    print(f"  {tag} SKIP {compact!r}: {d['skipped']}")
                else:
                    print(f"  {tag} {compact!r}: {d['in_edges']} in, "
                          f"{d['out_edges']} out → {canonical!r}")
    finally:
        drv.close()
    return results


if __name__ == "__main__":
    dry = "--apply" not in sys.argv
    print(f"=== merge_compact_into_canonical {'(DRY-RUN)' if dry else '(APPLY)'} ===")
    print(f"Target: {len(URI_MAP)} compact-form nodes")
    print()
    results = run(dry_run=dry)
    print()
    total_edges = sum(r.get("edges_moved", 0) for r in results)
    if dry:
        total_in = sum(r.get("in_edges", 0) for r in results)
        total_out = sum(r.get("out_edges", 0) for r in results)
        print(f"DRY-RUN summary: {total_in} in_edges + {total_out} out_edges "
              f"= {total_in + total_out} edge-moves would execute.")
        print("Pass --apply to perform the migration.")
    else:
        print(f"APPLY summary: {total_edges} edges moved across "
              f"{sum(1 for r in results if not r.get('skipped'))} nodes.")
