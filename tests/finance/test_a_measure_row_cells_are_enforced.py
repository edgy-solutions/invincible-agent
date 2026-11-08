"""A measure row's `policy.cells` is enforced: the verb's registered domains, refused on every path.

WHY: `policy.cells` was loaded and validated and nothing read it, though the contract said it "names
the access cells that may see the measure". A declared measure is a figure about a program, and the
program check (`can_view_program`) says only that the caller is on the program, not that the caller
may see THIS kind of figure. A cell here is a DOMAIN (the matrix is persona x domain; a row's list
holds domains). Now the row's cells are what the verb registers under, and the engine refuses a caller
who holds none of them: on `/measure/{fn}`, on `/package_export` (before any panel is measured), on
`/cdrl_export` (before anything is built), and on `/artifact/{name}` for a CDRL file (which holds the
same figures). A built-in verb is not gated and asks the directory nothing.

The control in every arm: the same caller, the same program, the same double; only the row's cells
differ. The directory is the real `entitled_domains` over an `httpx.MockTransport` that serves real
`httpx.Response`s and records the requests it was sent.

Arms: a registration, b /measure, c order (program first), d outage on four routes, e package,
f cdrl_export, g artifact, h built-in ungated, i the BFF relay, j `caller` has no default, plus the
pin: `entitled_domains` sends the gateway client's requests.

Run: uv run --no-sync pytest tests/finance/test_a_measure_row_cells_are_enforced.py -q
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.finance_agent import cdrl, export_profiles, measures, seed  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.utils import entitled_domains as eds  # noqa: E402

SAMPLE = REPO / "policy" / "overlays" / "sample" / "measure_verbs"
PROFILES_DIR = REPO / "policy" / "overlays" / "sample" / "fin_export_profiles"
PROGRAM = seed.PROGRAM_ID
ALICE, BOB, CAROL = "alice@example.com", "bob@example.com", "carol@example.com"
CELL, OTHER = "PROGRAM_FINANCE", "SOME_OTHER_DOMAIN"
PROFILE = "cdrl_a001_ev_summary"
DIRECTORY = "http://topaz.test"
BUILTIN = "fin_performance_indices"


# -- the directory: real httpx.Responses over a recording transport ----------------------------

class Directory:
    """`held[user]` = the domains that user holds, served as the Directory v3 relations the gateway
    client reads: user -> member -> group, group -> assumable_by -> `<PERSONA>:<DOMAIN>` cells."""

    def __init__(self):
        self.held: dict[str, set[str]] = {}
        self.requests: list[tuple[str, dict]] = []
        self.down = False
        self.pages = 1

    def handler(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.requests.append((request.url.path, params))
        if self.down:
            return httpx.Response(500, json={"error": "directory down"}, request=request)
        if params.get("relation") == "member":
            user = params["subject_id"]
            results = [{"object_type": "group", "object_id": f"g:{user}"}] if user in self.held else []
            return httpx.Response(200, json={"results": results, "page": {}}, request=request)
        group = params["subject_id"]
        user = group.split(":", 1)[1]
        cells = [f"PERSONA:{d}" for d in sorted(self.held.get(user, ()))]
        # `pages` > 1 serves the cells one per page, to make a client that drops pagination lose some
        page = int(params.get("page.token") or 0)
        if self.pages > 1 and len(cells) > 1:
            body = {"results": [{"object_id": cells[page]}],
                    "page": {"next_token": str(page + 1) if page + 1 < len(cells) else ""}}
        else:
            body = {"results": [{"object_id": c} for c in cells], "page": {}}
        return httpx.Response(200, json=body, request=request)

    def asked_about_cells(self) -> list[dict]:
        return [p for _path, p in self.requests if p.get("object_type") == "cell"]


@pytest.fixture
def directory(monkeypatch):
    d = Directory()
    d.held = {ALICE: {CELL}, BOB: {OTHER}, CAROL: {CELL}}
    real_client = httpx.Client

    def client(*a, **k):
        return real_client(*a, transport=httpx.MockTransport(d.handler), **k)

    monkeypatch.setattr(eds, "httpx", SimpleNamespace(Client=client))
    monkeypatch.setenv("TOPAZ_DIRECTORY_URL", DIRECTORY)
    monkeypatch.setattr(engine, "entitled_domains", eds.entitled_domains)
    return d


class Program:
    """The program double: ALICE and BOB are on the program; CAROL holds the cell and is not."""

    def __init__(self):
        self.calls = []

    def __call__(self, program, caller_id, **kw):
        self.calls.append((program, caller_id))
        return (program, caller_id) in {(PROGRAM, ALICE), (PROGRAM, BOB)}


@pytest.fixture
def program(monkeypatch):
    p = Program()
    monkeypatch.setattr(engine, "can_view_program", p)
    return p


def _rows(tmp_path, monkeypatch, tcpi_cells=(CELL,), vac_cells=(CELL,)):
    d = tmp_path / "ov"
    d.mkdir(exist_ok=True)
    for name, cells in (("fin_tcpi.yaml", tcpi_cells), ("fin_vac.yaml", vac_cells)):
        raw = yaml.safe_load((SAMPLE / name).read_text(encoding="utf-8"))
        raw["policy"]["cells"] = list(cells)
        (d / name).write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(d))
    rows = engine._load_declared()
    monkeypatch.setattr(engine, "DECLARED", rows)
    monkeypatch.setitem(engine.VERB_TO_FN, "mesh:finToCompletePerformanceIndex", "fin_tcpi")
    return rows


def _measure(c, fn, user=ALICE):
    return c.post(f"/measure/{fn}", json={"params": {"program_id": PROGRAM}, "user_email": user})


def _client():
    return TestClient(engine.app)


# -- a: registration ---------------------------------------------------------------------------

def test_a_a_declared_verb_registers_under_exactly_its_rows_cells(tmp_path, monkeypatch):
    _rows(tmp_path, monkeypatch, tcpi_cells=[OTHER])
    by_ep = {c["endpoint_url"].rsplit("/", 1)[-1]: c for c in engine._registration_calls("http://e")}
    assert list(by_ep["fin_tcpi"]["domains"]) == [OTHER]          # the row's, not this engine's
    assert list(by_ep["fin_vac_cpi"]["domains"]) == [CELL]        # the control: its row says CELL


def test_a_built_ins_keep_the_engines_domains(tmp_path, monkeypatch):
    _rows(tmp_path, monkeypatch, tcpi_cells=[OTHER])
    built_in = [c for c in engine._registration_calls("http://e")
                if c["endpoint_url"].rsplit("/", 1)[-1] not in engine.DECLARED]
    assert built_in
    assert all(list(c["domains"]) == engine.DOMAINS for c in built_in)


# -- b: /measure -------------------------------------------------------------------------------

def test_b_a_caller_outside_the_rows_cells_is_refused_and_inside_is_served(
        tmp_path, monkeypatch, directory, program):
    _rows(tmp_path, monkeypatch, tcpi_cells=[CELL], vac_cells=[OTHER])
    with _client() as c:
        ok = _measure(c, "fin_tcpi")
        assert ok.status_code == 200, ok.text                      # the control: same caller, program
        r = _measure(c, "fin_vac_cpi")
    assert r.status_code == 403, r.text
    d = r.json()["detail"]
    assert d["error"] == "measure_not_in_cell" and d["measure"] == "fin_vac_cpi"
    assert d["missing_domains"] == [OTHER]
    assert d["refusal"]["policy_id"] == "groups" and d["refusal"]["candidates"] == []
    assert OTHER in d["refusal"]["missing_binding"]
    assert BOB not in json.dumps(d) and "grantable_by" not in d["refusal"]   # never who else holds it


def test_b_the_cell_comparison_is_case_blind(tmp_path, monkeypatch, directory, program):
    _rows(tmp_path, monkeypatch, tcpi_cells=["program_finance"])
    directory.held[ALICE] = {"Program_Finance"}
    with _client() as c:
        assert _measure(c, "fin_tcpi").status_code == 200


def test_b_a_misspelt_cell_denies_everyone(tmp_path, monkeypatch, directory, program):
    _rows(tmp_path, monkeypatch, tcpi_cells=["PROGRAM_FINANCEE"])
    with _client() as c:
        assert _measure(c, "fin_tcpi").status_code == 403


def test_b_a_service_holds_no_cell_and_asks_the_directory_nothing(tmp_path, monkeypatch, directory):
    # `_can_view` already refuses a `svc:` caller on the program; the cell gate agrees on its own.
    _rows(tmp_path, monkeypatch)
    for who in ("svc:supervisor", ""):
        with pytest.raises(engine.HTTPException) as ei:
            engine._require_cell("fin_tcpi", who)
        assert ei.value.status_code == 403 and ei.value.detail["error"] == "measure_not_in_cell"
    assert directory.requests == []


# -- c: the order ------------------------------------------------------------------------------

def test_c_a_caller_with_the_cell_and_not_the_program_gets_program_not_visible(
        tmp_path, monkeypatch, directory, program):
    _rows(tmp_path, monkeypatch)
    with _client() as c:
        r = _measure(c, "fin_tcpi", user=CAROL)
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "program_not_visible"
    assert directory.requests == [], "a caller outside the program learns nothing about cells"
    assert program.calls == [(PROGRAM, CAROL)]


# -- d: outage, four routes --------------------------------------------------------------------

def _package_body(builtin_only=False):
    panels = [{"panel": 0, "verb": "mesh:finPerformanceIndices", "params": {"program_id": PROGRAM}}]
    if not builtin_only:
        panels.append({"panel": 1, "verb": "mesh:finToCompletePerformanceIndex",
                       "params": {"program_id": PROGRAM}})
    return {"user_email": ALICE, "recipient_scope": f"program_office.{PROGRAM}",
            "canvas": {"template_id": "program_finance", "template_hash": "h", "panels": panels}}


@pytest.fixture
def package_stubs(monkeypatch):
    built: list[dict] = []

    class _Builder:
        @staticmethod
        def build(**kw):
            built.append(kw)
            return {"manifest": {"panels": kw["panels"], "as_of": "2026-01-01",
                                 "recipient_scope": kw["recipient_scope"],
                                 "algorithm_sha": kw["sha"], "template_id": kw["template_id"],
                                 "template_hash": kw["template_hash"]},
                    "html_sha256": "sha256:" + "a" * 64, "html_bytes": 1,
                    "duckdb_sha256": "sha256:" + "a" * 64}

    monkeypatch.setattr(engine, "_repo_root", lambda: REPO)
    monkeypatch.setitem(sys.modules, "build_fin_package", _Builder)
    monkeypatch.setattr("build_cost_package.algorithm_sha", lambda: "0" * 40)
    return built


@pytest.fixture
def profiles(monkeypatch):
    monkeypatch.setenv("FIN_EXPORT_PROFILE_OVERLAY_DIRS", str(PROFILES_DIR))

    def load():
        p = {x.name: x for x in export_profiles.load_export_profiles(declared=engine.DECLARED)}
        monkeypatch.setattr(engine, "PROFILES", p)
        return p
    return load


def _cdrl(c, user=ALICE):
    return c.post("/cdrl_export", json={"profile": PROFILE, "program_id": PROGRAM, "user_email": user})


def test_d_a_directory_outage_is_a_503_on_every_route_never_a_200_or_a_403(
        tmp_path, monkeypatch, directory, program, package_stubs, profiles):
    _rows(tmp_path, monkeypatch)
    profiles()
    root = tmp_path / "root"
    root.mkdir()
    cdrl_root = root
    with _client() as c:
        # the control: the directory up, the same four requests served
        assert _measure(c, "fin_tcpi").status_code == 200
        assert c.post("/package_export", json=_package_body()).status_code == 200
        monkeypatch.setattr(engine, "_repo_root", lambda: cdrl_root)
        made = _cdrl(c)
        assert made.status_code == 200, made.text
        name = made.json()["artifact_filename"]
        monkeypatch.setattr(engine, "_current_caller", lambda: SimpleNamespace(authz_id=ALICE))
        assert c.get(f"/artifact/{name}").status_code == 200

        directory.down = True
        monkeypatch.setattr(engine, "_repo_root", lambda: REPO)
        got = {
            "measure": _measure(c, "fin_tcpi"),
            "package": c.post("/package_export", json=_package_body()),
        }
        monkeypatch.setattr(engine, "_repo_root", lambda: cdrl_root)
        got["cdrl"] = _cdrl(c)
        got["artifact"] = c.get(f"/artifact/{name}")
    for route, r in got.items():
        assert r.status_code == 503, (route, r.status_code, r.text)
    assert len(package_stubs) == 1, "the outage must stop the package before it is built"


def test_d_a_transport_failure_is_also_a_503(tmp_path, monkeypatch, directory, program):
    _rows(tmp_path, monkeypatch)

    def boom(request):
        raise httpx.ConnectError("no route to host", request=request)
    directory.handler = boom
    with _client() as c:
        assert _measure(c, "fin_tcpi").status_code == 503


# -- e: /package_export ------------------------------------------------------------------------

@pytest.fixture
def spy(monkeypatch):
    calls: list[str] = []
    real = engine._measure_envelope

    def wrapped(fn, params, **kw):
        calls.append(fn)
        return real(fn, params, **kw)
    monkeypatch.setattr(engine, "_measure_envelope", wrapped)
    return calls


def test_e_a_panel_outside_the_callers_cells_refuses_the_package_and_measures_nothing(
        tmp_path, monkeypatch, directory, program, package_stubs, spy):
    _rows(tmp_path, monkeypatch, tcpi_cells=[OTHER])
    with _client() as c:
        r = c.post("/package_export", json=_package_body())
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "measure_not_in_cell"
    assert spy == [], f"a panel was measured before the refusal: {spy}"
    assert package_stubs == []


def test_e_the_control_same_caller_and_canvas_with_the_cell_held_is_built(
        tmp_path, monkeypatch, directory, program, package_stubs, spy):
    _rows(tmp_path, monkeypatch, tcpi_cells=[CELL])
    with _client() as c:
        r = c.post("/package_export", json=_package_body())
    assert r.status_code == 200, r.text
    assert sorted(spy) == ["fin_performance_indices", "fin_tcpi"]
    assert len(package_stubs) == 1 and len(package_stubs[0]["panels"]) == 2


# -- f: /cdrl_export ---------------------------------------------------------------------------

@pytest.fixture
def cdrl_world(tmp_path, monkeypatch, profiles):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(engine, "_repo_root", lambda: root)
    return root / "dist", profiles


def test_f_a_source_outside_the_callers_cells_refuses_the_export_and_writes_nothing(
        tmp_path, monkeypatch, directory, program, cdrl_world, spy):
    dist, profiles = cdrl_world
    _rows(tmp_path, monkeypatch, tcpi_cells=[OTHER])
    profiles()
    built = []
    real_build = cdrl.build_cdrl
    monkeypatch.setattr(cdrl, "build_cdrl", lambda *a, **k: built.append(1) or real_build(*a, **k))
    with _client() as c:
        r = _cdrl(c)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "measure_not_in_cell"
    assert r.json()["detail"]["measure"] == "fin_tcpi"
    assert not built, "the build started before the refusal"
    assert spy == [], f"a source was measured before the refusal: {spy}"
    assert not dist.exists() or not list(dist.iterdir()), "a file was written"


def test_f_the_control_same_caller_and_profile_with_the_cell_held_is_built(
        tmp_path, monkeypatch, directory, program, cdrl_world):
    dist, profiles = cdrl_world
    _rows(tmp_path, monkeypatch, tcpi_cells=[CELL])
    profiles()
    with _client() as c:
        r = _cdrl(c)
    assert r.status_code == 200, r.text
    assert (dist / r.json()["artifact_filename"]).is_file()


# -- g: /artifact ------------------------------------------------------------------------------

def test_g_a_program_viewer_outside_the_cell_cannot_fetch_the_file_another_caller_built(
        tmp_path, monkeypatch, directory, program, cdrl_world):
    dist, profiles = cdrl_world
    _rows(tmp_path, monkeypatch, tcpi_cells=[CELL])
    profiles()
    with _client() as c:
        made = _cdrl(c, user=ALICE)
        assert made.status_code == 200, made.text
        name = made.json()["artifact_filename"]
        monkeypatch.setattr(engine, "_current_caller", lambda: SimpleNamespace(authz_id=BOB))
        asked_before = len(directory.requests)
        r = c.get(f"/artifact/{name}")
        assert r.status_code == 403, r.status_code
        assert r.json()["detail"]["error"] == "measure_not_in_cell"
        assert len(directory.requests) > asked_before          # BOB was on the program: the cell was asked
        monkeypatch.setattr(engine, "_current_caller", lambda: SimpleNamespace(authz_id=ALICE))
        ok = c.get(f"/artifact/{name}")                        # the control: the permitted caller
        assert ok.status_code == 200 and ok.content == (dist / name).read_bytes()
        # the closed set stays first: a name in no profile is a 404 and asks the directory nothing
        n = len(directory.requests)
        monkeypatch.setattr(engine, "_current_caller", lambda: SimpleNamespace(authz_id=BOB))
        assert c.get("/artifact/fin-cdrl-nope-NOPE.xlsx").status_code == 404
        assert len(directory.requests) == n


def test_g_the_origin_names_the_profile_as_well_as_the_program(tmp_path, monkeypatch, profiles):
    _rows(tmp_path, monkeypatch)
    p = profiles()
    name = cdrl.artifact_filename(PROFILE, PROGRAM, p[PROFILE].format)
    origin = engine._cdrl_artifact_origin(name)
    assert origin is not None and origin[0].name == PROFILE and origin[1] == PROGRAM
    assert engine._cdrl_artifact_program(name) == PROGRAM
    assert engine._cdrl_artifact_origin("fin-cdrl-nope-NOPE.xlsx") is None


# -- h: a built-in is not gated ----------------------------------------------------------------

def test_h_a_built_in_verb_asks_the_directory_nothing_for_a_caller_in_no_cell(
        tmp_path, monkeypatch, directory, program):
    _rows(tmp_path, monkeypatch)
    with _client() as c:
        r = _measure(c, BUILTIN, user=BOB)                      # BOB holds only OTHER
        assert r.status_code == 200, r.text
        assert directory.requests == []
        assert _measure(c, "fin_tcpi", user=BOB).status_code == 403   # the control: a declared one
    assert directory.requests, "the declared row did ask"


# -- i: the BFF relay --------------------------------------------------------------------------

REFUSAL = {"error": "measure_not_in_cell", "measure": "fin_tcpi",
           "refusal": {"policy_id": "groups",
                       "missing_binding": f"a_group_granting(<persona>, {CELL})", "candidates": []},
           "missing_domains": [CELL], "message": "fin_tcpi is declared for the access cells."}


def _engines_own_403(tmp_path, monkeypatch, directory, program):
    _rows(tmp_path, monkeypatch, tcpi_cells=[OTHER])
    with _client() as c:
        r = _measure(c, "fin_tcpi")
    assert r.status_code == 403
    return r.json()["detail"]


def test_i_the_bff_relays_the_engines_403_completed_with_a_grantor(
        tmp_path, monkeypatch, directory, program):
    from src.iagent import gateway
    from tests.finance.test_the_bff_relays_finance_measure import _User

    sent = _engines_own_403(tmp_path, monkeypatch, directory, program)
    assert sent["refusal"] == {k: REFUSAL["refusal"][k] for k in ("policy_id", "candidates")} | {
        "missing_binding": sent["refusal"]["missing_binding"]}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            req = httpx.Request("POST", url)
            return httpx.Response(403, content=__import__("json").dumps({"detail": sent}).encode(),
                                  headers={"content-type": "application/json"}, request=req)

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User()
    try:
        with TestClient(gateway.app) as bff:
            r = bff.post("/finance/measure/fin_tcpi", json={"params": {"program_id": PROGRAM}},
                         headers={"Authorization": "Bearer t"})
    finally:
        gateway.app.dependency_overrides.clear()
    assert r.status_code == 403, r.text
    d = r.json()["detail"]
    assert d["error"] == "measure_not_in_cell" and d["measure"] == "fin_tcpi"
    assert d["refusal"]["policy_id"] == "groups"
    assert d["refusal"]["missing_binding"] == sent["refusal"]["missing_binding"]
    assert "grantable_by" in d["refusal"], "the BFF names the grantor; the engine cannot"


def test_i_the_cdrl_route_relays_it_too():
    from src.iagent import gateway
    failure = gateway._engine_failure("fin", SimpleNamespace(
        status_code=403, json=lambda: {"detail": REFUSAL}, text=""), "/cdrl_export")
    assert failure.status_code == 403
    assert failure.detail["error"] == "measure_not_in_cell"
    assert "grantable_by" in failure.detail["refusal"]


# -- j: the signature --------------------------------------------------------------------------

def test_j_caller_is_a_required_keyword_on_the_envelope_and_the_cdrl_source():
    for fn in (engine._measure_envelope, engine._cdrl_source):
        p = inspect.signature(fn).parameters["caller"]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, fn.__name__
        assert p.default is inspect.Parameter.empty, f"{fn.__name__}: caller has a default"


def test_j_an_envelope_asked_for_without_a_cell_refuses_by_itself(tmp_path, monkeypatch, directory):
    _rows(tmp_path, monkeypatch, tcpi_cells=[OTHER])
    with pytest.raises(engine.HTTPException) as ei:
        engine._measure_envelope("fin_tcpi", {"program_id": PROGRAM}, caller=ALICE)
    assert ei.value.status_code == 403 and ei.value.detail["error"] == "measure_not_in_cell"


# -- the pin: this module asks the directory what the gateway's client asks --------------------

def _gateway_requests(user, d):
    from src.iagent.authz.topaz_client import TopazDirectoryClient
    client = TopazDirectoryClient(DIRECTORY)
    client._client = httpx.Client(base_url=DIRECTORY, transport=httpx.MockTransport(d.handler))
    cells = client.get_entitlements(user).cells
    return {c.domain.upper() for c in cells}


@pytest.mark.parametrize("pages", [1, 3])
def test_the_engine_asks_the_directory_what_the_gateway_client_asks(directory, pages):
    directory.held[ALICE] = {"AA", "BB", "CC"}
    directory.pages = pages
    directory.requests.clear()
    gateway_domains = _gateway_requests(ALICE, directory)
    gateway_requests = list(directory.requests)
    directory.requests.clear()
    engine_domains = engine.entitled_domains(ALICE)
    assert engine_domains == gateway_domains == {"AA", "BB", "CC"}
    assert directory.requests == gateway_requests, "the engine's requests drifted from the gateway's"
    if pages > 1:
        assert any("page.token" in p for _path, p in gateway_requests), "the pin never paged"


def test_the_engine_reads_a_404_as_empty_and_an_unconfigured_directory_as_a_deny(directory, monkeypatch):
    directory.handler = lambda request: httpx.Response(404, json={}, request=request)
    assert engine.entitled_domains(ALICE) == frozenset()
    monkeypatch.delenv("TOPAZ_DIRECTORY_URL")
    assert eds.entitled_domains(ALICE) == frozenset()
    assert eds.entitled_domains("") == frozenset()
