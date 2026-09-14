"""Jena connection posture — PURE, so the credential rule is testable without booting engine-o.

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
