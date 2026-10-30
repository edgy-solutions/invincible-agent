"""docs/api/cortex-bff.openapi.json is exactly what the BFF's app.openapi() renders at this sha.

Cortex generates its client types from the committed file at its pinned producer sha. So a route, model or field
that changes without a regenerated file is a contract cortex cannot see, and this test reds the change.
Architect ruling 2026-10-24, item 5(a).

Regenerate with: uv run python scripts/generate_bff_openapi.py
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.iagent import gateway  # noqa: E402

_spec = importlib.util.spec_from_file_location("_gen_bff_openapi", ROOT / "scripts" / "generate_bff_openapi.py")
gen = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gen
_spec.loader.exec_module(gen)


def test_the_committed_document_is_what_the_app_renders():
    committed = gen.read_committed()
    assert committed is not None, "docs/api/cortex-bff.openapi.json is missing: run scripts/generate_bff_openapi.py"
    assert committed == gen.serialise(gateway.app.openapi()), (
        "docs/api/cortex-bff.openapi.json is stale: run scripts/generate_bff_openapi.py")


def test_the_document_covers_every_route_the_app_serves():
    """The generator wrote the WHOLE document: every APIRoute path is in it, not a filtered subset."""
    from fastapi.routing import APIRoute

    served = {r.path for r in gateway.app.routes if isinstance(r, APIRoute) and r.include_in_schema}
    paths = set(json.loads(gen.read_committed())["paths"])
    assert served == paths, {"served_not_documented": sorted(served - paths),
                             "documented_not_served": sorted(paths - served)}
