"""ENGINE-F'S PRESENTATIONS RETRIED NOTHING, AND THE REGISTRAR'S READINESS COULD NOT SEE BOLT.

Two halves of one failure mode, and they are only worth fixing together.

HALF ONE — THE RETRY THAT WAS NEVER ARMED. `_emit_to_registrar` (the ENGINE path) arms
`_start_retry` on failure and records the outcome, so an engine whose dependency boots late
costs minutes of Not Ready instead of hours of silent unroutability. The PRESENTATION path
next to it did neither: `register_presentation_to_mesh` classified the refusal, logged it,
fell back to a DataHub audit emit, and returned. engine-f's lifespan caught the exception per
capability and warned. So a registrar that was down for the eleven seconds engine-f booted in
left every presentation unregistered until somebody rolled the pod — and nothing anywhere
reported it, because the presentation path never touched `_REG_STATE` either.

THE RETRY WAITS ON THE GRAPH WRITE. Measured 2026-08-21 and recorded in
test_registrar_presentation_species.py: 11 presentation URNs in DataHub, 0 rendersAs rows in
Weaviate. The gateway is sole writer of the edge, so the DataHub fallback is an AUDIT RECORD
and satisfies nothing. A retry that accepted it would report success over a presentation that
is still undiscoverable by /search_predicates — the same shape as the helper that returned
None and let eleven engines count every non-raising call as a registration that landed.

AND NOT EVERY FAILURE IS WORTH RETRYING. The three reason classes have opposite repairs, so
`gateway-rejected-REFUSED` records FAILED and arms nothing: a manifest a current gateway
rejects does not become acceptable by waiting, and a permanent "retrying" would hide it.

HALF TWO — A CHECK THAT RAN AND COULD NOT BE SEEN. The registrar's `/health` called
`verify_connectivity()`, put the answer in `neo4j_reachable`, and returned 200 either way. It
is the READINESS probe, and a kubelet reads the status code, never the body. So the check
ran, its premise was true, it computed the right answer, and the probe it was wired to could
not read it — a guard weakened rather than absent, which is the kind no test OF the guard can
find. `/health` now answers 503 when bolt is unreachable.

The liveness/readiness split is the load-bearing part and is asserted in BOTH directions.
`/v1/healthz` must stay DB-free: wired the other way, a Neo4j outage on the node that holds
its PV becomes a CrashLoopBackOff, which is worse than the outage it reports.

Run: uv run --frozen pytest tests/test_registration_retries_until_the_graph_write_lands.py -v
"""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_MR_PATH = _REPO / "agent_fleet" / "utils" / "mesh_registration.py"
_REGISTRAR_PATH = _REPO / "agent_fleet" / "mesh_registrar" / "main.py"
_CHART = _REPO / "helm" / "invincible-agent" / "templates" / "mesh-registrar.yaml"

_PRESENTATION = dict(
    name="presentation_contribution_ranking_for_cost_lot_share",
    description="ranked contributions for a cost lot",
    subject_uri="mesh:CostLotShare",
    object_uri="mesh:ContributionRanking",
    archetype="CONTRIBUTION_RANKING",
    expected_fields=["rows", "total"],
)


def _stub_the_sdk_only_if_it_is_absent(monkeypatch):
    """Stub `iagent_mesh` ONLY when the real one is missing.

    ⛔ THE INSTRUMENT POISONED ITS SUBJECT. The first version of this fixture inserted a bare
    `ModuleType("iagent_mesh")` unconditionally. That is not a PACKAGE, so every later
    `iagent_mesh.transport_auth` import in the same process failed -- and the registrar arms
    below skipped with the reason "mesh_registrar not importable here", which is a claim about
    the registrar that was false. The venv has the real SDK; my fixture had broken it.

    A skip is a test that did not run and its reason is a claim, so the stub is now
    conditional and package-shaped, and it is undone with the test.
    """
    try:
        import iagent_mesh  # noqa: F401,PLC0415
        import iagent_mesh.registration_transport  # noqa: F401,PLC0415
        return
    except ImportError:
        pass
    pkg = types.ModuleType("iagent_mesh")
    pkg.__path__ = []  # a package, so submodule imports resolve rather than TypeError
    tr = types.ModuleType("iagent_mesh.registration_transport")
    tr.register_with_mesh = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "iagent_mesh", pkg)
    monkeypatch.setitem(sys.modules, "iagent_mesh.registration_transport", tr)


@pytest.fixture()
def mr(monkeypatch):
    """A FRESH module per test.

    Fresh because `_REG_STATE` is module-global: a test that left a component behind would
    decide the next test's readiness, and the arm that matters most here is the one asserting
    a component is ABSENT.
    """
    _stub_the_sdk_only_if_it_is_absent(monkeypatch)
    spec = importlib.util.spec_from_file_location("mesh_registration__retry_seal", _MR_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setenv("MESH_REGISTER_ON_STARTUP", "true")
    monkeypatch.setenv("MESH_REGISTRAR_URL", "http://registrar.invalid:8090")
    # The DataHub fallback is left UNCONFIGURED on purpose. It is not what any arm here is
    # about, and an unset GMS url makes it a logged no-op instead of a network call.
    monkeypatch.delenv("DATAHUB_GMS_URL", raising=False)
    return mod


@pytest.fixture()
def armed(mr, monkeypatch):
    """Capture the retry at the THREAD seam, so `_start_retry` itself still runs.

    ⛔ A DOUBLE THAT REMOVED THE CALL UNDER TEST. The first version replaced `_start_retry`
    with a recorder. But `_record(component, _REG_RETRYING)` lives INSIDE `_start_retry`, so
    stubbing it deleted the only thing that makes an unregistered presentation visible -- and
    the arms asserting that visibility failed with a KeyError against source that was right.
    The mutation died in the setup.

    So the seam moved one layer down: `_start_retry` runs for real and does its own recording,
    and only the thread spawn is suppressed. What is captured comes from the actual call, which
    also lets the daemon flag and the target be asserted as ARGUMENTS rather than as text.
    """
    spawned: list = []

    class _Thread:
        def __init__(self, *, target, args, name, daemon):
            self.target, self.args, self.name, self.daemon = target, args, name, daemon

        def start(self):
            spawned.append(self)

    # `mr.threading` is replaced rather than `threading.Thread` patched globally: `_REG_LOCK`
    # was built at import and `_record` holds it directly, so nothing here needs the real
    # module, and nothing outside this test sees a patched Thread.
    monkeypatch.setattr(mr, "threading", types.SimpleNamespace(Thread=_Thread))
    return spawned


def _retry_of(mr, spawned):
    """The component and the callable the retry loop was actually given."""
    (t,) = spawned
    assert t.target is mr._retry_forever, "the retry thread does not run the retry loop"
    assert t.daemon is True, "a non-daemon retry thread would hold the engine open at shutdown"
    component, attempt_once = t.args
    return component, attempt_once


def _emitter(mr, monkeypatch, *outcomes):
    """Drive `_emit_presentation_to_registrar` through a scripted sequence of outcomes."""
    calls: list = []

    def fake(**kw):
        calls.append(kw)
        return outcomes[min(len(calls) - 1, len(outcomes) - 1)]

    monkeypatch.setattr(mr, "_emit_presentation_to_registrar", fake)
    return calls


# ── the success path is the positive control, and it comes first ─────────────

def test_a_gateway_acceptance_RECORDS_the_presentation_and_arms_nothing(mr, monkeypatch, armed):
    """Without this, a function that only ever recorded failure would report every healthy
    engine-f as carrying an unregistered presentation forever."""
    _emitter(mr, monkeypatch, True)
    mr.register_presentation_to_mesh(**_PRESENTATION)
    assert mr.registration_status()["components"] == {_PRESENTATION["name"]: mr._REG_OK}
    assert mr.registration_is_ready() is True
    assert armed == [], "a successful registration must not leave a retry loop running"


def test_a_presentation_appears_in_the_status_AT_ALL(mr, monkeypatch, armed):
    """The fact the module's own docstring used to deny: `registration_is_ready` said the
    presentation agent registers on its own path, which is what made four hours of engine-f
    silence invisible to the one signal this fleet trusts."""
    _emitter(mr, monkeypatch, ("gateway-unreachable", "connection refused"))
    mr.register_presentation_to_mesh(**_PRESENTATION)
    assert _PRESENTATION["name"] in mr.registration_status()["components"]


# ── which failures retry, and which do not ──────────────────────────────────

@pytest.mark.parametrize("reason", ["gateway-unreachable", "gateway-rejected-STALE-IMAGE"])
def test_a_CURABLE_failure_arms_the_retry(mr, monkeypatch, armed, reason):
    """Both of these are cured by time and by nothing else the engine can do: a credential or
    a network on one, a registrar image that has not shipped yet on the other."""
    _emitter(mr, monkeypatch, (reason, "detail"))
    mr.register_presentation_to_mesh(**_PRESENTATION)
    component, _ = _retry_of(mr, armed)
    assert component == _PRESENTATION["name"]
    assert mr.registration_status()["components"][_PRESENTATION["name"]] == mr._REG_RETRYING
    assert mr.registration_is_ready() is False


def test_a_REFUSED_manifest_is_recorded_FAILED_and_retried_NEVER(mr, monkeypatch, armed):
    """A current gateway rejected THIS manifest. Retrying is a busy loop, and a permanent
    "retrying" reads as a dependency that has not arrived — hiding a defect behind the word
    for a healthy wait."""
    _emitter(mr, monkeypatch, ("gateway-rejected-REFUSED", "Contract D: subject not a class"))
    mr.register_presentation_to_mesh(**_PRESENTATION)
    assert armed == [], "a manifest no gateway will accept must not spin a retry thread"
    status = mr.registration_status()
    assert status["components"][_PRESENTATION["name"]] == mr._REG_FAILED
    assert status["status"] == mr._REG_FAILED, (
        "a failed component rolled up as 'pending' would read as not-started-yet"
    )
    assert mr.registration_is_ready() is False


def test_the_FOUR_STATUS_WORDS_ARE_DISTINCT_ON_THE_WIRE(mr):
    """FOUND BY MUTATION, and it survived everything else in this file.

    Every other arm compares against `mr._REG_FAILED` symbolically, so redefining it as
    `"retrying"` passed all 28 of them — the state machine would then be internally consistent
    and externally mute. What reaches an operator is the STRING in `registration_status()`, and
    a vocabulary where two conditions share a word cannot report the difference between "the
    registrar has not booted yet" and "this manifest will never be accepted", which is the
    entire reason the fourth state exists.
    """
    words = [mr._REG_PENDING, mr._REG_OK, mr._REG_RETRYING, mr._REG_FAILED]
    assert len(set(words)) == 4, f"two registration states share a word: {words}"
    assert mr._REG_FAILED == "failed", (
        "the word an operator reads for a permanent refusal is part of the contract"
    )


def test_FAILED_outranks_RETRYING_in_the_rollup(mr):
    """Precedence, not membership. engine-f registers eleven presentations; if one is
    permanently refused while another is legitimately waiting, the summary must name the
    condition that needs a human, not the one that needs a minute."""
    mr._record("p-refused", mr._REG_FAILED, "Contract D")
    mr._record("p-waiting", mr._REG_RETRYING, "registrar down")
    assert mr.registration_status()["status"] == mr._REG_FAILED


# ── what the retry actually retries ─────────────────────────────────────────

def test_the_armed_RETRY_targets_the_GATEWAY_and_returns_True_only_on_acceptance(
    mr, monkeypatch, armed
):
    """THE ARM THIS FILE EXISTS FOR. The closure is captured and CALLED: a retry aimed at the
    DataHub fallback, or one treating a classified refusal tuple as a truthy success, would
    satisfy every assertion about the retry EXISTING while marking a presentation registered
    that no /search_predicates query can find. A non-empty tuple is truthy in Python, which is
    exactly how that mistake gets made.
    """
    calls = _emitter(
        mr, monkeypatch,
        ("gateway-unreachable", "connection refused"),   # the first attempt, at startup
        ("gateway-unreachable", "still refused"),        # a retry that has not landed yet
        True,                                            # the gateway finally accepts
    )
    mr.register_presentation_to_mesh(**_PRESENTATION)
    _, attempt_once = _retry_of(mr, armed)

    assert len(calls) == 1
    assert attempt_once() is False, "a classified refusal tuple is truthy — it is NOT a landing"
    assert len(calls) == 2, "the retry did not re-attempt through the gateway emitter"
    assert attempt_once() is True
    assert calls[-1]["registrar_url"] == "http://registrar.invalid:8090"
    assert calls[-1]["subject_uri"] == _PRESENTATION["subject_uri"]
    assert calls[-1]["archetype"] == _PRESENTATION["archetype"]


@pytest.mark.parametrize("reason", [
    "gateway-unreachable", "gateway-rejected-STALE-IMAGE", "gateway-rejected-REFUSED",
])
def test_NO_refusal_class_ever_ends_with_the_presentation_marked_REGISTERED(
    mr, monkeypatch, armed, reason
):
    """The 2026-08-21 measurement as an assertion: 11 presentation URNs in DataHub, 0 rendersAs
    rows in Weaviate. The DataHub fallback exists so deploy ordering does not matter, not so
    the engine can claim an edge it never wrote — and it runs AFTER the gateway branch, so it
    is the last thing that could wrongly mark the component registered.

    Driven across all three classes rather than one, because "does not mark it OK" is the claim
    the classes have in common while everything else about them differs.
    """
    _emitter(mr, monkeypatch, (reason, "detail"))
    mr.register_presentation_to_mesh(**_PRESENTATION)
    assert mr.registration_status()["components"][_PRESENTATION["name"]] != mr._REG_OK
    assert mr.registration_is_ready() is False


def test_the_ONLY_success_record_in_the_function_is_the_GATEWAY_branch():
    """The structural half of the arm above, and it reaches somewhere behaviour cannot.

    The arms here run with DATAHUB_GMS_URL unset, which is the honest configuration for a
    checkout but means the audit emit returns early. So what they cannot rule out is a
    `_record(name, _REG_OK)` added further down that path later. This reads the source: there
    is exactly ONE success record in the function, and it sits under the gateway acceptance.

    A text assertion is the weaker instrument and it is used deliberately for the one claim
    that is about code which no reachable configuration here executes.
    """
    # AST, not a "\ndef " scan: this is the LAST function in the module, so a scan for the
    # next definition finds nothing and raises. The slice has to come from the parse.
    src = _MR_PATH.read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "register_presentation_to_mesh"
    )
    body = ast.get_source_segment(src, fn) or ""
    assert body, "could not slice the function out of the source"
    records_ok = [ln.strip() for ln in body.splitlines() if "_REG_OK" in ln]
    assert records_ok == ["_record(name, _REG_OK)"], (
        f"expected one success record in the gateway branch, found {records_ok}"
    )
    gateway_branch = body[body.index("registered VIA GATEWAY"):]
    assert "_record(name, _REG_OK)" in gateway_branch.split("return", 1)[0], (
        "the success record is no longer inside the gateway-accepted branch"
    )


def test_an_engine_that_registers_NOTHING_is_still_ready(mr):
    """The control for every arm above: none of this may take a service out of rotation for a
    registration it never attempted. MESH_REGISTER_ON_STARTUP unset is the ordinary case in
    CI and on a bare checkout."""
    assert mr.registration_status()["components"] == {}
    assert mr.registration_is_ready() is True


def test_registration_is_SKIPPED_ENTIRELY_when_the_opt_in_is_off(mr, monkeypatch, armed):
    """A skipped registration is not a failed one. Recording it would make every CI process
    and every engine booted without the env var report itself unready."""
    monkeypatch.setenv("MESH_REGISTER_ON_STARTUP", "false")
    calls = _emitter(mr, monkeypatch, True)
    mr.register_presentation_to_mesh(**_PRESENTATION)
    assert calls == [] and armed == []
    assert mr.registration_status()["components"] == {}
    assert mr.registration_is_ready() is True


# ── the registrar's readiness, both directions ──────────────────────────────

_REGISTRAR_MOD = "mesh_registrar_main__readiness_seal"


def _registrar():
    """Load the registrar under a UNIQUE module name.

    Never bare "main": 155 files in this repo are named main.py and `import main` returns
    whichever was cached first, which has already turned a security suite red on collection
    order alone.
    """
    cached = sys.modules.get(_REGISTRAR_MOD)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(_REGISTRAR_MOD, _REGISTRAR_PATH)
    m = importlib.util.module_from_spec(spec)
    sys.modules[_REGISTRAR_MOD] = m
    try:
        spec.loader.exec_module(m)
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(_REGISTRAR_MOD, None)
        pytest.skip(f"mesh_registrar not importable here: {type(exc).__name__}: {exc}")
    return m


@pytest.fixture()
def client():
    reg = _registrar()
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    return reg, fastapi_testclient.TestClient(reg.app, raise_server_exceptions=False)


class _LiveDriver:
    def verify_connectivity(self):
        return None


def test_readiness_FAILS_when_bolt_is_unreachable(client, monkeypatch):
    """The registrar is sole writer of predicate edges. Without bolt it cannot do its only
    job, so it belongs out of the Service endpoints rather than accepting registrations it
    will not land."""
    reg, c = client
    monkeypatch.setattr(reg, "_get_neo4j_driver", lambda: (_ for _ in ()).throw(
        RuntimeError("Unable to retrieve routing information")))
    r = c.get("/health")
    assert r.status_code == 503, "a 200 here is the whole defect: the probe cannot read a body"
    body = r.json()
    assert body["neo4j_reachable"] is False
    assert body["status"] == "degraded", "'ok' alongside neo4j_reachable=false is a lie"
    assert "Unable to retrieve routing information" in (body["neo4j_error"] or "")


def test_readiness_PASSES_when_bolt_answers(client, monkeypatch):
    """The positive control in the same breath. A /health hardwired to 503 would take the
    registrar permanently out of rotation, and every arm above would still pass."""
    reg, c = client
    monkeypatch.setattr(reg, "_get_neo4j_driver", lambda: _LiveDriver())
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["neo4j_reachable"] is True


def test_the_health_BODY_keeps_every_key_in_BOTH_states(client, monkeypatch):
    """A degraded answer is still an answer. `manifest_species` is read off this endpoint as
    the retirement condition for engine-f's direct-emit fallback, and a 503 that dropped keys
    would make a documented check unobservable -- which is how that trigger died the first
    time, keyed on a log line the logger was not emitting."""
    reg, c = client
    monkeypatch.setattr(reg, "_get_neo4j_driver", lambda: _LiveDriver())
    up = set(c.get("/health").json())
    monkeypatch.setattr(reg, "_get_neo4j_driver", lambda: (_ for _ in ()).throw(OSError("down")))
    down = set(c.get("/health").json())
    assert up == down, f"keys differ between states: {up ^ down}"
    assert {"neo4j_reachable", "neo4j_error", "version", "manifest_species"} <= down


def test_LIVENESS_stays_DB_FREE(client, monkeypatch):
    """The direction nobody would think to seal, and the one that costs the most if someone
    later "fixes" it for consistency. Bolt lives on the node that holds its own PV; a liveness
    probe depending on it converts an outage into a CrashLoopBackOff, so the pod loses its
    logs on top of its database."""
    reg, c = client
    monkeypatch.setattr(reg, "_get_neo4j_driver", lambda: (_ for _ in ()).throw(OSError("down")))
    r = c.get("/v1/healthz")
    assert r.status_code == 200, "liveness must not fail on a dependency it cannot fix"
    assert r.json()["status"] == "ok"


# ── the join: the endpoints are correct, and the chart points at them ───────

def _probe_paths() -> dict[str, str]:
    """Read the deployment's two probe paths out of the chart.

    Line-walked rather than yaml-parsed: the template carries Go expressions that no YAML
    loader accepts, and the probe block itself is literal.
    """
    text = _CHART.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for kind in ("livenessProbe", "readinessProbe"):
        block = text.split(f"{kind}:", 1)
        assert len(block) == 2, f"{kind} is absent from the chart"
        m = re.search(r"path:\s*(\S+)", block[1])
        assert m, f"{kind} declares no httpGet path"
        found[kind] = m.group(1)
    return found


def test_the_CHART_points_readiness_at_the_bolt_dependent_path_and_liveness_at_the_other():
    """BOTH SIDES WERE ALREADY RIGHT AND THE RELATION WAS ASSERTED NOWHERE. /health measured
    bolt; the chart wired readiness to /health; and it still could not work, because the
    endpoint answered 200. Nothing in the suite joined the two declarations, so no
    per-declaration check could see it.

    Derived from the sources in both directions, so swapping the two probe paths -- the
    plausible-looking edit, since /v1/healthz is the newer versioned path -- reds here.
    """
    paths = _probe_paths()
    src = _REGISTRAR_PATH.read_text(encoding="utf-8")

    def handler_body(route: str) -> str:
        i = src.index(f'@app.get("{route}")')
        nxt = src.find("\n@app.", i + 1)
        return src[i:nxt if nxt != -1 else len(src)]

    ready = handler_body(paths["readinessProbe"])
    live = handler_body(paths["livenessProbe"])

    assert paths["readinessProbe"] != paths["livenessProbe"], (
        "one path cannot carry both budgets: readiness must fail on a dependency that "
        "liveness must ignore"
    )
    assert "_get_neo4j_driver" in ready, (
        f"readiness is wired to {paths['readinessProbe']}, which never touches bolt"
    )
    assert "503" in ready, (
        f"{paths['readinessProbe']} reads bolt but cannot report it: a kubelet sees the "
        "status code and never the body"
    )
    assert "_get_neo4j_driver" not in live, (
        f"liveness is wired to {paths['livenessProbe']}, which depends on bolt — a Neo4j "
        "outage would now restart the registrar instead of parking it"
    )
