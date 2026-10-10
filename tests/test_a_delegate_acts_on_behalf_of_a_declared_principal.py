"""A delegate acts on a human task on behalf of a declared principal (R-089).

R-089 (docs/rulings/README.md): a delegate's `on_behalf_of` is an ASSERTION trusted by
DEPLOYMENT CONFIGURATION this pass -- iagent records it and does not verify it. "Anything
built on the asserted form must say so where it reads the field, so that the move to token
exchange finds every reader" -- so every reading site carries the literal text R-089, and
arm J below checks that structurally rather than by function name.

`actor` (who authorization questions -- can_act, the lookups, the resolution, the resume --
are about) and `via` (who authenticated, carried only for the record) are kept apart
throughout: can_act is asked about the PRINCIPAL, never the delegate.

Run: uv run --frozen pytest tests/test_a_delegate_acts_on_behalf_of_a_declared_principal.py -v
"""
from __future__ import annotations

import ast
import inspect
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway, human_tasks  # noqa: E402

_REPO = Path(__file__).resolve().parents[1]
_RA = _REPO / "agent_fleet" / "restate_analyst"
for _p in (str(_RA), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

yaml = pytest.importorskip("yaml")
pytest.importorskip("restate")
import restate  # noqa: E402
import main  # noqa: E402  -- the real executor
import workflow_definition as wd  # noqa: E402
import workflow_runner as wr  # noqa: E402

_CHART = "helm/invincible-agent"

# The env var's name, derived ONCE from the function that reads it -- never re-typed, so a
# rename of the var in gateway.py breaks THIS line, not a stale string elsewhere in the file.
_env_match = re.search(r'os\.environ\.get\("([A-Z_]+)"\)',
                        inspect.getsource(gateway._delegate_principals))
assert _env_match, "could not derive the delegate env var's name from _delegate_principals"
ENV_NAME = _env_match.group(1)

# The sandbox's real declared fixtures (helm/invincible-agent/values-sandbox.yaml) -- arm I's
# JOIN checks the chart render actually contains these, rather than this file re-asserting a
# number it alone invented.
DELEGATE = "svc:openddil"
PRINCIPAL_ATLANTIA = "11111111-1111-4111-8111-111111111111"  # brokered sub (keycloak.brokers.openddil.principals)
PRINCIPAL_BORDURIA = "22222222-2222-4222-8222-222222222222"
PRINCIPAL_LIAISON = "33333333-3333-4333-8333-333333333333"


# =============================================================================================
# BFF arms (A-H) -- fakes modelled on tests/safety/test_the_act_reaches_the_owning_workflow.py
# =============================================================================================

class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code

    def json(self):
        return {}


class _FakeRestate:
    """Stands in for `httpx.AsyncClient` against the Restate ingress. Records every POST."""

    def __init__(self, status=200):
        self.status, self.posts = status, []

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self.posts.append({"url": url, "json": json})
        return _FakeResponse(self.status)


class _User:
    def __init__(self, authz_id):
        self.authz_id = authz_id
        self.sub = authz_id
        self.email = authz_id
        self.persona = "TEST"
        self.entitled_domains: list = []
        self.is_authenticated = True


def _recording_can_act(allow=True):
    seen: list = []

    def f(audience, caller):
        seen.append((audience, caller))
        return allow
    f.seen = seen
    return f


@pytest.fixture
def route(monkeypatch):
    """Not the shared fixture from test_the_act_reaches_the_owning_workflow.py (that file's is
    scoped to its own module) -- same shape: TestClient + recording human_tasks doubles +
    `get_current_user` through `app.dependency_overrides`. `validate_decision` is a no-op here:
    this file is about WHO acts, not about which verb a kind accepts, and real declared-kind
    state depends on TASK_KIND_OVERLAY_DIRS this file has no reason to set up."""
    monkeypatch.setattr(human_tasks, "_SEED_ROWS_CACHE", None, raising=False)
    monkeypatch.setattr(human_tasks, "validate_decision", lambda *a, **k: None)
    calls = {"resolved": [], "settled": None, "list_tasks_for": []}
    rows: list = []

    def mark_resolved(tid, **kw):
        calls["resolved"].append((tid, kw))
        return 1

    def list_tasks_for(caller_id, *, status="pending"):
        calls["list_tasks_for"].append(caller_id)
        return rows

    monkeypatch.setattr(human_tasks, "mark_task_resolved", mark_resolved)
    monkeypatch.setattr(human_tasks, "get_task_resolution",
                         lambda tid, *, caller_id: calls["settled"])
    monkeypatch.setattr(human_tasks, "list_tasks_for", list_tasks_for)

    def login(authz_id):
        gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User(authz_id)

    with TestClient(gateway.app) as c:
        yield c, calls, rows, login, monkeypatch
    gateway.app.dependency_overrides.clear()


_TASK_ID = "wf-1:maint_fault"


def _task(**over):
    base = {
        "task_id": _TASK_ID, "kind": "maint_fault_approval", "audience": "maint:ORG",
        "workflow_id": "wf-1", "workflow_service": "BPMNWorkflowRunner",
        "promise_name": "approval_wf-1:maint_fault", "payload": {},
    }
    base.update(over)
    return base


def _act(c, task_id=_TASK_ID, decision="approved", comment="", on_behalf_of=None):
    body = {"decision": decision, "comment": comment}
    if on_behalf_of is not None:
        body["on_behalf_of"] = on_behalf_of
    return c.post(f"/human_tasks/{task_id}/act", json=body)


# ── A/B: a declared delegate acts for a declared principal ─────────────────────────────────

def test_A_delegate_acts_for_atlantia_on_a_maint_fault_task(route, monkeypatch):
    c, calls, rows, login, mp = route
    mp.setenv(ENV_NAME, json.dumps({DELEGATE: sorted([PRINCIPAL_ATLANTIA, PRINCIPAL_BORDURIA])}))
    cc = _recording_can_act(allow=True)
    mp.setattr(human_tasks, "check_can_act", cc)
    login(DELEGATE)
    fake = _FakeRestate(status=200)
    mp.setattr(gateway.httpx, "AsyncClient", fake)
    rows[:] = [_task()]

    resp = _act(c, on_behalf_of=PRINCIPAL_ATLANTIA)

    assert resp.status_code == 200, resp.text
    assert len(fake.posts) == 1
    body = fake.posts[0]["json"]
    assert body["acted_by"] == PRINCIPAL_ATLANTIA, body
    assert body["acted_via"] == DELEGATE, body
    assert calls["list_tasks_for"] == [PRINCIPAL_ATLANTIA], calls["list_tasks_for"]
    assert calls["resolved"][0][1]["caller_id"] == PRINCIPAL_ATLANTIA, calls["resolved"]
    assert cc.seen == [("maint:ORG", PRINCIPAL_ATLANTIA)], (
        f"check_can_act must be asked about the principal only, saw {cc.seen!r}")
    assert DELEGATE not in [who for _, who in cc.seen], (
        "check_can_act saw the delegate -- can_act must be about the principal, never the via")


def test_B_delegate_acts_for_liaison_on_a_maint_supervisor_task(route, monkeypatch):
    c, calls, rows, login, mp = route
    mp.setenv(ENV_NAME, json.dumps({DELEGATE: [PRINCIPAL_LIAISON]}))
    cc = _recording_can_act(allow=True)
    mp.setattr(human_tasks, "check_can_act", cc)
    login(DELEGATE)
    fake = _FakeRestate(status=200)
    mp.setattr(gateway.httpx, "AsyncClient", fake)
    rows[:] = [_task(kind="maint_supervisor_approval")]

    resp = _act(c, on_behalf_of=PRINCIPAL_LIAISON)

    assert resp.status_code == 200, resp.text
    body = fake.posts[0]["json"]
    assert body["acted_by"] == PRINCIPAL_LIAISON, body
    assert body["acted_via"] == DELEGATE, body
    assert calls["list_tasks_for"] == [PRINCIPAL_LIAISON]
    assert cc.seen == [("maint:ORG", PRINCIPAL_LIAISON)]
    assert DELEGATE not in [who for _, who in cc.seen]


# ── C: an undeclared principal is refused before any lookup ────────────────────────────────

def test_C_a_principal_not_declared_for_the_delegate_is_refused_with_no_lookup(route, monkeypatch):
    c, calls, rows, login, mp = route
    mp.setenv(ENV_NAME, json.dumps({DELEGATE: [PRINCIPAL_ATLANTIA]}))  # liaison NOT declared
    cc = _recording_can_act(allow=True)
    mp.setattr(human_tasks, "check_can_act", cc)
    login(DELEGATE)
    fake = _FakeRestate(status=200)
    mp.setattr(gateway.httpx, "AsyncClient", fake)
    rows[:] = [_task()]

    resp = _act(c, on_behalf_of=PRINCIPAL_LIAISON)

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "principal_not_declared_for_delegate", resp.json()
    assert calls["list_tasks_for"] == [], "an undeclared principal must be refused before any lookup"
    assert fake.posts == []
    assert cc.seen == []
    assert calls["resolved"] == []


# ── D: a non-delegate speaking for someone else is refused, nothing is called ──────────────

def test_D_a_non_delegate_sending_another_persons_id_is_refused_and_nothing_is_called(
        route, monkeypatch):
    c, calls, rows, login, mp = route
    mp.setenv(ENV_NAME, json.dumps({DELEGATE: [PRINCIPAL_ATLANTIA]}))
    cc = _recording_can_act(allow=True)
    mp.setattr(human_tasks, "check_can_act", cc)
    login("person@example.com")  # not a key of the delegate map
    fake = _FakeRestate(status=200)
    mp.setattr(gateway.httpx, "AsyncClient", fake)
    rows[:] = [_task()]

    resp = _act(c, on_behalf_of=PRINCIPAL_ATLANTIA)

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "not_a_delegate", resp.json()
    assert calls["list_tasks_for"] == []
    assert fake.posts == []
    assert cc.seen == []
    assert calls["resolved"] == []


# ── E: a person's own id and an omitted on_behalf_of are the unchanged path, byte-identical ─

def test_E_own_id_and_omitted_on_behalf_of_are_the_identical_unchanged_path(route, monkeypatch):
    c, calls, rows, login, mp = route
    cc = _recording_can_act(allow=True)
    mp.setattr(human_tasks, "check_can_act", cc)
    login("carla@example.com")
    rows[:] = [_task()]

    fake_self = _FakeRestate(status=200)
    mp.setattr(gateway.httpx, "AsyncClient", fake_self)
    resp_self = _act(c, on_behalf_of="carla@example.com")
    assert resp_self.status_code == 200, resp_self.text

    fake_omit = _FakeRestate(status=200)
    mp.setattr(gateway.httpx, "AsyncClient", fake_omit)
    resp_omit = _act(c, on_behalf_of=None)
    assert resp_omit.status_code == 200, resp_omit.text

    body_self, body_omit = fake_self.posts[0]["json"], fake_omit.posts[0]["json"]
    assert body_self == body_omit, (body_self, body_omit)
    assert "acted_via" not in body_self, body_self
    assert body_self["acted_by"] == "carla@example.com"


# ── F: a declared principal who lacks can_act is refused, asked about the principal ────────

def test_F_a_declared_principal_without_can_act_is_refused_and_was_asked_about(route, monkeypatch):
    c, calls, rows, login, mp = route
    mp.setenv(ENV_NAME, json.dumps({DELEGATE: [PRINCIPAL_ATLANTIA]}))
    cc = _recording_can_act(allow=False)
    mp.setattr(human_tasks, "check_can_act", cc)
    login(DELEGATE)
    fake = _FakeRestate(status=200)
    mp.setattr(gateway.httpx, "AsyncClient", fake)
    rows[:] = [_task()]

    resp = _act(c, on_behalf_of=PRINCIPAL_ATLANTIA)

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "not_authorized_to_act", resp.json()
    assert cc.seen == [("maint:ORG", PRINCIPAL_ATLANTIA)]
    assert fake.posts == []
    assert calls["resolved"] == []


# ── G: a delegated act on an out-of-scope kind or a no-workflow_id task is refused 409 ─────

@pytest.mark.parametrize("task_over", [
    {"kind": "document_promotion"},
    {"kind": "grouped_review"},
    {"kind": "access_request", "workflow_id": None},
    # WITH a workflow_id: refused by its kind, not by its shape -- its fulfilment grants as
    # the authenticated caller, which for a delegated act is the delegate.
    {"kind": "access_request"},
])
def test_G_a_delegated_act_unsupported_by_kind_or_shape_is_409_with_no_write(
        route, monkeypatch, task_over):
    c, calls, rows, login, mp = route
    mp.setenv(ENV_NAME, json.dumps({DELEGATE: [PRINCIPAL_ATLANTIA]}))
    cc = _recording_can_act(allow=True)
    mp.setattr(human_tasks, "check_can_act", cc)
    login(DELEGATE)
    fake = _FakeRestate(status=200)
    mp.setattr(gateway.httpx, "AsyncClient", fake)
    rows[:] = [_task(**task_over)]

    resp = _act(c, on_behalf_of=PRINCIPAL_ATLANTIA)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["error"] == "delegated_act_unsupported", resp.json()
    assert fake.posts == [], "an unsupported delegated kind must never reach a write"
    assert calls["resolved"] == []


# ── H: a malformed env var fails closed -- every delegated act refused ─────────────────────

def test_H_a_malformed_delegate_map_fails_closed(route, monkeypatch):
    c, calls, rows, login, mp = route
    mp.setenv(ENV_NAME, "{not valid json")
    cc = _recording_can_act(allow=True)
    mp.setattr(human_tasks, "check_can_act", cc)
    login(DELEGATE)
    fake = _FakeRestate(status=200)
    mp.setattr(gateway.httpx, "AsyncClient", fake)
    rows[:] = [_task()]

    resp = _act(c, on_behalf_of=PRINCIPAL_ATLANTIA)

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "not_a_delegate", resp.json()
    assert fake.posts == []
    assert calls["list_tasks_for"] == []


# =============================================================================================
# Chart arm (I) -- helm render, skipped if helm is absent
# =============================================================================================

pytestmark_helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def _run_helm(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["helm", "template", "t", _CHART, *args],
        capture_output=True, text=True, encoding="utf-8", cwd=str(_REPO), timeout=300,
    )


def _render(*extra: str) -> str:
    r = _run_helm(list(extra))
    assert r.returncode == 0, (
        f"helm template failed:\n{r.stderr[-1500:]}")
    assert r.stdout.strip(), "helm rendered nothing and reported success"
    return r.stdout


_SANDBOX_ARGS = ["-f", str(_REPO / _CHART / "values-sandbox.yaml")]


def _config_data(rendered: str, release: str = "t") -> dict:
    """The SHARED `-config` ConfigMap, matched EXACTLY on `{release}-config` -- this chart also
    renders `{release}-litellm-config` and `{release}-topaz-config`, both of which also end in
    the substring "-config", so a suffix match would be ambiguous."""
    target = f"{release}-config"
    for doc in yaml.safe_load_all(rendered):
        if doc and doc.get("kind") == "ConfigMap" and doc["metadata"]["name"] == target:
            return doc["data"]
    raise AssertionError(f"no ConfigMap named {target!r} in the render")


@pytestmark_helm
def test_I_the_base_chart_renders_an_empty_delegate_map():
    data = _config_data(_render())
    assert json.loads(data[ENV_NAME]) == {}


@pytestmark_helm
def test_I_the_sandbox_renders_openddils_three_principals():
    data = _config_data(_render(*_SANDBOX_ARGS))
    parsed = json.loads(data[ENV_NAME])
    assert parsed[DELEGATE] == sorted([PRINCIPAL_ATLANTIA, PRINCIPAL_BORDURIA, PRINCIPAL_LIAISON])


@pytestmark_helm
def test_I_JOIN_the_chart_key_is_the_one_the_gateway_reads_and_covers_arms_A_and_B():
    # The chart's OWN source names the key it assigns right before `$delegateMap | toJson` --
    # derived from the template text, not re-typed, so a rename on either side breaks this.
    configmap_src = (_REPO / _CHART / "templates/configmap.yaml").read_text(encoding="utf-8")
    chart_match = re.search(r'^\s*([A-Z_]+):\s*\{\{\s*\$delegateMap', configmap_src, re.MULTILINE)
    assert chart_match, "could not derive the chart's env var name from configmap.yaml"
    assert chart_match.group(1) == ENV_NAME, (
        "the chart renders a different key than cortex-bff's _delegate_principals() reads")

    data = _config_data(_render(*_SANDBOX_ARGS))
    rendered_principals = set(json.loads(data[ENV_NAME])[DELEGATE])
    assert {PRINCIPAL_ATLANTIA, PRINCIPAL_LIAISON} <= rendered_principals, (
        "arms A and B act on behalf of principals the sandbox render does not actually declare")


# =============================================================================================
# Source arm (J) -- AST: every function reading on_behalf_of from the act request, or calling
# _delegate_principals, carries R-089 in its own source
# =============================================================================================

def _own_body_nodes(func_node: ast.AST) -> list:
    """Every descendant of `func_node` EXCEPT the interior of a nested def -- so a match inside
    a nested closure is attributed to the nested function, not borrowed by its parent."""
    out: list = []

    def walk(node, is_root):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not is_root:
                continue
            out.append(child)
            walk(child, False)
    walk(func_node, True)
    return out


def test_J_every_reader_of_on_behalf_of_or_delegate_principals_names_R_089():
    src = (_REPO / "src" / "iagent" / "gateway.py").read_bytes().decode("utf-8")
    tree = ast.parse(src)
    func_nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    # The ACT REQUEST's own parameter name, derived from its type annotation -- so this does
    # NOT also catch /ingest's unrelated `req.on_behalf_of` (a different ruling, "no delegation
    # in v1"), which happens to share both the attribute name and the variable name "req".
    act_param_names: dict[int, str] = {}  # id(func_node) -> param name
    for fn in func_nodes:
        for arg in fn.args.args:
            if isinstance(arg.annotation, ast.Name) and arg.annotation.id == "HumanTaskActRequest":
                act_param_names[id(fn)] = arg.arg
    assert act_param_names, "no function takes a HumanTaskActRequest-typed parameter anymore"

    flagged: dict[str, ast.AST] = {}
    for fn in func_nodes:
        param_name = act_param_names.get(id(fn))
        for node in _own_body_nodes(fn):
            is_on_behalf_of_read = (
                param_name is not None and isinstance(node, ast.Attribute)
                and node.attr == "on_behalf_of"
                and isinstance(node.value, ast.Name) and node.value.id == param_name
            )
            is_delegate_call = (
                isinstance(node, ast.Call)
                and (
                    (isinstance(node.func, ast.Name) and node.func.id == "_delegate_principals")
                    or (isinstance(node.func, ast.Attribute) and node.func.attr == "_delegate_principals")
                )
            )
            if is_on_behalf_of_read or is_delegate_call:
                flagged[fn.name] = fn
                break

    assert flagged, "the AST scan found no function reading on_behalf_of from the act request"
    assert "act_on_human_task" in flagged, flagged.keys()

    for name, fn in flagged.items():
        segment = ast.get_source_segment(src, fn) or ""
        assert "R-089" in segment, (
            f"{name} reads on_behalf_of / calls _delegate_principals but its source carries "
            "no R-089 comment")


# =============================================================================================
# Runner arms (K-M) -- the authority gate directly, modelled on
# tests/security/test_approval_authority_gate.py
# =============================================================================================

_APPROVE = main.approve.__wrapped__


class _Promise:
    def __init__(self, rec, name):
        self._rec, self._name = rec, name

    async def resolve(self, value):
        self._rec.append((self._name, value))


class _Ctx:
    def __init__(self, state: dict):
        self._state = state
        self.resolved: list = []

    async def get(self, name, **kw):
        return self._state.get(name)

    def promise(self, name, type_hint=None):
        return _Promise(self.resolved, name)


def _approve_state(promise_name="approval_step-1", audience="maint:ORG", excluded=None):
    state = {main._audience_key(promise_name): audience}
    if excluded is not None:
        state[main._excluded_key(promise_name)] = excluded
    return state


@pytest.fixture(autouse=True)
def _install_decider_for_runner_arms(monkeypatch):
    import importlib
    for name in ("spo_step_executor", "agent_fleet.restate_analyst.spo_step_executor"):
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        monkeypatch.setattr(mod, "check_can_act", lambda aud, who: True, raising=False)


@pytest.mark.asyncio
async def test_K_acted_via_present_carries_through_absent_carries_no_key():
    ctx = _Ctx(_approve_state())
    await _APPROVE(ctx, {"task_id": "step-1", "status": "APPROVED",
                         "acted_by": PRINCIPAL_ATLANTIA, "acted_via": DELEGATE})
    name, payload = ctx.resolved[0]
    assert payload["acted_by"] == PRINCIPAL_ATLANTIA
    assert payload.get("acted_via") == DELEGATE, payload

    ctx2 = _Ctx(_approve_state())
    await _APPROVE(ctx2, {"task_id": "step-1", "status": "APPROVED", "acted_by": PRINCIPAL_ATLANTIA})
    _, payload2 = ctx2.resolved[0]
    assert "acted_via" not in payload2, payload2


@pytest.mark.asyncio
async def test_L_acted_via_equal_to_acted_by_or_blank_is_refused_400():
    ctx = _Ctx(_approve_state())
    with pytest.raises(restate.TerminalError) as exc:
        await _APPROVE(ctx, {"task_id": "step-1", "status": "APPROVED",
                             "acted_by": "m@x", "acted_via": "m@x"})
    assert exc.value.status_code == 400
    assert ctx.resolved == []

    # a case variant of the same id is still "acting via itself"
    ctx2 = _Ctx(_approve_state())
    with pytest.raises(restate.TerminalError) as exc2:
        await _APPROVE(ctx2, {"task_id": "step-1", "status": "APPROVED",
                              "acted_by": "m@x", "acted_via": "M@X"})
    assert exc2.value.status_code == 400
    assert ctx2.resolved == []

    ctx3 = _Ctx(_approve_state())
    with pytest.raises(restate.TerminalError) as exc3:
        await _APPROVE(ctx3, {"task_id": "step-1", "status": "APPROVED",
                              "acted_by": "m@x", "acted_via": "   "})
    assert exc3.value.status_code == 400
    assert ctx3.resolved == []


@pytest.mark.asyncio
async def test_M_an_excluded_delegate_is_refused_even_though_the_principal_is_not():
    ctx = _Ctx(_approve_state(excluded=[DELEGATE]))
    with pytest.raises(restate.TerminalError) as exc:
        await _APPROVE(ctx, {"task_id": "step-1", "status": "APPROVED",
                             "acted_by": PRINCIPAL_ATLANTIA, "acted_via": DELEGATE})
    assert exc.value.status_code == 403
    assert ctx.resolved == [], (
        "the excludes list named the delegate -- a delegate that seeded an artifact may not "
        "confirm it by speaking for someone else, even though can_act would allow the principal")


# =============================================================================================
# Runner arm (N) -- the chain, driven via the _Cluster harness (same shape as
# tests/test_a_case_runs_from_trigger_to_terminal.py). An INLINE definition: the maintenance
# template's first step is being replaced on another branch.
# =============================================================================================

class _ChainPromise:
    def __init__(self, ctx, name):
        self.ctx, self.name = ctx, name

    def value(self):
        async def _v():
            answer = self.ctx.cluster.answers.get((self.ctx._key, self.name))
            if answer is None:
                raise AssertionError(
                    f"{self.ctx._key} awaited {self.name!r}, which this arm did not script")
            return answer
        return _v()

    async def resolve(self, payload):
        self.ctx.resolved.append((self.name, payload))


class _ChainCtx:
    def __init__(self, cluster, key):
        self.cluster, self._key = cluster, key
        self.state: dict = {}
        self.runs: list = []
        self.resolved: list = []

    def key(self):
        return self._key

    def set(self, k, v):
        self.state[k] = v

    def clear(self, k):
        self.state.pop(k, None)

    async def get(self, k, **_kw):
        return self.state.get(k)

    async def run(self, name, fn):
        assert name not in self.runs, f"{self._key} journalled {name!r} twice"
        self.runs.append(name)
        return fn()

    def promise(self, name, type_hint=None):
        return _ChainPromise(self, name)

    def sleep(self, delta):
        async def _s():
            return None
        return _s()

    async def workflow_call(self, handler, key, arg):
        return await _chain_body(handler)(self.cluster.ctx(key), arg)

    async def object_call(self, handler, key, arg):
        return await _chain_body(handler)(self.cluster.obj(key), arg)

    def object_send(self, handler, key, arg):
        self.cluster.sends.append((handler, key, arg))


def _chain_body(handler):
    return getattr(handler, "__wrapped__", handler)


class _ChainCluster:
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.ctxs: dict = {}
        self.objs: dict = {}
        self.sends: list = []

    def ctx(self, key):
        return self.ctxs.setdefault(key, _ChainCtx(self, key))

    def obj(self, key):
        return self.objs.setdefault(key, _ChainCtx(self, key))

    async def start(self, key, trigger, facts):
        try:
            return await _chain_body(wr.run)(self.ctx(key), {"trigger": trigger, "facts": facts})
        finally:
            while self.sends:
                h, k, a = self.sends.pop(0)
                await _chain_body(h)(self.obj(k), a)


def _chain_answer(verb, who, via=None, comments=""):
    out = {"status": verb, "acted_by": who, "comments": comments, "task_id": "t"}
    if via is not None:
        out["acted_via"] = via
    return out


# Minimal INLINE two-step definition -- deliberately NOT the maintenance template (another
# branch is replacing its first step), but the exact same generic-runner shape
# test_a_case_runs_from_trigger_to_terminal.py already uses for its own two-instance chain arm.
_N_TRIGGERS = {
    "two_step": {"trigger": "two_step", "selection": "sel_two", "key": "event_id"},
}
_N_TABLES = {
    "sel_two": {"decision": "sel_two", "matches": ["level"],
                "domain": {"level": ["hi", "lo"]}, "rows": [{"then": "first"}]},
    "first_chain": {"decision": "first_chain", "after": "first", "matches": ["outcome"],
                    "domain": {"outcome": ["ok"]}, "rows": [{"then": "second"}]},
    "second_chain": {"decision": "second_chain", "after": "second", "matches": ["outcome"],
                     "domain": {"outcome": ["ok"]}, "terminals": ["done"],
                     "rows": [{"then": "done"}]},
}


def _n_await(**extra):
    return {"kind": "human_await", "id": "decide", "audience": "maint:{trigger.tier}", **extra}


_N_DEFINITIONS = {
    "first": {"id": "first", "name": "first",
              "steps": [_n_await(task_kind="review_kind", approves=["ok"], role="maintainer")]},
    "second": {"id": "second", "name": "second",
               "steps": [_n_await(task_kind="review_kind", approves=["ok"], role="supervisor")]},
}


def _n_dump(d: Path, rows: dict) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for name, row in rows.items():
        (d / f"{name}.yaml").write_bytes(yaml.safe_dump(row).encode("utf-8"))
    return d


def _n_facts(event_id="E-1"):
    return {"event_id": event_id, "asset_id": "A-7", "level": "hi", "tier": "ORG"}


@pytest.fixture
def n_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("CASE_TRIGGER_DIR", str(_n_dump(tmp_path / "triggers", _N_TRIGGERS)))
    monkeypatch.setenv("DECISION_TABLE_DIR", str(_n_dump(tmp_path / "decisions", _N_TABLES)))
    monkeypatch.setenv("WORKFLOW_DEFINITIONS_DIR",
                       str(_n_dump(tmp_path / "workflows", _N_DEFINITIONS)))
    monkeypatch.setattr(wd, "load_stub_verbs", lambda: {})
    monkeypatch.setattr(main, "_register_human_task",
                        lambda wf, task, kind="workflow_ack": {})
    return tmp_path


@pytest.mark.asyncio
async def test_N_the_chain_carries_acted_via_for_a_delegated_run_and_not_for_a_direct_one(
        n_policy):
    delegated = _ChainCluster({
        ("E-1~1", "approval_decide"): _chain_answer("ok", PRINCIPAL_ATLANTIA, via=DELEGATE),
        ("E-1~2", "approval_decide"): _chain_answer("ok", PRINCIPAL_LIAISON, via=DELEGATE),
    })
    out = await delegated.start("E-1", "two_step", _n_facts("E-1"))
    assert out["status"] == "CLOSED" and out["terminal"] == "done", out
    chain = out["approval_chain"]
    assert [(e["step"], e["role"], e["approver_sub"], e.get("acted_via")) for e in chain] == [
        (1, "maintainer", PRINCIPAL_ATLANTIA, DELEGATE),
        (2, "supervisor", PRINCIPAL_LIAISON, DELEGATE),
    ], chain

    # CONTROL: the same two-step shape, approved directly -- no acted_via key at all.
    direct = _ChainCluster({
        ("E-2~1", "approval_decide"): _chain_answer("ok", "m@x"),
        ("E-2~2", "approval_decide"): _chain_answer("ok", "s@x"),
    })
    out2 = await direct.start("E-2", "two_step", _n_facts("E-2"))
    chain2 = out2["approval_chain"]
    assert [(e["step"], e["role"], e["approver_sub"]) for e in chain2] == [
        (1, "maintainer", "m@x"), (2, "supervisor", "s@x")], chain2
    assert all("acted_via" not in e for e in chain2), chain2
