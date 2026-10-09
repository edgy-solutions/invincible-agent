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
  the run's cross-check compares positions and cannot see a label drift;
* A CUT FLOW (added for the run after roll #21, the NetworkPolicy gate on): an embedding call that
  fails falls back to bm25 on both paths, and a Topaz check that fails is dropped fail-closed --
  neither raises, so the run records both per cell and the diff reds them. The recorders attach to
  names in service.py, and those names are held to the calls the shipping paths make.

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
            "agrees_with_live": None if refused else True,
            "embed_failed": None, "gate_errors": 0, "gate_error": None}


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


@pytest.mark.parametrize("side", ["off", "on"])
def test_AN_EMBEDDING_CALL_THAT_FAILED_IS_RED_NOT_BM25_PARITY(side):
    """Both paths fall back to bm25 when the embedding call fails, so they still AGREE: without
    this red a cut model endpoint diffs green."""
    def m(off, on):
        _cell(off if side == "off" else on, "real")["embed_failed"] = "ConnectError: refused"
    reds = _red(m, f"on {side}, the embedding call failed in 1 of 3 cells (ConnectError: refused)")
    assert len(reds) == 1, reds        # the decisions agreed: the cut is the only red


@pytest.mark.parametrize("side", ["off", "on"])
def test_A_GATE_THAT_COULD_NOT_ASK_TOPAZ_IS_RED_AND_SAYS_SO(side):
    def m(off, on):
        _cell(off if side == "off" else on, "deny").update(gate_errors=2,
                                                           gate_error="ConnectTimeout: t")
    _red(m, f"on {side}, the gate could not ask Topaz in 1 of 3 cells (ConnectTimeout: t)")


def test_A_KEEP_NOTHING_CENSUS_WITH_A_CUT_GATE_NAMES_THE_WIRE_BESIDE_THE_POPULATION():
    """The shape a cut Topaz leaves: every check fails closed, so nothing is kept. The population
    red alone would send the reader to the grants."""
    def m(off, on):
        for doc in (off, on):
            for c in doc["cells"]:
                if c["kind"] in ("real", "deny"):
                    c.update(gate_errors=len(c["hits"]), gate_error="ConnectError: cut")
                    for h in c["hits"]:
                        h["kept"] = False
    reds = _red(m, "POPULATION: no real identity kept any shared source")
    assert any("could not ask Topaz" in r and "not a missing grant" in r for r in reds), reds


@pytest.mark.parametrize("side", ["off", "on"])
@pytest.mark.parametrize("field", ["embed_failed", "gate_errors"])
def test_A_FILE_WITH_NO_EMBED_OR_GATE_RECORD_IS_REFUSED(side, field):
    def m(off, on):
        del _cell(off if side == "off" else on, "real")[field]
    reds = _red(m, f"the {side} file has no embed/gate record in 1 cell(s)")
    assert len(reds) == 1, reds


# -- the RUN half, against a stand-in for the container's service module -----------------------

class _Obj:
    def __init__(self, **props):
        self.properties = props


class _Answer:
    def __init__(self, status, check=False):
        self.status_code, self._check = status, check

    def json(self):
        return {"check": self._check}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


_TOPAZ = "http://topaz.example"


def _service(flag, *, auth=True, granted=("a@x",), live_drift=False, embed_down=False,
             topaz=None, topaz_down_for=None):
    """A stand-in with service.py's surface. The gate reads ``source_url`` and lets a granted
    caller read doc-a only, ASKING its Topaz double over ``s.httpx.post`` and dropping fail-closed
    on any error, as ``_can_read_document`` does. Each path calls its embedding function through
    the module and falls back on failure, as the real paths do. ``live_drift`` makes
    retrieve_gated_chunks keep every chunk -- a live function the census's replication no longer
    speaks for. ``embed_down`` raises from both embedding calls; ``topaz`` is "down" (the post
    raises) or an HTTP status the check answers with."""
    s = types.ModuleType("service")
    s.KNOWLEDGE_SEARCH_VIA_MESH = flag
    s.ENABLE_AGENTIC_AUTH = auth
    s.TOPAZ_DIRECTORY_URL = _TOPAZ
    rows = [_Obj(source_url="doc-a"), _Obj(source_url="doc-b")]
    s.calls = []

    def embedder(q):
        if embed_down:
            raise ConnectionError("model endpoint unreachable")
        return [0.0]
    s.embed_query = s.observe_query_embedding = embedder

    def post(url, json=None, timeout=None):
        s.calls.append(("post", url))
        if not url.startswith(_TOPAZ):
            return _Answer(200)
        if topaz == "down" or json["subject_id"] == topaz_down_for:
            raise ConnectionError("topaz unreachable")
        if topaz:
            return _Answer(topaz)
        return _Answer(200, json["subject_id"] in granted and json["object_id"] == "doc-a")
    s.httpx = types.SimpleNamespace(post=post, Timeout=object)

    def direct(client, coll, label, q, filters):
        s.calls.append(("direct", label))
        try:
            s.embed_query(q)
        except Exception:
            pass                                    # bm25, as _search_direct falls back
        return rows

    def mesh(client, coll, label, q, filters, caller):
        s.calls.append(("mesh", label))
        if not caller:
            raise ValueError("Initiator.subject is required")
        try:
            s.observe_query_embedding(q)
        except Exception:
            pass                                    # bm25, as the reader degrades
        return rows

    def can_read(caller, source):
        if not caller or not source:
            return False
        try:
            r = s.httpx.post(f"{s.TOPAZ_DIRECTORY_URL}/api/v3/directory/check",
                             json={"subject_id": caller, "object_id": source}, timeout=5.0)
            r.raise_for_status()
            return bool(r.json().get("check", False))
        except Exception:
            return False                            # fail-closed, as _can_read_document does

    def gate(hits, caller):
        kept = [(i, o) for i, o in enumerate(hits) if can_read(caller, o.properties["source_url"])]
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
    assert {label for kind, label in svc.calls if kind != "post"} == {"MAINTE_NANCE_OPS"}


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


def test_CONTROL_A_RUN_WITH_EVERY_FLOW_UP_RECORDS_NO_CUT(plant):
    plant(_service(True))
    on = C.run("on", ["a@x"], [Q])
    assert [(c["embed_failed"], c["gate_errors"]) for c in on["cells"]] == [(None, 0)] * 3
    assert any(kind == "post" for kind, _ in sys.modules["service"].calls), (
        "the stand-in gate never asked Topaz: the gate arms below would be measuring nothing")


@pytest.mark.parametrize("flag", [False, True])
def test_A_RUN_RECORDS_AN_EMBEDDING_CALL_THAT_FELL_BACK(plant, flag):
    plant(_service(flag, embed_down=True))
    doc = C.run("on" if flag else "off", ["a@x"], [Q])
    searched = [c for c in doc["cells"] if not c["refused"]]
    assert searched and all(c["embed_failed"] == "ConnectionError: model endpoint unreachable"
                            for c in searched), doc["cells"]


@pytest.mark.parametrize("topaz, error", [("down", "ConnectionError: topaz unreachable"),
                                          (503, "HTTP 503")])
def test_A_RUN_RECORDS_A_GATE_THAT_COULD_NOT_ASK_TOPAZ(plant, topaz, error):
    plant(_service(False, topaz=topaz))
    off = C.run("off", ["a@x"], [Q])
    real = _cell(off, "real")
    # two rows, each asked twice (the replication and the live function), each failing
    assert (real["gate_errors"], real["gate_error"]) == (4, error), real
    assert not any(h["kept"] for h in real["hits"]), "the double did not fail closed"
    plant(_service(True, topaz=topaz))
    reds, _ = C.diff(off, C.run("on", ["a@x"], [Q]))
    assert any("could not ask Topaz" in r for r in reds), reds


def test_A_FAILURE_IS_RECORDED_AGAINST_ITS_OWN_CELL_ONLY(plant):
    """Topaz fails for the real identity alone: the deny cell, which follows it, asked Topaz and
    was answered, so it must carry no gate error. A recorder that kept counting across cells
    would put the real cell's cut on every cell after it."""
    plant(_service(False, topaz_down_for="a@x"))
    off = C.run("off", ["a@x"], [Q])
    assert _cell(off, "real")["gate_errors"] == 4, _cell(off, "real")
    assert (_cell(off, "deny")["gate_errors"], _cell(off, "deny")["gate_error"]) == (0, None)
    assert any(url.startswith(_TOPAZ) for kind, url in sys.modules["service"].calls
               if kind == "post"), "the control never asked Topaz"


def test_A_POST_THAT_IS_NOT_TO_TOPAZ_IS_NOT_RECORDED(plant):
    svc = plant(_service(False))
    C.run("off", ["a@x"], [Q])
    r = svc.httpx.post("http://elsewhere.example/x", json={})
    assert r.status_code == 200
    rec = C._Recorder()
    wire = C._RecordingWire(types.SimpleNamespace(post=lambda url, **k: _Answer(500)), rec, _TOPAZ)
    wire.post("http://elsewhere.example/x")
    assert rec.gate == []
    wire.post(f"{_TOPAZ}/api/v3/directory/check")
    assert rec.gate == ["HTTP 500"]


#: the four names the recorders replace, literal here so a script without them reds by name
_ATTACH = ("embed_query", "observe_query_embedding", "httpx", "TOPAZ_DIRECTORY_URL")


@pytest.mark.parametrize("name", _ATTACH)
def test_A_SERVICE_WITHOUT_AN_ATTACH_POINT_REFUSES_TO_START(plant, name):
    svc = plant(_service(False))
    delattr(svc, name)
    with pytest.raises(SystemExit, match=rf"service has no \['{name}'\]"):
        C.run("off", ["a@x"], [Q])


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


# -- the recorders' attach points against the calls service.py makes ---------------------------

def _names(fn: ast.FunctionDef) -> set:
    return {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}


def test_EVERY_ATTACH_POINT_IS_A_NAME_THE_SHIPPING_PATH_LOOKS_UP_AT_CALL_TIME():
    """The recorders replace module globals, so each must be a global the path reads WHEN IT RUNS.
    A path that bound the function at import (``from x import f as g``, a default argument) would
    call the original and the recorder would see nothing."""
    assert tuple(C.ATTACH_POINTS) == _ATTACH
    direct = _fn(_SERVICE, "_search_direct")
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "embed_query" for n in ast.walk(direct)), (
        "_search_direct no longer calls embed_query by its module name")
    mesh = _fn(_SERVICE, "_search_via_mesh")
    assert any(isinstance(n, ast.keyword) and n.arg == "embed"
               and isinstance(n.value, ast.Name) and n.value.id == "observe_query_embedding"
               for n in ast.walk(mesh)), (
        "_search_via_mesh no longer hands the reader observe_query_embedding by its module name")
    can_read = _fn(_SERVICE, "_can_read_document")
    posts = [n for n in ast.walk(can_read) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "post"
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "httpx"]
    assert len(posts) == 1, "_can_read_document no longer asks Topaz through httpx.post"
    url = posts[0].args[0]
    assert isinstance(url, ast.JoinedStr) and isinstance(url.values[0], ast.FormattedValue) \
        and isinstance(url.values[0].value, ast.Name) \
        and url.values[0].value.id == "TOPAZ_DIRECTORY_URL", (
            "the gate's post no longer starts with TOPAZ_DIRECTORY_URL: the wire recorder's "
            "prefix would match nothing")
    # and none of the four is shadowed by a local in the function that reads it
    for fn, name in ((direct, "embed_query"), (mesh, "observe_query_embedding"),
                     (can_read, "httpx"), (can_read, "TOPAZ_DIRECTORY_URL")):
        local = {a.arg for a in fn.args.args + fn.args.kwonlyargs} | {
            t.id for n in ast.walk(fn) if isinstance(n, ast.Assign)
            for t in n.targets if isinstance(t, ast.Name)}
        assert name not in local and name in _names(fn), (fn.name, name)
