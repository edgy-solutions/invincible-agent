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
from iagent_mesh.graph_manifest import (
    GraphManifest,
    RefusalViolation,
    compose,
    enforce_refusal,
    registration_payload,
)

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


#: Which saver a checkpointer row gets, and WHY IT IS REPORTED RATHER THAN ASSUMED.
#:
#: `langgraph-checkpoint-postgres` is a declared dependency of this engine and
#: `AsyncPostgresSaver` is the intended end state — `graph_host/__init__.py` names it as the
#: one part of Engine B worth keeping.
#:
#: IT IS WIRED NOW, and this paragraph said the opposite for as long as it was true. It read
#: "It is NOT wired: `graphHost.env` is `{}` in values.yaml and no DSN reaches this pod" —
#: accurate when written, false from `e36aa55`, which composed
#: `GRAPH_HOST_POSTGRES_DSN` from the shared BPMN parts. Measured in the running pod on
#: 2026-09-15: `[engine-lg] checkpointer: postgres (durable=True, ready=True)`.
#:
#: A STALE NEGATIVE IS THE EXPENSIVE KIND. A reader arriving at a 422 about `thread_id`
#: would have read this and concluded no checkpointer could be active, then looked for the
#: cause somewhere it was not. The claim was precise, sourced and wrong, which is what made
#: it credible — so it names its own supersession rather than being quietly deleted.
#:
#: WHAT THE ROWS DECLARE IS UNCHANGED. `fin_program_brief`'s row says `thread_id = run id`:
#: state scoped to ONE run, and the graph runs straight through with no interrupt, so
#: nothing resumes a thread in a second process. Postgres buys durability ACROSS pods and
#: restarts, which matters the moment a graph interrupts for a human — `HumanAwaitStep`.
#: The difference is that the durability is now real rather than pending.
#:
#: SO THE DEGRADATION IS NAMED WHERE IT CAN BE READ, not left to be inferred: the saver in use
#: is logged at boot and reported by `/health`. A durable-looking declaration served by
#: process memory is precisely the silent half-truth this host refuses elsewhere.
_CHECKPOINT_DSN_ENV = "GRAPH_HOST_POSTGRES_DSN"


#: The saver opened by the lifespan, or None when no DSN was declared. Module-level because
#: `load_graphs` compiles against it and the lifespan must therefore open it FIRST.
_SAVER: Any = None

#: What actually happened when we tried, so readiness and `/health` read the same fact rather
#: than each deriving one. R-012: the two reads answer different questions and neither may
#: guess. `open_error` is kept verbatim — a DSN that is declared and unreachable is a
#: different failure from one that was never declared, and they need different fixes.
_SAVER_STATUS: dict = {"kind": "in-process", "durable": False,
                       "dsn_configured": False, "open_error": None}


async def _open_saver(stack: Any) -> None:
    """Open the durable checkpointer if a DSN is declared. NO DEFAULT DSN — R-012.

    A plausible default here would point at *some* Postgres and silently checkpoint a
    programme's brief into whatever it reached. Absent means absent, and readiness says so.
    """
    global _SAVER
    dsn = os.getenv(_CHECKPOINT_DSN_ENV)
    _SAVER_STATUS.update({"dsn_configured": bool(dsn), "open_error": None})
    if not dsn:
        _SAVER = None
        _SAVER_STATUS.update({"kind": "in-process", "durable": False})
        return
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        saver = await stack.enter_async_context(AsyncPostgresSaver.from_conn_string(dsn))
        # ASSERTED REACHABLE AT OPEN, not on first use. `setup()` creates the checkpoint
        # tables and round-trips the connection, so a DSN that is declared-but-wrong fails
        # HERE, named, instead of at the first graph a user runs.
        await saver.setup()
        _SAVER = saver
        _SAVER_STATUS.update({"kind": "postgres", "durable": True})
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        _SAVER = None
        _SAVER_STATUS.update({"kind": "in-process", "durable": False,
                              "open_error": f"{type(exc).__name__}: {exc}"})


def _saver_for(m: GraphManifest) -> Any:
    """The checkpointer a row's `checkpointer: true` actually gets.

    Falls back to process memory when no durable saver opened, so the engine still SERVES
    rather than crash-looping — readiness is what refuses, per R-011/R-012, because a failing
    liveness probe on a missing config turns a slow dependency into a crash loop.
    """
    from langgraph.checkpoint.memory import InMemorySaver

    return _SAVER if _SAVER is not None else InMemorySaver()


def checkpointer_readiness() -> tuple[bool, dict]:
    """R-012's THREE STATES, and the middle one is why this is not just `durable or fail`.

        stateful rows AND no durable saver   -> NOT READY, naming the variable
        NO stateful rows AND no DSN          -> ready; `/health` says in-process
        durable saver open                   -> ready

    A row declaring `checkpointer: true` served by process memory is a promise the engine
    cannot keep across a restart or a second replica. Refusing readiness removes the pod from
    the Service rather than killing it, which is the correct cost: the config is wrong, not
    the code.
    """
    stateful = sorted(gid for gid, (mm, _g) in (_LOADED or {}).items() if mm.checkpointer)
    if not stateful:
        return True, {"checkpointing": "not required — no admitted row declares one",
                      **_SAVER_STATUS}
    if _SAVER_STATUS.get("durable"):
        # THE REPORT MUST AGREE WITH THE OBJECTS, and this is the only check that can tell
        # them apart. `load_graphs` COMPILES each stateful row against whatever `_saver_for`
        # returns at that moment. Open the saver AFTER compilation and every graph carries an
        # InMemorySaver while `_SAVER_STATUS` says durable — the engine reports durability it
        # does not have, readiness passes, and the loss shows up only as a thread that will not
        # resume, on a restart, in production.
        #
        # THIS IS THE `registered 3/3` SHAPE FOR DURABILITY: a status line derived from the
        # ATTEMPT rather than from the RESULT. So it is derived from the result — identity, not
        # truthiness, because an InMemorySaver is perfectly truthy.
        wrong = sorted(
            gid for gid, (mm, g) in (_LOADED or {}).items()
            if mm.checkpointer and getattr(g, "checkpointer", None) is not _SAVER
        )
        if wrong:
            return False, {
                "checkpointing": "REPORTED DURABLE, COMPILED AGAINST SOMETHING ELSE",
                "stateful_graphs": stateful,
                "reason": (
                    f"{wrong} compiled against a checkpointer that is not the opened saver. "
                    f"The saver must be opened BEFORE load_graphs, which compiles against it; "
                    f"opened afterwards it is held by nothing while this engine reports "
                    f"durable. Ordering defect in the lifespan, not configuration."
                ),
                **_SAVER_STATUS,
            }
        return True, {"checkpointing": "durable", "stateful_graphs": stateful, **_SAVER_STATUS}
    if _SAVER_STATUS.get("open_error"):
        return False, {
            "checkpointing": "DECLARED BUT UNREACHABLE",
            "stateful_graphs": stateful,
            "reason": (
                f"{_CHECKPOINT_DSN_ENV} is set and the checkpointer could not be opened: "
                f"{_SAVER_STATUS['open_error']}. These graphs would checkpoint to process "
                f"memory and lose their threads on restart."
            ),
            **_SAVER_STATUS,
        }
    return False, {
        "checkpointing": "UNDECLARED",
        "stateful_graphs": stateful,
        "reason": (
            f"{_CHECKPOINT_DSN_ENV} is not set, and {len(stateful)} admitted row(s) declare "
            f"`checkpointer: true`: {stateful}. Set it in graphHost.env. Serving these from "
            f"process memory would honour the declaration only until the next restart, and "
            f"not at all across replicas."
        ),
        **_SAVER_STATUS,
    }


def checkpointer_durability() -> dict:
    """What `/health` says about state, so nobody infers durability from a boolean.

    `rows` is derived from what was ADMITTED rather than from the policy directory — a row
    that failed to load cannot be carrying state, and reporting it here would be the census
    defect in miniature.
    """
    import os

    stateful = sorted(gid for gid, (mm, _g) in (_LOADED or {}).items() if mm.checkpointer)
    ready, detail = checkpointer_readiness()
    return {
        "saver": _SAVER_STATUS["kind"],
        "durable_across_restarts": bool(_SAVER_STATUS["durable"]),
        "stateful_graphs": stateful,
        "postgres_dsn_configured": bool(_SAVER_STATUS["dsn_configured"]),
        "open_error": _SAVER_STATUS["open_error"],
        # THE BOOLEAN IS NOT LEFT TO BE READ. A field nobody looks at is the log line nobody
        # greps; readiness is the half that ACTS, and this says which way it went.
        "ready": ready,
        "detail": detail.get("reason") or detail.get("checkpointing"),
    }


def load_graphs() -> dict[str, tuple[GraphManifest, Any]]:
    """Compose the ratified rows and compile one graph per row.

    FAIL LOUD. A host that skipped an unloadable row would come up healthy, serve every probe,
    and be missing exactly one verb — the failure mode with no symptom, and the one this
    project has paid for most often.
    """
    rows = compose(GRAPH_POLICY_DIR, GRAPH_OVERLAY_DIRS)
    if not rows:
        # THE FLOOR THAT WAS MISSING, and its absence shipped. `load_graphs` already failed
        # loud on a row it could not honour — but NOT on no rows at all, so an empty or absent
        # policy directory produced a host that admitted zero graphs, registered zero verbs and
        # answered `status: ok` to every probe. A graph host with no graphs is not a healthy
        # graph host; it is an unroutable pod with a green light, which is the failure mode
        # with no symptom this engine exists to refuse.
        raise RuntimeError(
            f"no ratified graph rows found under {GRAPH_POLICY_DIR} "
            f"(overlays: {[str(p) for p in GRAPH_OVERLAY_DIRS] or 'none'}). engine-lg admits "
            f"graphs ONLY from ratified rows, so with none it can serve nothing and register "
            f"nothing. If the directory is missing from the image, that is the defect — and "
            f"the COPY that ships it lives in the Dockerfile.agent HEREDOC inside "
            f".github/workflows/build-containers.yml. There is NO Dockerfile.agent FILE in "
            f"this repo, so one created with that name is never read."
        )
    out: dict[str, tuple[GraphManifest, Any]] = {}
    for m in rows:
        builder = _load_builder(m)
        graph = builder()
        # The CHECKPOINTER IS THE HOST'S TO HONOUR, which is why a row names a builder rather
        # than shipping a compiled graph: a module that compiled itself could attach durable
        # per-thread memory a row said was off.
        #
        # AND FOR ONE RELEASE THIS LINE HONOURED NOTHING. It read
        #     graph.compile() if not m.checkpointer else graph
        # — treating a checkpointer as a SUBSTITUTE for compiling rather than an ARGUMENT to
        # it. `ainvoke` exists only on the compiled graph, so every row declaring
        # `checkpointer: true` was stored as a BUILDER and returned 500 on first call:
        # `'StateGraph' object has no attribute 'ainvoke'`. Measured live on NP-MERIDIAN.
        # The traceback is the LAST line after the graph does ~57s of real work, so it reads
        # like a timeout and is not one.
        #
        # TWO DEFECTS, AND THE SECOND OUTLIVES THE FIRST. Compiling in both arms clears the
        # 500 — and would leave `checkpointer: true` attached to NOTHING, which is the exact
        # shape this host already paid for once with `refusal`: a row declaring behaviour that
        # nothing implements, green everywhere. The saver is therefore PASSED, not implied.
        out[m.graph_id] = (m, graph.compile(checkpointer=_saver_for(m)) if m.checkpointer
                           else graph.compile())
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
    # THE SAVER OPENS BEFORE THE GRAPHS, and the order is load-bearing rather than tidy:
    # `load_graphs` COMPILES each stateful row against the saver, so a saver opened afterwards
    # would be held by nothing. The graphs would compile against process memory and the engine
    # would report durable.
    from contextlib import AsyncExitStack

    async with AsyncExitStack() as stack:
        await _open_saver(stack)
        _LOADED = load_graphs()

        # NO SUCCESS LINE THAT DOES NOT CHECK SUCCESS. This says what was LOADED, which is a
        # fact this line can see. It deliberately does not say "registered": `✅ Registered`
        # printed on a path that did not register is the single most expensive line this repo
        # has shipped — an engine logged fourteen ticks and booted green while every
        # registration failed.
        print(f"[{COMPONENT}] {len(_LOADED)} ratified graph(s) loaded: {sorted(_LOADED)}",
              flush=True)
        # SAID AT BOOT, not only on a probe nobody calls. Which saver is in use decides whether
        # a stateful row's promise survives this pod.
        _ok, _detail = checkpointer_readiness()
        print(f"[{COMPONENT}] checkpointer: {_SAVER_STATUS['kind']} "
              f"(durable={_SAVER_STATUS['durable']}, ready={_ok}) "
              f"{_detail.get('reason') or ''}".rstrip(), flush=True)

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

    # ── ADMISSION: AN UNIDENTIFIED CALL IS REFUSED BEFORE THE FIRST NODE RUNS ───────────────
    # Ruled 2026-09-12. The third-caller case is an UNENTITLED caller, who is identified and
    # gets an answer shaped by what they may see. An UNIDENTIFIED call is a different thing and
    # gets nothing, named: there is no subject to scope a governed read to, and this host holds
    # no standing credential to fall back on.
    #
    # TWO LAYERS, AND THE INNER ONE IS THE ONE THAT MATTERS IF THIS REGRESSES. Each graph's
    # nodes ALSO refuse to call out without an initiator (see fin_program_brief's `_fetch`), so
    # a wrapper failure cannot launder access — that is the property the fixture harness's
    # fourth outcome proves, and this check is what makes that outcome unreachable in
    # production rather than merely handled.
    if not identity.get("authorization"):
        raise HTTPException(
            status_code=401,
            detail=(
                f"{graph_id} runs as the INITIATOR and this request carries no identity "
                f"(expected Authorization, plus X-Originator-Sub/Email). Refused before the "
                f"first node: a graph composing governed reads under no subject has nothing to "
                f"scope them to, and this host holds no credential of its own to use instead."
            ),
        )

    # THE THREAD IS THE CALLER'S RUN, AND THE OLD FALLBACK WAS A SHARED ONE. This read
    # `request.thread_id or graph_id`: every request arriving without a thread_id checkpointed
    # into a single thread NAMED AFTER THE GRAPH. On process memory that was already wrong and
    # bounded; against a durable saver it is a cross-caller state leak — the next caller
    # resumes the previous caller's brief, and reducers that append would merge two programmes'
    # findings into one answer.
    #
    # So for a STATEFUL row the thread is required and its absence is a 422 naming it (the row
    # declares `thread_id = run id`; the router supplies it). A stateless row keeps the old
    # tolerance, because nothing is written and there is nothing to collide.
    if m.checkpointer and not request.thread_id:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{graph_id} declares `checkpointer: true`, so it needs a thread_id to "
                f"checkpoint under — the row's contract is `thread_id = run id`. Refused "
                f"rather than defaulted: the old default was the graph's own name, which "
                f"every caller would have shared."
            ),
        )
    state = dict(request.params)
    state["identity"] = identity
    config: dict = {"configurable": {"thread_id": request.thread_id or graph_id,
                                     "user_id": request.user_id}}
    out = await graph.ainvoke(state, config=config)
    return _enforce_refusal(m, out)


def _enforce_refusal(m: GraphManifest, out: Any) -> Any:
    """Adapt the SDK's `enforce_refusal` to an HTTP answer.

    THE RULE ITSELF MOVED TO THE SDK in v0.7.0 and this host no longer owns it. It was
    implemented here first, on the ruling that the host holds both the row and the output —
    which was right and not sufficient: a convention only one host implements is one route C
    will not inherit. A team hosting their own graphs now imports the same function.

    What stays here is the only part that is genuinely this host's: turning the violation into
    a 502. A route-C host may answer differently; the CHECK must not differ.
    """
    try:
        return enforce_refusal(m, out)
    except RefusalViolation as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/health")
async def health() -> dict:
    """Liveness, and it must not say `ok` while admitting nothing.

    Reporting healthy with an empty graph set is what let rev 106 serve zero verbs behind a
    green probe. The boot floor in `load_graphs` should make this unreachable — it is kept
    because a probe that cannot express "up but useless" is how the first one was missed.
    """
    if not _LOADED:
        raise HTTPException(
            status_code=503,
            detail={"status": "no-graphs-admitted", "engine": COMPONENT,
                    "reason": f"zero ratified rows under {GRAPH_POLICY_DIR}"},
        )
    return {
        "status": "ok",
        "engine": COMPONENT,
        "graphs": sorted(_LOADED),
        # STATE IS REPORTED, NEVER INFERRED FROM THE ROW. A caller reading `checkpointer: true`
        # off a manifest would reasonably assume the state survives a restart. It does not yet.
        "checkpointing": checkpointer_durability(),
    }


@app.get("/ready")
async def ready() -> dict:
    """READINESS, NOT LIVENESS. A failing readiness probe removes the pod from Service
    endpoints; it does not restart it. So reporting not-ready while still retrying is correct
    and costs exactly what it should. Wiring this to a liveness probe would turn a slow
    dependency into a crash-loop, which is worse than the outage it fixes."""
    st = registration_status()
    if not registration_is_ready():
        raise HTTPException(status_code=503, detail=st)
    # R-012: A MISSING DECLARATION FAILS READINESS, NAMING THE VARIABLE. Checked after
    # registration so the two reasons never merge into one unreadable 503 — a reader must be
    # able to tell "the mesh has not accepted me yet" from "my state has nowhere durable to go".
    ck_ok, ck = checkpointer_readiness()
    if not ck_ok:
        raise HTTPException(status_code=503, detail={"status": "checkpointer-not-ready", **ck})
    return {"status": "ready", **st, "checkpointing": ck.get("checkpointing")}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
