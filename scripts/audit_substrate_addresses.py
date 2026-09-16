"""Derive, from SOURCE, which fleet members address a substrate directly.

── WHAT THIS IS, AND WHAT IT IS NOT ────────────────────────────────────────────────────────
It is the freshness check on `tests/test_substrate_allowlist_exceptions_expire.py`, whose
`SUBSTRATE_CLIENTS` dict says of itself: *"NOT AUTHORITATIVE ON ITS OWN — ca's census is the
authority on the full set, and this list is the part that has been read directly."*

That dict is a hand-curated snapshot of who MAY connect. Nothing re-reads it. A sixth engine
that opens a Neo4j connection tomorrow appears in neither the allowlist nor the exception list,
and every arm of that seal stays green — its `len(...) >= 4` floor cannot see a client it does
not know about. **That is the same disease the exceptions were given expiries to cure, one level
up: a declaration trusted more with age because nothing asks it to re-justify itself.**

So this derives who DOES address a substrate, and the seal beside it reds on a divergence. It is
a LINT, not an enforcement. It cannot stop a connection; it can only notice an undeclared one.

── THE THIRD ARM, AND WHY AN ADDRESS RATHER THAN A PACKAGE NAME ────────────────────────────
From docs/plans/engine-o-substrate-read-inventory.md §3 (F2): Jena is reached with raw
`httpx.post` to a URL — no `rdflib`, no `SPARQLWrapper`, nothing a name-based ban can match.
"A dependency seal that refuses driver PACKAGE NAMES is structurally blind to this entire
substrate." The three arms of the one law: *the import name is not the capability*; *the
pyproject is not the import*; and **the import is not the connection**. An address is the only
one of the three that a substrate needing no library still has to state.

── WHAT IT CANNOT SEE. READ THIS BEFORE CITING IT AS COVERAGE ──────────────────────────────
Named here AND in the seal's failure message, because a limit recorded only in a module
docstring is a limit nobody reads while triaging.

1. AN ADDRESS ASSEMBLED FROM PARTS. `f"http://{host}:{port}/sparql"` built from two generically
   named values matches nothing below.
2. AN ADDRESS READ FROM A GENERICALLY NAMED VARIABLE. `endpoint = os.environ["URL"]`, or a
   value arriving in a request body or a config blob, carries no substrate in its name.
3. SHARED CODE, beyond one hop. `agent_fleet/utils/weaviate_utils.py` holds a Weaviate address
   and is not a pod; its importers become substrate clients by importing it. One hop is
   resolved below. A module importing a module that imports it is NOT.

**A clean run means "no UNDECLARED direct address reference", never "no substrate access".**
Anyone citing this as defence in depth is citing defence in shallow.

Run: uv run --frozen python scripts/audit_substrate_addresses.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_FLEET = _ROOT / "agent_fleet"

#: Substrate address tokens. Scoped to the THREE stores the allowlist governs (Neo4j, Weaviate,
#: Jena/Fuseki) so the lint and the declaration answer the same question. Postgres/MinIO are
#: deliberately out of scope here rather than silently in it.
_SUBSTRATE = re.compile(
    r"\b(?:NEO4J|WEAVIATE|JENA|FUSEKI)[A-Z0-9_]*"
    r"(?:URI|URL|HOST|ENDPOINT|ADDRESS|PORT)\b"
)

#: PEER addresses are NOT substrate access — an engine calling another engine over the mesh is
#: the thing the architecture is FOR. Matched first so a peer URL never trips the lint.
_PEER = re.compile(
    r"\b(?:ENGINE_[A-Z0-9_]*|MESH_REGISTRAR|CORTEX_BFF|BROKER|LITELLM|KEYCLOAK|TOPAZ|DATAHUB)"
    r"[A-Z0-9_]*(?:URI|URL|HOST|ENDPOINT)\b"
)

#: Shared modules that hold a substrate address themselves. Importing one IS addressing a
#: substrate, so importers are attributed. ONE HOP ONLY — see limit 3 above.
_SHARED_CARRIERS = ("weaviate_utils",)


def _tracked_py() -> list[Path]:
    """`git ls-files`, not `rglob`. A glob walks __pycache__, stale build output and anything a
    previous run left behind, and attributes their contents to a live engine."""
    out = subprocess.run(
        ["git", "ls-files", "agent_fleet/**/*.py", "agent_fleet/*.py"],
        cwd=_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    return [_ROOT / p for p in out]


def _member_of(path: Path) -> str | None:
    """The fleet member a file belongs to, as its IMAGE NAME (== directory, hyphenated).

    Verified against helm/invincible-agent/values.yaml: engineO's image is `ontology-service`,
    engineE's `neo4j-expert`, engineF's `presentation-agent`. The COMPONENT names (engine-o,
    engine-e, engine-f) are a different namespace, and the allowlist mixes the two — which is
    why the seal beside this resolves every allowlist key back to a real directory.
    """
    try:
        rel = path.relative_to(_FLEET)
    except ValueError:
        return None
    if len(rel.parts) < 2:
        return None
    return rel.parts[0].replace("_", "-")


def scan() -> dict[str, dict]:
    """member -> {"direct": [sites], "via_shared": [sites]}."""
    found: dict[str, dict] = defaultdict(lambda: {"direct": [], "via_shared": []})

    for path in _tracked_py():
        member = _member_of(path)
        if member is None:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for lineno, line in enumerate(text.splitlines(), 1):
            if _PEER.search(line):
                continue  # a peer address is not substrate access
            hit = _SUBSTRATE.search(line)
            if hit:
                found[member]["direct"].append(
                    {"file": str(path.relative_to(_ROOT)).replace("\\", "/"),
                     "line": lineno, "token": hit.group(0)}
                )
                continue
            for carrier in _SHARED_CARRIERS:
                if carrier in line and ("import" in line or "from" in line):
                    found[member]["via_shared"].append(
                        {"file": str(path.relative_to(_ROOT)).replace("\\", "/"),
                         "line": lineno, "token": carrier}
                    )
                    break

    return {k: v for k, v in found.items() if v["direct"] or v["via_shared"]}


def members_addressing_a_substrate() -> set[str]:
    """The set the seal compares against the declaration."""
    return set(scan())


def main() -> int:
    result = scan()
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"\n{len(result)} fleet member(s) address a substrate directly or via shared code.",
          file=sys.stderr)
    print("A clean run means NO UNDECLARED DIRECT ADDRESS REFERENCE — not no substrate access. "
          "See the three blind spots in this module's docstring.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
