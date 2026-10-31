"""A CDRL profile names its format: xlsx, docx, csv or json, one contract.

Follow-up to `test_a_cdrl_is_an_export_profile.py` (arms 1-11, run unchanged as arm 8 here). The
contract every format keeps: a profile computes nothing, every refusal is at load and names the
file, the claim is `cells_sha256` over what the producer WROTE, one file per program.

Arms: 1 load refusals, 2 json (the proof: a committed profile and no template), 3 csv, 4 docx,
5 the hash recomputed from the delivered file alone, 6 the filename / media type / closed set,
7 the BFF.

Run: uv run --no-sync pytest tests/finance/test_a_cdrl_profile_names_its_format.py -q
"""
from __future__ import annotations

import asyncio
import copy
import csv
import hashlib
import io
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import docx
import pytest
import yaml
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openpyxl.utils.cell import get_column_letter

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.finance_agent import cdrl, export_profiles  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from tests.finance.test_a_cdrl_is_an_export_profile import (  # noqa: E402,F401
    ALICE, BOB, ENVELOPE, PROGRAM, ROW, SAMPLE, Double, declared, _rows,
)

JSON_NAME = "cdrl_a001_ev_summary_json"
JSON_ROW = SAMPLE / f"{JSON_NAME}.yaml"
IDX = "fin_performance_indices"
HEAD = ["Period", "Cum BCWS", "Cum CPI"]


# -- fixtures and builders ---------------------------------------------------------------------

def _docx_template(path: Path) -> str:
    """A 2-table template: a title table (3x2) and a data table with a header row and ONE body row
    of placeholder text (fewer rows than periods). Returns its sha256."""
    d = docx.Document()
    t1 = d.add_table(rows=3, cols=2)
    for i, label in enumerate(("Program", "Program id", "As of")):
        t1.cell(i, 0).text = label
    t2 = d.add_table(rows=2, cols=3)
    for j, h in enumerate(HEAD):
        t2.cell(0, j).text = h
    for j in range(3):
        t2.cell(1, j).text = "n/a"
    d.save(str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _docx_raw(sha: str) -> dict:
    return {
        "name": "fin_docx", "format": "docx", "scope": "program", "label": "L",
        "cdrl": {"item": "A001"}, "template": {"file": "t.docx", "sha256": sha},
        "cells": {"T1!B1": "program.name", "T1!B2": "program.id", "T1!B3": "as_of"},
        "sources": [{"fn": IDX}],
        "table": {"start": "T2!A2", "key": "period", "columns": [
            {"from": "period"},
            {"from": f"{IDX}.cum_bcws", "format": "#,##0"},
            {"from": f"{IDX}.cum_cpi", "format": "0.000"}]},
    }


def _csv_raw() -> dict:
    return {
        "name": "fin_csv", "format": "csv", "scope": "program", "label": "L",
        "cdrl": {"item": "A001"}, "sources": [{"fn": IDX}, {"fn": "fin_tcpi"}],
        "table": {"key": "period", "columns": [
            {"from": "period", "as": "Period"},
            {"from": f"{IDX}.cum_bcws", "as": "Cum BCWS", "format": "#,##0"},
            {"from": f"{IDX}.cum_cpi", "as": "Cum CPI", "format": "0.000"},
            {"from": "fin_tcpi.tcpi", "as": "TCPI"}]},
    }


def _json_raw() -> dict:
    return yaml.safe_load(JSON_ROW.read_text(encoding="utf-8"))


def _write(d: Path, raw: dict, name: str = "row.yaml") -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return d


def _load(d: Path, declared, extra=()):
    return export_profiles.load_export_profiles(
        policy_dir=d.parent / "no-seed", overlay_dirs=[*extra, d], declared=declared)


@pytest.fixture
def fmt_profiles(declared, monkeypatch, tmp_path):
    """The xlsx and json samples plus a docx and a csv profile, composed and installed."""
    ov = tmp_path / "ov-formats"
    ov.mkdir()
    sha = _docx_template(ov / "t.docx")
    _write(ov, _docx_raw(sha), "docx.yaml")
    _write(ov, _csv_raw(), "csv.yaml")
    got = export_profiles.load_export_profiles(
        policy_dir=tmp_path / "no-seed", overlay_dirs=[SAMPLE, ov], declared=declared)
    p = {x.name: x for x in got}
    monkeypatch.setattr(engine, "PROFILES", p)
    return p


def _build(profile, out, *, state=None, source=None):
    return cdrl.build_cdrl(
        state or engine.STATE, profile, program_id=PROGRAM, as_of="2026-10-28", out_dir=out,
        run_source=source or (lambda fn, params: engine._cdrl_source(fn, params)))


def _drop_last_tcpi(fn, params):
    """The engine's source, except fin_tcpi did not return its last period."""
    env, method = engine._cdrl_source(fn, params)
    if fn == "fin_tcpi":
        env = {**env, "rows": list(env["rows"])[:-1]}
    return env, method


def _spent_state(monkeypatch):
    state = copy.deepcopy(engine.STATE)
    program = next(p for p in state.programs if p.program_id == PROGRAM)
    ca = {c.ca_id for c in state.accounts_of(PROGRAM)}
    wps = {w.wp_id for w in state.work_packages if w.ca_id in ca}
    state.facts = [replace(f, acwp=f.acwp + 10 * program.bac) if f.wp_id in wps else f
                   for f in state.facts]
    monkeypatch.setattr(engine, "STATE", state)
    return state


# -- arm 1: load refusals, one per table cell marked refused or required ------------------------

def _refuses(tmp_path, declared, raw, fragment):
    d = tmp_path / "ov"
    d.mkdir(exist_ok=True)
    _write(d, raw)
    with pytest.raises(export_profiles.ExportProfileError) as ei:
        _load(d, declared)
    msg = str(ei.value)
    assert "row.yaml" in msg, msg
    assert fragment in msg, msg


def _docx_ok(tmp_path):
    """The docx row with its template already beside it in `tmp_path/ov` (the zip is not
    byte-reproducible, so the template is written ONCE and the row pins that file)."""
    d = tmp_path / "ov"
    d.mkdir(exist_ok=True)
    return _docx_raw(_docx_template(d / "t.docx"))


def test_1_each_format_loads(declared, tmp_path):
    d = tmp_path / "ov"
    d.mkdir()
    _write(d, _docx_raw(_docx_template(d / "t.docx")), "docx.yaml")
    _write(d, _csv_raw(), "csv.yaml")
    got = {p.name: p for p in _load(d, declared, extra=[SAMPLE])}
    assert {n: p.format for n, p in got.items()} == {
        "fin_docx": "docx", "fin_csv": "csv", JSON_NAME: "json", "cdrl_a001_ev_summary": "xlsx",
        "cdrl_a002_cost_performance_docx": "docx"}
    assert all(p.provenance_sheets is False for n, p in got.items() if p.format != "xlsx")


def test_1_a_csv_with_a_template(declared, tmp_path):
    raw = _csv_raw()
    raw["template"] = {"file": "x.csv", "sha256": "0" * 64}
    _refuses(tmp_path, declared, raw, "template is not allowed on a csv profile")


def test_1_a_json_with_a_template(declared, tmp_path):
    raw = _json_raw()
    raw["template"] = {"file": "x.json", "sha256": "0" * 64}
    _refuses(tmp_path, declared, raw, "template is not allowed on a json profile")


def test_1_a_docx_without_a_template(declared, tmp_path):
    raw = _docx_ok(tmp_path)
    del raw["template"]
    _refuses(tmp_path, declared, raw, "template.file")


def test_1_a_docx_with_a_sheet(declared, tmp_path):
    raw = _docx_ok(tmp_path)
    raw["sheet"] = "S"
    _refuses(tmp_path, declared, raw, "sheet is not allowed on a docx profile")


def test_1_a_csv_with_cells(declared, tmp_path):
    raw = _csv_raw()
    raw["cells"] = {"A1": "as_of"}
    _refuses(tmp_path, declared, raw, "no title block")


def test_1_a_json_without_table_at(declared, tmp_path):
    raw = _json_raw()
    del raw["table"]["at"]
    _refuses(tmp_path, declared, raw, "table.at")


@pytest.mark.parametrize("make", [_csv_raw, _json_raw])
def test_1_a_csv_or_json_column_without_as(declared, tmp_path, make):
    raw = make()
    del raw["table"]["columns"][1]["as"]
    _refuses(tmp_path, declared, raw, "has no 'as'")


def test_1_an_xlsx_column_with_as(declared, tmp_path):
    raw = yaml.safe_load(ROW.read_text(encoding="utf-8"))
    raw["table"]["columns"][1]["as"] = "x"
    d = tmp_path / "ov"
    d.mkdir()
    (d / "cdrl_a001_ev_summary.xlsx").write_bytes((SAMPLE / "cdrl_a001_ev_summary.xlsx").read_bytes())
    _write(d, raw)
    with pytest.raises(export_profiles.ExportProfileError) as ei:
        _load(d, declared)
    assert "row.yaml" in str(ei.value) and "carries 'as'" in str(ei.value)


def test_1_a_json_column_with_a_format(declared, tmp_path):
    raw = _json_raw()
    raw["table"]["columns"][1]["format"] = "#,##0"
    _refuses(tmp_path, declared, raw, "a json number is a number")


@pytest.mark.parametrize("which", ["docx", "csv"])
def test_1_a_text_column_format_outside_TEXT_FORMATS(declared, tmp_path, which):
    raw = _docx_ok(tmp_path) if which == "docx" else _csv_raw()
    raw["table"]["columns"][1]["format"] = "0.0000"
    _refuses(tmp_path, declared, raw, "outside the text formats")


def test_1_a_docx_table_that_the_template_does_not_hold(declared, tmp_path):
    raw = _docx_ok(tmp_path)
    raw["cells"] = {"T9!A1": "as_of"}
    _refuses(tmp_path, declared, raw, "holds 2 table(s)")


def test_1_a_docx_cell_outside_the_tables_grid(declared, tmp_path):
    raw = _docx_ok(tmp_path)
    raw["cells"] = {"T1!C1": "as_of"}
    _refuses(tmp_path, declared, raw, "whose grid is 3 row(s) x 2 column(s)")


def test_1_a_json_pointer_collision(declared, tmp_path):
    raw = _json_raw()
    raw["cells"] = {"/a": "as_of", "/a/b": "program.id"}
    _refuses(tmp_path, declared, raw, "collides with or nests under")


@pytest.mark.parametrize("ptr", ["", "/", "/a//b", "a/b", "/a/~0", "/a/0"])
def test_1_a_malformed_json_pointer(declared, tmp_path, ptr):
    raw = _json_raw()
    raw["cells"] = {ptr: "as_of"}
    _refuses(tmp_path, declared, raw, "pointer")


@pytest.mark.parametrize("which", ["docx", "csv", "json"])
def test_1_provenance_sheets_outside_xlsx(declared, tmp_path, which):
    raw = {"docx": lambda: _docx_ok(tmp_path), "csv": _csv_raw, "json": _json_raw}[which]()
    raw["provenance_sheets"] = False
    _refuses(tmp_path, declared, raw,
             "only an xlsx has sheets, so the delivered file is exactly the form")


def test_1_an_unknown_format(declared, tmp_path):
    raw = _json_raw()
    raw["format"] = "pdf"
    _refuses(tmp_path, declared, raw, "'pdf'")


# -- arm 2: json, the proof: a committed profile and NO template ---------------------------------

def _json_build(fmt_profiles, tmp_path, **kw):
    path, env = _build(fmt_profiles[JSON_NAME], tmp_path, **kw)
    return path, env, json.loads(path.read_text(encoding="utf-8"))


def test_2_the_sample_json_profile_needs_no_template(fmt_profiles):
    p = fmt_profiles[JSON_NAME]
    assert p.template_path is None and p.template_sha256 is None and p.sheet is None


def test_2_title_facts_sit_at_their_pointers(fmt_profiles, tmp_path):
    _, _, obj = _json_build(fmt_profiles, tmp_path)
    program = next(p for p in engine.STATE.programs if p.program_id == PROGRAM)
    assert obj["header"] == {"program_name": program.name, "program_id": PROGRAM,
                             "as_of": "2026-10-28", "cdrl_item": "A001"}


def test_2_one_row_object_per_period_in_order_each_number_the_envelopes(fmt_profiles, tmp_path):
    path, env, obj = _json_build(fmt_profiles, tmp_path)
    idx, tc = _rows(IDX), _rows("fin_tcpi")
    periods = list(idx)
    assert len(periods) >= 2
    rows = obj["summary"]["periods"]
    assert [r["period"] for r in rows] == periods
    for r in rows:
        for field, src in (("cum_bcws", idx), ("cum_bcwp", idx), ("cum_acwp", idx),
                           ("cum_cpi", idx), ("cum_spi", idx), ("tcpi", tc)):
            want = src[r["period"]][field]
            assert r[field] == cdrl._norm(want), (r["period"], field)
    assert env["format"] == "json" and path.name == f"fin-cdrl-{JSON_NAME}-{PROGRAM}.json"


def test_2_an_undefined_period_carries_the_reason_string(fmt_profiles, tmp_path, monkeypatch):
    state = _spent_state(monkeypatch)
    _, _, obj = _json_build(fmt_profiles, tmp_path, state=state)
    assert {r["tcpi"] for r in obj["summary"]["periods"]} == {"undefined: budget_spent"}


def test_2_an_absent_value_is_an_absent_key(fmt_profiles, tmp_path):
    path, _, obj = _json_build(fmt_profiles, tmp_path, source=_drop_last_tcpi)
    rows = obj["summary"]["periods"]
    assert "tcpi" not in rows[-1], rows[-1]
    assert all("tcpi" in r for r in rows[:-1])
    assert "null" not in path.read_text(encoding="utf-8")


def test_2_key_order_is_the_declaration_order(fmt_profiles, tmp_path):
    path, _, obj = _json_build(fmt_profiles, tmp_path)
    assert list(obj["header"]) == ["program_name", "program_id", "as_of", "cdrl_item"]
    assert list(obj["summary"]["periods"][0]) == [
        "period", "cum_bcws", "cum_bcwp", "cum_acwp", "cum_cpi", "cum_spi", "tcpi"]
    text = path.read_text(encoding="utf-8")
    assert text.endswith("}\n") and not text.endswith("\n\n")


# -- arm 3: csv --------------------------------------------------------------------------------

def _csv_build(fmt_profiles, tmp_path, **kw):
    path, env = _build(fmt_profiles["fin_csv"], tmp_path, **kw)
    data = path.read_bytes()
    return path, env, data, list(csv.reader(io.StringIO(data.decode("utf-8"), newline="")))


def test_3_header_rows_and_rendered_values(fmt_profiles, tmp_path):
    _, env, data, got = _csv_build(fmt_profiles, tmp_path)
    assert got[0] == ["Period", "Cum BCWS", "Cum CPI", "TCPI"]
    idx, tc = _rows(IDX), _rows("fin_tcpi")
    periods = list(idx)
    assert [r[0] for r in got[1:]] == periods
    for r in got[1:]:
        p = r[0]
        assert r[1] == cdrl._text(idx[p]["cum_bcws"], "#,##0")
        assert r[2] == cdrl._text(idx[p]["cum_cpi"], "0.000")
        assert r[3] == cdrl._text(tc[p]["tcpi"], None)
    assert env["format"] == "csv"


def test_3_crlf_utf8_no_bom(fmt_profiles, tmp_path):
    _, _, data, _ = _csv_build(fmt_profiles, tmp_path)
    assert data.endswith(b"\r\n")
    assert data.count(b"\n") == data.count(b"\r\n"), "a bare LF line ending"
    assert not data.startswith(b"\xef\xbb\xbf")
    data.decode("utf-8")


def test_3_an_absent_value_is_an_empty_field(fmt_profiles, tmp_path):
    _, _, _, got = _csv_build(fmt_profiles, tmp_path, source=_drop_last_tcpi)
    assert got[-1][3] == "" and got[-1][0] != ""
    assert all(r[3] != "" for r in got[1:-1])


# -- arm 4: docx -------------------------------------------------------------------------------

def _docx_build(fmt_profiles, tmp_path):
    path, env = _build(fmt_profiles["fin_docx"], tmp_path)
    return path, env, docx.Document(str(path))


def test_4_title_cells_hold_their_facts_and_the_rest_is_untouched(fmt_profiles, tmp_path):
    _, _, doc = _docx_build(fmt_profiles, tmp_path)
    program = next(p for p in engine.STATE.programs if p.program_id == PROGRAM)
    t1 = doc.tables[0]
    assert [t1.cell(i, 1).text for i in range(3)] == [program.name, PROGRAM, "2026-10-28"]
    assert [t1.cell(i, 0).text for i in range(3)] == ["Program", "Program id", "As of"]


def test_4_data_rows_are_text_through_TEXT_FORMATS_and_rows_were_appended(fmt_profiles, tmp_path):
    _, _, doc = _docx_build(fmt_profiles, tmp_path)
    idx = _rows(IDX)
    periods = list(idx)
    t2 = doc.tables[1]
    assert len(periods) > 1, "the arm needs more periods than the template's one body row"
    assert len(t2.rows) == 1 + len(periods), "rows were not appended to fit"
    for i, p in enumerate(periods, start=1):
        assert [c.text for c in t2.rows[i].cells] == [
            p, "{:,.0f}".format(cdrl._norm(idx[p]["cum_bcws"])),
            "{:.3f}".format(cdrl._norm(idx[p]["cum_cpi"]))], p


def test_4_the_header_row_is_untouched(fmt_profiles, tmp_path):
    _, _, doc = _docx_build(fmt_profiles, tmp_path)
    assert [c.text for c in doc.tables[1].rows[0].cells] == HEAD


def test_4_the_template_run_style_survives(fmt_profiles, tmp_path):
    """The write replaces the first run's text, so a run's formatting is the template's."""
    ov = tmp_path / "styled"
    ov.mkdir()
    d = docx.Document()
    t = d.add_table(rows=1, cols=1)
    t.cell(0, 0).paragraphs[0].add_run("x").bold = True
    t.cell(0, 0).paragraphs[0].add_run("y")
    p = ov / "t.docx"
    d.save(str(p))
    cell = docx.Document(str(p)).tables[0].cell(0, 0)
    cdrl._set_cell_text(cell, "NEW")
    assert cell.text == "NEW" and cell.paragraphs[0].runs[0].bold is True


# -- arm 5: the hash, recomputed from the delivered file alone ----------------------------------

def _walk(node, pointer=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{pointer}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{pointer}/{i}")
    else:
        yield ["json", pointer, node]


def test_5_json_hash_from_the_object_alone(fmt_profiles, tmp_path):
    _, env, obj = _json_build(fmt_profiles, tmp_path)
    assert cdrl._sha(sorted(_walk(obj), key=lambda c: (c[0], c[1]))) == env["cells_sha256"]


def test_5_json_hash_with_an_absent_key(fmt_profiles, tmp_path):
    _, env, obj = _json_build(fmt_profiles, tmp_path, source=_drop_last_tcpi)
    assert cdrl._sha(sorted(_walk(obj), key=lambda c: (c[0], c[1]))) == env["cells_sha256"]


def test_5_csv_hash_from_every_non_empty_field(fmt_profiles, tmp_path):
    for src in (None, _drop_last_tcpi):
        out = tmp_path / ("a" if src is None else "b")
        _, env, _, got = _csv_build(fmt_profiles, out, **({} if src is None else {"source": src}))
        cells = [["csv", f"{get_column_letter(j)}{i}", t]
                 for i, line in enumerate(got, start=1) for j, t in enumerate(line, start=1) if t != ""]
        assert cdrl._sha(sorted(cells, key=lambda c: (c[0], c[1]))) == env["cells_sha256"]


def docx_claim(delivered: Path, template: Path) -> str:
    """The docx `cells_sha256` recomputed from the delivered file and its template alone: every
    cell whose text differs from the template's, as [T<n>, A1, text], sorted."""
    doc, tpl = docx.Document(str(delivered)), docx.Document(str(template))
    cells = []
    for n, table in enumerate(doc.tables, start=1):
        base = tpl.tables[n - 1]
        for i, row in enumerate(table.rows):
            for j, cell in enumerate(row.cells):
                was = base.cell(i, j).text if i < len(base.rows) else ""
                if cell.text != was:
                    cells.append([f"T{n}", f"{get_column_letter(j + 1)}{i + 1}", cell.text])
    assert cells
    return cdrl._sha(sorted(cells, key=lambda c: (c[0], c[1])))


def test_5_docx_hash_from_every_cell_that_differs_from_the_template(fmt_profiles, tmp_path):
    path, env, doc = _docx_build(fmt_profiles, tmp_path)
    assert docx_claim(path, fmt_profiles["fin_docx"].template_path) == env["cells_sha256"]


def test_5_the_csv_header_is_part_of_the_claim(fmt_profiles, tmp_path):
    _, env, _, got = _csv_build(fmt_profiles, tmp_path)
    body = [["csv", f"{get_column_letter(j)}{i}", t]
            for i, line in enumerate(got, start=1) if i > 1 for j, t in enumerate(line, start=1) if t]
    assert cdrl._sha(sorted(body, key=lambda c: (c[0], c[1]))) != env["cells_sha256"]


# -- arm 6: filename, media type and the closed set (engine) -------------------------------------

@pytest.fixture
def served(fmt_profiles, monkeypatch, tmp_path):
    d = Double()
    monkeypatch.setattr(engine, "can_view_program", d)
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(engine, "_repo_root", lambda: root)
    with TestClient(engine.app) as c:
        yield c, root / "dist", d


def _post(c, profile, user=ALICE):
    return c.post("/cdrl_export", json={"profile": profile, "program_id": PROGRAM, "user_email": user})


EXPECT = {
    "cdrl_a001_ev_summary": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    JSON_NAME: ("json", "application/json"),
    "fin_csv": ("csv", "text/csv; charset=utf-8"),
    "fin_docx": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
}


def test_6_cdrl_export_names_the_file_by_the_profiles_format(served):
    c, dist, _ = served
    for name, (ext, _media) in EXPECT.items():
        r = _post(c, name)
        assert r.status_code == 200, (name, r.text)
        b = r.json()
        assert b["artifact_filename"] == f"fin-cdrl-{name}-{PROGRAM}.{ext}"
        assert b["envelope"]["format"] == ext
        assert (dist / b["artifact_filename"]).is_file()


def test_6_artifact_serves_a_member_with_the_formats_media_type_and_a_non_member_403(served, monkeypatch):
    c, dist, _ = served
    for name, (ext, media) in EXPECT.items():
        fname = _post(c, name).json()["artifact_filename"]
        assert c.get(f"/artifact/{fname}").status_code == 403, name       # no bearer: not a member
        with monkeypatch.context() as m:
            m.setattr(engine, "_current_caller", lambda: SimpleNamespace(authz_id=BOB))
            assert c.get(f"/artifact/{fname}").status_code == 403, name   # bearer, not a member
        with monkeypatch.context() as m:
            m.setattr(engine, "_current_caller", lambda: SimpleNamespace(authz_id=ALICE))
            r = c.get(f"/artifact/{fname}")
        assert r.status_code == 200, name
        assert r.headers["content-type"] == media, name
        assert r.content == (dist / fname).read_bytes()


def test_6_a_name_with_the_wrong_extension_for_that_profile_is_404(served, monkeypatch):
    c, _, _ = served
    _post(c, JSON_NAME)
    monkeypatch.setattr(engine, "_current_caller", lambda: SimpleNamespace(authz_id=ALICE))
    for ext in ("xlsx", "csv", "docx"):
        assert c.get(f"/artifact/fin-cdrl-{JSON_NAME}-{PROGRAM}.{ext}").status_code == 404, ext
    assert c.get(f"/artifact/fin-cdrl-{JSON_NAME}-{PROGRAM}.json").status_code == 200


def test_6_artifact_filename_is_the_one_place_a_file_is_named(fmt_profiles):
    for name, (ext, _m) in EXPECT.items():
        assert cdrl.artifact_filename(name, PROGRAM, fmt_profiles[name].format) == (
            f"fin-cdrl-{name}-{PROGRAM}.{ext}")
        assert engine._cdrl_artifact_program(f"fin-cdrl-{name}-{PROGRAM}.{ext}") == PROGRAM


# -- arm 7: the BFF -----------------------------------------------------------------------------

class _Resp:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = json.dumps(self._payload)
        self.content = content

    def json(self):
        return self._payload


class _User:
    authz_id = "alice@example.com"


class _Req:
    headers = {"authorization": "Bearer tok"}


CELLS = "cd" * 32


@pytest.fixture
def bff(monkeypatch):
    import iagent.gateway as gw

    calls, answers = [], {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append(("POST", url))
            return answers["post"]

        async def get(self, url, headers=None):
            calls.append(("GET", url))
            return _Resp(200, content=b"bytes")

    monkeypatch.setattr(gw.httpx, "AsyncClient", _Client)
    return gw, calls, answers


def _export(gw, answers, filename):
    answers["post"] = _Resp(200, {"artifact_filename": filename, "envelope": {"cells_sha256": CELLS}})
    try:
        return 200, asyncio.run(gw.export_cdrl(_Req(), "p", PROGRAM, _User()))
    except HTTPException as exc:
        return exc.status_code, exc.detail


@pytest.mark.parametrize("ext", ["csv", "docx", "json", "xlsx"])
def test_7_the_media_type_follows_the_extension_and_the_hash_header_is_set(bff, ext):
    gw, calls, answers = bff
    filename = f"fin-cdrl-p-{PROGRAM}.{ext}"
    status, resp = _export(gw, answers, filename)
    assert status == 200
    assert resp.media_type == dict(EXPECT.values())[ext]
    assert resp.headers["x-cells-sha256"] == CELLS
    assert resp.headers["content-disposition"] == f'attachment; filename="{filename}"'
    assert calls[1][1].endswith(f"/artifact/{filename}")


def test_7_a_pdf_filename_is_not_fetched(bff):
    gw, calls, answers = bff
    status, detail = _export(gw, answers, f"fin-cdrl-p-{PROGRAM}.pdf")
    assert status == 502 and detail["error"] == "fin_engine_bad_cdrl_response"
    assert len(calls) == 1
