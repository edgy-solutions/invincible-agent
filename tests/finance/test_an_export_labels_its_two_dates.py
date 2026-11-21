"""An export labels its two dates (architect ruling, 2026-11-21).

One date, called `as_of`, used to be filled with the request date and shown as "as of". Now an
export carries `data_as_of` (the source's own as-of, read from the asset read's ticket receipt)
and `generated_on` (when the export was generated), each labelled. The generation date is never
shown as the data date; an unavailable as-of says so in its field.

The asset read is replaced at ONE seam, `_export_program_state`, which hands the route a receipt
exactly as the real one does (into the list the route passes). The page build is the real
`build_fin_package.build`; only the JavaScript syntax check and the pyodide runtime fetch are
stubbed (no `.pyodide-cache` in a plain checkout).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl
import pytest
import yaml
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.finance_agent import export as fin_export  # noqa: E402
from agent_fleet.finance_agent import export_profiles, seed  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from iagent.canvas_template import load_template, panel_dispatch  # noqa: E402

try:
    from agent_fleet.finance_agent import export_dates  # noqa: E402
except ImportError:  # unfixed code: the unit tests fail by name, the rest by behaviour
    export_dates = None

SAMPLE = REPO / "policy" / "overlays" / "sample" / "fin_export_profiles"
JSON_NAME = "cdrl_a001_ev_summary_json"
XLSX_NAME = "cdrl_a001_ev_summary"
PROGRAM = seed.PROGRAM_ID
SCOPE = f"program_office.{PROGRAM}"
ALICE = "alice@example.com"
URN = "urn:li:dataset:(urn:li:dataPlatform:file,fin_test_asset,TEST)"
DATA = "2026-10-31"
GENERATED = "2026-11-21"
NO_SOURCE = "as-of unavailable: the notional seed carries no as-of"


def receipt(**over):
    return {"urn": URN, "ticket_id": "tkt-0001", "issued_at": "2026-11-21T00:00:00Z",
            "as_of": DATA, "as_of_source": "read_at_authorize", **over}


@pytest.fixture
def declared(monkeypatch):
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(REPO / "policy/overlays/sample/measure_verbs"))
    rows = engine._load_declared()
    monkeypatch.setattr(engine, "DECLARED", rows)
    monkeypatch.setitem(engine.VERB_TO_FN, "mesh:finToCompletePerformanceIndex", "fin_tcpi")
    return rows


@pytest.fixture
def served(declared, monkeypatch, tmp_path):
    monkeypatch.setenv("FIN_EXPORT_PROFILE_OVERLAY_DIRS", str(SAMPLE))
    monkeypatch.setattr(engine, "PROFILES",
                        {p.name: p for p in export_profiles.load_export_profiles(declared=declared)})
    monkeypatch.setattr(engine, "can_view_program", lambda program, caller_id, **kw: True)
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(engine, "_repo_root", lambda: root)
    with TestClient(engine.app) as c:
        yield c, root


def asset_backed(monkeypatch, rcpt):
    """The program-state read comes from an asset whose ticket receipt is `rcpt`."""
    def fake(reads, program_id, fns, receipts):
        receipts.append(dict(rcpt))
        return engine.STATE, {"kind": "asset", "urn": URN}
    monkeypatch.setattr(engine, "_export_program_state", fake)


def cdrl(c, profile=JSON_NAME, generated=GENERATED):
    return c.post("/cdrl_export", json={"profile": profile, "program_id": PROGRAM,
                                        "user_email": ALICE, "as_of": generated})


def cdrl_json_file(r):
    d = engine._cdrl_out_dir()
    return json.loads((d / r.json()["artifact_filename"]).read_text(encoding="utf-8"))


# 1 -- an asset-backed package -----------------------------------------------------------------

@pytest.fixture
def package(monkeypatch, tmp_path):
    import build_fin_package as real
    monkeypatch.setattr(real, "embedded_runtime", lambda runtime_dir: ({}, ""))
    monkeypatch.setattr(real, "check_javascript", lambda html: [])
    monkeypatch.setattr("build_cost_package.algorithm_sha", lambda: "0" * 40)
    monkeypatch.setattr(engine, "can_view_program", lambda program, caller_id, **kw: True)
    monkeypatch.setattr(engine, "_repo_root", lambda: REPO)
    dist = tmp_path / "dist"
    monkeypatch.setattr(engine, "_dist_dir", lambda root: dist)
    manifests = []
    real_audit = fin_export.audit_line

    def spy(manifest, **kw):
        manifests.append(manifest)
        return real_audit(manifest, **kw)

    monkeypatch.setattr(fin_export, "audit_line", spy)
    with TestClient(engine.app) as c:
        yield c, dist, manifests


def _canvas():
    t = load_template("program_finance")
    panels = [panel_dispatch(t, i, {"program": PROGRAM}) for i in range(len(t.panels))]
    return {"template_id": "program_finance", "template_hash": "h",
            "panels": [{"panel": i, "verb": v, "params": dict(p)} for i, (v, _s, p) in enumerate(panels)]}


def _package(c, generated=GENERATED):
    return c.post("/package_export", json={"user_email": ALICE, "recipient_scope": SCOPE,
                                           "canvas": _canvas(), "as_of": generated})


def _page(dist):
    html_name, _ = fin_export.artifact_filenames(SCOPE)
    return (dist / html_name).read_text(encoding="utf-8")


def test_an_asset_backed_package_labels_the_sources_as_of_and_the_generation_date(package, monkeypatch):
    c, dist, manifests = package
    asset_backed(monkeypatch, receipt())
    r = _package(c)
    assert r.status_code == 200, r.text[:400]
    assert manifests[0]["data_as_of"] == DATA
    assert manifests[0]["generated_on"] == GENERATED
    assert manifests[0]["schema"] == "fin-export/2" and "as_of" not in manifests[0]
    assert f"data as of {DATA} &middot; generated {GENERATED}" in _page(dist)


def test_control_a_package_page_never_shows_the_generation_date_as_the_data_date(package, monkeypatch):
    c, dist, _ = package
    asset_backed(monkeypatch, receipt())
    assert _package(c).status_code == 200
    html = _page(dist)
    assert f"as of {GENERATED}" not in html
    assert f"data as of {GENERATED}" not in html


# 2 -- an asset-backed CDRL --------------------------------------------------------------------

def test_an_asset_backed_cdrl_json_carries_both_dates_in_envelope_response_and_header(served, monkeypatch):
    c, _root = served
    asset_backed(monkeypatch, receipt())
    r = cdrl(c)
    assert r.status_code == 200, r.text[:400]
    body = r.json()
    assert (body["data_as_of"], body["generated_on"]) == (DATA, GENERATED)
    assert "as_of" not in body
    assert (body["envelope"]["data_as_of"], body["envelope"]["generated_on"]) == (DATA, GENERATED)
    header = cdrl_json_file(r)["header"]
    assert header["as_of"] == DATA and header["generated_on"] == GENERATED


def test_an_asset_backed_xlsx_cdrl_shows_the_data_as_of_in_b4(served, monkeypatch):
    c, _root = served
    asset_backed(monkeypatch, receipt())
    r = cdrl(c, profile=XLSX_NAME)
    assert r.status_code == 200, r.text[:400]
    ws = openpyxl.load_workbook(engine._cdrl_out_dir() / r.json()["artifact_filename"])["EV Summary"]
    assert ws["B4"].value == DATA
    assert r.json()["generated_on"] == GENERATED and r.json()["data_as_of"] == DATA


# 3 -- unavailable -----------------------------------------------------------------------------

@pytest.mark.parametrize("as_of", [None, ""])
@pytest.mark.parametrize("reason", [None, "reader_failed"])
def test_an_unavailable_as_of_says_so_in_the_field_and_is_never_the_generation_date(
        served, monkeypatch, as_of, reason):
    c, _root = served
    over = {"as_of": as_of, "as_of_source": None}
    if reason:
        over["as_of_unavailable"] = reason
    asset_backed(monkeypatch, receipt(**over))
    r = cdrl(c)
    assert r.status_code == 200, r.text[:400]
    want = "as-of unavailable" + (f": {reason}" if reason else "")
    header = cdrl_json_file(r)["header"]
    for got in (r.json()["data_as_of"], r.json()["envelope"]["data_as_of"], header["as_of"]):
        assert got == want
        assert got and got != GENERATED


# 4 -- advertised at load ----------------------------------------------------------------------

def test_an_advertised_at_load_as_of_carries_the_date_and_the_label(served, monkeypatch):
    c, _root = served
    asset_backed(monkeypatch, receipt(as_of_source="advertised_at_load"))
    r = cdrl(c)
    assert r.json()["data_as_of"] == f"{DATA} (advertised at load, not read for this export)"
    assert cdrl_json_file(r)["header"]["as_of"] == r.json()["data_as_of"]


def test_control_a_read_at_authorize_as_of_is_the_bare_date(served, monkeypatch):
    c, _root = served
    asset_backed(monkeypatch, receipt(as_of_source="read_at_authorize"))
    r = cdrl(c)
    assert r.json()["data_as_of"] == DATA


# 5 -- a seed-sourced export -------------------------------------------------------------------

def test_a_seed_sourced_cdrl_says_the_seed_carries_no_as_of_never_the_generation_date(served):
    c, _root = served
    r = cdrl(c)
    assert r.status_code == 200, r.text[:400]
    assert r.json()["data_as_of"] == NO_SOURCE and r.json()["data_as_of"] != GENERATED
    assert cdrl_json_file(r)["header"]["as_of"] == NO_SOURCE


def test_a_seed_sourced_package_says_the_seed_carries_no_as_of(package):
    c, dist, manifests = package
    assert _package(c).status_code == 200
    assert manifests[0]["data_as_of"] == NO_SOURCE
    assert manifests[0]["generated_on"] == GENERATED
    assert f"data as of {NO_SOURCE} &middot; generated {GENERATED}" in _page(dist)


# 6 -- the profile vocabulary ------------------------------------------------------------------

def _load_with_cell(declared, tmp_path, fact):
    raw = yaml.safe_load((SAMPLE / f"{XLSX_NAME}.yaml").read_text(encoding="utf-8"))
    raw["cells"]["B6"] = fact
    d = tmp_path / "ov"
    d.mkdir()
    (d / f"{XLSX_NAME}.xlsx").write_bytes((SAMPLE / f"{XLSX_NAME}.xlsx").read_bytes())
    (d / "row.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    return export_profiles.load_export_profiles(
        policy_dir=tmp_path / "no-seed", overlay_dirs=[d], declared=declared)


def test_a_profile_naming_generated_on_loads(declared, tmp_path):
    got = _load_with_cell(declared, tmp_path, "generated_on")
    assert got[0].cells["B6"] == "generated_on"


def test_a_profile_naming_an_unknown_fact_is_still_refused(declared, tmp_path):
    with pytest.raises(export_profiles.ExportProfileError) as ei:
        _load_with_cell(declared, tmp_path, "as_of_today")
    assert "as_of_today" in str(ei.value)


# 7 -- export_dates.data_as_of -----------------------------------------------------------------

def test_unit_no_receipt_is_the_seed_string():
    assert export_dates.data_as_of(None) == NO_SOURCE


@pytest.mark.parametrize("as_of", [None, ""])
def test_unit_no_usable_as_of_without_a_reason_is_the_bare_label(as_of):
    assert export_dates.data_as_of({"as_of": as_of}) == "as-of unavailable"
    assert export_dates.data_as_of({}) == "as-of unavailable"


@pytest.mark.parametrize("as_of", [None, ""])
def test_unit_no_usable_as_of_carries_the_reason(as_of):
    got = export_dates.data_as_of({"as_of": as_of, "as_of_unavailable": "reader_declined"})
    assert got == "as-of unavailable: reader_declined"


def test_unit_unavailable_wins_over_an_advertised_source():
    assert export_dates.data_as_of({"as_of": None, "as_of_source": "advertised_at_load"}) \
        == "as-of unavailable"


def test_unit_advertised_at_load_carries_the_label():
    got = export_dates.data_as_of({"as_of": DATA, "as_of_source": "advertised_at_load"})
    assert got == f"{DATA} (advertised at load, not read for this export)"


@pytest.mark.parametrize("source", ["read_at_authorize", None, "snapshot"])
def test_unit_otherwise_the_as_of_is_returned_unchanged(source):
    assert export_dates.data_as_of({"as_of": DATA, "as_of_source": source}) == DATA
