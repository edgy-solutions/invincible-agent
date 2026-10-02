"""packageExport takes a CANVAS, and the alpha canvas exports the 09-06 alpha document.

THE DISPATCH (lane/74, 2026-09-30): packageExport takes a canvas (a list of answer artifacts plus
a recipient_scope), not a fixed question set, and the 09-06
`cost-validation-notional-customer-alpha.html` is the acceptance test: a canvas holding the alpha
customer's cost questions, exported, must produce that document from live data.

"THAT DOCUMENT" IS DEFINED IN `scripts/cost_package_identities.py`: same disclosure, same rows,
same manifest, same pricing module, same sections. The fixture was extracted from the 09-06 file
by that script (its provenance block names the file's sha256), not typed. What it does not
compare (file hash, locator, commit, date, the .duckdb container's bytes) is listed there with a
reason for each.

IF THIS GOES RED ON `manifest_modules` OR `manifest_checks`, pricing changed. A different
algorithm is a different document, so that red is correct. Re-extract only from a document
the new algorithm produced and a person accepted, never from this test's own output.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_cost_package as B  # noqa: E402
import cost_package_identities as I  # noqa: E402

from agent_fleet.cost_agent import canvas as C  # noqa: E402
from agent_fleet.cost_agent import export as X  # noqa: E402
from agent_fleet.cost_agent import measures as M  # noqa: E402
from agent_fleet.cost_agent.seed import build_state, lots_for_recipient  # noqa: E402

FIXTURE = json.loads(
    (ROOT / "tests" / "fixtures" / "cost_alpha_2026_09_06_identities.json").read_text("utf-8"))
ALPHA = "notional-customer-alpha"
MESH = C.MESH


def _a(aid, verb, subject=None):
    return {"id": aid, "verb_iri": f"mesh:{verb}", "subject_instance_id": subject}


#: The alpha customer's cost questions, one answer per exportable verb, spread over their lots.
#: The shape is the bff's ArtifactResponse fields for an answer on a board.
ALPHA_CANVAS = {"answers": [
    _a("ans-labor-1", "costLaborComposition", 1),
    _a("ans-trend", "costUnitPriceTrend"),
    _a("ans-price-2", "costPriceComposition", 2),
    _a("ans-breakdown-3", "costLotBreakdown", "3"),
    _a("ans-category-4", "costCategoryBreakdown", 4),
    _a("ans-rates-5", "costRateComparison", 5),
    _a("ans-suppliers-3", "costSupplierConcentration", 3),
    _a("ans-assumptions", "costRateAssumptions"),
]}


@pytest.fixture(scope="module")
def state():
    return build_state()


def _resolve(canvas, scope=ALPHA):
    return C.resolve(canvas, recipient_scope=scope, entitled_lots=lots_for_recipient(scope))


def _dataset_package(state, composed):
    return X.build_dataset_package(
        state, recipient_scope=ALPHA, algorithm_sha="test", duckdb_path="unused.duckdb",
        duckdb_hash="sha256:unused", lots=composed["lots"], sections=composed["sections"],
        canvas_answers=composed["answers"])


# ── THE ACCEPTANCE ──────────────────────────────────────────────────────────────────────


def test_the_fixture_is_the_09_06_document():
    """Provenance, so the fixture cannot quietly become some other file's identities."""
    p = FIXTURE["provenance"]
    assert p["source_file"] == "cost-validation-notional-customer-alpha.html"
    assert p["source_file_sha256"] == (
        "sha256:63b58d9a3d672238d6d82bd66216d33221c759c2079f1acb2f2472f5409c5123")
    assert p["as_of"] == "2026-09-06" and p["recipient_scope"] == ALPHA


@pytest.mark.skipif(not os.environ.get("COST_ALPHA_0906_HTML"),
                    reason="set COST_ALPHA_0906_HTML to the 09-06 document to re-derive")
def test_the_fixture_re_derives_from_the_document():
    assert I.extract(pathlib.Path(os.environ["COST_ALPHA_0906_HTML"])) == FIXTURE


def test_the_alpha_canvas_resolves_to_the_whole_alpha_disclosure():
    composed = _resolve(ALPHA_CANVAS)
    assert composed["lots"] == tuple(FIXTURE["identities"]["lots"])
    assert composed["sections"] == tuple(FIXTURE["sections"])
    assert composed["answers"] == [a["id"] for a in ALPHA_CANVAS["answers"]]


def test_the_alpha_canvas_package_IS_the_09_06_document(state):
    """THE ACCEPTANCE, at the package: the served state, composed by the canvas, carries the
    09-06 document's data, manifest and sections."""
    pkg = _dataset_package(state, _resolve(ALPHA_CANVAS))
    assert I.identities(pkg) == FIXTURE["identities"]
    assert pkg["sections"] == FIXTURE["sections"]
    assert pkg["canvas_answers"] == [a["id"] for a in ALPHA_CANVAS["answers"]]


def test_the_VERB_exports_the_alpha_canvas_as_the_09_06_document(state, isolated_dist):
    """THE ACCEPTANCE, end to end: the verb, the real builder, DuckDB and the Pyodide page,
    read back off the disk it wrote."""
    pytest.importorskip("duckdb")
    if not (ROOT / ".pyodide-cache" / "pyodide.js").exists():
        pytest.skip("the pinned Pyodide runtime is not fetched here")
    out = M.package_export(state, recipient_scope=ALPHA, canvas=ALPHA_CANVAS)
    ids = [a["id"] for a in ALPHA_CANVAS["answers"]]
    assert out["lots_disclosed"] == FIXTURE["identities"]["lots"]
    assert out["sections"] == FIXTURE["sections"]
    assert out["canvas_answers"] == ids and out["audit"]["canvas_answers"] == ids
    assert out["rows_sha256"] == FIXTURE["identities"]["rows_sha256"]

    html = (isolated_dist / out["artifact_filename"]).read_text(encoding="utf-8")
    assert I.identities(I.package_from_html(html)) == FIXTURE["identities"]
    assert I.sections_from_html(html) == FIXTURE["sections"]
    assert B.check_javascript(html) == []


def test_the_VERB_narrows_the_page_it_writes_not_only_its_response(state, isolated_dist):
    """The response and the file are built by two calls; both must take the canvas."""
    pytest.importorskip("duckdb")
    if not (ROOT / ".pyodide-cache" / "pyodide.js").exists():
        pytest.skip("the pinned Pyodide runtime is not fetched here")
    import duckdb

    out = M.package_export(state, recipient_scope=ALPHA,
                           canvas={"answers": [_a("only", "costLaborComposition", 3)]})
    assert out["lots_disclosed"] == [3] and out["sections"] == ["labor", "sepm"]
    html = (isolated_dist / out["artifact_filename"]).read_text(encoding="utf-8")
    assert I.package_from_html(html)["lots"] == [3]
    assert I.sections_from_html(html) == ["labor", "sepm"]
    con = duckdb.connect(str(isolated_dist / out["dataset_filename"]), read_only=True)
    try:
        assert [r[0] for r in con.execute("SELECT DISTINCT lot FROM results").fetchall()] == [3]
    finally:
        con.close()


# ── A CANVAS NARROWS ────────────────────────────────────────────────────────────────────


def test_one_labor_answer_discloses_one_lot_and_shows_its_two_sections(state):
    composed = _resolve({"answers": [_a("only", "costLaborComposition", 3)]})
    assert composed == {"lots": (3,), "sections": ("labor", "sepm"), "answers": ["only"]}
    pkg = _dataset_package(state, composed)
    assert pkg["lots"] == [3]
    assert [c["lot"] for c in pkg["manifest"]["checks"]] == [3]
    assert {r["lot"] for r in pkg["dataset"]["rows"]["lots"]} == {3}
    assert {r["lot"] for r in pkg["dataset"]["rows"]["results"]} == {3}


def test_a_lot_rides_WHOLE_whichever_sections_show(state):
    """The manifest reprices a lot from all of its inputs, so the rows are the lot's, not the
    section's. A labor-only canvas carries lot 3's material rows too (canvas.py says why)."""
    labor = _dataset_package(state, _resolve({"answers": [_a("l", "costLaborComposition", 3)]}))
    material = _dataset_package(
        state, _resolve({"answers": [_a("m", "costCategoryBreakdown", 3)]}))
    assert labor["dataset"]["rows_sha256"] == material["dataset"]["rows_sha256"]


def test_a_program_wide_answer_discloses_every_entitled_lot():
    composed = _resolve({"answers": [_a("t", "costUnitPriceTrend")]})
    assert composed["lots"] == lots_for_recipient(ALPHA)
    assert composed["sections"] == ("program",)


def test_an_assumptions_answer_adds_a_section_and_no_lot():
    composed = _resolve({"answers": [_a("r", "costRateAssumptions"),
                                     _a("l", "costLaborComposition", 2)]})
    assert composed["lots"] == (2,)
    assert composed["sections"] == ("labor", "sepm", "scenario")


def test_the_subject_may_be_a_digit_string_or_a_full_mesh_IRI():
    composed = _resolve({"answers": [
        {"id": "a", "verb_iri": MESH + "costLotBreakdown", "subject_instance_id": " 4 "}]})
    assert composed["lots"] == (4,)


def test_the_page_carries_only_the_canvas_sections(state, tmp_path):
    pytest.importorskip("duckdb")
    if not (ROOT / ".pyodide-cache" / "pyodide.js").exists():
        pytest.skip("the pinned Pyodide runtime is not fetched here")
    import build_cost_dataset as D

    db = D.build(ALPHA, tmp_path / f"cost-{ALPHA}.duckdb", state=state, lots=(3,))
    html = B.build_html(ALPHA, ROOT / ".pyodide-cache", duckdb_path=db, state=state,
                        lots=(3,), sections=("labor", "sepm"), canvas_answers=["only"])
    assert I.sections_from_html(html) == ["labor", "sepm"]
    for gone in ('id="program-chart"', 'id="composition"', 'id="material-table"',
                 'id="scenario-metrics"', 'id="threshold"', 'id="slope"'):
        assert gone not in html, gone
    for kept in ('id="metrics"', 'id="sepm-metrics"', 'id="algorithm"'):
        assert kept in html, kept
    assert B.check_javascript(html) == []
    import duckdb

    con = duckdb.connect(str(db), read_only=True)
    try:
        assert [r[0] for r in con.execute("SELECT lot FROM lots").fetchall()] == [3]
    finally:
        con.close()


# ── REFUSED, NEVER DROPPED ──────────────────────────────────────────────────────────────


def test_a_lot_outside_the_recipients_scope_is_UNENTITLED_and_named():
    canvas = {"answers": [_a("mine", "costLaborComposition", 2),
                          _a("theirs", "costLaborComposition", 7)]}
    with pytest.raises(C.Unentitled, match=r"theirs \(lot 7\)"):
        _resolve(canvas)


def test_a_lot_not_in_the_model_is_UNENTITLED_too_so_scope_does_not_reveal_existence():
    with pytest.raises(C.Unentitled):
        _resolve({"answers": [_a("x", "costLaborComposition", 99)]})


def test_entitlement_is_decided_BEFORE_exportability():
    canvas = {"answers": [_a("bad", "seedCanvas"), _a("theirs", "costLotBreakdown", 8)]}
    with pytest.raises(C.Unentitled):
        _resolve(canvas)


@pytest.mark.parametrize("canvas,match", [
    (None, "a canvas is"),
    ({"answers": "ans-1"}, "a canvas is"),
    ({"answers": []}, "holds no answers"),
    ({"answers": [{"verb_iri": "mesh:costLotBreakdown"}]}, "carries no id"),
    ({"answers": [_a("d", "costLotBreakdown", 1), _a("d", "costLotBreakdown", 2)]},
     "appears twice"),
    ({"answers": [_a("s", "seedCanvas", 1)]}, "not cost answers"),
    ({"answers": [{"id": "q", "verb_iri": "costLotBreakdown", "subject_instance_id": 1}]},
     "not cost answers"),
    ({"answers": [_a("n", "costLotBreakdown")]}, "name none"),
    ({"answers": [_a("b", "costLotBreakdown", True)]}, "name none"),
    ({"answers": [_a("r", "costRateAssumptions")]}, "verify nothing"),
    ({"answers": [_a("p", "packageExport")]}, "not cost answers"),
])
def test_a_canvas_this_engine_cannot_export_is_NOT_IN_MODEL_by_name(canvas, match):
    with pytest.raises(C.NotInModel, match=match):
        _resolve(canvas)


def test_the_VERB_refuses_a_canvas_with_the_fixed_page(state, isolated_dist):
    with pytest.raises(M.NotInModel, match="include_dataset=false"):
        M.package_export(state, recipient_scope=ALPHA, canvas=ALPHA_CANVAS,
                         include_dataset=False)


def test_the_VERB_refuses_an_unentitled_canvas_before_building(state, monkeypatch, isolated_dist):
    monkeypatch.setattr(M, "_repo_root", lambda: pytest.fail("built before refusing"))
    with pytest.raises(M.Unentitled):
        M.package_export(state, recipient_scope=ALPHA,
                         canvas={"answers": [_a("t", "costLotBreakdown", 6)]})


def test_the_builders_narrow_and_never_widen(state):
    with pytest.raises(X.Unentitled):
        X.build_package(state, recipient_scope=ALPHA, algorithm_sha="t", lots=(5, 6))
    with pytest.raises(X.Unentitled):
        X.build_package(state, recipient_scope=ALPHA, algorithm_sha="t", lots=())
    with pytest.raises(ValueError):
        X.build_package(state, recipient_scope=ALPHA, algorithm_sha="t", sections=("charts",))
    pkg = X.build_package(state, recipient_scope=ALPHA, algorithm_sha="t", lots=(4, 2))
    assert pkg["lots"] == [2, 4]


# ── JOINS: the tables this rests on agree with what they describe ──────────────────────


def test_EXPORTABLE_is_exactly_the_engines_answering_verbs():
    from agent_fleet.cost_agent.main import CATALOGUE

    served = {e["verb"].split(":", 1)[1]: e["fn"] for e in CATALOGUE}
    served.pop("packageExport")
    assert {v: row["fn"] for v, row in C.EXPORTABLE.items()} == served


def test_every_section_is_reachable_and_every_row_names_real_sections():
    named = {s for row in C.EXPORTABLE.values() for s in row["sections"]}
    assert named == set(C.SECTIONS)


def test_the_page_template_marks_every_section_exactly_once():
    for name in C.SECTIONS:
        assert B.SLICE2_TEMPLATE.count(f"<!-- section:{name} -->") == 1, name
        assert B.SLICE2_TEMPLATE.count(f"<!-- /section:{name} -->") == 1, name


def test_a_lost_section_marker_REFUSES_the_build():
    broken = B.SLICE2_TEMPLATE.replace("<!-- /section:material -->", "", 1)
    with pytest.raises(SystemExit, match="material"):
        B.select_sections(broken, C.SECTIONS)


def test_the_algorithm_panel_survives_every_selection():
    for name in C.SECTIONS:
        assert 'id="algorithm"' in B.select_sections(B.SLICE2_TEMPLATE, (name,))


def test_the_canvas_is_a_HANDLE_slot_and_recipient_stays_the_only_mandatory_one():
    from agent_fleet.cost_agent.slots import mandatory_slots, slots_for

    decl = {s["name"]: s for s in slots_for("package_export")}["canvas"]
    assert decl["kind"] == "handle" and decl["type"] == "object"
    assert decl["required"] is False and "referent" not in decl
    assert mandatory_slots("package_export") == ["recipient_scope"]
