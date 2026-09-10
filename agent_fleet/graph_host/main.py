"""engine-lg — the graph host. A thin consumer of the SDK's graph contract.

ADR-0046 slice 1 (re-scoped 2026-09-08): the engine a team plugs a LangGraph graph into. It
owns no contract of its own — the models, the loader, ADR-0036 composition and
``register_graph`` live in ``iagent_mesh.graph_manifest`` (v0.5.0) so that a team running their
own host validates against the same schema. This file is WHERE graphs run by default, and
nothing more.

── THE REFUSAL IS THE ARCHITECTURE ─────────────────────────────────────────────────────────
ADR-0046 §2 refuses ``run_any_graph``. There is no endpoint here that takes a graph name and a
payload. The host learns a graph exists from exactly one place — a ratified row in the composed
policy directory — and serves ``POST /graphs/{graph_id}`` only for ids it loaded. A module
sitting in ``graphs/`` with no row is unreachable and unregistered, and the seal for that asserts
against the MESH's verbs rather than this host's files: a file-derived population answers "what
did we intend", and the question is "what is reachable".

── PLAYBOOK ITEMS, EACH WHERE IT BELONGS (docs/runbooks/adding-an-engine.md @ 0c6bcaa) ──────
§0  the four names: values key ``graphHost``, component ``engine-lg``, image ``graph-host``,
    keycloak ``iagent-graph-host``, port 8098. All verified free before any wiring.
§5  every intra-tree import written twice, FLAT FIRST. Getting the order backwards cost Engine P
    a full roll: the import failed, the registration helper became ``None``, and twelve
    registrations were skipped while the engine reported perfectly healthy.
§6  transport auth is a birth rule — announced and applied here, not added later.
§7  ``/version`` from the FIRST commit, through the one shared helper. A per-service copy is how
    fourteen services come to report eleven shapes.
§8  retry with backoff, readiness that fails on GAVE UP and not on STILL TRYING, and no success
    line that does not check success. **All three are inherited rather than reimplemented** —
    ``agent_fleet/utils/mesh_registration.py`` already owns them, and a second copy of a retry
    policy is a second policy that diverges the first time one is tuned.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

# ── the contract: from the SDK, never local ────────────────────────────────────────────────
from iagent_mesh.graph_manifest import GraphManifest, compose, registration_payload

# ── flat in the image (/app), packaged in the repo — §5, and the order is load-bearing ──────
try:
    from utils.mesh_registration import (
        engine_mint,
        register_engine_to_mesh,
        registration_is_ready,
        registration_status,
    )
except ImportError:  # pragma: no cover - exercised by the flat-layout seal
    from agent_fleet.utils.mesh_registration import (  # type: ignore[no-redef]
        engine_mint,
        register_engine_to_mesh,
        registration_is_ready,
        registration_status,
    )

try:
    from utils.version_endpoint import mount_version as _mount_version
except ImportError:  # pragma: no cover
    from agent_fleet.utils.version_endpoint import mount_version as _mount_version  # type: ignore

from iagent_mesh.transport_auth import announce as _announce_transport_auth
from iagent_mesh.transport_auth import app_docs_kwargs as _docs_kwargs
from iagent_mesh.transport_auth import make_transport_auth_dependency as _transport_auth

COMPONENT = "engine-lg"
PORT = int(os.getenv("PORT", "8098"))

#: WHERE THE COMPOSED ROWS ARE READ FROM. The seed ships in this repo; a work-side overlay adds,
#: replaces or deletes (ADR-0036); composition happens at the repo and the composed directory is
#: what this host reads. It does not know or care which repo a row came from — only that it
#: validated, which is the property that lets one `validate_dir` serve both rails.
GRAPH_POLICY_DIR = Path(os.getenv("GRAPH_POLICY_DIR", "/app/policy/graphs"))
GRAPH_OVERLAY_DIRS = [Path(p) for p in os.getenv("GRAPH_OVERLAY_DIRS", "").split(os.pathsep) if p]

ENDPOINT_BASE = os.getenv("GRAPH_HOST_URL", f"http://iagent-{COMPONENT}:{PORT}")

#: graph_id -> (manifest, compiled graph). The ONLY registry. Populated at boot from ratified
#: rows and never from a directory listing of `graphs/`.
_LOADED: dict[str, tuple[GraphManifest, Any]] = {}


def _load_builder(m: GraphManifest):
    """Import a row's builder. Flat first, exactly as §5 requires of every other import here."""
    import importlib

    last: Exception | None = None
    for mod in (m.module, f"agent_fleet.graph_host.{m.module}"):
        try:
            return getattr(importlib.import_module(mod), m.builder)
        except (ImportError, AttributeError) as exc:
            last = exc
    raise RuntimeError(
        f"{m.graph_id}: cannot import {m.builder!r} from {m.module!r} (flat or packaged): {last}"
    )


def load_graphs() -> dict[str, tuple[GraphManifest, Any]]:
    """Compose the ratified rows and compile one graph per row.

    FAIL LOUD. A host that skipped an unloadable row would come up healthy, serve every probe,
    and be missing exactly one verb — the failure mode with no symptom, and the one this
    project has paid for most often.
    """
    out: dict[str, tuple[GraphManifest, Any]] = {}
    for m in compose(GRAPH_POLICY_DIR, GRAPH_OVERLAY_DIRS):
        builder = _load_builder(m)
        graph = builder()
        # The CHECKPOINTER IS THE HOST'S TO HONOUR, which is why a row names a builder rather
        # than shipping a compiled graph: a module that compiled itself could attach durable
        # per-thread memory a row said was off.
        out[m.graph_id] = (m, graph.compile() if not m.checkpointer else graph)
    return out


def _register_all() -> None:
    """One registration per ratified row, through the fleet helper.

    RETRY, READINESS AND THE 422 RULE ARE INHERITED, NOT REIMPLEMENTED. The helper already
    carries jittered backoff on a daemon thread, `registration_is_ready()` that reports False
    while still trying and stays False after giving up, and the rule that a Contract D 422 is
    PERMANENT and not retried because the classes are simply not in the graph yet.
    """
    mint = engine_mint(client_id=os.getenv("GRAPH_HOST_CLIENT_ID", "iagent-graph-host"),
                       secret_env="ENGINE_LG_CLIENT_SECRET")
    for gid, (m, _graph) in _LOADED.items():
        p = registration_payload(m, endpoint_url=f"{ENDPOINT_BASE}/graphs/{gid}")
        # The SDK owns manifest -> payload; this adapter owns payload -> the fleet helper's
        # kwargs. Two mappings on purpose: route C should not inherit our retry policy, and we
        # should not maintain a second manifest reader to get it.
        register_engine_to_mesh(
            mint=mint,
            name=p["name"],
            description=p["description"],
            verb=p["verb_iri"],
            input_uri=p["input_uri"],
            output_uri=p["output_uri"],
            endpoint_url=p["endpoint_url"],
            verb_synonyms=p["verb_synonyms"],
            verb_anti_synonyms=p["verb_anti_synonyms"],
            owner_persona=p["owner_persona"],
            domains=p["domains"],
            cost_class=p["cost_class"],
            requires_human_approval=p["requires_human_approval"],
            timeout_s=p["timeout_s"],
            slots=p["slots"],
            arity=p["arity"],
            required_args=p["required_args"],
        )


from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _LOADED
    _LOADED = load_graphs()

    # NO SUCCESS LINE THAT DOES NOT CHECK SUCCESS. This says what was LOADED, which is a fact
    # this line can see. It deliberately does not say "registered": `✅ Registered` printed on a
    # path that did not register is the single most expensive line this repo has shipped — an
    # engine logged fourteen ticks and booted green while every registration failed.
    print(f"[{COMPONENT}] {len(_LOADED)} ratified graph(s) loaded: {sorted(_LOADED)}", flush=True)

    if os.getenv("MESH_REGISTER_ON_STARTUP", "false").lower() in ("1", "true", "yes"):
        await asyncio.get_running_loop().run_in_executor(None, _register_all)
    yield
    _LOADED = {}


_announce_transport_auth(component=COMPONENT)
app = FastAPI(
    **_docs_kwargs(),
    dependencies=[Depends(_transport_auth(COMPONENT))],
    title="engine-lg — graph host",
    description="Runs LangGraph graphs admitted by ratified manifest rows. One row, one verb.",
    version="0.1.0",
    lifespan=lifespan,
)
_mount_version(app, COMPONENT)


class GraphRequest(BaseModel):
    """The spoken slots, by name. NOT a payload passthrough — the router fills these from the
    row's declared slots, and a field this graph did not declare has nowhere to go."""

    params: dict[str, Any] = {}
    thread_id: str | None = None
    user_id: str | None = None


#: The headers that carry WHO IS ASKING, forwarded verbatim to every inner verb. Named as a
#: constant so the set is one thing rather than three string literals at the point of use.
_IDENTITY_HEADERS = ("authorization", "x-originator-sub", "x-originator-email")


@app.post("/graphs/{graph_id}")
async def run_graph(graph_id: str, http_request: Request, request: GraphRequest) -> dict:
    """Invoke ONE admitted graph. There is no endpoint that takes a graph the host did not load."""
    entry = _LOADED.get(graph_id)
    if entry is None:
        # NAMES WHAT IS ADMITTED. A bare 404 here reads as "wrong URL" when the real answer is
        # "that graph has no ratified row", which is a different fix in a different repo.
        raise HTTPException(
            status_code=404,
            detail=(f"no ratified row admits {graph_id!r}; admitted graphs: {sorted(_LOADED)}"),
        )
    m, graph = entry
    missing = [s.name for s in m.slots if s.required and s.name not in request.params]
    if missing:
        raise HTTPException(status_code=422, detail=f"{graph_id} requires {missing}")
    # IDENTITY IS AN ARGUMENT, THREADED — never read from ambient env inside a node, and never
    # the host's own. ADR-0049 Ruling 1: the inner call carries the INITIATOR's credential, so a
    # caller entitled to less sees less. This host holds no standing credential to fall back on,
    # which is what makes that true by construction rather than by discipline.
    identity = {h: v for h in _IDENTITY_HEADERS
                if (v := http_request.headers.get(h)) is not None}
    state = dict(request.params)
    state["identity"] = identity
    config: dict = {"configurable": {"thread_id": request.thread_id or graph_id,
                                     "user_id": request.user_id}}
    return await graph.ainvoke(state, config=config)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "engine": COMPONENT, "graphs": sorted(_LOADED)}


@app.get("/ready")
async def ready() -> dict:
    """READINESS, NOT LIVENESS. A failing readiness probe removes the pod from Service
    endpoints; it does not restart it. So reporting not-ready while still retrying is correct
    and costs exactly what it should. Wiring this to a liveness probe would turn a slow
    dependency into a crash-loop, which is worse than the outage it fixes."""
    st = registration_status()
    if not registration_is_ready():
        raise HTTPException(status_code=503, detail=st)
    return {"status": "ready", **st}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
