#!/usr/bin/env python3
"""Generate the mcp OpenAPI document (docs/api/mcp.openapi.json).

    python scripts/generate_mcp_openapi.py          # write the document
    python scripts/generate_mcp_openapi.py --check  # exit 1 if the document is stale

Only operations tagged `mcp` (src/iagent/ingest_api.py MCP_TAG / MCP_ROUTES) are published: the
BFF surface an MCP server wraps. The filtering helpers are generate_ingest_openapi.py's, imported.
Unknown args and --help never write.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "api" / "mcp.openapi.json"
MCP_API_VERSION = "1"
_USAGE = __doc__.split("\n\n")[1].rstrip()

_spec = importlib.util.spec_from_file_location(
    "_gen_ingest_openapi", ROOT / "scripts" / "generate_ingest_openapi.py")
_ingest = importlib.util.module_from_spec(_spec)
sys.modules.setdefault(_spec.name, _ingest)
_spec.loader.exec_module(_ingest)

serialise = _ingest.serialise
_read = _ingest._read


def filter_mcp(full: dict, tag: str, version: str = MCP_API_VERSION) -> dict:
    out = _ingest._filter_ops(full, lambda op: tag in (op.get("tags") or []))
    out["info"] = {"title": "Cortex BFF mcp surface", "version": version}
    return out


def build() -> dict:
    sys.path.insert(0, str(ROOT))
    from src.iagent import gateway
    from src.iagent.ingest_api import MCP_TAG
    return filter_mcp(gateway.app.openapi(), MCP_TAG)


def write() -> int:
    doc = build()
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DOC_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(serialise(doc))
    print(f"wrote {DOC_PATH.name}")
    return 0


def check() -> int:
    if _read(DOC_PATH) != serialise(build()):
        print(f"STALE: {DOC_PATH} differs from regenerated; run the generator", file=sys.stderr)
        return 1
    print("ok: mcp")
    return 0


def main(argv: list[str]) -> int:
    if argv == []:
        return write()
    if argv == ["--check"]:
        return check()
    helped = argv in (["--help"], ["-h"])
    print(_USAGE, file=sys.stdout if helped else sys.stderr)
    return 0 if helped else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
