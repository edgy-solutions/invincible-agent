"""Direct store clients per engine: the SDK adoption census, as a detector.

A "direct" store client is an engine reaching Weaviate or Neo4j with the vendor library rather
than through the SDK protocols (`MeshVectors`, `MeshGraph`). The detector walks a tree with `ast`,
so comments, strings and docstrings never count. It counts two things per file:

* imports: an `Import` / `ImportFrom` whose module root is a store vendor;
* constructions: a `Call` whose dotted name is a store vendor's client constructor.

The vendor table is DATA (`STORE_VENDORS`); a new store is a row, not a code change.
Grouping: the engine is the first directory under `agent_fleet/` (so `agent_fleet/utils` is the
row `utils`); `src/iagent` is the row `bff-orchestrator`. Files outside those two roots (scripts/,
setup/, tests/) are operator tools or tests and are not counted.
"""

from __future__ import annotations

import ast
from pathlib import Path

STORE_VENDORS: dict[str, dict[str, list[str]]] = {
    "graph": {
        "modules": ["neo4j"],
        "constructors": [
            "GraphDatabase.driver",
            "neo4j.GraphDatabase.driver",
            "AsyncGraphDatabase.driver",
        ],
    },
    "vector": {
        "modules": ["weaviate"],
        "constructors": [
            "weaviate.connect_to_custom",
            "weaviate.connect_to_local",
            "weaviate.connect_to_wcs",
            "weaviate.connect_to_weaviate_cloud",
            "weaviate.Client",
            "weaviate.WeaviateClient",
            "WeaviateClient",
        ],
    },
}

EXCLUDED_DIRS = frozenset(
    {"tests", "__pycache__", "baml_client", ".git", "node_modules", "dist", "tmp", "agent_workspace"}
)
BFF_ROW = "bff-orchestrator"
# Only the engines and the orchestrator side are counted; scripts/ and setup/ are operator tools.
ROOTS = (("agent_fleet",), ("src", "iagent"))


def _excluded(parts: tuple[str, ...]) -> bool:
    return any(p in EXCLUDED_DIRS or p.startswith(".venv") for p in parts)


def engine_of(rel: Path) -> str:
    parts = rel.parts
    if parts[0] == "agent_fleet" and len(parts) > 2:
        return parts[1]
    if parts[:2] == ("src", "iagent"):
        return BFF_ROW
    return parts[0]


def _dotted(node: ast.AST) -> str | None:
    bits: list[str] = []
    while isinstance(node, ast.Attribute):
        bits.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        bits.append(node.id)
        return ".".join(reversed(bits))
    return None


def scan_file(path: Path) -> list[tuple[str, str, int]]:
    """[(surface, kind, lineno)] with kind in {"imports", "constructions"}."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return []
    mods = {m: s for s, v in STORE_VENDORS.items() for m in v["modules"]}
    ctors = {c: s for s, v in STORE_VENDORS.items() for c in v["constructors"]}
    out: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in mods:
                    out.append((mods[a.name.split(".")[0]], "imports", node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and node.module.split(".")[0] in mods:
                out.append((mods[node.module.split(".")[0]], "imports", node.lineno))
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name in ctors:
                out.append((ctors[name], "constructions", node.lineno))
    return out


def findings(root: Path) -> list[tuple[str, str, str, str, int]]:
    """[(engine, surface, kind, relpath, lineno)] for every finding under root."""
    root = Path(root)
    res = []
    paths = [p for r in ROOTS if root.joinpath(*r).is_dir() for p in root.joinpath(*r).rglob("*.py")]
    for p in sorted(paths):
        rel = p.relative_to(root)
        if _excluded(rel.parts[:-1]):
            continue
        for surface, kind, line in scan_file(p):
            res.append((engine_of(rel), surface, kind, rel.as_posix(), line))
    return res


def census(root: Path) -> dict[str, dict[str, dict[str, int]]]:
    """{engine: {surface: {"imports": n, "constructions": m}}}, zero rows omitted."""
    out: dict[str, dict[str, dict[str, int]]] = {}
    for engine, surface, kind, _f, _l in findings(root):
        cell = out.setdefault(engine, {}).setdefault(surface, {"imports": 0, "constructions": 0})
        cell[kind] += 1
    return {e: dict(sorted(s.items())) for e, s in sorted(out.items())}
