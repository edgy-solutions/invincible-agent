"""RULED 2026-09-13 — the Fuseki credential has NO DEFAULT, and a configured endpoint without it
fails readiness naming the variable.

`_JENA_PASSWORD = os.getenv("FUSEKI_PASSWORD", "Admin123!")` is a default that fails OPEN in the
one package that legitimately holds the connection. It did not even agree with the chart, whose
`fuseki.auth.adminPassword` renders a different string into the `FUSEKI_PASSWORD` secret the
engine pods consume by `envFrom` — so a pod that lost the secret authenticated as somebody who
does not exist and failed at the substrate, one layer further from the cause than a readiness
refusal would have been.

THE REQUIREMENT IS CONDITIONAL AND THAT IS THE WHOLE DESIGN. Engine-o runs with no Jena at all —
`_get_local_graph()` parses `Maintenance.rdf` off disk — so demanding a credential unconditionally
would refuse readiness for a deployment that never opens a connection. Required exactly when an
endpoint is configured. The controls below assert BOTH directions, because "refuses when the
credential is missing" and "always refuses" are the same test result against a probe that can
only fail.

WHY THE SOURCE ARM PARSES INSTEAD OF GREPPING: the fix's own comments quote `verify=False` and
`FUSEKI_PASSWORD` while explaining their removal, so a string check would match the explanation
and go red against the corrected code. That shape has now bitten three instruments in two lanes
in one week — a check matching a STRING cannot see a BEHAVIOUR. `ast` does not see comments at
all, which makes the blind spot structural rather than a matter of writing a cleverer regex.

Run: uv run --frozen pytest tests/test_a_missing_fuseki_credential_fails_readiness.py -v
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agent_fleet.ontology_service.substrate_posture import (  # noqa: E402
    jena_posture,
    missing_declarations,
    neo4j_posture,
)

_MAIN = _REPO / "agent_fleet" / "ontology_service" / "main.py"
_ENDPOINT = "http://iagent-fuseki.iagent.svc.cluster.local:3030/ds/query"


# --------------------------------------------------------------------------- the rule


def test_a_configured_endpoint_without_a_credential_is_NOT_READY():
    """THE RULING."""
    p = jena_posture({"JENA_SPARQL_ENDPOINT": _ENDPOINT})
    assert p.missing == ("FUSEKI_PASSWORD",), (
        f"a configured endpoint with no credential reported {p.missing!r} — readiness cannot "
        f"refuse for a reason it was never told about"
    )
    assert not p.usable
    assert p.auth is None, "auth was assembled from an empty password rather than withheld"


def test_a_configured_endpoint_WITH_a_credential_is_READY():
    """THE CONTROL. Without it, the assertion above is satisfied by a posture that never passes —
    and a readiness probe that never passes takes engine-o out of the Service permanently."""
    p = jena_posture({"JENA_SPARQL_ENDPOINT": _ENDPOINT, "FUSEKI_PASSWORD": "s3cret"})
    assert p.missing == ()
    assert p.usable
    assert p.auth == ("admin", "s3cret"), "the default USERNAME is still admin; only the secret lost its default"


def test_NO_endpoint_and_no_credential_is_READY():
    """THE OTHER CONTROL, and the one that keeps the rule conditional.

    No endpoint means the local-graph path — no connection is opened, so there is no credential to
    owe. An unconditional requirement would refuse readiness for a legitimate deployment, which is
    how a security fix becomes an outage.
    """
    p = jena_posture({})
    assert p.missing == ()
    assert not p.configured
    assert p.auth is None


def test_a_whitespace_only_credential_counts_as_MISSING():
    """`FUSEKI_PASSWORD: ""` is what a half-rendered template produces. Accepting it would put the
    fail-open default back through the door this change closed."""
    p = jena_posture({"JENA_SPARQL_ENDPOINT": _ENDPOINT, "FUSEKI_PASSWORD": "   "})
    assert p.missing == ("FUSEKI_PASSWORD",)
    assert p.auth is None


def test_a_whitespace_only_endpoint_is_NOT_configured():
    """The same rule on the other variable — otherwise a blank endpoint would demand a credential
    for a connection nobody can make."""
    p = jena_posture({"JENA_SPARQL_ENDPOINT": "   "})
    assert not p.configured
    assert p.missing == ()


# --------------------------------------------------------------------------- the floor on main.py
#
# The rule lives in a pure module; these assert that main.py cannot re-introduce what the rule
# removed. Parsed, never grepped — see the module docstring.


def _main_tree() -> ast.Module:
    return ast.parse(_MAIN.read_text(encoding="utf-8"))


def test_no_TLS_VERIFICATION_OVERRIDE_survives_anywhere_in_main():
    """Every Jena call used to pass `verify=False`. It was INERT against today's plain-http
    endpoint — verification applies to https — which is precisely why it was dangerous: a latent
    override waiting for the first deployment to point `externalFuseki.url` at an https address,
    where it would have disabled verification silently with nothing going red.

    Asserted over every call in the module, not just the Jena ones: the next one to be written is
    the one nobody remembers to check.
    """
    offenders = []
    for node in ast.walk(_main_tree()):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "verify" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                offenders.append(node.lineno)
    assert not offenders, (
        f"verify=False re-appeared at main.py line(s) {offenders}. TLS verification is not a "
        f"per-call-site decision; the Jena client factory is the one place that may express it."
    )


def test_no_CREDENTIAL_DEFAULT_survives_anywhere_in_main():
    """`os.getenv("FUSEKI_PASSWORD", <anything>)` is the defect itself. Checked for any secret-ish
    variable, not only the one that was wrong, because the class is what matters."""
    secretish = ("FUSEKI_PASSWORD", "NEO4J_PASSWORD", "WEAVIATE_API_KEY", "JENA_PASSWORD")
    offenders = []
    for node in ast.walk(_main_tree()):
        if not (isinstance(node, ast.Call) and len(node.args) == 2):
            continue
        fn = node.func
        is_getenv = (isinstance(fn, ast.Attribute) and fn.attr == "getenv") or (
            isinstance(fn, ast.Name) and fn.id == "getenv"
        )
        if not is_getenv:
            continue
        name, default = node.args
        if not (isinstance(name, ast.Constant) and name.value in secretish):
            continue
        if not (isinstance(default, ast.Constant) and default.value in ("", None)):
            offenders.append(f"{name.value} at line {node.lineno}")
    assert not offenders, (
        f"a credential default was re-added: {offenders}. A secret with a fallback is a secret the "
        f"deployment can forget to supply without anybody finding out."
    )


def test_no_SUBSTRATE_ADDRESS_DEFAULT_survives_anywhere_in_main():
    """RULED 2026-09-14. `NEO4J_URI` defaulted to `bolt://iagent-neo4j:7687` — a hardcoded
    in-cluster address standing in for a missing declaration, so a pod the chart never configured
    still reached a real graph and the map could disagree with the territory in silence.

    Over the CLASS of substrate addresses, for the same reason the credential check is: the one
    that got reported is never the only one.
    """
    addresses = ("NEO4J_URI", "JENA_SPARQL_ENDPOINT", "JENA_UPDATE_ENDPOINT", "WEAVIATE_HTTP_HOST")
    offenders = []
    for node in ast.walk(_main_tree()):
        if not (isinstance(node, ast.Call) and len(node.args) == 2):
            continue
        fn = node.func
        is_getenv = (isinstance(fn, ast.Attribute) and fn.attr == "getenv") or (
            isinstance(fn, ast.Name) and fn.id == "getenv"
        )
        if not is_getenv:
            continue
        name, default = node.args
        if not (isinstance(name, ast.Constant) and name.value in addresses):
            continue
        if not (isinstance(default, ast.Constant) and default.value in ("", None)):
            offenders.append(f"{name.value} -> {ast.unparse(default)} at line {node.lineno}")
    assert not offenders, (
        f"a substrate address default was re-added: {offenders}. An address the deployment did "
        f"not declare must not resolve to one somebody hardcoded."
    )


# --------------------------------------------------------------------------- declared, not derived


def test_the_update_endpoint_is_NOT_DERIVED_from_a_query_endpoint_ending_in_sparql():
    """RULED 2026-09-14. The old fallback was `endpoint.replace("/sparql", "/update")`.

    THE FIXTURE IS THE WHOLE TEST. It uses an endpoint ending `/ds/sparql` — the one spelling the
    substitution actually transformed, and the one the sandbox deploys. Any other fixture passes
    against the old code too, and would have sealed nothing: a `/ds/query` endpoint came out of
    the substitution unchanged, so the derivation and its absence are indistinguishable there.
    """
    p = jena_posture(
        {"JENA_SPARQL_ENDPOINT": "http://iagent-fuseki:3030/ds/sparql", "FUSEKI_PASSWORD": "pw"}
    )
    assert p.update_endpoint == "", (
        f"a write endpoint was derived from the query endpoint: {p.update_endpoint!r}. String "
        f"surgery that happens to work on one spelling is one chart edit from POSTing updates "
        f"at a query endpoint."
    )


def test_a_declared_update_endpoint_is_used_verbatim():
    """THE CONTROL. Without it, 'never derives' is satisfied by a posture that never produces a
    write endpoint at all — which would refuse every write in every deployment."""
    p = jena_posture(
        {
            "JENA_SPARQL_ENDPOINT": "http://iagent-fuseki:3030/ds/sparql",
            "JENA_UPDATE_ENDPOINT": "http://iagent-fuseki:3030/ds/update",
            "FUSEKI_PASSWORD": "pw",
        }
    )
    assert p.update_endpoint == "http://iagent-fuseki:3030/ds/update"


def test_the_write_refusal_NAMES_the_variable():
    """A 503 reading "Jena update endpoint not configured" sends the reader to the code. The
    variable name sends them to the chart, which is where the fix is."""
    src = _MAIN.read_text(encoding="utf-8")
    fn = src[src.index("async def _execute_sparql_update") :][:900]
    assert "JENA_UPDATE_ENDPOINT is not declared" in fn, (
        "the write path refuses without naming the variable the deployment has to declare"
    )


# --------------------------------------------------------------------------- the Neo4j rule
#
# ABSENT is a fault; EMPTY is a declaration of absence. Both halves are the rule, and the second
# is not a nicety: `docker-compose.e2e.yml` runs engine-o with no Neo4j in the stack at all.


def test_an_UNDECLARED_neo4j_uri_is_a_deploy_fault():
    """THE RULING. No default, and readiness must be able to say which variable."""
    p = neo4j_posture({})
    assert p.missing == ("NEO4J_URI",)
    assert p.uri == "", "a fallback address was substituted for a missing declaration"
    assert not p.declared_absent


def test_a_DECLARED_EMPTY_neo4j_uri_is_a_deployment_WITHOUT_A_GRAPH():
    """THE CONTROL THAT KEEPS A REAL DEPLOYMENT ALIVE.

    Without this half, the rule above refuses readiness for `docker-compose.e2e.yml`, whose
    engine-o has no Neo4j service to reach and whose healthcheck polls `/health` for a 200 with
    everything downstream waiting on it. Declaring an absence is cheap and visible in review;
    forgetting is neither, and the two must not produce the same answer.
    """
    p = neo4j_posture({"NEO4J_URI": ""})
    assert p.missing == ()
    assert p.declared_absent
    assert not p.configured


def test_a_declared_neo4j_uri_is_used_verbatim():
    p = neo4j_posture({"NEO4J_URI": "bolt://declared:7687", "NEO4J_PASSWORD": "pw"})
    assert p.uri == "bolt://declared:7687"
    assert p.missing == ()
    assert p.auth == ("neo4j", "pw")


def test_the_e2e_stack_DECLARES_its_absent_graph():
    """THE CONSUMER, sealed rather than remembered.

    This rule breaks `docker-compose.e2e.yml` the moment that file stops declaring `NEO4J_URI`,
    and the failure would surface as a healthcheck timing out after 60 retries in a stack nobody
    associates with a posture module. A fix is not finished until you have read the consumer of
    what you fixed; this is that reading, written down so it cannot rot.
    """
    compose = (_REPO / "docker-compose.e2e.yml").read_text(encoding="utf-8")
    assert "NEO4J_URI=" in compose, (
        "docker-compose.e2e.yml no longer declares NEO4J_URI. Engine-o's readiness will refuse "
        "and its healthcheck will never go green — declare it empty to say the stack has no graph."
    )


def test_missing_declarations_UNIONS_every_substrate():
    """The readiness answer comes from one function. Two substrates owed at once must BOTH be
    named, or a deploy fault gets fixed one variable per redeploy."""
    both = missing_declarations({"JENA_SPARQL_ENDPOINT": _ENDPOINT})
    assert set(both) == {"FUSEKI_PASSWORD", "NEO4J_URI"}, both
    assert missing_declarations({"JENA_SPARQL_ENDPOINT": "", "NEO4J_URI": ""}) == ()


def test_readiness_CONSULTS_the_posture_rather_than_restating_it():
    """The join. The pure module can be perfectly right while `/health` never asks it — two
    correct halves and an unasserted relation between them is a defect this repo has paid for.

    Asserted structurally: the `health` handler must reference the posture object. A handler that
    recomputed the condition from the environment would pass every test above and still drift.
    """
    health = next(
        n
        for n in ast.walk(_main_tree())
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "health"
    )
    names = {n.id for n in ast.walk(health) if isinstance(n, ast.Name)}
    assert "_missing_declarations" in names, (
        "/health does not call the ONE function that unions every substrate's missing "
        "declarations — the rules and the probe that is supposed to enforce them meet nowhere. "
        "A handler that re-checks one posture directly passes every other test in this file and "
        "silently stops covering the next substrate added."
    )


def test_every_JENA_client_is_built_by_the_ONE_factory():
    """Reachability is a property of a path. The factory raising on a missing credential protects
    only the call sites that go THROUGH it, so a fifth site building its own client would be
    unauthenticated, unverified, and invisible to every assertion above.

    SCOPED TO THE SUBSTRATE, NOT TO httpx. main.py builds two other `httpx.AsyncClient`s — the
    resolveInstance and enumerateInstances fan-outs — and those are PEER doors: calling a named
    operation on another engine is the permitted pattern and has nothing to do with a store
    credential. A blanket 'one AsyncClient in this module' assertion would go red against healthy
    code, which is how a seal teaches people to delete seals. So the rule is expressed as it is
    meant: a function that names a JENA endpoint must not construct its own client.
    """
    offenders = []
    for fn in ast.walk(_main_tree()):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn.name == "_jena_client":
            continue
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        if not (names & {"_JENA_ENDPOINT", "_JENA_UPDATE_ENDPOINT"}):
            continue
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "AsyncClient"
            ):
                offenders.append(f"{fn.name} at line {node.lineno}")
    assert not offenders, (
        f"a Jena connection is built outside the factory: {offenders}. That path gets no "
        f"credential check and no TLS default — both properties live in `_jena_client()` only."
    )
