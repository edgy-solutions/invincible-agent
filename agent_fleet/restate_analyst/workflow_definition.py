"""SPO-native WorkflowDefinition — the git-asserted process model (ADR-0029 Slice 1).

A workflow definition is a **git-asserted** YAML (``policy/workflows/*.yaml``),
reviewed like ``asset_grants.yaml`` / ``task_grants.yaml`` so classification +
grants compose, and executed on the Restate ``BPMNWorkflowRunner``.

Design (see ``docs/reference/slice-1-spo-workflow-promotion.md`` + ADR-0029):

* **A step is PRE-RESOLVED.** An ``spo_operation`` step *declares* its
  ``(subject, verb)`` — it does NOT go through the router's NL-resolution
  (stages 1+3). At execution it hits the router's **structural eligibility
  verifier (stage 2)**; a declared verb not in the caller's eligible set
  (``domain ∩ arity ∩ argument-fit ∩ permission``) → fail-and-release. This is
  what makes "a workflow cannot launder access" true by construction.
* **``human_await``** maps 1:1 onto the sealed HITL mechanics (register durable
  HumanTask → suspend on the promise → Topaz ``can_act`` → resolve).
* **``direct_call`` is TRANSITIONAL and MUST be gated** (RULING Q3): it may
  escape the verb *ontology* (an action not yet a mesh verb) but NEVER the
  *gate* — it declares a ``capability`` that Topaz decides
  (``can_invoke(caller, capability)``). The schema makes ``capability``
  **required**, so a permanently-ungated step kind cannot be expressed. A
  ``direct_call`` is a promotion candidate: close it by registering the action
  as a real verb (→ ``spo_operation``) or keep it capability-gated.

The schema is the SDK's (``iagent_mesh.workflow_definition``, re-exported below); this module is
its **loader, registry and binder only** (Slice-1 foundation). The executor
(stage-2 verifier + dispatch) and the runner cutover are separate, reviewable
increments — they touch the sealed runner and get their own seal.
"""
import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

__all__ = [
    "CompletionPolicy",
    "HumanAwaitStep",
    "SpoOperationStep",
    "DirectCallStep",
    "DispatchFanoutStep",
    "RenderStep",
    "SignalAwaitStep",
    "WaitStep",
    "EmitStep",
    "StubVerb",
    "WorkflowDefinition",
    "WorkflowDefinitionError",
    "load_workflow_definition",
    "load_all_workflows",
    "definitions_dir",
    "get_workflow_definition",
]


# The DSL is the SDK's. The engine's copy was the original (ADR-0029 Slice 1, 2026-07-14); the SDK
# mirrored it on 2026-10-08, and from v0.9.15 the engine reads the SDK's. Re-exported here so every
# importer of this module keeps its names and gets the one class object.
from iagent_mesh.workflow_definition import (  # noqa: E402
    CompletionPolicy,
    DirectCallStep,
    DispatchFanoutStep,
    EmitStep,
    HumanAwaitStep,
    RenderStep,
    SignalAwaitStep,
    SpoOperationStep,
    Step,
    WaitStep,
    WorkflowDefinition,
    WorkflowDefinitionError,
)


class _Declared(BaseModel):
    """Every model a definition author writes. AN UNKNOWN FIELD IS REFUSED, NOT DROPPED.

    pydantic's default is ``extra="ignore"``: a misspelled ``deadline_secs`` or a field this
    runner does not implement validated cleanly and then did nothing. For an approval process that
    is the worst failure available -- the YAML reads as declaring an escalation, a task kind or a
    quorum, and the executor never sees it. Refusing at load turns a silent no-op into a typo.
    The DSL's own models are the SDK's and forbid unknown fields there; this base is for the
    models the engine still declares (``StubVerb`` here, ``case_routing.Trigger``). Sealed by
    tests/test_a_definition_field_the_runner_cannot_see_is_refused.py.
    """

    model_config = ConfigDict(extra="forbid")


def load_workflow_definition(path: str | Path) -> WorkflowDefinition:
    """Load + validate one workflow YAML. Raises ``WorkflowDefinitionError`` on
    any parse/validation failure (config errors fail loud, never silent)."""
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise WorkflowDefinitionError(f"cannot read/parse {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise WorkflowDefinitionError(f"{p}: top level must be a mapping")
    try:
        return WorkflowDefinition.model_validate(raw)
    except ValidationError as exc:
        raise WorkflowDefinitionError(f"{p}: invalid workflow definition:\n{exc}") from exc


def candidate_definition_dirs(module_path: Path) -> list[Path]:
    """The ordered places a definitions directory can live, given this module's path.

    TWO LAYOUTS, and the second one is why this is a function rather than a line:
      * REPO — ``agent_fleet/restate_analyst/workflow_definition.py``, so the
        definitions are three levels up at ``<repo>/policy/workflows``.
      * CONTAINER — the image FLATTENS the service directory into ``/app``, so this
        module is ``/app/workflow_definition.py`` and the definitions are baked
        beside it at ``/app/policy/workflows``.

    The repo candidate is GUARDED on depth. ``Path('/app/workflow_definition.py')``
    has exactly two parents, so an unguarded ``parents[2]`` raises IndexError in the
    container — which would crash BEFORE the loud, specific WorkflowDefinitionError
    below could ever be raised. An honest error path that is unreachable in the only
    environment that needs it is not an error path.
    """
    here = module_path.resolve()
    out: list[Path] = []
    if len(here.parents) >= 3:  # repo layout only; guarded, see docstring
        out.append(here.parents[2] / "policy" / "workflows")
    out.append(here.parent / "policy" / "workflows")  # flattened container layout
    return out


def definition_dirs() -> "list[Path]":
    """The SEED-THEN-OVERLAY search path, lowest precedence first (ADR-0036).

    ``WORKFLOW_DEFINITIONS_DIR`` is an ``os.pathsep``-separated LIST, not a single directory —
    the same shape as ``TASK_KIND_OVERLAY_DIRS``. A deployment's own definitions compose over
    the platform's by id, **full replacement by key**, exactly as a task-kind overlay row
    replaces a seed row rather than merging into it.

    WHY A LIST RATHER THAN ONE DIRECTORY. A single path forces a deployment that needs one
    domain definition to either fork the whole directory or bake its own copy of every platform
    definition — and a forked copy stops tracking the original silently, which is the drift the
    overlay layer exists to prevent. It is also what ADR-0039 needs: a programme tailors ITS
    definitions without carrying ours.

    A SINGLE PATH STILL WORKS AND MEANS WHAT IT MEANT. One entry is a list of one, so every
    existing deployment keeps its behaviour without an edit — the compatibility that makes this
    safe to land ahead of the decision tables that will use it.

    LATER WINS, and the order is the declaration. Unset falls back to the repo/container
    candidates as before; if none exist the first is returned anyway, so the error names a
    concrete path rather than a guess.
    """
    env = os.environ.get("WORKFLOW_DEFINITIONS_DIR")
    if env:
        # A trailing or doubled separator is a typo, not a request to search the CWD — an empty
        # entry would resolve to Path(""), i.e. ".", and silently admit whatever is beside the
        # process.
        parts = [p.strip() for p in env.split(os.pathsep)]
        dirs = [Path(p) for p in parts if p]
        if dirs:
            return dirs
    candidates = candidate_definition_dirs(Path(__file__))
    existing = [c for c in candidates if c.is_dir()]
    if not existing:
        return candidates[:1]
    # THE SEED, THEN EVERY OVERLAY'S workflows/ IN NAME ORDER -- the same default
    # `decision_table.decision_dirs` composes, so a definition and the table that selects it
    # resolve from the same overlays. Before this an overlay could ship a selection table naming a
    # definition the registry could not find. Name order is not a precedence anyone chose, so no
    # two overlays may declare one definition id (sealed).
    seed = existing[0]
    return [seed, *sorted(p for p in (seed.parent / "overlays").glob("*/workflows") if p.is_dir())]


def definitions_dir() -> Path:
    """The HIGHEST-PRECEDENCE directory — kept for callers that want one path to name.

    Returns the LAST entry of :func:`definition_dirs`, because later overrides earlier. Use
    :func:`definition_dirs` for anything that resolves a definition: this cannot see a platform
    definition that an overlay does not replace.
    """
    return definition_dirs()[-1]


def describe_registry() -> dict:
    """What the runtime ACTUALLY loaded — the startup/roll witness in one call.

    Returns the resolved search path and the COMPOSED definition ids. Deliberately reports the
    INVENTORY, not a count: "loaded 2 definitions" passes over the wrong two as happily as the
    right two, and the roll's claim is that the image carries the definitions the gate tested.

    IT REPORTS EVERY DIRECTORY, INCLUDING THE ONES THAT DO NOT EXIST. A missing overlay is the
    most likely deploy defect once the path is a list, and it fails SILENTLY — composition over
    an absent directory contributes nothing and the platform definitions still resolve, so the
    service looks healthy while a programme's tailoring is simply not there. The witness has to
    name what it could not find, or nobody can tell that case from a correct one-entry path.
    """
    dirs = definition_dirs()
    composed: dict = {}
    for d in dirs:
        if d.is_dir():
            for p in sorted(d.glob("*.yaml")):
                composed[p.stem] = str(d)      # later wins: full replacement by id
    return {
        "directories": [{"path": str(d), "exists": d.is_dir()} for d in dirs],
        # The single `directory` key is kept so an existing reader does not break; it is the
        # highest-precedence entry, which is what it always effectively named.
        "directory": str(dirs[-1]),
        "exists": any(d.is_dir() for d in dirs),
        "ids": sorted(composed),
        "resolved_from": composed,
    }


def get_workflow_definition(workflow_id: str) -> WorkflowDefinition:
    """Fetch ONE git-asserted definition by id, for a runner that must not accept a
    client-supplied process.

    Fails LOUDLY and specifically when the definitions are ABSENT — which is the
    expected failure until they are shipped into the pod. A definition that exists
    in git but not in the running service is not a definition the runner has; the
    error says which, and where it looked, because the alternative (an empty
    registry read as "no such workflow") is the silent-degrade this whole arc
    hunts. Presence in the repo is not presence in the running system.
    """
    dirs = definition_dirs()
    if not any(d.is_dir() for d in dirs):
        raise WorkflowDefinitionError(
            f"no workflow definitions directory exists in this runtime — looked in "
            f"{[str(d) for d in dirs]}. The git-asserted definitions are not shipped here. Set "
            "WORKFLOW_DEFINITIONS_DIR (an os.pathsep-separated list) or mount/bake "
            "policy/workflows/."
        )
    # NO TWO OVERLAYS MAY DECLARE ONE DEFINITION. The seal on the committed tree cannot see a
    # deployment's own overlays, and between overlays "later" is name order, which nobody chose.
    owners = [d for d in dirs[1:] if (d / f"{workflow_id}.yaml").is_file()]
    if len(owners) > 1:
        raise WorkflowDefinitionError(
            f"definition {workflow_id!r} is declared by two overlays ({[str(d) for d in owners]}); "
            "name order is not a precedence anyone chose"
        )
    # LATER WINS, so search in REVERSE precedence order and take the first hit: an overlay's
    # definition replaces the platform's by id, wholesale, never field-merged.
    for d in reversed(dirs):
        path = d / f"{workflow_id}.yaml"
        if path.is_file():
            return load_workflow_definition(path)
    # THE ERROR NAMES EVERY DIRECTORY AND THE COMPOSED INVENTORY, not just the last one. With a
    # search path, "not in <dir>" is a true statement that answers the wrong question — the
    # reader needs to know where it looked and what it did find, or a missing overlay and a
    # misspelled id produce the same message.
    available = sorted({p.stem for d in dirs if d.is_dir() for p in d.glob("*.yaml")})
    raise WorkflowDefinitionError(
        f"no git-asserted definition {workflow_id!r} in any of "
        f"{[str(d) for d in dirs if d.is_dir()]} (have: {available})"
    )


def load_all_workflows(directory: str | Path) -> dict[str, WorkflowDefinition]:
    """Load every ``*.yaml`` under ``directory`` (default home:
    ``policy/workflows/``), keyed by definition ``id``. Duplicate ids fail
    loudly (two files claiming one workflow is a config error)."""
    d = Path(directory)
    out: dict[str, WorkflowDefinition] = {}
    for f in sorted(d.glob("*.yaml")):
        wf = load_workflow_definition(f)
        if wf.id in out:
            raise WorkflowDefinitionError(
                f"duplicate workflow id {wf.id!r} ({f} vs a prior file)"
            )
        out[wf.id] = wf
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# PLACEHOLDER BINDING — strictly at ADMISSION, or fail loud THERE
# ═══════════════════════════════════════════════════════════════════════════════════════════════
#
# THE DEFECT THIS CLOSES (2026-08-09, found on the FIRST EVER execution of the autonomous dispatch
# path). `autonomous_review.yaml` declares `endpoint: "{dispatch_endpoint}"` and NOTHING bound it.
# The literal string reached an HTTP client:
#
#     [500 Internal] Invalid URL '{dispatch_endpoint}': No scheme supplied.   retry_count 16
#
# Three things made that possible, and the fix has to answer all three:
#
#   1. NOTHING BOUND IT. `direct_call` passed `step.endpoint` through raw.
#   2. NOTHING NOTICED. Both existing tests INJECT `dispatch_endpoint` into their bindings and then
#      assert the workflow used it — transport proven, sourcing never. The tests agreed with
#      themselves and never once asked the runtime.
#   3. NOTHING RAN IT. The step sat behind `can_invoke(mesh:dispatchDispositions)`, granted to
#      nobody, so it had executed ZERO times. The gate that made the system safe also made the bug
#      invisible — every expected-deny is a lid over virgin code.
#
# THIRD MEMBER OF THE UNBOUND-PLACEHOLDER CLASS (`{compartment}` audience binding, `{artifact_label}`
# cosmetics, now `{dispatch_endpoint}`), so it gets the general rule rather than a third patch:
# **every placeholder in a definition binds at ADMISSION or fails loud there** — never at
# HTTP-client time, sixteen retries deep, where the cause surfaces as a URL-parsing complaint three
# layers away from the thing that was actually missing.
#
# ONE VALUE, ONE HOME. Config placeholders resolve from the SAME source of truth the working
# supervised path already uses (`dispatch_driver.ENGINE_O_URL` <- ONTOLOGY_SERVICE_URL), never a
# second declaration that can drift from it.

_PLACEHOLDER_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


class UnboundPlaceholder(WorkflowDefinitionError):
    """A definition names a placeholder the runtime cannot bind. Raised at ADMISSION."""


def collect_placeholders(node: object) -> set:
    """Every placeholder reachable in a PARSED definition.

    Parsed, never raw text: YAML comments are already gone, so prose that happens to contain
    `{...}` cannot manufacture a phantom requirement. Only values the executor can actually
    substitute are considered.
    """
    found: set = set()
    if isinstance(node, str):
        found.update(_PLACEHOLDER_RE.findall(node))
    elif isinstance(node, dict):
        for v in node.values():
            found |= collect_placeholders(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            found |= collect_placeholders(v)
    return found


def bff_base_url() -> str:
    """cortex-bff's base URL -- the one `config_bindings` builds its BFF endpoints from."""
    return os.getenv("CORTEX_BFF_URL", "http://iagent-cortex-bff:8090").rstrip("/")


def config_bindings() -> dict:
    """Runtime CONFIG placeholders — the deployment's own wiring, not per-request data.

    Sourced from the same env the working dispatch path reads, so the autonomous path cannot
    disagree with the supervised one about where engine-o lives.
    """
    engine_o = os.getenv("ONTOLOGY_SERVICE_URL", "http://iagent-engine-o:8084").rstrip("/")
    bff = bff_base_url()
    return {
        # The disposition write engine-a already performs on the SUPERVISED path
        # (`dispatch_driver`: f"{ENGINE_O_URL}/write_item_state"). Same endpoint, same source.
        "dispatch_endpoint": f"{engine_o}/write_item_state",
        "publish_endpoint": f"{bff}/internal/human_tasks/register",
        # origin_record's `written` step (item B, 2026-10-03) — same BFF, same env var.
        "origin_write_endpoint": f"{bff}/internal/origin/write",
    }


def bind_placeholders(definition: dict, trigger: dict) -> dict:
    """Substitute every placeholder in `definition`, or RAISE naming the unbound ones.

    Returns a bound COPY; the definition itself is git-asserted and never mutated.

    Failing here is the whole point. An unbound placeholder is a DEPLOYMENT defect — it is true of
    every run of this definition, not of this notice — so it must surface once, loudly, at
    admission, rather than as a retryable-looking transport error per invocation.
    """
    bindings = {**config_bindings(),
                **{k: v for k, v in (trigger or {}).items() if isinstance(v, (str, int, float))}}
    required = collect_placeholders(definition)
    missing = sorted(p for p in required if p not in bindings)
    if missing:
        raise UnboundPlaceholder(
            f"workflow definition {definition.get('id')!r} names placeholder(s) {missing} that the "
            f"RUNTIME does not bind. Available: config={sorted(config_bindings())} "
            f"trigger={sorted(k for k in (trigger or {}) if isinstance((trigger or {})[k], (str, int, float)))}. "
            f"This is a DEPLOYMENT defect, not a per-notice one — every run of this definition "
            f"fails identically. Bind it in `config_bindings()` (config) or supply it on the "
            f"trigger (data); do NOT let the literal reach a client, where it surfaces as a URL "
            f"parse error three layers from its cause."
        )

    def _sub(node):
        if isinstance(node, str):
            return _PLACEHOLDER_RE.sub(lambda m: str(bindings[m.group(1)]), node)
        if isinstance(node, dict):
            return {k: _sub(v) for k, v in node.items()}
        # The same containers collect_placeholders walks: a tuple it counts as required and this
        # skipped would pass the unbound check and reach the step as its literal.
        if isinstance(node, list):
            return [_sub(v) for v in node]
        if isinstance(node, tuple):
            return tuple(_sub(v) for v in node)
        return node

    return _sub(definition)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# STUB VERBS — a verb a definition names before the engine that serves it exists
# ═══════════════════════════════════════════════════════════════════════════════════════════════


class StubVerb(_Declared):
    """A declared stand-in for a mesh verb that is not served yet.

    THE STUB IS DECLARED, NAMED AND DATED, never a Python branch: ``stub: true`` and a non-empty
    ``retired_by`` say on the row itself that this is not the verb, and what replaces it. Its
    ``returns`` renders from the run's context with the strict renderer, so a stub reads no store
    and performs no effect -- which is the only reason it may skip the stage-2 verifier. Honoured
    only from the registry, like every field that changes what a run does."""

    verb: str = Field(..., min_length=1)
    stub: Literal[True]
    retired_by: str = Field(..., min_length=1)
    returns: Any


def verb_dirs() -> "list[Path]":
    """``policy/verbs`` (if any) then every ``policy/overlays/*/verbs``, beside the definitions."""
    seed = definition_dirs()[0].parent / "verbs"
    return [seed, *sorted(p for p in (seed.parent / "overlays").glob("*/verbs") if p.is_dir())]


def load_stub_verbs() -> "dict[str, StubVerb]":
    """Every declared stub, keyed by verb. A YAML doc with no ``stub`` key is some OTHER verb
    kind's (a declared-query verb shares this same ``verbs/`` layout) and is skipped here, never
    validated as a stub. TWO DECLARATIONS OF ONE VERB ARE REFUSED -- name order would otherwise
    pick which canned answer a run sees."""
    out: dict[str, StubVerb] = {}
    for d in verb_dirs():
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.yaml")):
            try:
                doc = yaml.safe_load(p.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as exc:
                raise WorkflowDefinitionError(f"{p}: unreadable verb: {exc}") from exc
            if not (isinstance(doc, dict) and "stub" in doc):
                continue
            try:
                v = StubVerb.model_validate(doc)
            except ValidationError as exc:
                raise WorkflowDefinitionError(f"{p}: invalid stub verb:\n{exc}") from exc
            if v.verb in out:
                raise WorkflowDefinitionError(f"{p}: stub verb {v.verb!r} is declared twice")
            out[v.verb] = v
    return out


def load_query_verbs() -> "dict[str, 'QueryVerb']":
    """Every declared-query verb (``agent_fleet/utils/declared_query.py``), over the SAME
    ``verb_dirs()`` the stub registry shares. A verb declared as both a stub and a declared query
    is refused here -- exactly the stub registry's own "declared twice" reasoning, one layer up:
    the runner would otherwise have two canned answers for one verb and name order would choose."""
    try:  # pragma: no cover - import path differs by runtime
        from utils.declared_query import (  # type: ignore[no-redef]
            DeclaredQueryError, load_query_verbs as _load_query_verbs,
        )
    except ImportError:  # pragma: no cover
        from agent_fleet.utils.declared_query import (
            DeclaredQueryError, load_query_verbs as _load_query_verbs,
        )
    try:
        queries = _load_query_verbs(verb_dirs())
    except DeclaredQueryError as exc:
        raise WorkflowDefinitionError(f"declared-query verb registry: {exc}") from exc
    clash = sorted(set(queries) & set(load_stub_verbs()))
    if clash:
        raise WorkflowDefinitionError(
            f"verb(s) {clash} are declared as both a stub and a declared query")
    return queries
