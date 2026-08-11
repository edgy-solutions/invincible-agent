"""Client for the generic ``/policy_rules`` endpoint — the CONSUMER that interprets the served Turtle.

engine-o is a thin window: it serves the rule subgraph as Turtle + whether the graph holds any triples,
and interprets nothing. THIS is the only place a ruleset flows toward the proposer, so this is where it
is loaded and validated — validate-at-serve becomes validate-here, report-don't-reject: the corrupt
ruleset can't reach the proposer looking valid because nothing consumes the raw Turtle. The
loader/validator live here (with the proposer that uses them), not duplicated into engine-o.

The FOUR failure modes are decided HERE, where the distinctions are made:
  * ``not_found`` — the graph holds no triples at all (likely a bad graph name).
  * ``empty``     — the graph holds triples but no rules of this kind (the abstain-everything case;
                    the caller decides what an empty ruleset means for its domain).
  * ``invalid``   — rules present but ``validate_ruleset`` returns errors (reported, not rejected).
  * ``ok``        — rules present and valid.

CONSTRUCT-over-SELECT: the served Turtle preserves RDF term types, so boolean rule conditions load as
booleans. (The engine-o SELECT path stringifies terms — see the runbook finding; typed reads go
CONSTRUCT->parse.)
"""
from __future__ import annotations

import os

import requests

try:  # lazy-import dance
    from policy_rules_loader import load_disposition_rules  # type: ignore[no-redef]
    from policy_evaluator import validate_ruleset  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.restate_analyst.policy_rules_loader import load_disposition_rules
    from agent_fleet.restate_analyst.policy_evaluator import validate_ruleset

# Module-level, not function-local: engine-a's image flattens agent_fleet/utils -> /app/utils.
try:  # pragma: no cover - import path differs by runtime
    from utils.service_identity import outbound_auth_headers  # type: ignore[no-redef]
except ImportError:  # pragma: no cover
    from agent_fleet.utils.service_identity import outbound_auth_headers

ENGINE_O_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://iagent-engine-o:8084")
_HTTP_TIMEOUT = float(os.getenv("AGENT_HTTP_TIMEOUT", "30"))


def parse_policy_rules(turtle: str, *, graph_nonempty: bool, known_dispositions=None, ruleset_label: str = "") -> dict:
    """Load + validate the served Turtle, deciding the four failure modes. PURE (no HTTP) — seals as a
    unit against the real TTL. Returns a JSON-native dict so it rides a Restate journal directly.

    ``known_dispositions`` is the caller's registered actions (its domain vocab). Absent -> the
    registration check is skipped honestly (``registration_checked: false``, no false 'unregistered'
    flags) while the structural checks (subsumption, schema-drift) still run."""
    import rdflib

    g = rdflib.Graph()
    if turtle and turtle.strip():
        g.parse(data=turtle, format="turtle")
    ruleset, category_classes, ruleset_ref = load_disposition_rules(g, ruleset_label=ruleset_label)

    if not ruleset:
        status = "empty" if graph_nonempty else "not_found"
        return {
            "status": status, "ruleset": [], "category_classes": category_classes,
            "ruleset_ref": ruleset_ref if status == "empty" else "",
            "valid": True, "validation_errors": [], "registration_checked": False,
        }

    known = set(known_dispositions or [])
    registration_checked = bool(known)
    # No known set -> substitute the present dispositions so the registration check is a no-op (never a
    # false 'unregistered'); subsumption + schema-drift still run. Marked so the caller knows.
    check_against = known or {r.get("proposesDisposition") for r in ruleset}
    errors = validate_ruleset(ruleset, known_dispositions=check_against)
    return {
        "status": "invalid" if errors else "ok",
        "ruleset": ruleset, "category_classes": category_classes, "ruleset_ref": ruleset_ref,
        "valid": not errors, "validation_errors": errors, "registration_checked": registration_checked,
    }


def fetch_policy_rules(graph: str, ruleset_label: str = "", *, known_dispositions=None) -> dict:  # pragma: no cover - deploy-gated
    """LIVE fetch: POST the generic engine-o ``/policy_rules`` (which serves Turtle + graph_nonempty),
    then ``parse_policy_rules`` locally. The route is domain-free; the domain is the ``graph`` argument."""
    resp = requests.post(
        f"{ENGINE_O_URL}/policy_rules",
        json={"graph": graph, "ruleset_label": ruleset_label}, timeout=_HTTP_TIMEOUT,
        # svc:engine-a — this process's own identity, named HERE. Ungoverned read
        # (ruleset fetch), so the credential is transport only; see the identity ruling in
        # docs/plans/unminted-caller-enumeration.md.
        headers=outbound_auth_headers(
            client_id="iagent-engine-a", secret_env="ENGINE_A_CLIENT_SECRET",
        ),
    )
    resp.raise_for_status()
    body = resp.json()
    return parse_policy_rules(
        body.get("turtle", ""), graph_nonempty=bool(body.get("graph_nonempty", False)),
        known_dispositions=known_dispositions, ruleset_label=body.get("ruleset_label") or ruleset_label,
    )
