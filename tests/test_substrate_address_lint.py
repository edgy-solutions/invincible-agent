"""THE DECLARATION MUST STILL DESCRIBE REALITY: who addresses a substrate vs who may.

`test_substrate_allowlist_exceptions_expire.py` gave every EXCEPTION an expiry, on the argument
that "an exception that cannot expire is not an exception. It is the policy, written where
nobody looks for the policy." This file applies that same argument one level up, to the
ALLOWLIST itself — which has no expiry, no re-read, and says of itself: *"NOT AUTHORITATIVE ON
ITS OWN … this list is the part that has been read directly."*

A sixth engine that opens a Neo4j connection tomorrow lands in neither list, and every arm over
there stays green: the `len(SUBSTRATE_CLIENTS) >= 4` floor cannot see a client it does not know
about. A hand-curated list of who MAY connect, with nothing deriving who DOES, becomes more
trusted with age rather than less. That is the stale-claim shape applied to a security
declaration.

── THIS IS A LINT. IT IS NOT AN ENFORCEMENT, AND IT MAY NOT HAVE ONE BEHIND IT ─────────────
The allowlist seal opens "The NetworkPolicy allowlist names which pods may open a connection".
**There is no NetworkPolicy manifest in this repository**, and that sentence is the ONLY
occurrence of the word "NetworkPolicy" anywhere in it (searched 2026-09-15). Two readings, not
discriminated from here:
  (a) it is applied out-of-band — cluster-level, a platform team, another repo — so the chart
      correctly does not carry it; or
  (b) it was planned, never built, and the sentence has been read as current fact since.
Either way nothing in this repo lets a reader verify the enforcement exists, which is itself
the shape both seals were written against. **Recorded as UNPROVEN rather than asserted**, and
routed to the architect. Until it resolves, do not describe this lint as the second layer of a
defence in depth — it may be the only instrument there is.

── WHAT A GREEN RUN DOES NOT MEAN ──────────────────────────────────────────────────────────
"No undeclared DIRECT ADDRESS REFERENCE" — never "no substrate access". The three blind spots
live in scripts/audit_substrate_addresses.py and are repeated in the failure messages below,
because a limit stated only in a docstring is a limit nobody reads while triaging a red.

Run: uv run --frozen pytest tests/test_substrate_address_lint.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1] / "scripts"))
sys.path.insert(0, str(_HERE.parent))  # sibling seal import below

from audit_substrate_addresses import scan  # noqa: E402

# SINGLE HOME. The declaration is imported, never copied — a second copy of an allowlist is a
# second answer to "who may connect", and the permissive copy wins silently.
from test_substrate_allowlist_exceptions_expire import (  # noqa: E402
    EXCEPTIONS,
    SUBSTRATE_CLIENTS,
)

#: The allowlist is written in IMAGE-NAME namespace (`restate-analyst`, `weaviate-expert`,
#: `neo4j-expert`, `mesh-registrar`) with ONE exception: `engine-o` is a COMPONENT name.
#: Verified in helm/invincible-agent/values.yaml — engineO's image is `ontology-service`, and
#: templates/engines.yaml maps engineO -> component `engine-o`. Recorded as an alias rather than
#: silently normalised, so the mixed namespace stays visible instead of being papered over.
_COMPONENT_ALIASES = {"engine-o": "ontology-service"}

#: Shared code that HOLDS a substrate address and is not a deployable pod, so it can never be
#: allowlisted. Declared here on purpose: the alternative is the lint ignoring it, and a
#: substrate address sitting in code nobody governs is precisely the hole worth a name.
_SHARED_NOT_A_POD = {"utils"}

_BLIND_SPOTS = (
    "\nWHAT THIS LINT CANNOT SEE (so a green run is not coverage):\n"
    "  1. an address ASSEMBLED FROM PARTS — f\"http://{host}:{port}/sparql\"\n"
    "  2. an address from a GENERICALLY NAMED variable — os.environ['URL'], or one arriving\n"
    "     in a request body or config blob\n"
    "  3. shared code BEYOND ONE HOP — an importer of an importer of weaviate_utils\n"
)


def _declared() -> set[str]:
    declared = set(SUBSTRATE_CLIENTS) | {e.pod for e in EXCEPTIONS}
    return {_COMPONENT_ALIASES.get(name, name) for name in declared}


def _derived() -> set[str]:
    return set(scan())


# ── the lint proper ──────────────────────────────────────────────────────────────────────

def test_EVERY_MEMBER_THAT_ADDRESSES_A_SUBSTRATE_IS_DECLARED():
    """THE ARM THIS FILE EXISTS FOR — a substrate client that nobody declared.

    TRIPWIRE: a red here is a NOTIFICATION, not necessarily a defect. Either a fleet member
    grew substrate access (declare it, or route it through the mesh), or shared code it
    imports did.
    """
    undeclared = _derived() - _declared() - _SHARED_NOT_A_POD
    assert not undeclared, (
        f"TRIPWIRE: {sorted(undeclared)} address a substrate and appear in neither "
        f"SUBSTRATE_CLIENTS nor EXCEPTIONS in tests/"
        f"test_substrate_allowlist_exceptions_expire.py.\n"
        f"This is a NOTIFICATION, not automatically a defect. Either the access is legitimate "
        f"— add it to the allowlist WITH A REASON — or it is the access the policy exists to "
        f"stop, and it moves behind the mesh. What must not happen is it staying undeclared "
        f"because nothing asked.\n"
        f"Run: python scripts/audit_substrate_addresses.py  (shows file and line)"
        + _BLIND_SPOTS
    )


def test_EVERY_DECLARED_NAME_RESOLVES_TO_A_REAL_FLEET_MEMBER():
    """A declaration naming a pod that does not exist grants nothing and protects nothing, and
    reads as coverage. This is what caught `engine-o` sitting in a list of image names."""
    fleet_root = Path(__file__).resolve().parents[1] / "agent_fleet"
    real = {p.name.replace("_", "-") for p in fleet_root.iterdir()
            if p.is_dir() and not p.name.startswith("__")}
    for name in _declared():
        assert name in real, (
            f"{name!r} is declared a substrate client but matches no agent_fleet directory.\n"
            f"The allowlist is written in IMAGE-NAME namespace with one COMPONENT-name entry "
            f"(`engine-o`), which is why _COMPONENT_ALIASES exists. A new entry in a third "
            f"namespace needs an alias here, or it silently governs nothing."
        )


def test_SHARED_CODE_HOLDING_AN_ADDRESS_IS_NAMED_NOT_IGNORED():
    """`agent_fleet/utils` holds a Weaviate address and is not a pod, so it can never be
    allowlisted — and a lint that silently skipped it would hide the one place a substrate
    address is governed by nobody. It is excluded BY NAME so the exclusion is visible."""
    derived = _derived()
    for shared in _SHARED_NOT_A_POD:
        if shared not in derived:
            pytest.fail(
                f"{shared!r} no longer addresses a substrate — if the address moved behind "
                f"MeshVectors, delete it from _SHARED_NOT_A_POD so the exclusion does not "
                f"outlive its reason."
            )


# ── controls: the lint must be shown to discriminate ─────────────────────────────────────

def test_THE_SCAN_IS_NOT_VACUOUS():
    """POSITIVE CONTROL. A scanner matching nothing would pass every arm above."""
    derived = _derived()
    assert len(derived) >= 5, f"the scan found almost nothing ({sorted(derived)})"
    for expected in ("ontology-service", "mesh-registrar", "presentation-agent"):
        assert expected in derived, (
            f"{expected} is a known substrate client and the scan missed it — the lint is "
            f"reporting a clean fleet because it cannot see, not because nothing connects"
        )


def test_SHARED_CARRIER_ATTRIBUTION_IS_LOAD_BEARING():
    """restate-analyst and weaviate-expert reach Weaviate ONLY through `weaviate_utils` — they
    reference no substrate address of their own. A lint checking direct references alone would
    report both as clean, which is the `pyproject is not the import` hole in its concrete form."""
    result = scan()
    for member in ("restate-analyst", "weaviate-expert"):
        assert member in result, f"{member} vanished from the scan"
        assert not result[member]["direct"], (
            f"{member} now references a substrate address directly — this control assumed it "
            f"did not, so re-pick a member that only reaches a substrate via shared code"
        )
        assert result[member]["via_shared"], (
            f"{member} is no longer attributed through shared code — the one-hop attribution "
            f"has stopped working and two real substrate clients now read as clean"
        )


def test_A_PEER_ADDRESS_DOES_NOT_TRIP_THE_LINT():
    """THE DISCRIMINATOR. An engine calling another engine is what the architecture is FOR. A
    lint that flagged `MESH_REGISTRAR_URL` alongside `NEO4J_URI` would make every member a
    finding, and a finding on everything is a finding on nothing."""
    from audit_substrate_addresses import _PEER, _SUBSTRATE

    for peer in ("MESH_REGISTRAR_URL", "CORTEX_BFF_URL", "ENGINE_O_PUBLIC_URL", "BROKER_URL"):
        assert _PEER.search(peer), f"{peer} is a peer address and must be excluded"
    for substrate in ("NEO4J_URI", "WEAVIATE_HTTP_HOST", "JENA_SPARQL_ENDPOINT"):
        assert _SUBSTRATE.search(substrate), f"{substrate} must be seen"
        assert not _PEER.search(substrate), (
            f"{substrate} matches the PEER pattern — the peer filter runs FIRST, so this "
            f"substrate would be silently excluded from the lint entirely"
        )
