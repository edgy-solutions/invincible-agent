"""B3 hard gate — Engine O has zero PROVIDER-COUPLED logic.

Per the architect's reframe (2026-06-13, after the third Phase-5-prophecy
occurrence): the gate's INTENT was always "onboarding a new
mesh:resolveInstance provider requires zero Engine O changes that are
PROVIDER-SPECIFIC." A byte-identity check was a proxy for that intent
and turned out to be too literal — when Session 2's A3 missed a
single hardcoded URI in Engine O's discovery Cypher, an in-memory
cache hid the bug until B3's restart invalidated it.

The original byte-identity guard would have either:
  (a) forced the post-A3 Engine O to stay byte-identical to its pre-A3
      form (impossible — the cache invalidation surfaces the bug
      regardless of B3), or
  (b) blocked a legitimate one-line URI realignment (the fix is a
      Session-2 cleanup, not a B3 capability change).

Reframed guard checks the INTENT directly:

  1. The discovery Cypher walks ALL edges from the InstanceIdentifier
     node, naming no specific provider. Adding engine_e_dmc didn't
     require the query to learn about engine_e_dmc — third application
     of the generality gate, certified by code structure.

  2. The fan-out logic is loop-shaped over discovered providers, not
     dispatched by provider name. A new provider plugs in via the
     substrate edge alone — the router iterates without branching on
     identity.

  3. No file in agent_fleet/ontology_service/ contains a hardcoded
     reference to "engine_e_dmc", "engine_dmc", or any provider name
     introduced by this work.

  4. (Class guard, new) — no engine's discovery/routing Cypher
     contains a hardcoded COMPACT-form URI for any class that has a
     canonical full-IRI form. Generalizes the Session-2 A3 lesson:
     if such a hardcode survives a redeploy that invalidates a cache,
     this guard fires red BEFORE the next restart strips the system.

The byte-identity check is removed. It was protecting the wrong
invariant.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent.parent
ENGINE_O_DIR = REPO_ROOT / "agent_fleet" / "ontology_service"


# Names of resolveInstance providers shipped to date. New providers
# added here MUST NOT appear in engine_o source — that's the
# generality-gate proof made concrete.
RESOLVE_INSTANCE_PROVIDERS = [
    "engine_d_resolve_instance",
    "engine_e_resolve_instance",
    "engine_e_dmc_resolve_instance",   # B3 — this is the third
]


# ---------------------------------------------------------------------------
# (1) Discovery is provider-agnostic.
# ---------------------------------------------------------------------------

def test_engine_o_discovery_cypher_is_provider_agnostic():
    """Engine O's discovery query must walk ALL edges from the
    canonical InstanceIdentifier node, naming no specific provider.

    The query MAY filter by:
      - r.iri = 'mesh:resolveInstance' (verb identity — universal)
      - r.endpoint_url IS NOT NULL (correctness check — universal)
    The query MUST NOT filter by:
      - r.provider = <specific value>
      - any string equality on a provider's name
    """
    main_py = (ENGINE_O_DIR / "main.py").read_text(encoding="utf-8")

    # Find the discovery Cypher block.
    m = re.search(
        r"_INSTANCE_RESOLVERS_CYPHER\s*=\s*\"\"\"(.*?)\"\"\"",
        main_py,
        re.DOTALL,
    )
    assert m, "Could not locate _INSTANCE_RESOLVERS_CYPHER in Engine O."
    cypher = m.group(1)

    # The query must walk the canonical FULL-IRI node, not the compact
    # form (Session 2 A3 migration discipline + Phase-5-prophecy lesson).
    assert "http://invincible-agent/mesh#InstanceIdentifier" in cypher, (
        "Discovery Cypher must reference the canonical full-IRI form "
        "'http://invincible-agent/mesh#InstanceIdentifier'. The compact "
        "form 'mesh:InstanceIdentifier' (the pre-A3 shape) reproduces "
        "the third Phase-5-prophecy occurrence — A3-migration miss "
        "masked by the discovery cache."
    )
    assert "'mesh:InstanceIdentifier'" not in cypher, (
        "Discovery Cypher must NOT reference the compact form "
        "'mesh:InstanceIdentifier' (pre-A3 shape). Hardcoded compact "
        "URIs that survive a cache invalidation reproduce the third "
        "Phase-5-prophecy occurrence."
    )

    # Provider-agnostic: no specific provider name appears in the query.
    for provider_name in RESOLVE_INSTANCE_PROVIDERS:
        # The provider's URN suffix names are what would appear in a
        # provider-specific filter.
        assert provider_name not in cypher, (
            f"Discovery Cypher names provider {provider_name!r} — "
            f"this couples Engine O to a specific provider, violating "
            f"the generality claim that resolveInstance is "
            f"registry-discovered."
        )


# ---------------------------------------------------------------------------
# (2) Fan-out is loop-shaped, not provider-dispatched.
# ---------------------------------------------------------------------------

def test_engine_o_fanout_loops_over_discovered_providers():
    """Engine O's fan-out iterates the discovered providers without
    branching on provider identity.

    Concretely: the file must reference the cache list
    (_INSTANCE_RESOLVERS_CACHE / _discover_instance_resolvers) and
    iterate over its entries, but must NOT contain `if provider ==
    'engine_X'` branches anywhere in the resolution path.
    """
    main_py = (ENGINE_O_DIR / "main.py").read_text(encoding="utf-8")

    # Loop / iteration vocabulary
    iterates = any(
        token in main_py
        for token in ("_discover_instance_resolvers", "_INSTANCE_RESOLVERS_CACHE")
    )
    assert iterates, (
        "Engine O does not appear to iterate over discovered providers — "
        "fan-out must be loop-shaped over the registry, not "
        "dispatched."
    )

    # No provider-specific branch.
    for provider in [
        '"engine_d"', "'engine_d'",
        '"engine_e"', "'engine_e'",
        '"engine_e_dmc"', "'engine_e_dmc'",
        '"engine_dmc"', "'engine_dmc'",
    ]:
        assert provider not in main_py, (
            f"Engine O contains a hardcoded provider name "
            f"{provider}. The router must remain provider-agnostic — "
            f"adding a new provider via registration alone is the "
            f"generality claim."
        )


# ---------------------------------------------------------------------------
# (3) No provider-name leakage in Engine O at all.
# ---------------------------------------------------------------------------

def test_engine_o_files_contain_no_resolveinstance_provider_names():
    """No file under agent_fleet/ontology_service/ mentions a
    resolveInstance provider by name. The router learns about
    providers via the substrate, never by hardcoded reference.
    """
    files = [p for p in ENGINE_O_DIR.rglob("*.py") if "__pycache__" not in str(p)]
    violations = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        for provider in RESOLVE_INSTANCE_PROVIDERS:
            if provider in text:
                violations.append(f"{f.relative_to(REPO_ROOT)}: {provider}")

    assert not violations, (
        f"Engine O files contain hardcoded resolveInstance provider "
        f"names: {violations}. The router must not know about "
        f"specific providers — adding a new one via registration "
        f"alone is the generality claim."
    )


# ---------------------------------------------------------------------------
# (4) Class guard — no hardcoded compact-form URIs across the fleet.
#
# Generalizes the third Phase-5-prophecy occurrence (A3 missed Engine
# O's discovery Cypher). Any engine's discovery / routing / linkage
# Cypher that hardcodes a `mesh:` / `idp:` / `mro:` / `mil:` compact
# form URI will reproduce the identical failure mode the next time a
# cache invalidates.
# ---------------------------------------------------------------------------

COMPACT_PREFIXES_WITH_CANONICAL_FULL_IRI = [
    # (compact_prefix, canonical_full_iri_marker)
    ("mesh:InstanceIdentifier", "http://invincible-agent/mesh#InstanceIdentifier"),
    ("mesh:InstanceResolution", "http://invincible-agent/mesh#InstanceResolution"),
    ("mesh:AgentTask",          "http://invincible-agent/mesh#AgentTask"),
    ("mesh:AgentResponse",      "http://invincible-agent/mesh#AgentResponse"),
    ("idp:Dataset",             "http://invincible-agent/idp#Dataset"),
    # Added 2026-06-15: source-resident regressions surfaced by the
    # mesh:Thing investigation's writer-hunt expansion. Three source
    # locations carried hardcoded compact mro:* URIs (seed_mro_extension_runtime.py
    # CLASSES list + agent_fleet/neo4j_expert/main.py line 145 input_uri +
    # lines 355-356 _LABEL_TO_CLASS_URI mapping). All five mro:* classes
    # below have canonical full-IRI counterparts materialized by
    # sync_jena_ontologies_to_neo4j from mro_extension.ttl.
    #
    # mro:Part is INTENTIONALLY OMITTED from this list — it has no
    # canonical full-IRI declaration in the substrate (would need a
    # TTL update + canonical ingest). Engine E's _LABEL_TO_CLASS_URI
    # keeps mro:Part compact and the widened substrate guard
    # correctly flags it as a TBox-decision item alongside
    # data:Dashboard and data:Dataset. Adding mro:Part here would
    # spuriously block Engine E's source until the TBox declaration
    # lands; the substrate guard is the right surface for that wait.
    ("mro:TechnicalManual",     "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/TechnicalManual"),
    ("mro:Diagram",             "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/Diagram"),
    ("mro:ProcedureStep",       "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/ProcedureStep"),
    ("mro:Equipment",           "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/Equipment"),
    ("mro:Procedure",           "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/Procedure"),
    ("mro:Symptom",             "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/Symptom"),
]

# The allowlist is split into TWO categories — same exempt status, but
# the distinction matters semantically and is enforced by the
# scripts/-scanning guard below. The architect's framing
# (2026-06-13): a one-time migration script that intentionally
# references compact forms in its DELETE/MERGE-and-redirect logic is
# CATEGORICALLY DIFFERENT from a re-runnable seed that bootstraps a
# sandbox — the former is a tool that runs once and stops; the latter
# is a writer that runs every cluster init.
#
# The original allowlist conflated them under "scripts intentionally
# reference compact forms." That over-broad allowlist licensed
# seed_sandbox_predicates.py to keep reintroducing compact-form
# OntologyClass nodes on every sandbox seed (caught 2026-06-13 late
# when the substrate-level test_no_compact_form_for_migrated_subjects
# guard fired red on mesh:GraphExpertResponse + mesh:KnowledgeRetrievalResponse,
# and the trace led back to ENGINES in seed_sandbox_predicates.py).
FILES_THAT_LEGITIMATELY_DOCUMENT_MIGRATION = {
    # State/ADR docs explain the migration AND name the pre-A3 forms.
    # That's the documentation, not a runtime path.
    "tests/routing/STATE_GATEWAY_V02.md",
    "tests/routing/STATE_RECIPE_V2.md",
    "tests/routing/STATE_2026_06_11.md",
    "tests/routing/MORNING_HANDOFF.md",
    "tests/routing/SESSION_3_DEPLOY_CHECKLIST.md",
    "tests/routing/STEP0_DOCS_PHASE_SPEC.md",
    "docs/adr/ADR-0006-verb-registry-location.md",
    "docs/adr/ADR-0019-ontology-routing-substrate.md",
    "tests/routing/test_substrate_invariants.py",  # uses constants
    "tests/routing/test_b3_engine_o_unchanged.py", # this file, naming the rule
}

# ONE-TIME migration scripts: legitimately reference compact forms in
# their MATCH-and-redirect logic, ran once historically. Exempt.
ONE_TIME_MIGRATION_SCRIPTS = {
    "scripts/migrate_compact_to_full_iri.py",
    "scripts/retype_verbs_to_real_subjects.py",
    "scripts/phase5_catalog_verb_migration.py",
    "scripts/recreate_verb_edges.py",
    "scripts/sync_predicate_to_typed_inputs.py",
}

# RE-RUNNABLE seed scripts: bootstrap state every time they run. MUST
# use canonical full-IRI forms. NOT exempt — held to the same
# canonical-form discipline as engine source.
RE_RUNNABLE_SEED_SCRIPTS_NOT_EXEMPT = {
    "scripts/seed_sandbox_predicates.py",
    "scripts/seed_datahub_catalog.py",
    "scripts/seed_mro_extension_runtime.py",
    "scripts/seed_weaviate_manuals.py",
}


def test_no_engine_hardcodes_a_migrated_compact_uri_in_a_query():
    """No engine source (agent_fleet/*) NOR re-runnable seed script
    (scripts/seed_*) hardcodes a compact-form URI for a class that has
    a canonical full-IRI form in the substrate.

    A hardcoded compact URI in a Cypher query / SDK declaration /
    config will reproduce the third Phase-5-prophecy occurrence the
    next time a cache invalidates: pre-A3 shape works while the cache
    holds, dies when the cache rebuilds against the post-A3 substrate.

    Re-runnable seeds (scripts/seed_*.py) get extra scrutiny because
    a compact-form URI there doesn't just risk a cache miss — it
    actively re-creates duplicate OntologyClass nodes on every
    cluster init, defeating prior migrations by overwriting the
    substrate's canonical state with shadow compact forms. The
    architect's framing (2026-06-13): "seeds are re-runnable; they
    must use canonical form like any other source." Seeds are
    explicitly held to the canonical-form contract.

    Exempt: state docs, ADRs, ONE-TIME migration scripts
    (FILES_THAT_LEGITIMATELY_DOCUMENT_MIGRATION +
    ONE_TIME_MIGRATION_SCRIPTS).
    """
    EXEMPT = FILES_THAT_LEGITIMATELY_DOCUMENT_MIGRATION | ONE_TIME_MIGRATION_SCRIPTS
    # Scan agent_fleet/*.py (the original scope) PLUS scripts/seed_*.py
    # (the architect's widening — re-runnable seeds were the blind spot
    # the old allowlist created).
    paths = list((REPO_ROOT / "agent_fleet").rglob("*.py"))
    paths += list((REPO_ROOT / "scripts").glob("seed_*.py"))

    violations = []
    for fp in paths:
        if "__pycache__" in str(fp):
            continue
        rel = fp.relative_to(REPO_ROOT).as_posix()
        if rel in EXEMPT:
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for compact, full in COMPACT_PREFIXES_WITH_CANONICAL_FULL_IRI:
            for delim in ("'", '"'):
                lit = f"{delim}{compact}{delim}"
                if lit in text:
                    violations.append(
                        f"{rel}: hardcoded compact-form {lit} "
                        f"(canonical: {full})"
                    )
    assert not violations, (
        f"Hardcoded compact-form URIs detected. These reproduce the "
        f"third Phase-5-prophecy occurrence (A3-migration miss masked "
        f"by an in-memory cache, surfaces on next cache invalidation). "
        f"For seed scripts the failure mode is worse: every re-seed "
        f"re-creates duplicate OntologyClass nodes alongside the "
        f"canonicals. Migrate to the canonical full-IRI form:\n"
        + "".join(f"  - {v}\n" for v in violations[:15])
        + (f"  ... and {len(violations) - 15} more\n"
           if len(violations) > 15 else "")
    )
