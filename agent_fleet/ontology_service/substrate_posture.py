"""Substrate connection posture — PURE, so the rules are testable without booting engine-o.

Was `jena_posture.py` for one commit. Renamed when the Neo4j ruling landed the next day: a module
named after one substrate that holds the rules for two is a name that lies, and Weaviate belongs
here next. The FUNCTION names did not change.

**ABSENT AND EMPTY MEAN DIFFERENT THINGS, and that difference is the whole design of the Neo4j
rule.** `docker-compose.e2e.yml` runs engine-o with no Neo4j in the stack at all, behind a
healthcheck that polls `/health` for a 200 — so "engine-o with no graph" is a REAL working
deployment, not a mistake to refuse. But a hardcoded in-cluster fallback address is exactly what
R-012 prohibits. So:

    NEO4J_URI absent  ->  a deploy fault. Readiness refuses and NAMES the variable.
    NEO4J_URI empty   ->  a DECLARATION that this deployment has no graph. Ready, no driver.

Declaring an absence is cheap and visible in review; forgetting is neither. The convention is not
invented here — `docker-compose.e2e.yml` already writes `JENA_SPARQL_ENDPOINT=` empty for exactly
that meaning, and the Jena rule below reads it that way.

**IT DIFFERS DELIBERATELY FROM THE SERVICE-URL SEAL**, where a whitespace-only value counts as
UNDECLARED. That rule governs PEER doors, which every deployment needs; this one governs
SUBSTRATES, which a deployment may legitimately not have. Same spelling, opposite reading — written
down here because otherwise the next reader will "fix" one to match the other.

Born pure for the same reason `state_sparql` and `policy_rules_sparql` were: `main.py` imports
rdflib, weaviate, neo4j and baml_client at module scope, so nothing in it can be exercised by a
unit test, and a rule that cannot be exercised is a rule nobody will notice breaking.

RULED 2026-09-13: **the Fuseki credential has no default.** It used to be a literal in source
(`os.getenv("FUSEKI_PASSWORD", "Admin123!")`), which is a default that fails OPEN in the one
package that legitimately holds the connection — and it did not even match the chart, whose
`fuseki.auth.adminPassword` is a different string. So a pod that lost the secret would not have
run unauthenticated; it would have authenticated as somebody else and failed at the substrate,
one layer further from the cause than a readiness refusal that names the variable.

**The requirement is CONDITIONAL, and the condition is the point.** Engine-o runs without Jena at
all — `_get_local_graph()` parses `Maintenance.rdf` off disk when no endpoint is configured, which
is how the module is developed and how several tests run. Demanding a credential there would
refuse readiness for a deployment that never opens a connection. So: **a credential is required
exactly when an endpoint is configured.**
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Tuple


@dataclass(frozen=True)
class JenaPosture:
    """What engine-o may do with Jena, derived from the environment alone."""

    endpoint: str
    update_endpoint: str
    auth: Optional[Tuple[str, str]]
    #: Variables the deployment owes us. Non-empty means NOT READY.
    missing: Tuple[str, ...]

    @property
    def configured(self) -> bool:
        return bool(self.endpoint)

    @property
    def usable(self) -> bool:
        return self.configured and not self.missing


def _clean(env: Mapping[str, str], key: str, default: str = "") -> str:
    """A whitespace-only value is NOT a declaration.

    `VAR: ""` is what a half-finished chart template renders, and treating it as a value is how a
    fail-open default comes back through the door the fix just closed. Same rule the service-URL
    readiness seal applies to `ONTOLOGY_SERVICE_URL`.
    """
    return (env.get(key) or default or "").strip()


def jena_posture(env: Mapping[str, str]) -> JenaPosture:
    """Read the Jena posture out of an environment mapping. No I/O, no globals."""
    endpoint = _clean(env, "JENA_SPARQL_ENDPOINT")
    username = _clean(env, "JENA_USERNAME", "admin")
    # NO DEFAULT. A password is a secret; a secret with a fallback is a secret the deployment
    # can forget to supply without anybody finding out until the substrate says no.
    password = _clean(env, "FUSEKI_PASSWORD")

    # The SPARQL UPDATE endpoint — engine-o's ONE write path (the pcn disposition stamp).
    # DERIVATION PRESERVED VERBATIM. The DEPLOYED `JENA_SPARQL_ENDPOINT` ends `/ds/sparql`
    # (values-sandbox.yaml:187, confirmed against the live pod), so this substitution FIRES and
    # yields `/ds/update`, the correct Fuseki convention. It does NOT fire for the chart's own
    # default or template, which render `/ds/query` — and per that same values file `/ds/query`
    # returns 405 on POST for this dataset, so such a deployment has a broken READ path before
    # its write path matters. A chart defect, not this module's.
    update_endpoint = _clean(env, "JENA_UPDATE_ENDPOINT") or (
        endpoint.replace("/sparql", "/update") if endpoint else ""
    )

    missing: Tuple[str, ...] = ()
    if endpoint and not password:
        missing = ("FUSEKI_PASSWORD",)

    return JenaPosture(
        endpoint=endpoint,
        update_endpoint=update_endpoint,
        auth=(username, password) if password else None,
        missing=missing,
    )


@dataclass(frozen=True)
class Neo4jPosture:
    """What engine-o may do with Neo4j, derived from the environment alone."""

    uri: str
    auth: Optional[Tuple[str, str]]
    #: Variables the deployment owes us. Non-empty means NOT READY.
    missing: Tuple[str, ...]
    #: The deployment said, in as many words, that it has no graph.
    declared_absent: bool

    @property
    def configured(self) -> bool:
        return bool(self.uri)


def neo4j_posture(env: Mapping[str, str]) -> Neo4jPosture:
    """RULED 2026-09-14: `NEO4J_URI` has NO DEFAULT and readiness names it when undeclared.

    It used to default to `bolt://iagent-neo4j:7687` — a hardcoded in-cluster address standing in
    for a missing declaration, which is the shape the service-URL ruling prohibited for peer URLs
    on 2026-09-11. A pod whose chart never declared the address still reached one, so the map and
    the territory could disagree with nothing to say so.

    ABSENT is a fault; EMPTY is a declaration of absence. See the module docstring for why the two
    differ here and why that is the opposite of the peer-URL reading.
    """
    raw = env.get("NEO4J_URI")
    uri = (raw or "").strip()
    user = _clean(env, "NEO4J_USERNAME", "neo4j")
    # NO DEFAULT, for the same reason FUSEKI_PASSWORD has none.
    password = _clean(env, "NEO4J_PASSWORD")

    declared_absent = raw is not None and not uri
    missing: Tuple[str, ...] = () if (uri or declared_absent) else ("NEO4J_URI",)

    # The credential is NOT required here, and the omission is deliberate rather than an oversight:
    # a Neo4j with auth disabled is a legitimate configuration, nobody has ruled on it, and a
    # requirement invented by a lane becomes a contract nobody agreed to. The default it used to
    # carry is gone, which is the half that was actually wrong.
    return Neo4jPosture(
        uri=uri,
        auth=(user, password) if password else None,
        missing=missing,
        declared_absent=declared_absent,
    )


def missing_declarations(env: Mapping[str, str]) -> Tuple[str, ...]:
    """Every variable the deployment owes engine-o, across every substrate — the readiness answer.

    ONE function so `/health` cannot drift from the rules: a probe that consults two of three
    postures is the join-unasserted defect, and it reads as a complete check.
    """
    return jena_posture(env).missing + neo4j_posture(env).missing
