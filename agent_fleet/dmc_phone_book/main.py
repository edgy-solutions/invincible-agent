"""B3 — DMC phone book.

The third instance-resolution provider for `mesh:resolveInstance`, per the
architect's B3 recipe (2026-06-13). Takes an identifier-shaped token,
canonicalizes to S1000D DMC string form, looks up the matching DataModule
instance in Neo4j (the B2-ingested mil:* substrate), and returns the
canonical mil:* content kind with provenance.

This service exists to close the exact gap captured live on 2026-06-13:

  Query: "Tell me about DMC-SANDBOXRTX-B-72-30-10-00A-520A-A"
  BEFORE B3: instance_resolved=false, both providers returned 0,
             LLM fell through to mro:WorkInstruction.
  AFTER B3:  instance_resolved=true, this provider returns 1,
             resolved subject is mil:ProcedureDataModule.

Boundary rule rides into this code: the SANDBOXRTX marker may appear in
SANDBOX test data this service reads from Neo4j, but MUST NOT appear in
this source file or in any Helm value, env default, or registration
declaration. The negative-boundary guard in
tests/routing/test_b2_ingest_sandboxrtx.py asserts this for every
deploy-path artifact (this file included).

The hard gate for B3: zero Engine O changes. This is the third
application of the generality gate (after engine_d for catalog assets
and engine_e for maintenance instances). The proof is git-diff-empty
on agent_fleet/ontology_service/, not inspection. See
tests/routing/test_b3_engine_o_unchanged.py.

Same-canonicalizer-both-sides rule: this service imports
doc_tools.parsers.dmc_canonicalizer.canonicalize_dmc, the IDENTICAL
function s1000d_ingest uses to write canonical-form DMCs. A bug in the
canonicalizer fails the B2 ingest tests AND this service's probes
identically — the architectural property the rule was named for.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, List, Optional

from fastapi import FastAPI
from neo4j import GraphDatabase
from pydantic import BaseModel

logger = logging.getLogger("dmc-phone-book")
logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------------
# Shared canonicalizer — same code as the B2 ingest writer's copy in
# doc-tools/doc_tools/parsers/dmc_canonicalizer.py. The two files are
# kept byte-identical; tests/routing/test_b3_canonicalizer_drift.py
# asserts SHA256 equality so a divergence fails CI before it can break
# routing. This is the "same canonicalizer both sides" rule made
# mechanical: drift detection at the test layer, single import path
# at runtime.
# ---------------------------------------------------------------------------

try:
    from utils.dmc_canonicalizer import canonicalize_dmc
except ImportError:
    from agent_fleet.utils.dmc_canonicalizer import canonicalize_dmc


# ---------------------------------------------------------------------------
# Pydantic models — match the existing ResolveInstance interface
# engine_d and engine_e expose. The router's Recipe-v2 dispatcher consumes
# these identically across all providers.
# ---------------------------------------------------------------------------

class ResolveInstanceRequest(BaseModel):
    identifier: str
    query: Optional[str] = None


class InstanceCandidate(BaseModel):
    instance_id: str   # the canonical DMC string serves as the identity
    class_uri: str     # full-IRI mil:* content kind
    label: str
    score: float       # 1.0 for exact match (we have a primary key)


class ResolveInstanceResponse(BaseModel):
    candidates: List[InstanceCandidate]


# ---------------------------------------------------------------------------
# Neo4j driver — lazy-init so /health works before the substrate is up.
# ---------------------------------------------------------------------------

_DRIVER: Any = None


def _driver():
    global _DRIVER
    if _DRIVER is None:
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USERNAME", "neo4j")
        pw = os.environ.get("NEO4J_PASSWORD", "changeme")
        _DRIVER = GraphDatabase.driver(uri, auth=(user, pw))
    return _DRIVER


# ---------------------------------------------------------------------------
# Lookup — pure Cypher, MATCH by canonical DMC against the
# dmc_uri_unique-indexed :DataModule nodes B2 wrote.
# ---------------------------------------------------------------------------

CYPHER_LOOKUP = """
MATCH (dm:DataModule {dmc: $canonical})-[:INSTANCE_OF]->(kind:OntologyClass)
RETURN dm.dmc AS dmc, kind.uri AS class_uri,
       coalesce(dm.techName, dm.dmc) AS label
LIMIT 5
"""


def lookup_dmc(canonical: str) -> List[dict]:
    """Lookup a canonical DMC against the B2 substrate. Returns the
    candidate dicts (empty list = honest "no match")."""
    with _driver().session() as session:
        result = session.run(CYPHER_LOOKUP, {"canonical": canonical})
        return [dict(r) for r in result]


# ---------------------------------------------------------------------------
# Registration — the SDK call mirrors engine_d's shape exactly. This is
# the third provider for mesh:resolveInstance. Zero Engine O changes
# required — the router discovers this provider via the substrate edge
# the gateway saga writes during this registration.
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        try:
            from utils.mesh_registration import register_engine_to_mesh
        except ImportError:
            from agent_fleet.utils.mesh_registration import register_engine_to_mesh

        endpoint = os.getenv(
            "DMC_PHONE_BOOK_SVC_URL",
            "http://iagent-dmc-phone-book:8091",
        ).rstrip("/") + "/resolve_instance"

        register_engine_to_mesh(
            name="engine_dmc_resolve_instance",
            description=(
                "Resolves a Data Module Code (DMC) — the S1000D identity "
                "of a technical-manual data module — to its canonical "
                "mil:* content kind (ProcedureDataModule, "
                "FaultIsolationDataModule, etc.). Looks up the "
                "canonical DMC string form against the maintenance "
                "documentation graph; returns the matching content "
                "kind with provenance. An empty list is a first-class "
                "answer — the provider abstains honestly when the "
                "input isn't a DMC or no module matches. Used by the "
                "router's instance-resolution pre-step (Recipe v2). "
                "Third application of the zero-Engine-O-changes "
                "generality gate."
            ),
            verb="mesh:resolveInstance",
            input_uri="http://invincible-agent/mesh#InstanceIdentifier",
            output_uri="http://invincible-agent/mesh#InstanceResolution",
            verb_synonyms=[
                "resolve dmc",
                "look up data module",
                "what kind of data module",
                "classify dmc",
                "identify data module code",
            ],
            endpoint_url=endpoint,
            owner_persona="TECH_WRITER",
            domains=["MAINTENANCE"],
            cost_class="fast",
            requires_human_approval=False,
            provider="engine_dmc",
            # Direct Neo4j primary-key lookup. Sub-second consistently;
            # 2s budget is plenty of headroom and matches the engine_e
            # default for analogous graph lookups.
            timeout_s=2.0,
        )
        logger.info("mesh:resolveInstance registered for engine_dmc")
    except Exception as e:
        logger.error(f"[DMC Phone Book] mesh:resolveInstance registration failed: {e}")

    yield


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="DMC Phone Book",
    description=(
        "B3 — instance-resolution provider for mesh:resolveInstance over "
        "S1000D Data Module Codes. Same-canonicalizer-both-sides as the "
        "B2 ingest writer; substrate-indexed lookup; zero Engine O "
        "changes."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/resolve_instance", response_model=ResolveInstanceResponse)
async def resolve_instance(request: ResolveInstanceRequest) -> ResolveInstanceResponse:
    """Resolve a DMC-shaped identifier to its canonical mil:* content kind.

    Contract (per Recipe v2 + ADR-0019 Contract A):
      - Empty list is a first-class answer. The phone book abstains
        honestly when (a) the input isn't a DMC and the canonicalizer
        returns None, or (b) the canonical form has no matching
        DataModule in Neo4j.
      - Class assignment comes from the substrate's INSTANCE_OF edge
        (which B2's ingest wrote deterministically from the info code).
        NEVER from the identifier's lexical shape.
      - Score is 1.0 on exact match (we have a primary-key index) or
        0.0 on miss. No fuzziness — DMCs are precise identifiers.

    Boundary rule observance: this code reads from the substrate the B2
    ingest wrote. In sandbox/CI that substrate may contain SANDBOXRTX
    test instances; on the work cluster it contains real DMCs from
    real ingested manuals. Same code, different data population — the
    boundary the architect made mechanical.
    """
    raw = (request.identifier or "").strip()
    canonical = canonicalize_dmc(raw)
    if canonical is None:
        # Honest abstain: not a DMC shape, nothing to look up.
        logger.info(
            f"abstain on non-DMC input: {raw!r} (canonicalize returned None)"
        )
        return ResolveInstanceResponse(candidates=[])

    try:
        rows = lookup_dmc(canonical)
    except Exception as e:
        logger.error(f"Neo4j lookup failed for canonical={canonical!r}: {e}")
        return ResolveInstanceResponse(candidates=[])

    candidates = [
        InstanceCandidate(
            instance_id=row["dmc"],
            class_uri=row["class_uri"],
            label=row["label"] or row["dmc"],
            score=1.0,
        )
        for row in rows
    ]
    logger.info(
        f"resolve_instance: raw={raw!r} canonical={canonical!r} "
        f"candidates={len(candidates)}"
    )
    return ResolveInstanceResponse(candidates=candidates)
