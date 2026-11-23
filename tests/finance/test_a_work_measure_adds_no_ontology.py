"""A deployment that declares a measure adds no ontology: every declared measure is ONE class.

WHY (ruled by Chris, 2026-11-02): "One shared class for every declared measure
(fin#DeclaredMeasureSeries with the measure id as a property) so work adds no ontology."
Before, a row named an `output_uri`, so each new measure needed a new `owl:Class` in
`finance_extension.ttl`, a re-prime, and a platform-team edit -- and Contract D refused the whole
registration batch (built-ins included) until all three had happened. Now the class is shared and the
measure is told apart by its id, which the wire already carries as the envelope's `measure` and
`method.measure_id`.

Arms:
  a  a row under a NEW measure id and verb, with no ttl edit, registers with the shared class, and
     that class is declared in the ttl (read from the PARSE, not grepped out of the code);
  b  a row that still carries `outputs.output_uri` is refused, naming the file;
  c  two declared rows answer with the same `output_uri` and DIFFERENT `measure` and
     `method.measure_id`, each equal to its row; each registration keeps its own verb and endpoint;
  d  `fin:measureId` is declared, with the shared class as its domain;
  e  the ttl declares no per-measure class: the two sample ones are gone;
  f  presentation picks the shape from `render` with the shared class as output_uri, for both rows.

Run: uv run --no-sync pytest tests/finance/test_a_work_measure_adds_no_ontology.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent import measure_verbs, measures, seed  # noqa: E402

SAMPLE = REPO / "policy" / "overlays" / "sample" / "measure_verbs"
TCPI_ROW = SAMPLE / "fin_tcpi.yaml"
TTL = REPO / "setup" / "ontologies" / "finance_extension.ttl"
MESH_TTL = REPO / "setup" / "ontologies" / "mesh_system.ttl"
SHARED = measures.FIN + "DeclaredMeasureSeries"
PROGRAM = seed.PROGRAM_ID
ALICE = "alice@example.com"
BUILTINS = (measures.OUTPUT_URI, [v["verb"].split(":", 1)[-1] for v in engine.VERBS])


def _parse(*paths):
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    for p in paths:
        g.parse(str(p), format="turtle")
    return g, rdflib


def _classes(*paths):
    g, rdflib = _parse(*paths)
    return {str(s) for s in g.subjects(rdflib.RDF.type, rdflib.OWL.Class)}


def _new_row(tmp_path, measure_id="fin_work_made_up", verb="finWorkMadeUp"):
    raw = yaml.safe_load(TCPI_ROW.read_text(encoding="utf-8"))
    raw["measure_id"], raw["verb"] = measure_id, verb
    d = tmp_path / "ov"
    d.mkdir(exist_ok=True)
    (d / f"{measure_id}.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return d, raw


def _load(overlay_dirs, tmp_path):
    return measure_verbs.load_measure_verbs(
        policy_dir=tmp_path / "no-seed", overlay_dirs=list(overlay_dirs), builtins=BUILTINS)


# -- a ----------------------------------------------------------------------------------------

def test_a_a_new_measure_registers_with_the_shared_class_and_no_ttl_edit(tmp_path, monkeypatch):
    before = TTL.read_bytes()
    d, raw = _new_row(tmp_path)
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(d))
    declared = engine._load_declared()
    assert list(declared) == [raw["measure_id"]]
    monkeypatch.setattr(engine, "DECLARED", declared)
    call = next(c for c in engine._registration_calls()
                if c["verb"] == "mesh:" + raw["verb"])
    assert call["output_uri"] == SHARED
    assert call["fn"] == raw["measure_id"]
    declared_classes = _classes(TTL, MESH_TTL)
    # Contract D: BOTH ends of the edge are declared owl:Class in a seeded ttl
    assert SHARED in declared_classes, "the shared class is declared in the ttl, read from the parse"
    assert call["input_uri"] in declared_classes, call["input_uri"]
    assert TTL.read_bytes() == before, "the test edits no ontology"


# -- b ----------------------------------------------------------------------------------------

def test_b_a_row_that_names_a_class_is_refused_naming_the_file(tmp_path):
    d, raw = _new_row(tmp_path)
    (d / "fin_work_made_up.yaml").unlink()
    raw["outputs"]["output_uri"] = "AnotherSeries"
    (d / "bad.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(measure_verbs.MeasureVerbError) as ei:
        _load([d], tmp_path)
    msg = str(ei.value)
    assert "bad.yaml" in msg
    assert "DeclaredMeasureSeries" in msg and "output_uri" in msg


def test_b_the_control_is_the_same_row_without_the_key(tmp_path):
    d, raw = _new_row(tmp_path)
    assert "output_uri" not in raw["outputs"]
    assert [r.measure_id for r in _load([d], tmp_path)] == ["fin_work_made_up"]


# -- c ----------------------------------------------------------------------------------------

@pytest.fixture
def two_declared(monkeypatch):
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(SAMPLE))
    # State-kind rows, answered by name. A dataset row is served only to a bearer holding the asset
    # grant; its class is asserted where it is served (test_variance_decomposition_over_the_ev_fixture).
    declared = {fn: r for fn, r in engine._load_declared().items()
                if r.kind != measure_verbs.KIND_DATASET}
    assert len(declared) >= 2
    monkeypatch.setattr(engine, "DECLARED", declared)
    monkeypatch.setattr(engine, "can_view_program", lambda *a, **k: True)
    return declared


def test_c_two_rows_answer_with_one_class_and_two_measure_ids(two_declared):
    seen = {}
    with TestClient(engine.app) as c:
        for fn, row in two_declared.items():
            r = c.post(f"/measure/{fn}",
                       json={"params": {"program_id": PROGRAM}, "user_email": ALICE})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["output_uri"] == SHARED, fn
            assert body["measure"] == row.measure_id == fn
            assert body["method"]["measure_id"] == row.measure_id
            seen[fn] = body
    assert len({b["output_uri"] for b in seen.values()}) == 1
    assert len({b["measure"] for b in seen.values()}) == len(two_declared)
    assert len({b["method"]["measure_id"] for b in seen.values()}) == len(two_declared)


def test_c_each_registration_keeps_its_own_verb_and_endpoint(two_declared):
    calls = [c for c in engine._registration_calls()
             if c["fn"] in two_declared]
    assert len(calls) == len(two_declared)
    assert {c["output_uri"] for c in calls} == {SHARED}
    for c in calls:
        row = two_declared[c["fn"]]
        assert c["verb"] == "mesh:" + row.verb
        assert c["fn"] == row.measure_id
    assert len({c["verb"] for c in calls}) == len(calls)
    assert len({c["fn"] for c in calls}) == len(calls)


# -- d / e ------------------------------------------------------------------------------------

def test_d_measure_id_is_a_declared_property_of_the_shared_class():
    g, rdflib = _parse(TTL)
    prop = rdflib.URIRef(measures.FIN + "measureId")
    assert (prop, rdflib.RDF.type, rdflib.OWL.DatatypeProperty) in g
    assert (prop, rdflib.RDFS.domain, rdflib.URIRef(SHARED)) in g
    assert (prop, rdflib.RDFS.range, rdflib.XSD.string) in g
    assert (rdflib.URIRef(SHARED), rdflib.RDFS.subClassOf,
            rdflib.URIRef("http://invincible-agent/mesh#Response")) in g


def test_e_the_ttl_declares_no_per_measure_class():
    classes = _classes(TTL)
    assert SHARED in classes
    for gone in ("ToCompletePerformanceIndexSeries", "VarianceAtCompletionSeries"):
        assert measures.FIN + gone not in classes, gone


# -- f ----------------------------------------------------------------------------------------

def test_f_presentation_picks_the_shape_from_render_with_the_shared_class(two_declared, monkeypatch):
    sys.path.insert(0, str(REPO / "agent_fleet" / "presentation_agent"))
    cr = pytest.importorskip("capability_registry")
    out_uri = "fin:DeclaredMeasureSeries"
    caps = [{"archetype": s, "subject_uri": "http://invincible-agent/mesh#SomeBuiltinClass"}
            for s in {r.archetype for r in two_declared.values()}]
    assert caps, "no declared shape"
    menu = {"frontend_id": "fe", "frontend_version": "1", "capabilities": caps}
    monkeypatch.setattr(cr, "menu_for", lambda fid, *_a: menu)
    payload = {"chart_data": None, "chart_type": None}
    for fn, row in two_declared.items():
        # the control: with no declaration the shared class is on no menu
        assert cr.select_presentation("fe", out_uri, payload)[0] is None, fn
        cap, prov = cr.select_by_declared_shape("fe", row.archetype, payload, output_uri=out_uri)
        assert cap is not None and cap["archetype"] == row.archetype, fn
        assert prov["selection_basis"] == "declared_render"
