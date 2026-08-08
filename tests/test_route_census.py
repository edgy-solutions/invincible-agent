"""Every route on every app is accounted for — a CENSUS, not a coverage claim.

WHY THIS EXISTS, and it is a class rather than an incident. Under REQUIRE on a live pod,
`/openapi.json`, `/docs` and `/redoc` answered **200 unauthenticated**. FastAPI registers those
through Starlette's `add_route`, so app-level `dependencies=` NEVER applies to them — and the
endpoint-gating manifest's claim that the app-level dependency "covers every route" (written by
this repo's own agent) was false for three routes on every service.

DOCS ARE ONLY THE KNOWN MEMBER. Any future `add_route`, `Mount`, static-files mount or
websocket endpoint bypasses the dependency the same silent way. Fixing the member leaves the
class open, so this file enumerates `app.routes` per app and requires every route to be exactly
one of:

    * DEPENDENCY-COVERED — an APIRoute, which app-level `dependencies=` does reach
    * EXEMPT-BY-LIST     — a declared kubelet probe path
    * ALLOW-LISTED MOUNT — a named, reasoned exception

Coverage claims get censuses; censuses verify membership. That rule was earned this week by an
enforcement-point count that stayed numerically stable across a real change while its membership
silently shifted — and it applies to the route table exactly as it applied there.

WHAT THIS CANNOT SEE, stated so no one reads it as more than it is: it inspects apps as
CONSTRUCTED IN THIS REPO. A route added by middleware at runtime, or by a library on first
request, is outside its reach. The live REQUIRE witness on a throwaway pod remains the check
that closes that gap.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# Kubelet paths, mirrored from iagent_mesh.transport_auth.DEFAULT_EXEMPT_PATHS plus the
# registrar's configured addition. Duplicated deliberately: this suite must FAIL if the SDK
# quietly widens its exemptions, so it asserts against its own copy and reconciles below.
_EXPECTED_SDK_EXEMPT = {"/health", "/healthz", "/livez", "/readyz"}

# Routes FastAPI adds outside the dependency system. Every entry is a NAMED exception with a
# reason; an empty allow-list is the goal state, and these three are expected to disappear
# entirely now that docs are disabled by default.
_ALLOWED_NON_API_ROUTES = {
    "/openapi.json": "FastAPI docs (disabled in deployment via app_docs_kwargs)",
    "/docs": "FastAPI docs (disabled in deployment)",
    "/docs/oauth2-redirect": "FastAPI docs (disabled in deployment)",
    "/redoc": "FastAPI docs (disabled in deployment)",
}


def _app_sources() -> list[Path]:
    found = sorted({p for g in ("agent_fleet/*/main.py", "src/iagent/**/app.py",
                                "helm/invincible-agent/files/*.py")
                    for p in _ROOT.glob(g)
                    if re.search(r"^\s*app = FastAPI\(", p.read_text(encoding="utf-8"), re.M)})
    assert found, "positive control: no FastAPI app sources discovered — the glob is broken"
    return found


def test_the_sdk_exempt_list_has_not_widened():
    """The SDK owns the exemption policy; this asserts it has not grown without a decision.

    A widening there silently un-gates routes on twelve services, and nothing else in this
    repo would notice — the guard-gone-quiet shape applied to someone else's default.
    """
    ta = pytest.importorskip("iagent_mesh.transport_auth")
    assert set(ta.DEFAULT_EXEMPT_PATHS) == _EXPECTED_SDK_EXEMPT, (
        f"the SDK's default exempt set changed to {sorted(ta.DEFAULT_EXEMPT_PATHS)}. Every "
        f"entry must be justifiable as a KUBELET path and nothing else — re-read the list, "
        f"then update this expectation deliberately."
    )


@pytest.mark.parametrize("src", _app_sources(),
                         ids=lambda p: str(p.relative_to(_ROOT)).replace("\\", "/"))
def test_every_app_source_applies_the_docs_kwargs(src: Path):
    """Docs must be disabled at EVERY construction site, not just the SDK's factory.

    The ten platform engines build `FastAPI(...)` themselves, so a factory-only fix would have
    protected the scaffolded engines and left the fleet exposed — coverage decided by which
    construction path a service happened to use, the same defect shape as "fleet-wide meant ten
    because of a glob".
    """
    s = src.read_text(encoding="utf-8")
    assert "_docs_kwargs()" in s or "app_docs_kwargs()" in s, (
        f"{src.relative_to(_ROOT)} constructs a FastAPI app without app_docs_kwargs(): its "
        f"/openapi.json, /docs and /redoc are served UNAUTHENTICATED even under REQUIRE, "
        f"because FastAPI registers them via Starlette's add_route and app-level "
        f"`dependencies=` never reaches them."
    )


def test_docs_kwargs_actually_removes_the_routes():
    """The PROPERTY, not the mechanism. A source-grep above proves the call is written; this
    proves the call does what the grep implies — the two are different claims, and this week
    produced four defects that lived precisely in that gap."""
    fastapi = pytest.importorskip("fastapi")
    ta = pytest.importorskip("iagent_mesh.transport_auth")
    import os
    os.environ.pop("IAGENT_MESH_DOCS", None)
    app = fastapi.FastAPI(**ta.app_docs_kwargs())
    paths = {r.path for r in app.routes}
    leaked = paths & set(_ALLOWED_NON_API_ROUTES)
    assert not leaked, f"docs routes still present after app_docs_kwargs(): {sorted(leaked)}"


def test_census_every_route_is_covered_exempt_or_allowlisted():
    """THE CENSUS. Enumerates a constructed app's routes and classifies each one.

    Built on a representative app rather than by importing ten engines (which drag in restate,
    weaviate and neo4j clients): the property under test belongs to FastAPI's route model and
    the SDK's dependency, not to any engine's business logic.
    """
    fastapi = pytest.importorskip("fastapi")
    ta = pytest.importorskip("iagent_mesh.transport_auth")
    from fastapi.routing import APIRoute

    app = fastapi.FastAPI(
        **ta.app_docs_kwargs(),
        dependencies=[fastapi.Depends(ta.make_transport_auth_dependency("census"))],
    )

    @app.get("/health")
    async def health():
        return {}

    @app.post("/work")
    async def work():
        return {}

    # A deliberately BYPASSING route, added the way FastAPI adds docs — the counterexample
    # pre-positioned, so the census is shown to be able to catch its own target class.
    async def raw(_request):
        from starlette.responses import JSONResponse
        return JSONResponse({})

    app.add_route("/raw-bypass", raw)

    unclassified = []
    for r in app.routes:
        path = getattr(r, "path", None)
        if path is None:
            continue
        if isinstance(r, APIRoute):
            continue                                  # dependency-covered
        if path in ta.DEFAULT_EXEMPT_PATHS:
            continue                                  # exempt-by-list
        if path in _ALLOWED_NON_API_ROUTES:
            continue                                  # named exception
        unclassified.append(path)

    assert unclassified == ["/raw-bypass"], (
        f"the census did not classify exactly the planted bypass; got {unclassified}. If this "
        f"is empty the census cannot SEE a Starlette-mounted route, and it is asserting nothing."
    )
