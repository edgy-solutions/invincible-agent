"""The Engine W identity census (scripts/probes/engine_w_identity_census.py) must red on every
way the two retrieval paths can disagree about WHO MAY READ WHAT, and must not green on a census
that compared nothing.

The census has two halves: a RUN inside the Engine W container (one per value of
``KNOWLEDGE_SEARCH_VIA_MESH``) and a DIFF of the two JSON files. Neither half can be run against
the live gate from here, so this file seals:

* the DIFF on fixtures, every red with the one-change control that greens it;
* the RUN against a stand-in ``service`` module: it refuses a flag its label does not claim, refuses
  a gate with auth off, records a refusal as a datum, and records when its own search-then-gate
  disagrees with ``retrieve_gated_chunks``;
* the census's SOURCE LABEL against the keys ``_gate_hits`` actually reads, out of service.py --
  the run's cross-check compares positions and cannot see a label drift.

Run: uv run --frozen pytest tests/test_engine_w_identity_census.py -v
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CENSUS = _ROOT / "scripts" / "probes" / "engine_w_identity_census.py"
_SERVICE = _ROOT / "agent_fleet" / "weaviate_expert" / "service.py"


def _load():
    spec = importlib.util.spec_from_file_location("_w_census_under_test", _CENSUS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = _load()
Q = ("MAINTENANCE", "fuel pump failure modes")


def _hits(*pairs):
    return [{"pos": i, "source": s, "kept": k} for i, (s, k) in enumerate(pairs)]


def _c(identity, kind, hits=(), refused=None):
    return {"identity": identity, "kind": kind, "domain": Q[0], "query": Q[1],
            "refused": refused, "hits": list(hits),
            "agrees_with_live": None if refused else True}


def _pair():
    """A GREEN census: one granted identity keeps doc-a and is denied doc-b on both paths; the
    mesh path also retrieved doc-c (retrieval, not the gate); the deny control keeps nothing; the
    empty caller is the ruled difference."""
    off = {"census": "engine-w-identity", "label": "off", "flag": False,
           "collection": "DocumentChunks", "cells": [
               _c("a@x", "real", _hits(("doc-a", True), ("doc-b", False))),
               _c(C.DENY_CONTROL, "deny", _hits(("doc-a", False))),
               _c("", "empty", _hits(("doc-a", False)))]}
    on = {"census": "engine-w-identity", "label": "on", "flag": True,
          "collection": "DocumentChunks", "cells": [
              _c("a@x", "real", _hits(("doc-a", True), ("doc-b", False), ("doc-c", True))),
              _c(C.DENY_CONTROL, "deny", _hits(("doc-a", False))),
              _c("", "empty", refused="ValueError: Initiator.subject is required")]}
    return off, on


def _cell(doc, kind):
    return next(c for c in doc["cells"] if c["kind"] == kind)


def test_CONTROL_THE_RULED_SHAPE_IS_GREEN_AND_SAYS_WHAT_IT_COMPARED():
    reds, notes = C.diff(*_pair())
    assert reds == []
    assert any("3 shared" in n and "1 kept by a real identity" in n for n in notes), notes
    assert any("retrieved by one path only" in n and "doc-c" in n for n in notes), notes


def _red(mutate, fragment):
    off, on = _pair()
    mutate(off, on)
    reds, _ = C.diff(off, on)
    assert any(fragment in r for r in reds), reds
    return reds


def test_A_SHARED_SOURCE_DECIDED_DIFFERENTLY_IS_RED():
    def m(off, on):
        _cell(on, "real")["hits"][1]["kept"] = True          # doc-b now kept on the mesh path
    _red(m, "source 'doc-b' kept=[False] off, kept=[True] on")


@pytest.mark.parametrize("side", ["off", "on"])
def test_THE_DENY_CONTROL_KEEPING_ANYTHING_IS_RED_ON_EITHER_PATH(side):
    def m(off, on):
        _cell(off if side == "off" else on, "deny")["hits"][0]["kept"] = True
    _red(m, f"the deny control kept [('{side}', 'doc-a')]")


def test_A_SOURCE_KEPT_AND_DROPPED_IN_ONE_RUN_IS_RED():
    def m(off, on):
        _cell(off, "real")["hits"].append({"pos": 2, "source": "doc-a", "kept": False})
    _red(m, "on off, sources both kept and dropped: ['doc-a']")


def test_A_RUN_THAT_DISAGREES_WITH_THE_LIVE_FUNCTION_IS_RED():
    def m(off, on):
        _cell(on, "real")["agrees_with_live"] = False
    _red(m, "the on run's replication disagrees with retrieve_gated_chunks")


def test_A_REAL_IDENTITY_WHOSE_SEARCH_DID_NOT_RUN_IS_RED():
    def m(off, on):
        _cell(on, "real").update(refused="RuntimeError: mesh unreachable", hits=[],
                                 agrees_with_live=None)
    _red(m, "the search did not run: off=None on='RuntimeError: mesh unreachable'")


@pytest.mark.parametrize("change, fragment", [
    (lambda off, on: _cell(off, "empty").update(refused="boom", hits=[]), "OFF should search"),
    (lambda off, on: _cell(off, "empty")["hits"][0].update(kept=True), "OFF should search"),
    (lambda off, on: _cell(on, "empty").update(refused=None, hits=_hits(("doc-a", False))),
     "ON should be refused by the SDK's Initiator"),
], ids=["off-refused", "off-kept", "on-searched"])
def test_THE_EMPTY_CALLER_MAY_DIFFER_ONLY_AS_RULED(change, fragment):
    _red(change, fragment)


def test_A_CENSUS_THAT_SHARED_NO_SOURCE_IS_RED_NOT_GREEN():
    def m(off, on):
        for doc in (off, on):
            for c in doc["cells"]:
                if c["kind"] in ("real", "deny"):
                    for h in c["hits"]:
                        h["source"] = f"{h['source']}-{doc['label']}"
    _red(m, "POPULATION: no source was retrieved by both paths")


def test_PARITY_ON_A_GATE_THAT_KEEPS_NOTHING_IS_RED():
    def m(off, on):
        for doc in (off, on):
            for h in _cell(doc, "real")["hits"]:
                h["kept"] = False
    reds = _red(m, "POPULATION: no real identity kept any shared source")
    assert len(reds) == 1, reds        # every decision agreed: the population is the only red


@pytest.mark.parametrize("change, fragment", [
    (lambda off, on: on["cells"].pop(0), "two different censuses"),
    (lambda off, on: on.update(collection="Other"), "two different censuses"),
    (lambda off, on: on.update(flag=False), "the on file is not an Engine W census run"),
    (lambda off, on: off.update(label="on"), "the off file is not an Engine W census run"),
], ids=["cells", "collection", "on-flag", "off-label"])
def test_TWO_RUNS_THAT_ARE_NOT_ONE_CENSUS_ARE_REFUSED(change, fragment):
    _red(change, fragment)


def test_THE_DIFF_EXITS_ON_ITS_REDS(tmp_path, capsys):
    off, on = _pair()
    (tmp_path / "off.json").write_text(json.dumps(off))
    (tmp_path / "on.json").write_text(json.dumps(on))
    assert C.main(["diff", str(tmp_path / "off.json"), str(tmp_path / "on.json")]) == 0
    _cell(on, "deny")["hits"][0]["kept"] = True
    (tmp_path / "on.json").write_text(json.dumps(on))
    assert C.main(["diff", str(tmp_path / "off.json"), str(tmp_path / "on.json")]) == 1
    assert "RED   " in capsys.readouterr().out


# -- the RUN half, against a stand-in for the container's service module -----------------------

class _Obj:
    def __init__(self, **props):
        self.properties = props


def _service(flag, *, auth=True, granted=("a@x",), live_drift=False):
    """A stand-in with service.py's surface. The gate reads ``source_url`` and lets a granted
    caller read doc-a only. ``live_drift`` makes retrieve_gated_chunks keep every chunk -- a live
    function the census's replication no longer speaks for."""
    s = types.ModuleType("service")
    s.KNOWLEDGE_SEARCH_VIA_MESH = flag
    s.ENABLE_AGENTIC_AUTH = auth
    rows = [_Obj(source_url="doc-a"), _Obj(source_url="doc-b")]
    s.calls = []

    def direct(client, coll, label, q, filters):
        s.calls.append(("direct", label))
        return rows

    def mesh(client, coll, label, q, filters, caller):
        s.calls.append(("mesh", label))
        if not caller:
            raise ValueError("Initiator.subject is required")
        return rows

    def gate(hits, caller):
        kept = [(i, o) for i, o in enumerate(hits)
                if caller in granted and o.properties["source_url"] == "doc-a"]
        return kept, len(hits) - len(kept)

    def live(client, *, collection_name, domain_label, semantic_query, metadata_filters,
             caller_email):
        hits = (mesh(client, collection_name, domain_label, semantic_query, None, caller_email)
                if flag else direct(client, collection_name, domain_label, semantic_query, None))
        kept, dropped = gate(hits, caller_email)
        if live_drift:
            kept, dropped = list(enumerate(hits)), 0
        return kept, dropped, len(hits)

    s._search_direct, s._search_via_mesh, s._gate_hits = direct, mesh, gate
    s.retrieve_gated_chunks, s.get_weaviate_client = live, lambda: object()
    return s


@pytest.fixture
def plant(monkeypatch):
    def _plant(svc):
        monkeypatch.setitem(sys.modules, "service", svc)
        return svc
    return _plant


def test_CONTROL_TWO_RUNS_OF_ONE_GATE_DIFF_GREEN(plant):
    plant(_service(False))
    off = C.run("off", ["a@x"], [Q])
    plant(_service(True))
    on = C.run("on", ["a@x"], [Q])
    assert C.diff(off, on) == ([], [
        "4 shared (identity, query, source) decisions, 1 kept by a real identity on both paths"])
    assert [c["kind"] for c in on["cells"]] == ["real", "deny", "empty"]
    assert _cell(on, "empty")["refused"] == "ValueError: Initiator.subject is required"


def test_THE_RUN_SEARCHES_BY_THE_LABEL_THE_LIVE_HANDLER_DERIVES(plant):
    svc = plant(_service(False))
    C.run("off", ["a@x"], [("mainte-nance ops", "q")])
    assert {label for _, label in svc.calls} == {"MAINTE_NANCE_OPS"}


def test_A_RUN_WHOSE_FLAG_IS_NOT_ITS_LABEL_REFUSES_TO_START(plant):
    plant(_service(True))
    with pytest.raises(SystemExit, match="label 'off' but the imported module's flag is True"):
        C.run("off", ["a@x"], [Q])


def test_A_RUN_WITH_AUTH_OFF_REFUSES_TO_START(plant):
    plant(_service(False, auth=False))
    with pytest.raises(SystemExit, match="agentic auth is off"):
        C.run("off", ["a@x"], [Q])


def test_A_LIVE_REFUSAL_THE_REPLICATION_DID_NOT_SEE_IS_RECORDED_NOT_RAISED(plant):
    svc = plant(_service(False))
    real_live = svc.retrieve_gated_chunks

    def live(client, **kw):
        if kw["caller_email"] == "a@x":
            raise RuntimeError("live path down")
        return real_live(client, **kw)
    svc.retrieve_gated_chunks = live
    off = C.run("off", ["a@x"], [Q])           # the run completes: the refusal is a datum
    cell = _cell(off, "real")
    assert (cell["agrees_with_live"], cell["live_refused"]) == (
        False, "RuntimeError: live path down")


def test_A_RUN_RECORDS_WHEN_THE_LIVE_FUNCTION_DECIDES_OTHERWISE(plant):
    plant(_service(False, live_drift=True))
    off = C.run("off", ["a@x"], [Q])
    assert _cell(off, "real")["agrees_with_live"] is False
    plant(_service(True))
    reds, _ = C.diff(off, C.run("on", ["a@x"], [Q]))
    assert any("replication disagrees with retrieve_gated_chunks" in r for r in reds), reds


@pytest.mark.parametrize("ident", ["", "  ", C.DENY_CONTROL])
def test_THE_RUN_REFUSES_TO_BE_HANDED_ITS_OWN_CONTROLS(plant, capsys, ident):
    plant(_service(False))                  # a run that WOULD succeed, so only the guard refuses
    with pytest.raises(SystemExit) as e:
        C.main(["run", "--label", "off", "--identity", ident])
    assert e.value.code == 2
    assert "added by the census itself" in capsys.readouterr().err


# -- the label against the gate it describes -----------------------------------------------------

def _get_keys(fn: ast.FunctionDef):
    """The string keys of every ``<x>.properties.get("<key>")`` in a function, in source order."""
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "get" and isinstance(n.func.value, ast.Attribute)
             and n.func.value.attr == "properties" and n.args
             and isinstance(n.args[0], ast.Constant)]
    return [n.args[0].value for n in sorted(calls, key=lambda n: (n.lineno, n.col_offset))]


def _fn(path, name):
    hits = [n for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(hits) == 1, (path, name, len(hits))
    return hits[0]


def test_THE_CENSUS_LABELS_A_HIT_BY_THE_SOURCE_THE_GATE_DECIDES_ON():
    gate = _get_keys(_fn(_SERVICE, "_gate_hits"))
    assert gate, "found no properties.get(...) in service._gate_hits: the matcher reaches nothing"
    assert _get_keys(_fn(_CENSUS, "_source")) == gate
    # and both treat the ingest placeholder as no source at all
    for path, name in ((_SERVICE, "_gate_hits"), (_CENSUS, "_source")):
        consts = {n.value for n in ast.walk(_fn(path, name)) if isinstance(n, ast.Constant)}
        assert "Unknown Document" in consts, (path, name)


def test_EVERY_TOOL_AN_AGENT_IS_HANDED_SEARCHES_THROUGH_THE_CENSUSED_FUNCTION():
    """The census speaks for ``retrieve_gated_chunks``. service.py also holds an OUTER
    ``search_knowledge_base`` with its own search and its own copy of the gate, which ignores
    ``KNOWLEDGE_SEARCH_VIA_MESH``; it is dead today (no agent is handed it). Every function named
    in a ``tools=[...]`` must call ``retrieve_gated_chunks``, or the census measures a function the
    agent does not use."""
    tree = ast.parse(_SERVICE.read_text(encoding="utf-8"))
    handed = [e.id for n in ast.walk(tree) if isinstance(n, ast.Call)
              for k in n.keywords if k.arg == "tools" and isinstance(k.value, ast.List)
              for e in k.value.elts if isinstance(e, ast.Name)]
    assert handed, "found no tools=[...] in service.py: the matcher reaches nothing"
    defs = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.setdefault(n.name, []).append(n)
    for name in handed:
        assert len(defs.get(name, [])) == 1, (name, len(defs.get(name, [])))
        calls = {c.func.id for c in ast.walk(defs[name][0])
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        assert "retrieve_gated_chunks" in calls, (
            f"the agent is handed {name!r}, which does not search through retrieve_gated_chunks")
