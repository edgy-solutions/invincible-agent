"""The node shape of a hazard INSTANCE in a graph store. Pure: it reads the fixture and returns
dicts. It seeds nothing and nothing in this engine calls it - that is the other lane's half.

DERIVED, NOT TYPED. Every value comes from `entities.HAZARDS`; every property NAME is the local
name of a `safety:` datatype property in `setup/ontologies/safety_extension.ttl`
(`hazardStatus`, `severity`, `probability`), and the label is the local name of the class
`safety:Hazard`. A test reads the ttl and fails when a name here is not declared there.

TWO CHOICES THAT ARE PROPOSALS, NOT RULINGS (sent to the seeder's owner):
  * `identifier` carries the HAZ id, the key `instances.py` already uses for the same thing, so
    the phone book and the graph agree on one name for it.
  * `platform` carries the Platform id (PLT-*). The ontology calls a platform a FRACAS PROGRAM
    (`safety:Platform` comment) and the fixture's field is `platform`, so no second vocabulary
    is minted. The ontology has NO hazard-to-platform property yet; this one is undeclared.

A hazard nobody assessed has severity/probability None. The key is OMITTED, never written as a
bottom-of-matrix value: absence says "not assessed", a seeded `E`/`IV` says "assessed negligible".
"""
from __future__ import annotations

from typing import Any, Dict, List

try:  # flat in the image (/app), packaged in the repo - runbook section 5, FLAT FIRST.
    from entities import HAZARDS
except ImportError:  # pragma: no cover
    from agent_fleet.safety_agent.entities import HAZARDS  # type: ignore[no-redef]

SAFETY = "http://internal/sustainment/safety#"
LABEL = "Hazard"  # local name of safety:Hazard
#: Declared in the ttl as datatype properties of safety:Hazard.
ONTOLOGY_PROPS = ("hazardStatus", "severity", "probability")
#: Not declared in the ttl; see the module docstring.
UNDECLARED_PROPS = ("identifier", "platform")


def hazard_nodes() -> List[Dict[str, Any]]:
    """One node per fixture hazard: `{label, class_uri, props}`."""
    nodes: List[Dict[str, Any]] = []
    for h in HAZARDS:
        props: Dict[str, Any] = {
            "identifier": h.hazard_id,
            "hazardStatus": h.status,
            "platform": h.platform,
        }
        if h.severity is not None:
            props["severity"] = h.severity
        if h.probability is not None:
            props["probability"] = h.probability
        nodes.append({"label": LABEL, "class_uri": SAFETY + LABEL, "props": props})
    return nodes
