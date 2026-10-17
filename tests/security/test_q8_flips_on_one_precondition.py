"""RULING Q8 (2026-10-10) is sealed behind ONE precondition: `SEED_PROVENANCE_STAMPED`.

Q8: "no provenance_ingest_id and no seed provenance -> unresolved -> withheld", PARKED until
doc-tools stamps seed provenance. Until then no provenance reads as seeded. Two branches decide
"seeded" -- `source_visibility` (no `provenance_ingest_id`) and `visible_notice_ids` (a notice IRI
with no Neo4j row) -- and they must flip TOGETHER. Both read `_unstamped_reads_as_seeded()`.
"""
from __future__ import annotations

import ast
import inspect
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

pytest.importorskip("rdflib", reason="the agent-fleet extra carries rdflib")

from agent_fleet.ontology_service import notice_parts as np_mod  # noqa: E402

NB = "http://internal/sustainment/doc/"
NOTICE_CLASS = "http://internal/sustainment/pcn#ProductChangeNotice"
TABLE = {"SUSTAINMENT": frozenset({"SUSTAINMENT"})}
HELPER = "_unstamped_reads_as_seeded"


def _seeded_row(nid):
    return {"notice": {"id": nid, "type": "PCN", "mfr": "ACME"}, "mpns": ["5530-1"], "total": 1,
            "dropped_by": None, "has_artifact": False, "promoted": False, "promoted_by": None}


class _Rec:
    def __init__(self, d):
        self._d = d

    def data(self):
        return dict(self._d)


class _Driver:
    def __init__(self, rows):
        self.rows = rows

    def session(self, **kw):
        drv = self

        class _S:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def run(self, cypher, params=None, **kw2):
                missing = set(re.findall(r"\$(\w+)", cypher)) - set(params or {})
                assert not missing, f"statement run without ${sorted(missing)}"
                nid = params["notice_id"]
                return [_Rec(drv.rows[nid])] if nid in drv.rows else []
        return _S()


class _Jena:
    def __init__(self, instances):
        self.instances = list(instances)

    async def __call__(self, query, domain="MAINTENANCE", **kw):
        return list(self.instances)


@pytest.fixture()
def resolve(monkeypatch):
    from fastapi.testclient import TestClient
    from agent_fleet.ontology_service import main as mod
    monkeypatch.setattr(mod, "_load_domain_consumption_for_notice_parts", lambda: TABLE)
    monkeypatch.setattr(mod, "_notice_parts_can_view_program", lambda program, caller: True)

    def _go(nid, rows):
        monkeypatch.setattr(mod, "execute_sparql",
                            _Jena([{"s": NB + nid, "type": NOTICE_CLASS}]))
        monkeypatch.setattr(mod, "_NEO4J_DRIVER", _Driver(rows))
        r = TestClient(mod.app).post("/resolve_instance", json={
            "identifier": nid, "user_email": "steward@example.com",
            "entitled_domains": ["SUSTAINMENT"]})
        assert r.status_code == 200, r.text
        return [c["instance_id"] for c in r.json()["candidates"]]
    return _go


def _read_answers(nid):
    out = np_mod.read_notice_parts(
        _Driver({nid: _seeded_row(nid)}), nid, caller_id="steward@example.com",
        viewer_domains=("SUSTAINMENT",), table=TABLE, can_view_program=lambda p, c: True)
    return out.get("status") == "ok"


# -- the default ---------------------------------------------------------------------------------

def test_the_precondition_is_off_and_names_q8():
    assert np_mod.SEED_PROVENANCE_STAMPED is False
    assert "Q8" in inspect.getsource(np_mod)


# -- today: no provenance reads as seeded --------------------------------------------------------

def test_today_a_no_provenance_notice_is_visible_on_both_callers(resolve):
    assert _read_answers("PCN-S1") is True
    assert resolve("PCN-S1", {"PCN-S1": _seeded_row("PCN-S1")}) == [NB + "PCN-S1"]


def test_today_a_notice_iri_with_no_graph_row_is_kept(resolve):
    assert resolve("PCN-N1", {}) == [NB + "PCN-N1"]


# -- flipped: both withheld, together --------------------------------------------------------------

def test_flipped_a_no_provenance_notice_is_withheld_on_both_callers(resolve, monkeypatch):
    monkeypatch.setattr(np_mod, "SEED_PROVENANCE_STAMPED", True)
    assert _read_answers("PCN-S1") is False
    assert resolve("PCN-S1", {"PCN-S1": _seeded_row("PCN-S1")}) == []


def test_flipped_a_notice_iri_with_no_graph_row_is_withheld(resolve, monkeypatch):
    monkeypatch.setattr(np_mod, "SEED_PROVENANCE_STAMPED", True)
    assert resolve("PCN-N1", {}) == []


# -- one precondition: every decision site consults the helper -------------------------------------

def _functions_calling(tree, name):
    out = set()
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for n in ast.walk(fn):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id == name):
                    out.add(fn.name)
    return out


def _functions_with_literal(tree, literal):
    out = set()
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for n in ast.walk(fn):
                if isinstance(n, ast.Constant) and n.value == literal:
                    out.add(fn.name)
    return out


def test_every_decision_site_goes_through_the_one_helper():
    callers = {}
    deciders = set()
    for path in (Path(np_mod.__file__),
                 Path(np_mod.__file__).with_name("main.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        callers.update({k: path for k in _functions_calling(tree, HELPER)})
        deciders |= _functions_with_literal(tree, "provenance_ingest_id")
    # the two branches that decide "seeded"
    deciders |= {"visible_notice_ids"}
    missing = sorted(d for d in deciders if d not in callers)
    assert not missing, f"decide 'seeded' without {HELPER}: {missing}"
    assert {"source_visibility", "visible_notice_ids"} <= set(callers)
