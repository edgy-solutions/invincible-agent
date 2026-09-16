"""engine-docs — `mesh:explain`, the smallest engine in the fleet.

ONE VERB. It answers *"how do I do X"* and *"what is X"* by returning the reviewed write-up that
covers X, whole, with the persona it was written for and the checks it names.

BUILT FROM `docs/runbooks/adding-an-engine.md`, BY THAT PAGE'S OWN LANE, WHICH IS THE POINT. The
first question this engine answers is *"how do I add an engine"* and the page it returns is the
one that was followed to build it. If the runbook is wrong, the engine that would prove it does
not come up.

  §0  name claimed. Four namespaces, all verified free before a line was written:
      service `engine-docs` · values key `engineDocs` · image `docs-agent` · Keycloak
      `iagent-docs-agent`. They differ, which is normal, and is why grepping any one of them
      finds only part of the wiring.
  §1  both ends of Contract D exist BEFORE registration. Input `mesh:DocPage` is platform
      vocabulary in `mesh_system.ttl`; output `docs:DocExplanation` is this engine's own, in its
      own namespace and its own file (`setup/ontologies/docs_extension.ttl`).
  §4  slots DERIVED, in `slots.py`, from the shared `utils/slot_declarations.py`.
  §5  every intra-engine and utils import written twice, FLAT FIRST.
  §7  `/version` from the first commit, reporting the sha baked into the image.
  §8  registration checks its own success, and readiness FAILS ON GAVE UP.

THE READ PATH IS NOT WIRED AND SAYS SO — a degradation must name itself. `MeshGraph` does not
exist yet (verified: absent from this repo and from `iagent-mesh` v0.8.1), and this engine is
being built as its first consumer rather than around a driver it would later have to give up. So
`/explain` answers `503` with the reason and the missing dependency NAMED, and the same guard
appears in `/health`. An engine that returned a plausible empty answer instead would be the
failure this whole corpus is written against.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI
from pydantic import BaseModel

# `app_docs_kwargs()` turns /docs, /redoc and /openapi.json off in deployment: they are the
# Starlette-bypass class of route, reachable without passing the transport dependency.
from iagent_mesh.transport_auth import announce as _announce_transport_auth
from iagent_mesh.transport_auth import app_docs_kwargs as _docs_kwargs
from iagent_mesh.transport_auth import make_transport_auth_dependency as _transport_auth

try:  # flat in the image (/app), packaged in the repo — runbook §5, FLAT FIRST.
    import explain as explain_mod
    import slots as slots_mod
    from reads import BodyStore, DocPageReader
except ImportError:  # pragma: no cover — exercised by the flat-layout seal
    from agent_fleet.docs_agent import explain as explain_mod
    from agent_fleet.docs_agent import slots as slots_mod
    from agent_fleet.docs_agent.reads import BodyStore, DocPageReader

COMPONENT = "engine-docs"

MESH = "http://invincible-agent/mesh#"
DOCS = "http://invincible-agent/docs#"

#: ONE ROW, READ TWICE — as the registration source and as the catalogue. Two hand-kept tables
#: for one verb is how a verb lands in one and not the other: servable by direct call, invisible
#: to the mesh, healthy on every probe and never routed to.
#:
#: THE DESCRIPTION IS THE ROUTING SIGNAL AND THE NOT-CLAUSE IS LOAD-BEARING. Without it this verb
#: competes for every question containing the word "how", including ones that want a computed
#: answer rather than a written one.
VERBS: List[Dict[str, Any]] = [
    {
        "fn": "explain",
        "verb": f"{MESH}explain",
        "input_uri": f"{MESH}DocPage",
        "output_uri": f"{DOCS}DocExplanation",
        "desc": (
            "Return the reviewed write-up covering a named thing — the procedure for doing it, "
            "or what it means — as the text an author wrote and a reviewer approved, with the "
            "persona it addresses and the checks it names. Answers questions of the form 'how do "
            "I …' and 'what is …' about parts of this system. NOT for computing a figure, "
            "retrieving a record, or reporting current state: those are answered from data, and "
            "this returns prose. NOT a summary or a rewrite — the writing is carried whole. "
            "Returns nothing and says so when no write-up covers what was asked."
        ),
        "synonyms": ["how do I", "how to", "what is", "explain", "documentation for",
                     "runbook for", "walk me through"],
        "anti_synonyms": ["compute", "calculate", "current value", "how many", "how much",
                          "status of", "latest"],
    },
]


def _catalogue_agrees() -> None:
    """THE BOOT GUARD (runbook §8). It raises; it is not softened to a warning.

    One verb makes this look decorative, and it is not: the check is over the JOIN between what
    this engine registers and what it can actually serve, and the failure it refuses — a verb in
    one table and absent from another — is invisible from outside. An engine that boots, reports
    healthy, and answers when addressed by name while never being routed to is the shape this
    fleet has paid for more than once.
    """
    for v in VERBS:
        if not hasattr(explain_mod, v["fn"]):
            raise RuntimeError(
                f"{COMPONENT}: VERBS declares {v['fn']!r} and the module cannot serve it. "
                f"Registering it would advertise a verb this engine answers 404 for.")
        for end in ("input_uri", "output_uri"):
            uri = v[end]
            if not uri.startswith(("http://", "https://")):
                raise RuntimeError(
                    f"{COMPONENT}: {end}={uri!r} is not a full IRI. Contract D matches both ends "
                    f"against :OntologyClass nodes holding FULL IRIs, so a compact form misses "
                    f"and the row registers accepted-and-unreachable.")
    declared = slots_mod.slots_for("explain")
    if not declared:
        raise RuntimeError(
            f"{COMPONENT}: the slot derivation returned nothing. Without declarations the router "
            f"cannot know a slot is MISSING — only that nothing cleared threshold, which surfaces "
            f"as NO_VERB_CLASSIFIED: an information gap wearing a threshold gap's clothes.")


#: Set once the mesh client exists. Until then the engine registers, serves, and refuses to
#: answer — in that order, and each of the three is deliberate.
READER: Optional[DocPageReader] = None
STORE: Optional[BodyStore] = None

_NO_READER = (
    "engine-docs has no MeshGraph reader wired. The verb is registered and the corpus is primed; "
    "what is missing is the one client the ADR requires an engine to read through, which does "
    "not exist yet. This engine will not hold a driver in the meantime."
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _catalogue_agrees()

    if not os.getenv("MESH_REGISTER_ON_STARTUP"):
        print(f"[{COMPONENT}] MESH_REGISTER_ON_STARTUP not set — NO verbs registered")
        yield
        return

    register_engine_to_mesh = None
    engine_mint = None
    try:  # FLAT FIRST — see the module header.
        from utils.mesh_registration import engine_mint, register_engine_to_mesh
    except ImportError:
        try:
            from agent_fleet.utils.mesh_registration import engine_mint, register_engine_to_mesh
        except ImportError:  # pragma: no cover — local runs without the fleet extra
            register_engine_to_mesh = None

    if register_engine_to_mesh is None:
        # SAY SO. A registration that silently does not happen leaves an engine that passes every
        # probe and answers nothing — the failure mode with no symptom.
        print(f"[{COMPONENT}] mesh registration helper unavailable — NO verbs registered")
        yield
        return

    base = os.getenv("ENGINE_DOCS_PUBLIC_URL", "http://iagent-engine-docs:8100").rstrip("/")

    # IDENTITY IS AN ARGUMENT, NEVER DERIVED FROM THE COMPONENT NAME (runbook §6). The client id
    # and the env var holding its secret are both named HERE, at the call site.
    _mint = engine_mint(client_id="iagent-docs-agent", secret_env="ENGINE_DOCS_CLIENT_SECRET")

    registered, failed = [], []
    for v in VERBS:
        try:
            # THE KEYWORD NAMES ARE THE HELPER'S, CHECKED AGAINST ITS SIGNATURE RATHER THAN COPIED
            # FROM A NEIGHBOUR. `endpoint_url`, `verb_synonyms`, `verb_anti_synonyms` — a sibling
            # engine on master passes `endpoint`, `synonyms`, `anti_synonyms`, which raises
            # TypeError on every verb and registers none of them. Copying the newest engine is
            # how a defect propagates by being exemplary.
            register_engine_to_mesh(
                name=f"engine_docs_{v['fn']}",
                verb=v["verb"],
                input_uri=v["input_uri"],
                output_uri=v["output_uri"],
                endpoint_url=f"{base}/explain",
                description=v["desc"],
                verb_synonyms=v["synonyms"],
                verb_anti_synonyms=v["anti_synonyms"],
                slots=slots_mod.slots_for(v["fn"]),
                mint=_mint,
            )
            registered.append(v["verb"])
        except Exception as exc:  # noqa: BLE001
            # NO SUCCESS LINE THAT DOES NOT CHECK SUCCESS (runbook §8).
            failed.append((v["verb"], str(exc)))
            print(f"[{COMPONENT}] REGISTRATION FAILED {v['verb']}: {exc}")

    print(f"[{COMPONENT}] registered {len(registered)}/{len(VERBS)} verbs")
    if failed:
        app.state.registration_incomplete = [v for v, _ in failed]
    yield


_announce_transport_auth(component=COMPONENT)

app = FastAPI(
    lifespan=lifespan,
    **_docs_kwargs(),
    dependencies=[Depends(_transport_auth(COMPONENT))],
    title="engine-docs — the corpus answers for itself",
    description=(
        "One verb. `mesh:explain` returns the reviewed write-up covering a named thing, carried "
        "whole rather than summarised, refused outright if the text is not what was indexed."
    ),
)

# ONE IMPLEMENTATION, MOUNTED PER SERVICE. Reports the sha BAKED INTO THE IMAGE, never one a
# chart injected. REQUIRED from the first commit (runbook §7).
try:  # pragma: no cover - import path differs by runtime
    from utils.version_endpoint import mount_version as _mount_version
except ImportError:  # pragma: no cover
    from agent_fleet.utils.version_endpoint import mount_version as _mount_version
_mount_version(app, COMPONENT)


class ExplainRequest(BaseModel):
    """The envelope. `params` carries the slots; there is no state ref — engine-docs reads."""

    fn: str = "explain"
    params: Dict[str, Any] = {}


@app.get("/health", tags=["ops"])
def health() -> Dict[str, Any]:
    """Liveness, and it reports the read path's absence rather than hiding it.

    `ready` is False without a reader ON PURPOSE. An engine that reported ready while unable to
    answer would be discovered by a user, and the whole point of carrying this state as a field
    is that an operator finds it first.
    """
    incomplete = getattr(app.state, "registration_incomplete", None)
    return {
        "status": "ok",
        "component": COMPONENT,
        "verbs": [v["verb"] for v in VERBS],
        "reader_wired": READER is not None,
        "body_store_wired": STORE is not None,
        "ready": READER is not None and STORE is not None and not incomplete,
        "registration_incomplete": incomplete,
        "degraded_reason": None if READER and STORE else _NO_READER,
    }


@app.post("/explain", tags=["mesh"])
def explain_endpoint(req: ExplainRequest) -> Dict[str, Any]:
    """Resolve the subject to a page, read its body, assert the sha, return the page.

    THE ORDER IS THE CONTRACT: resolve, read, ASSERT, render. Nothing reaches a caller that has
    not been checked against the sha the graph indexed.
    """
    from fastapi import HTTPException

    if req.fn != "explain":
        raise HTTPException(status_code=422, detail=f"engine-docs serves one verb; {req.fn!r} is not it")

    subject = (req.params or {}).get("subject")
    if not subject:
        # THE SLOT IS DECLARED MANDATORY, so a missing one is a legible refusal naming the slot
        # rather than a threshold miss the router has to guess at.
        raise HTTPException(status_code=422, detail="slot 'subject' is required and was not supplied")

    if READER is None or STORE is None:
        raise HTTPException(status_code=503, detail=_NO_READER)

    rows = READER.page_for_subject(subject)
    if not rows:
        # A gap in the writing, not a failure of the question — and the corpus's normal state,
        # because nobody writes a page for a task nobody has done.
        return explain_mod.abstain(subject)

    row = rows[0]
    body = STORE.read(row.source)
    try:
        return explain_mod.explain(row, body)
    except explain_mod.BodyShaMismatch as exc:
        # REFUSED, NOT ANNOTATED. Text that is not what was indexed is wrong in the one way a
        # reader cannot detect: the wrong page is fluent, well-formed and roughly on topic.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
