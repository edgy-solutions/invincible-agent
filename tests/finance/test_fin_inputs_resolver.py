"""The finance inputs resolver (docs/plans/fin-inputs-resolver.md): behind `FIN_DATASET_URN`, a
declared measure computes over rows read, as the caller, from one catalogued asset. Unset, the
seed answers exactly as before.

Real polars frames throughout. The mesh client is replaced at ONE seam, `asset_inputs._load_client`
(never by writing `sys.modules`), with a double that records how it was built. The real client's
behaviour is pinned elsewhere (`test_the_resolver_speaks_the_real_client.py`, which needs the
pinned dag-tools).

Run: uv run --no-sync pytest tests/finance/test_fin_inputs_resolver.py
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

pl = pytest.importorskip("polars")
jwt = pytest.importorskip("jwt")

from fastapi.testclient import TestClient  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.finance_agent import asset_inputs, measure_verbs, seed  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent.entities import FISCAL_PERIODS, NotInModel  # noqa: E402

SAMPLE = REPO / "policy" / "overlays" / "sample" / "measure_verbs"
PROFILES_DIR = REPO / "policy" / "overlays" / "sample" / "fin_export_profiles"
PROGRAM = seed.PROGRAM_ID
OTHER_PROGRAM = "NP-OTHER"
ALICE = "alice@example.com"
URN = "urn:li:dataset:(urn:li:dataPlatform:file,fin_test_asset,TEST)"
BANNER = "SYNTHETIC TEST ASSET - not a real program."
GATEWAY = "http://gateway.test"
PREFIX = "a governed finance read requires the caller's id"
SECRET = "hunter2-fake-credential"


class NotEntitled(Exception):
    pass


class MeshUnavailable(Exception):
    pass


# ── the seam double ─────────────────────────────────────────────────────────────────────

class Seam:
    """Replaces `asset_inputs._load_client`. Records every call and how the client was built."""

    def __init__(self):
        self.loads = 0
        self.kwargs: list[dict] = []
        self.urns: list[str] = []
        self.frame = None
        self.raises: Exception | None = None
        seam = self

        class Client:
            def __init__(self, **kw):
                seam.kwargs.append(kw)

            def get_dataframe(self, urn):
                seam.urns.append(urn)
                if seam.raises is not None:
                    raise seam.raises
                return seam.frame

        self.Client = Client

    def load(self):
        self.loads += 1
        return self.Client, NotEntitled, MeshUnavailable


def token(email: str) -> str:
    return jwt.encode({"email": email}, "k", algorithm="HS256")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("FIN_DATASET_URN", "FIN_DATASET_BANNER", "FIN_ASSET_MAX_ROWS", "CENTRAL_GATEWAY_URL",
              "MESH_JWT_PUBLIC_KEY", "KEYCLOAK_PUBLIC_KEY", "REQUIRE_TRANSPORT_AUTH",
              "MEASURE_VERB_OVERLAY_DIRS"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def declared(monkeypatch):
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(SAMPLE))
    rows = engine._load_declared()
    monkeypatch.setattr(engine, "DECLARED", rows)
    monkeypatch.setitem(engine.VERB_TO_FN, "mesh:finToCompletePerformanceIndex", "fin_tcpi")
    return rows


@pytest.fixture
def members(monkeypatch):
    monkeypatch.setattr(engine, "can_view_program",
                        lambda program, caller_id, **kw: (program, caller_id) == (PROGRAM, ALICE)
                        or (program, caller_id) == (OTHER_PROGRAM, ALICE))


@pytest.fixture
def seam(monkeypatch):
    s = Seam()
    monkeypatch.setattr(engine.asset_inputs, "_load_client", s.load)
    return s


@pytest.fixture
def flag(monkeypatch):
    monkeypatch.setenv("FIN_DATASET_URN", URN)
    monkeypatch.setenv("FIN_DATASET_BANNER", BANNER)
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", GATEWAY)


@pytest.fixture
def on(declared, members, seam, flag):
    """The flag set, the declared rows loaded, the seam in place. A fixture that boots the app
    asks for this first, so the boot check sees the environment."""
    return seam


@pytest.fixture
def client(on):
    with TestClient(engine.app) as c:
        on.loads = 0  # the boot check loaded the client once; count from the first request
        yield c


@pytest.fixture
def off_client(declared, members, monkeypatch):
    def boom():
        raise AssertionError("the flag is off: nothing may load the mesh client")
    monkeypatch.setattr(engine.asset_inputs, "_load_client", boom)
    with TestClient(engine.app) as c:
        yield c


class Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture
def logs():
    g = Grab()
    targets = [logging.getLogger(), asset_inputs.log]
    for t in targets:
        t.addHandler(g)
    yield g
    for t in targets:
        t.removeHandler(g)


# ── frames ──────────────────────────────────────────────────────────────────────────────

def frame_of(state=None):
    s = state or seed.build_seed()
    ca_of = {w.wp_id: w.ca_id for w in s.work_packages}
    prog = s.programs[0]
    return pl.DataFrame([
        {"program_id": prog.program_id, "program_name": prog.name, "program_bac": prog.bac,
         "control_account": ca_of[f.wp_id], "work_package": f.wp_id, "period": f.period,
         "bcws": f.bcws, "bcwp": f.bcwp, "acwp": f.acwp}
        for f in s.facts
    ])


def measure(c, fn="fin_tcpi", *, tok=token(ALICE), params=None, body_user=ALICE):
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    return c.post(f"/measure/{fn}", headers=headers, json={
        "params": params if params is not None else {"program_id": PROGRAM}, "user_email": body_user})


def seed_rows(declared, window=None):
    return {fn: measure_verbs.run_declared(seed.build_seed(), r, program_id=PROGRAM, window=window)
            for fn, r in declared.items()}


def seed_figures(declared):
    out = set()
    for rows in seed_rows(declared).values():
        for r in rows:
            out |= {v for v in r["inputs"].values() if len(v) >= 6}
    assert out
    return out


def same_figures(a, b):
    assert len(a) == len(b)
    for x, y in zip(a, b):
        assert x["period"] == y["period"] and x["scope_label"] == y["scope_label"]
        assert {k: Decimal(v) for k, v in x["inputs"].items()} == {k: Decimal(v) for k, v in y["inputs"].items()}
        extra = set(x) - {"inputs"}
        assert {k: x[k] for k in extra} == {k: y[k] for k in extra}


# ── flag off ────────────────────────────────────────────────────────────────────────────

def test_flag_off_the_seam_is_never_called_and_the_envelope_is_the_old_shape(off_client, declared):
    for fn in sorted(declared):
        r = measure(off_client, fn)
        assert r.status_code == 200, r.text
        env = r.json()
        assert "data_source" not in env
        assert env["data_provenance"] == seed.notional_banner()
        assert [k for k in env] == [k for k in (
            "measure", "output_uri", "artifact_id", "value_label", "series", "render",
            "reference", "data_provenance", "method", "verdict", "rows") if k in env]
        assert env["rows"], "the control must have figures to compare"
    # no bearer at all is fine when the flag is off: nothing reads as anyone
    assert measure(off_client, tok=None).status_code == 200


# ── same figures ────────────────────────────────────────────────────────────────────────

WINDOWS = [None, ["FY26-02", "FY26-03", "FY26-05"]]


@pytest.mark.parametrize("window", WINDOWS, ids=["no-window", "subset-window"])
def test_every_declared_row_computes_the_same_figures_over_rows_as_over_the_seed(declared, window):
    assert set(declared) >= {"fin_tcpi", "fin_vac_cpi"}
    state = asset_inputs.state_from_rows(frame_of(), PROGRAM)
    for fn, row in declared.items():
        got = measure_verbs.run_declared(state, row, program_id=PROGRAM, window=window)
        want = measure_verbs.run_declared(seed.build_seed(), row, program_id=PROGRAM, window=window)
        assert got, fn
        same_figures(got, want)


def test_a_source_with_float_amounts_changes_the_audit_strings_and_no_figure(declared):
    """A real source may hold every amount as a float. The strings then read 12000000.0, and the values are equal."""
    floats = frame_of().with_columns(pl.col(c).cast(pl.Float64) for c in asset_inputs.NUMERIC_COLUMNS)
    state = asset_inputs.state_from_rows(floats, PROGRAM)
    changed = 0
    for fn, row in declared.items():
        got = measure_verbs.run_declared(state, row, program_id=PROGRAM)
        want = measure_verbs.run_declared(seed.build_seed(), row, program_id=PROGRAM)
        assert len(got) == len(want) and got, fn
        changed += got != want
        for g, w in zip(got, want):
            assert g.keys() == w.keys()
            assert {k: Decimal(v) for k, v in g["inputs"].items()} == {k: Decimal(v) for k, v in w["inputs"].items()}
            for k in g.keys() - {"inputs"}:
                if k.endswith("_exact"):
                    assert Decimal(g[k]) == Decimal(w[k]), k
                else:
                    assert g[k] == w[k], k
    assert changed, "every amount is a float here, so some audit string must read differently"


def test_the_same_figures_seal_can_fail(declared):
    df = frame_of()
    bumped = df.with_columns(
        pl.when(pl.int_range(pl.len()) == 0).then(pl.col("acwp") + 1).otherwise(pl.col("acwp")).alias("acwp"))
    state = asset_inputs.state_from_rows(bumped, PROGRAM)
    row = declared["fin_tcpi"]
    got = measure_verbs.run_declared(state, row, program_id=PROGRAM)
    want = measure_verbs.run_declared(seed.build_seed(), row, program_id=PROGRAM)
    with pytest.raises(AssertionError):
        same_figures(got, want)


def test_the_route_over_a_parquet_asset_answers_the_seeds_figures(client, seam, declared, tmp_path):
    path = tmp_path / "fin.parquet"
    frame_of().write_parquet(path)
    seam.frame = pl.scan_parquet(path)
    for fn in sorted(declared):
        r = measure(client, fn)
        assert r.status_code == 200, r.text
        same_figures(r.json()["rows"], json.loads(json.dumps(seed_rows(declared)[fn], default=str)))


# ── the window keeps BAC ────────────────────────────────────────────────────────────────

def test_dropping_a_work_package_from_the_window_does_not_move_the_programs_bac(declared):
    df = frame_of()
    dropped_wp = df["work_package"][0]
    full = asset_inputs.state_from_rows(df, PROGRAM)
    short = asset_inputs.state_from_rows(df.filter(pl.col("work_package") != dropped_wp), PROGRAM)
    for fn in ("fin_tcpi", "fin_vac_cpi"):
        a = measure_verbs.run_declared(full, declared[fn], program_id=PROGRAM)
        b = measure_verbs.run_declared(short, declared[fn], program_id=PROGRAM)
        assert [r["inputs"]["bac"] for r in a] == [r["inputs"]["bac"] for r in b]
        assert {Decimal(r["inputs"]["bac"]) for r in b} == {Decimal(str(seed.build_seed().programs[0].bac))}
        assert [r["inputs"]["bcwp"] for r in a] != [r["inputs"]["bcwp"] for r in b], "the drop must be real"


# ── the filter is real ──────────────────────────────────────────────────────────────────

def _two_program_parquet(tmp_path):
    df = frame_of()
    other = df.with_columns(pl.lit(OTHER_PROGRAM).alias("program_id"),
                            pl.lit("Other").alias("program_name"),
                            (pl.col("program_bac") + 7).alias("program_bac"),
                            (pl.col("bcws") + 3).alias("bcws"))
    wide = pl.concat([df, other]).with_columns(pl.lit("must-not-be-read").alias("extra_column"))
    path = tmp_path / "two.parquet"
    wide.write_parquet(path)
    return path, df


def test_the_read_collects_only_the_asked_program_and_only_the_contract_columns(tmp_path):
    path, df = _two_program_parquet(tmp_path)
    got = asset_inputs.read_rows(lambda urn: pl.scan_parquet(path), URN, PROGRAM, None)
    assert got.columns == list(asset_inputs.COLUMNS)
    assert set(got["program_id"]) == {PROGRAM} and got.height == df.height
    assert "extra_column" not in got.columns
    windowed = asset_inputs.read_rows(lambda urn: pl.scan_parquet(path), URN, PROGRAM, ["FY26-02"])
    assert set(windowed["period"]) == {"FY26-02"} and set(windowed["program_id"]) == {PROGRAM}


def test_the_route_blends_nothing_from_a_second_program(client, seam, declared, tmp_path):
    path, _ = _two_program_parquet(tmp_path)
    seam.frame = pl.scan_parquet(path)
    r = measure(client)
    assert r.status_code == 200, r.text
    same_figures(r.json()["rows"], json.loads(json.dumps(seed_rows(declared)["fin_tcpi"], default=str)))
    r2 = measure(client, params={"program_id": OTHER_PROGRAM})
    assert r2.status_code == 200
    assert Decimal(r2.json()["rows"][0]["inputs"]["bac"]) == Decimal(seed.build_seed().programs[0].bac) + 7


def test_a_frame_that_forgot_its_filter_is_refused_not_blended(tmp_path):
    path, _ = _two_program_parquet(tmp_path)
    unfiltered = pl.read_parquet(path).select(list(asset_inputs.COLUMNS))
    with pytest.raises(asset_inputs.ContractViolation) as ei:
        asset_inputs.state_from_rows(unfiltered, PROGRAM)
    assert ei.value.rule == "other_program_rows"


# ── the client's construction ───────────────────────────────────────────────────────────

def test_the_client_is_built_with_the_env_gateway_the_caller_and_the_bearer_only(client, seam, tmp_path):
    seam.frame = frame_of().lazy()
    tok = token(ALICE)
    assert measure(client, tok=tok).status_code == 200
    assert len(seam.kwargs) == 1 and seam.urns == [URN]
    kw = seam.kwargs[0]
    assert kw == {"broker_url": GATEWAY, "originator_email": ALICE, "jwt_token": tok}
    assert not {"client_id", "client_secret", "originator_sub"} & set(kw)


def test_the_body_never_names_who_the_read_is_for(client, seam):
    seam.frame = frame_of().lazy()
    assert measure(client, tok=token(ALICE), body_user="mallory@example.com").status_code in (200, 403)
    assert all(k["originator_email"] == ALICE for k in seam.kwargs)


# ── identity ────────────────────────────────────────────────────────────────────────────

class _Refusing:
    authz_id = ALICE

    def require_authz_id(self):
        raise PermissionError("caller identity unresolved")


@pytest.mark.parametrize("case", ["no-bearer", "service-bearer-names-a-user", "unresolved-bearer",
                                  "require-authz-id-raises"])
def test_an_identity_that_is_not_a_person_is_a_401_and_no_client_is_built(client, seam, monkeypatch, case):
    seam.frame = frame_of().lazy()
    if case == "no-bearer":
        r = measure(client, tok=None)
    elif case == "service-bearer-names-a-user":
        r = measure(client, tok=token("svc:supervisor"), body_user=ALICE)
    elif case == "unresolved-bearer":
        r = measure(client, tok="not-a-jwt")
    else:
        monkeypatch.setattr(engine, "_current_caller", lambda: _Refusing())
        r = measure(client, tok=token(ALICE))
    assert r.status_code == 401, r.text
    assert r.json()["detail"].startswith(PREFIX)
    assert seam.kwargs == [] and seam.urns == [] and seam.loads == 0


# ── the outcome table ───────────────────────────────────────────────────────────────────

def test_not_entitled_is_a_403_that_names_the_grant_and_carries_no_figure(client, seam, declared, logs):
    seam.raises = NotEntitled(f"the gate refused ({SECRET})")
    r = measure(client)
    assert r.status_code == 403, r.text
    d = r.json()["detail"]
    assert d["status"] == "access_denied" and d["denied_assets"] == [URN] and d["subject"] == ALICE
    assert d["message"]
    assert d["refusal"] == {"policy_id": "asset_grants", "missing_binding": f"reader({URN})",
                            "candidates": []}
    assert not any(f in r.text for f in seed_figures(declared))
    assert SECRET not in r.text and SECRET not in " ".join(logs.lines)


def test_the_denial_this_engine_sends_opens_request_access_on_the_chat_path(client, seam):
    """The join, on the engine's own body. The supervisor relays a refusal-bearing 403 as a refusal
    dict, and the request-access flow is keyed on what that dict still carries."""
    requests = pytest.importorskip("requests")
    from src.iagent.defs import dynamic_supervisor as ds

    seam.raises = NotEntitled("the gate refused")
    answer = measure(client)
    assert answer.status_code == 403, answer.text
    wire = requests.Response()
    wire.status_code = answer.status_code
    wire._content = answer.content

    events = []

    class Ctx:
        class log:
            info = error = staticmethod(lambda *a, **k: None)

        log_event = staticmethod(events.append)

    relayed = ds._refusal_from_engine_4xx(Ctx(), "http://engine-fin/measure/fin_tcpi", wire)
    assert relayed["refused"] is True
    ds._log_subtask_access_denied_asset(Ctx(), engine_response=relayed, sub_query="q")
    assert [e.asset_key.path for e in events] == [["subtask_access_denied"]]
    metadata = events[0].metadata
    assert json.loads(metadata["denied_assets_json"].value) == [URN]
    assert metadata["subject"].value == ALICE
    assert metadata["message"].value == answer.json()["detail"]["message"]


def test_mesh_unavailable_is_a_503_and_its_text_reaches_neither_the_answer_nor_the_log(
        client, seam, declared, logs):
    seam.raises = MeshUnavailable(f"could not reach the gateway: Bearer {SECRET}")
    r = measure(client)
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "asset_unavailable"
    assert SECRET not in r.text and SECRET not in " ".join(logs.lines)
    assert not any(f in r.text for f in seed_figures(declared))
    assert any("MeshUnavailable" in line for line in logs.lines), "the type is the log's evidence"


def test_a_scan_failure_is_a_503_by_type_only(client, seam, declared, logs, tmp_path):
    seam.frame = pl.scan_parquet(tmp_path / f"{SECRET}-missing.parquet")
    r = measure(client)
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "asset_unavailable"
    assert SECRET not in r.text and SECRET not in " ".join(logs.lines)
    assert not any(f in r.text for f in seed_figures(declared))


def _idx0(name, value):
    return pl.when(pl.int_range(pl.len()) == 0).then(value).otherwise(pl.col(name)).alias(name)


def _mutations():
    df = frame_of()
    assert df.filter(pl.col("work_package") == df["work_package"][0]).height > 1
    return {
        "missing_column": df.drop("acwp"),
        "null_value": df.with_columns(_idx0("bcwp", None)),
        "duplicate_work_package_period": pl.concat([df, df.head(1)]),
        "program_name_not_unique": df.with_columns(_idx0("program_name", pl.lit("Another name"))),
        "program_bac_not_unique": df.with_columns(_idx0("program_bac", pl.col("program_bac") + 1)),
        "work_package_in_two_accounts": df.with_columns(_idx0("control_account", pl.lit("CA-ELSEWHERE"))),
        "period_outside_calendar": df.with_columns(_idx0("period", pl.lit("FY27-01"))),
        "wrong_type": df.with_columns(pl.col("bcws").cast(pl.String)),
        "non_finite": df.with_columns(pl.col("bcws").cast(pl.Float64)).with_columns(
            _idx0("bcws", float("nan"))),
    }


@pytest.mark.parametrize("rule", list(_mutations()))
def test_each_contract_rule_is_its_own_502_and_names_no_money(client, seam, declared, rule):
    seam.frame = _mutations()[rule].lazy()
    r = measure(client)
    assert r.status_code == 502, r.text
    d = r.json()["detail"]
    assert d["error"] == "asset_contract_violation" and d["rule"] == rule
    assert not any(f in r.text for f in seed_figures(declared))
    # the control: the same frame, unbroken, is served
    seam.frame = frame_of().lazy()
    assert measure(client).status_code == 200


def test_more_rows_than_the_cap_is_a_422_asset_too_large(client, seam, monkeypatch):
    seam.frame = frame_of().lazy()
    monkeypatch.setenv("FIN_ASSET_MAX_ROWS", "5")
    r = measure(client)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "asset_too_large" and r.json()["detail"]["max_rows"] == 5
    monkeypatch.setenv("FIN_ASSET_MAX_ROWS", str(frame_of().height))   # exactly at the cap is served
    assert measure(client).status_code == 200


def test_no_rows_for_the_program_or_the_window_is_a_422_not_in_model_never_an_empty_200(client, seam):
    seam.frame = frame_of().filter(pl.col("period").is_in(list(FISCAL_PERIODS[:3]))).lazy()
    none_for_program = measure(client, params={"program_id": OTHER_PROGRAM})
    none_for_window = measure(client, params={"program_id": PROGRAM, "window": ["FY26-12"]})
    for r in (none_for_program, none_for_window):
        assert r.status_code == 422, r.text
        assert "not_in_model" in r.json()["detail"]
    assert measure(client, params={"program_id": PROGRAM, "window": ["FY26-02"]}).status_code == 200


def test_an_unknown_period_is_refused_before_any_read(client, seam):
    seam.frame = frame_of().lazy()
    r = measure(client, params={"program_id": PROGRAM, "window": ["FY99-01"]})
    assert r.status_code == 422 and "not_in_model" in r.json()["detail"]
    assert seam.urns == [] and seam.kwargs == []


def test_state_from_rows_refuses_an_empty_frame_by_name():
    with pytest.raises(NotInModel):
        asset_inputs.state_from_rows(frame_of().head(0), PROGRAM)


# ── boot ────────────────────────────────────────────────────────────────────────────────

def _boots():
    with TestClient(engine.app):
        pass


def test_the_flag_set_with_everything_present_boots(on):
    _boots()


@pytest.mark.parametrize("break_it", ["banner", "gateway", "urn-form", "client-not-importable"])
def test_a_flag_that_cannot_be_honoured_fails_the_boot(on, monkeypatch, break_it):
    if break_it == "banner":
        monkeypatch.delenv("FIN_DATASET_BANNER")
    elif break_it == "gateway":
        monkeypatch.delenv("CENTRAL_GATEWAY_URL")
    elif break_it == "urn-form":
        monkeypatch.setenv("FIN_DATASET_URN", "s3://bucket/key")
    else:
        def missing():
            raise ImportError("No module named 'dag_tools.cortex_data.identity'")
        monkeypatch.setattr(engine.asset_inputs, "_load_client", missing)
    with pytest.raises(RuntimeError, match="FIN_DATASET_URN"):
        _boots()


def test_a_bad_row_cap_fails_the_boot(on, monkeypatch):
    monkeypatch.setenv("FIN_ASSET_MAX_ROWS", "lots")
    with pytest.raises(RuntimeError):
        _boots()


# ── exports ─────────────────────────────────────────────────────────────────────────────

def _package_body(builtin_only=False):
    panels = [{"panel": 0, "verb": "mesh:finPerformanceIndices", "params": {"program_id": PROGRAM}}]
    if not builtin_only:
        panels.append({"panel": 1, "verb": "mesh:finToCompletePerformanceIndex",
                       "params": {"program_id": PROGRAM}})
    return {"user_email": ALICE, "recipient_scope": f"program_office.{PROGRAM}",
            "canvas": {"template_id": "program_finance", "template_hash": "h", "panels": panels}}


@pytest.fixture
def spy(monkeypatch):
    calls: list[tuple[str, dict]] = []
    real = engine._measure_envelope

    def wrapped(fn, params, **kw):
        env = real(fn, params, **kw)
        calls.append((fn, env))
        return env
    monkeypatch.setattr(engine, "_measure_envelope", wrapped)
    return calls


def test_a_package_naming_a_declared_measure_is_a_409_before_anything_is_measured(client, seam, spy):
    r = client.post("/package_export", json=_package_body())
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["error"] == "asset_export_unsupported" and d["measures"] == ["fin_tcpi"]
    assert spy == [] and seam.urns == [] and seam.loads == 0


def test_a_cdrl_naming_a_declared_measure_is_a_409_before_anything_is_measured(
        client, seam, spy, monkeypatch, tmp_path):
    from agent_fleet.finance_agent import export_profiles
    monkeypatch.setenv("FIN_EXPORT_PROFILE_OVERLAY_DIRS", str(PROFILES_DIR))
    profiles = {p.name: p for p in export_profiles.load_export_profiles(declared=engine.DECLARED)}
    monkeypatch.setattr(engine, "PROFILES", profiles)
    name = "cdrl_a001_ev_summary"
    assert set(profiles[name].sources) & set(engine.DECLARED), "the profile must source a declared measure"
    r = client.post("/cdrl_export", json={"profile": name, "program_id": PROGRAM, "user_email": ALICE})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "asset_export_unsupported"
    assert spy == [] and seam.urns == [] and seam.loads == 0


def test_a_built_in_only_package_still_works_and_carries_the_notional_banner(
        client, seam, spy, monkeypatch):
    import build_fin_package as builder

    def fake_build(**kw):
        return {"manifest": {"recipient_scope": f"program_office.{PROGRAM}", "as_of": "t",
                             "algorithm_sha": "0" * 40, "template_id": "program_finance",
                             "template_hash": "h", "panels": [{"artifact_id": "a"}]},
                "html_sha256": "sha256:" + "a" * 64, "html_bytes": 1,
                "duckdb_sha256": "sha256:" + "a" * 64}
    monkeypatch.setattr(builder, "build", fake_build)
    monkeypatch.setattr(engine, "_repo_root", lambda: REPO)
    monkeypatch.setattr("build_cost_package.algorithm_sha", lambda: "0" * 40)
    r = client.post("/package_export", json=_package_body(builtin_only=True))
    assert r.status_code == 200, r.text
    assert spy and all(env["data_provenance"] == seed.notional_banner() for _fn, env in spy)
    assert seam.urns == [] and seam.loads == 0


# ── provenance ──────────────────────────────────────────────────────────────────────────

def test_an_asset_answer_carries_the_banner_and_the_urn_and_not_the_notional_text(client, seam):
    seam.frame = frame_of().lazy()
    env = measure(client).json()
    assert BANNER in env["data_provenance"] and URN in env["data_provenance"]
    assert seed.notional_banner() not in env["data_provenance"] and "NOTIONAL" not in env["data_provenance"]
    assert env["data_source"] == {"kind": "asset", "urn": URN}


def test_a_built_in_with_the_flag_set_keeps_the_notional_banner_and_reads_nothing(client, seam):
    r = client.post("/measure/fin_performance_indices", headers={"Authorization": f"Bearer {token(ALICE)}"},
                    json={"params": {"program_id": PROGRAM}, "user_email": ALICE})
    assert r.status_code == 200, r.text
    env = r.json()
    assert env["data_provenance"] == seed.notional_banner() and "data_source" not in env
    assert seam.urns == [] and seam.loads == 0


# ── timing ──────────────────────────────────────────────────────────────────────────────

LINE = re.compile(r"^asset read ticket_ms=\d+ scan_ms=\d+ sql_ms=0 rows=(\d+) bytes=\d+ urn=(\S+)$")


def test_one_timing_line_per_read_with_the_urn_and_neither_the_caller_nor_the_bearer(client, seam, logs):
    seam.frame = frame_of().lazy()
    tok = token(ALICE)
    for expected_lines in (1, 2):
        assert measure(client, tok=tok).status_code == 200
        timing = [ln for ln in logs.lines if ln.startswith("asset read ")]
        assert len(timing) == expected_lines
    m = LINE.match(timing[-1])
    assert m and int(m.group(1)) == frame_of().height and m.group(2) == URN
    blob = " ".join(ln for ln in logs.lines if ln.startswith("asset "))  # ours; the SDK logs its own
    assert blob and ALICE not in blob and tok not in blob and "alice" not in blob


def test_the_logger_prints_at_info_with_no_root_configuration():
    assert any(isinstance(h, logging.StreamHandler) for h in asset_inputs.log.handlers)
    assert asset_inputs.log.isEnabledFor(logging.INFO)
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from agent_fleet.finance_agent import asset_inputs as a;"
        "a.log.info('asset read probe-line')"
    )
    out = subprocess.run([sys.executable, "-c", code, str(REPO)], capture_output=True, text=True,
                         timeout=120, cwd=str(REPO))
    assert out.returncode == 0, out.stderr[-400:]
    assert "asset read probe-line" in out.stderr


# ── the bearer is request-scoped ────────────────────────────────────────────────────────

def test_the_bearer_does_not_outlive_its_request(client, seam):
    seam.frame = frame_of().lazy()
    assert measure(client, tok=token(ALICE)).status_code == 200
    assert measure(client, tok=None).status_code == 401, "the previous request's bearer must be gone"
