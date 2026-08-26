"""The BFF's planning routes — the seam cortex-ui actually calls.

WHAT THESE DEFEND THAT THE ENGINE'S OWN ROUTE TESTS DO NOT:

  * the BFF must NOT name an archetype. `/instances_by_property` next door is a "temporary
    feeder" that hand-sets `"archetype": "INSTANCES_BY_PROPERTY"` — acknowledged as such, and
    exactly the `archetype-chosen-before-data` shape ADR-0042 §2 forbids for new work. A new
    route copying its neighbour is the most likely way that shape spreads, so it is asserted
    against here rather than trusted to discipline.

  * `frontend_id` must reach the response. It is what makes menu-scoped selection possible at
    all, and wiring it as None is the trap the seam's own packet records: every caller
    resolves to the default menu and every answer becomes a KNOWLEDGE_DOCUMENT — a regression
    that reads as completion.

  * an engine refusal must cross as a refusal. A 422 `not_in_model` collapsing into a 200 with
    an empty list at the BFF would destroy the honest-refusal path one hop from where it was
    carefully built.

The engine is stubbed rather than run: these are tests of the BFF's TRANSLATION, and standing
up Engine P would test the engine again while hiding a translation defect behind a working
backend.
"""
from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402


ENGINE_OK = {
    "measure": "plan_cost_curve",
    "output_uri": "http://invincible-agent/mesh#PeriodCostSeries",
    "state_ref": "baseline",
    "state_version": 3,
    "rows": [{"period": "FY26-Q3", "total": 5050000.0, "cap": 4000000.0,
              "over_cap": True, "overage": 1050000.0}],
}


#: Engine P's OWN shape for the version poll. Note the key: `version`, not `state_version`.
#: The rename IS the join under test.
ENGINE_VERSION = {"state_ref": "SC-DEMO", "version": 3}


class _Resp:
    def __init__(self, status: int, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("engine error", request=None, response=None)  # type: ignore[arg-type]


@pytest.fixture
def stub_engine(monkeypatch):
    """Capture what the BFF sends and control what the engine returns."""
    sent: dict = {}

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, **k):
            sent["url"] = url
            sent["json"] = json
            return sent.get("_resp") or _Resp(200, ENGINE_OK)

        async def get(self, url, **k):
            sent["url"] = url
            return sent.get("_get_resp") or _Resp(200, ENGINE_VERSION)

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)
    return sent


@pytest.fixture
def client(monkeypatch):
    """Auth is bypassed at the dependency, not by disabling it — the route keeps its
    Depends(get_current_user) so a future removal of that dependency is still a visible diff."""
    user = type("U", (), {"authz_id": "tester", "sub": "tester", "persona": "PORTFOLIO_LEAD",
                          # `entitled_domains` is the field the write gate reads —
                          # `domains` was this stub's own invention and matches no
                          # attribute on the real User model.
                          "entitled_domains": ["PORTFOLIO_PLANNING"],
                          "domains": ["PORTFOLIO_PLANNING"], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────

def test_the_bff_forwards_the_measure_and_returns_output_uri_and_rows(client, stub_engine):
    r = client.post("/plan/measure/plan_cost_curve",
                    json={"state_ref": "baseline", "params": {}},
                    headers={"X-Frontend-Id": "cortex-ui-desktop"})
    assert r.status_code == 200
    body = r.json()
    assert body["output_uri"] == "http://invincible-agent/mesh#PeriodCostSeries"
    assert body["rows"][0]["period"] == "FY26-Q3"
    assert body["state_version"] == 3
    assert stub_engine["url"].endswith("/measure/plan_cost_curve")


def test_the_bff_NAMES_NO_ARCHETYPE(client, stub_engine):
    """ADR-0042 §2. The BFF says WHAT this is; select_presentation decides HOW it draws.
    Its neighbour `/instances_by_property` hand-sets an archetype and is a documented
    temporary feeder — a new route copying it is how that shape spreads."""
    r = client.post("/plan/measure/plan_cost_curve", json={},
                    headers={"X-Frontend-Id": "cortex-ui-desktop"})
    # Non-vacuous: a 404 body also contains no archetype, so the status is asserted first.
    assert r.status_code == 200, "route missing — this assertion would pass over nothing"
    body = r.json()
    forbidden = {"archetype", "view", "chart_type", "component", "layout"}
    assert not (forbidden & set(body)), f"BFF named a presentation concern: {forbidden & set(body)}"


def test_the_frontend_id_reaches_the_response_so_selection_can_be_menu_scoped(client, stub_engine):
    """Wiring this as None is the trap the seam's packet records: every caller resolves to the
    default menu and every answer becomes a KNOWLEDGE_DOCUMENT — a regression that reads as
    completion, with 'the charts stopped appearing' as its only symptom."""
    body = client.post("/plan/measure/plan_cost_curve", json={},
                       headers={"X-Frontend-Id": "cortex-ui-desktop"}).json()
    assert body["frontend_id"] == "cortex-ui-desktop"


def test_an_absent_frontend_id_is_carried_as_absent_not_invented(client, stub_engine):
    """A non-UI caller is not an error. But the BFF must not substitute a plausible id — that
    would make an anonymous caller indistinguishable from a registered one at the selector,
    which is the exact distinction Ruling 9 depends on."""
    body = client.post("/plan/measure/plan_cost_curve", json={}).json()
    assert body["frontend_id"] is None


def test_an_engine_refusal_crosses_as_a_refusal(client, stub_engine):
    """422 with `not_in_model` must survive the hop. Collapsing it into a 200 with [] would
    destroy the honest-refusal path one hop from where it was built."""
    stub_engine["_resp"] = _Resp(422, {"detail": {"not_in_model": "unknown capability 'C99'"}})
    r = client.post("/plan/measure/plan_capability_path",
                    json={"params": {"capability_id": "C99"}},
                    headers={"X-Frontend-Id": "cortex-ui-desktop"})
    assert r.status_code == 422
    assert "not_in_model" in r.json()["detail"]


def test_an_unreachable_engine_is_502_and_says_so(client, stub_engine):
    """Not a 200 with empty rows. An unreachable engine and an empty result are different
    facts, and only one of them means 'nothing is planned'."""
    class _Boom:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise httpx.ConnectError("no route to host")
    import src.iagent.gateway as g
    g.httpx.AsyncClient = _Boom  # type: ignore[assignment]
    r = client.post("/plan/measure/plan_cost_curve", json={},
                    headers={"X-Frontend-Id": "cortex-ui-desktop"})
    assert r.status_code == 502
    assert "unreachable" in str(r.json()["detail"]).lower()


# ─────────────────────────────────────────────────────────────────────────────
# The refresh loop's poll — ADR-0042 OQ1's pull trigger
#
# Cortex wrote this client half before the server half existed, and said so:
# "when the server half lands the change is here and nowhere else". It calls
# GET /plan/state_version and reads `{state_version}`. Engine P answers
# `{state_ref, version}`. TWO CORRECT HALVES THAT DO NOT MEET — the same shape as this
# week's axis keys and the lost DashboardUI envelope, which is why it is tested at the
# seam rather than on either side.
# ─────────────────────────────────────────────────────────────────────────────

def test_the_poll_renames_engine_version_to_the_key_the_client_reads(client, stub_engine):
    r = client.get("/plan/state_version?state_ref=SC-DEMO")
    assert r.status_code == 200, "route missing — every assertion below would pass over nothing"
    body = r.json()
    assert body["state_version"] == 3, "the rename did not happen — the client reads undefined"
    assert "version" not in body, "engine's key leaked through; the client does not read it"
    assert stub_engine["url"].endswith("/state/SC-DEMO/version")


def test_the_poll_ECHOES_the_ref_it_answered_for(client, stub_engine):
    """The client's signature takes no argument, so it polls `baseline` — whose version NEVER
    bumps, because ops apply to scenarios. A loop polling baseline looks like it works and
    never fires. The echo is what lets a caller notice it asked about the wrong plan."""
    r = client.get("/plan/state_version")
    assert r.json()["state_ref"] == "SC-DEMO", "the answer does not say which plan it is about"
    assert stub_engine["url"].endswith("/state/baseline/version"), "default ref is not baseline"


def test_a_baseline_version_of_ZERO_survives_the_hop(client, stub_engine):
    """0 is a real version, not a missing one. Any truthiness test between here and the card
    turns 'the plan has never moved' into 'this card has no version', and the second reads as
    a broken feature."""
    stub_engine["_get_resp"] = _Resp(200, {"state_ref": "baseline", "version": 0})
    r = client.get("/plan/state_version")
    assert r.json()["state_version"] == 0
    assert r.json()["state_version"] is not None


def test_an_unknown_ref_is_a_404_not_a_200_with_zero(client, stub_engine):
    """Same argument as the measure route's not_in_model refusal one function up: a plan that
    does not exist and a plan that has never moved are different facts, and collapsing them
    stops the refresh loop forever while looking like 'nothing has changed'."""
    stub_engine["_get_resp"] = _Resp(404, {"detail": "unknown scenario 'SC-GHOST'"})
    r = client.get("/plan/state_version?state_ref=SC-GHOST")
    assert r.status_code == 404


def test_an_unreachable_engine_is_a_502_not_a_stale_zero(client, stub_engine, monkeypatch):
    class _Boom:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): raise RuntimeError("connection refused")
    # monkeypatch, NOT a direct assignment. A bare `gw.httpx.AsyncClient = _Boom` leaks
    # into whatever test runs next, and pytest-randomly means that is a different test each
    # run — the stub_engine fixture would then record _Boom as the value to restore.
    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Boom)
    r = client.get("/plan/state_version")
    assert r.status_code == 502
    assert r.json()["detail"]["error"] == "planning_engine_unreachable"


# ─────────────────────────────────────────────────────────────────────────────
# THE PLAN WRITE SEAM
#
# Engine P's write surface existed from Phase 1 and none of it was reachable from a browser.
# These test the BFF's TRANSLATION and its GATE — the two things that are genuinely the BFF's
# and cannot be tested at the engine, which can see neither the caller's identity nor the
# refusal codes it will be wrapped in.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def unentitled_client(monkeypatch):
    """A caller with NO entitled domains. `User.entitled_domains` is documented honest-empty —
    empty means no entitled domains, never 'no filter' — and privileged operations deny on it."""
    user = type("U", (), {"authz_id": "outsider@example.com", "sub": "outsider",
                          "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


WRITE_ROUTES = [
    ("/plan/scenario", {"scenario_id": "S1", "name": "What if"}),
    ("/plan/scenario/S1/op", {"op": "move_project", "project_id": "P12",
                              "start": "2026-03-18", "end": "2026-06-16"}),
    ("/plan/baseline/op", {"op": "set_cost", "project_id": "P12",
                           "period": "FY26-Q3", "kind": "capex", "amount": 1.0}),
    ("/plan/scenario/S1/reschedule", {"project_id": "P12", "start": "2026-03-18",
                                      "end": "2026-06-16"}),
    ("/plan/scenario/S1/commit", {"rationale": "Pulling Line 3 forward."}),
]


@pytest.mark.parametrize("path,body", WRITE_ROUTES, ids=[r[0] for r in WRITE_ROUTES])
def test_every_write_route_refuses_a_caller_without_the_domain(unentitled_client, stub_engine,
                                                               path, body):
    """AND THE ENGINE IS NEVER CALLED. The gate runs before the proxy, so an unentitled caller
    cannot use refusal codes to learn which scenario ids resolve — a 404 and a 400 from the
    engine say different things about a plan they may not read."""
    r = unentitled_client.post(path, json=body)
    assert r.status_code == 403, f"{path} let an unentitled caller through"
    assert r.json()["detail"]["required_domain"] == "PORTFOLIO_PLANNING"
    assert "url" not in stub_engine, f"{path} reached the engine before gating"


@pytest.mark.parametrize("path,body", WRITE_ROUTES, ids=[r[0] for r in WRITE_ROUTES])
def test_every_write_route_is_reachable_by_an_entitled_caller(client, stub_engine, path, body):
    """Positive control for the gate above. Without this, a route that 403s EVERYONE would
    pass the refusal test and be indistinguishable from a working gate."""
    r = client.post(path, json=body)
    assert r.status_code == 200, f"{path} refused an entitled caller: {r.text}"
    assert "url" in stub_engine and stub_engine["url"].startswith("http")


def test_the_drag_forwards_to_the_reschedule_route_not_the_raw_op_route(client, stub_engine):
    """THE DERIVATION LIVES WHERE THE STATE IS. A MoveProject alone moves the bar and not the
    load; the client holds no site-impact data and would have to INVENT windows to send two
    ops itself. So the drag hits `/reschedule`, which derives both offset-preserved."""
    client.post("/plan/scenario/SC-DEMO/reschedule",
                json={"project_id": "P12", "start": "2026-03-18", "end": "2026-06-16"})
    assert stub_engine["url"].endswith("/scenario/SC-DEMO/reschedule")
    assert set(stub_engine["json"]) == {"project_id", "start", "end"}, (
        "the client sent something about site impacts — it has no such data to send"
    )


def test_the_commit_actor_comes_from_the_TOKEN_and_cannot_be_sent(client, stub_engine):
    """THE FORGERY THIS CLOSES. Engine P takes `actor` as a field because it cannot see who is
    calling. If the BFF forwarded a client-supplied one, the DecisionArtifact — the governance
    record of who moved the portfolio and why — would be forgeable by anyone who can post JSON.
    The body model carries no `actor` at all: a field that cannot be sent cannot be spoofed."""
    r = client.post("/plan/scenario/SC-DEMO/commit",
                    json={"rationale": "Pulling Line 3 forward.",
                          "actor": "ceo@example.com"})
    assert r.status_code == 200
    assert stub_engine["json"]["actor"] == "tester", (
        "a client-supplied actor reached the engine — the decision record is forgeable"
    )


def test_a_blank_rationale_refusal_SURVIVES_the_hop(client, stub_engine):
    """The ceremony's gate runs FIRST at the engine — before the scenario resolves and before
    any op applies — so a refused commit changes nothing. The BFF's only job is to not swallow
    it. Collapsing this into a 200 would put the BFF exactly where a governance refusal goes
    to die."""
    stub_engine["_resp"] = _Resp(422, {"detail": "a commit needs a rationale"})
    r = client.post("/plan/scenario/SC-DEMO/commit", json={"rationale": "   "})
    assert r.status_code == 422
    assert "rationale" in str(r.json()["detail"])


def test_an_op_naming_something_unknown_stays_a_400(client, stub_engine):
    """A silently-dropped op is the failure where the room believes it made a change, the diff
    shows nothing, and the decision artifact records an op that never applied."""
    stub_engine["_resp"] = _Resp(400, {"detail": "move_project names unknown project 'P99'"})
    r = client.post("/plan/scenario/SC-DEMO/op",
                    json={"op": "move_project", "project_id": "P99",
                          "start": "2026-01-01", "end": "2026-02-01"})
    assert r.status_code == 400
    assert "P99" in str(r.json()["detail"])


def test_an_unknown_scenario_stays_a_404(client, stub_engine):
    stub_engine["_resp"] = _Resp(404, {"detail": "unknown scenario 'SC-GHOST'"})
    r = client.post("/plan/scenario/SC-GHOST/reschedule",
                    json={"project_id": "P12", "start": "2026-03-18", "end": "2026-06-16"})
    assert r.status_code == 404


def test_a_duplicate_scenario_id_stays_a_409(client, stub_engine):
    stub_engine["_resp"] = _Resp(409, {"detail": "scenario 'S1' already exists"})
    r = client.post("/plan/scenario", json={"scenario_id": "S1", "name": "What if"})
    assert r.status_code == 409


def test_an_unreachable_engine_is_a_502_never_a_silent_success(client, stub_engine, monkeypatch):
    """A write that reports success without reaching the engine is the worst outcome available:
    the room believes the plan moved and it did not."""
    class _Boom:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise RuntimeError("connection refused")
    # monkeypatch, NOT a direct assignment. A bare `gw.httpx.AsyncClient = _Boom` leaks
    # into whatever test runs next, and pytest-randomly means that is a different test each
    # run — the stub_engine fixture would then record _Boom as the value to restore.
    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Boom)
    r = client.post("/plan/scenario/SC-DEMO/reschedule",
                    json={"project_id": "P12", "start": "2026-03-18", "end": "2026-06-16"})
    assert r.status_code == 502
    assert r.json()["detail"]["error"] == "planning_engine_unreachable"
