"""MENUS ARE KEYED BY (frontend_id, frontend_version) -- a stale tab keeps its own menu.

WHY. A stale browser tab still runs the OLD bundle after a deploy, and the new bundle
asks for a different menu. Under the (frontend_id, archetype) row key the second
deploy silently overwrote the first, so the stale tab was served a menu its bundle
could not render. The version never reached the row: the gateway sent it in the
manifest and the saga never read it.

Arms:
  a. the unversioned key is byte-identical to before (one pinned uuid, computed from
     the code BEFORE this change); a versioned key differs from it
  b. two versions of one frontend write two rows; the row carries frontend_version
     and registered_at (ISO-8601 UTC, Z)
  c. the reader returns the newest as the top level and both under `versions`;
     legacy unversioned rows rank below versioned ones
  d. menu_for: asked + registered -> that menu, basis "asked"; asked + unregistered
     -> the newest, "newest-fallback"; none asked -> "newest"
  e. union_menu includes only each frontend's newest version
  f. eviction: deletes an old version past retention and an unversioned row; keeps an
     old version inside retention; keeps the kept version; never touches another
     frontend_id or a verb row; keep_version "" deletes no unversioned row
  g. the saga calls eviction after the mark, and only for a Presentation
  h. InterviewRequest and the render request accept frontend_version and it reaches
     select_presentation

Run: uv run pytest tests/test_menus_are_keyed_by_frontend_version.py -v
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
_PRESENTATION = _REPO / "agent_fleet" / "presentation_agent"
if str(_PRESENTATION) not in sys.path:
    sys.path.insert(0, str(_PRESENTATION))

_MESH = "http://invincible-agent/mesh#"

from agent_fleet.mesh_registrar import v2_saga  # noqa: E402
from agent_fleet.mesh_registrar import v2_substrate as sub  # noqa: E402
import capability_registry as cr  # noqa: E402


# ═══════════════════════════ a. the key ═══════════════════════════

# Computed from the code BEFORE the version part existed:
#   _deterministic_predicate_uuid("mesh:rendersAs", MESH/OwnershipFact, "cortex", "KNOWLEDGE_DOCUMENT")
_PRE_CHANGE_UUID = UUID("2c17b8a4-ff09-5de0-94e3-45ba697f5332")


def test_a_unversioned_key_is_byte_identical_to_before():
    k = sub._deterministic_predicate_uuid(
        "mesh:rendersAs", "http://x/OwnershipFact", "cortex", "KNOWLEDGE_DOCUMENT")
    assert k == _PRE_CHANGE_UUID
    assert sub._deterministic_predicate_uuid(
        "mesh:rendersAs", "http://x/OwnershipFact", "cortex", "KNOWLEDGE_DOCUMENT", "") == k


def test_a_versioned_key_differs_and_versions_differ_from_each_other():
    args = ("mesh:rendersAs", "http://x/OwnershipFact", "cortex", "KNOWLEDGE_DOCUMENT")
    v1 = sub._deterministic_predicate_uuid(*args, "1.0.0")
    v2 = sub._deterministic_predicate_uuid(*args, "2.0.0")
    assert v1 != _PRE_CHANGE_UUID and v2 != _PRE_CHANGE_UUID and v1 != v2


# ═══════════════════════════ b. the row ═══════════════════════════

class _Captor:
    """Weaviate stand-in that records every row written, keyed by uuid."""

    def __init__(self):
        self.rows = {}
        outer = self

        class _Coll:
            data = None

            def __init__(self):
                self.data = self

            def exists(self, uuid=None):
                return uuid in outer.rows

            def insert(self, properties=None, uuid=None, **kw):
                outer.rows[uuid] = dict(properties or {})

            def replace(self, properties=None, uuid=None, **kw):
                outer.rows[uuid] = dict(properties or {})

            def update(self, properties=None, uuid=None):
                outer.rows[uuid].update(properties or {})

            def delete_by_id(self, uuid=None):
                outer.rows.pop(uuid)

        class _Collections:
            @staticmethod
            def exists(name):
                return True

            @staticmethod
            def get(name):
                return _Coll()

        self.collections = _Collections()


def _write(client, **over):
    base = dict(
        weaviate_client=client, verb_iri="mesh:rendersAs",
        input_uri=f"{_MESH}OwnershipFact", output_uri=f"{_MESH}KnowledgeDocument",
        description="d", endpoint_url="", owner_persona="ANY", domains=[],
        cost_class="low", requires_human_approval=False, synonyms=[], anti_synonyms=[],
        tool_urn="urn:x", tool_kind="Presentation", frontend_id="cortex",
        archetype="KNOWLEDGE_DOCUMENT", expected_fields=["owner"],
    )
    base.update(over)
    sub.upsert_weaviate_predicate_row(**base)


def test_b_two_versions_write_two_rows_carrying_version_and_registered_at():
    c = _Captor()
    _write(c, frontend_version="1.0.0")
    _write(c, frontend_version="2.0.0")
    assert len(c.rows) == 2
    assert {r["frontend_version"] for r in c.rows.values()} == {"1.0.0", "2.0.0"}
    for r in c.rows.values():
        stamp = r["registered_at"]
        assert stamp.endswith("Z")
        datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ")


def test_b_unversioned_write_carries_empty_version_and_a_stamp():
    c = _Captor()
    _write(c)
    (row,) = c.rows.values()
    assert row["frontend_version"] == ""
    assert row["registered_at"].endswith("Z")


def test_b_mark_complete_addresses_the_versioned_row():
    c = _Captor()
    _write(c, frontend_version="1.0.0")
    assert sub.mark_registration_complete(
        weaviate_client=c, verb_iri="mesh:rendersAs", input_uri=f"{_MESH}OwnershipFact",
        frontend_id="cortex", archetype="KNOWLEDGE_DOCUMENT", frontend_version="1.0.0")
    assert sub.compensate_weaviate_predicate_row(
        weaviate_client=c, verb_iri="mesh:rendersAs", input_uri=f"{_MESH}OwnershipFact",
        frontend_id="cortex", archetype="KNOWLEDGE_DOCUMENT", frontend_version="1.0.0") is True
    assert c.rows == {}


# ═══════════════════════════ c. the reader ═══════════════════════════

_GMS = "graph_menu_source__versions_test"


def _gms():
    spec = importlib.util.spec_from_file_location(_GMS, _PRESENTATION / "graph_menu_source.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[_GMS] = m
    spec.loader.exec_module(m)
    return m


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def read(self):
        return json.dumps(self._p).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _row(**over):
    base = {
        "verb_iri": "mesh:rendersAs", "input_uri": f"{_MESH}OwnershipFact",
        "output_uri": f"{_MESH}KnowledgeDocument", "tool_kind": "Presentation",
        "frontend_id": "cortex", "archetype": "KNOWLEDGE_DOCUMENT",
        "expected_fields": ["owner"], "description": "d",
        "frontend_version": "", "registered_at": "",
    }
    base.update(over)
    return base


def _read(monkeypatch, rows, *, with_version_props=True):
    m = _gms()
    props = [{"name": "verb_iri"}, {"name": "frontend_id"}]
    if with_version_props:
        props += [{"name": "frontend_version"}, {"name": "registered_at"}]

    def urlopen(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if "/v1/schema/" in url:
            return _Resp({"properties": props})
        return _Resp({"data": {"Get": {"Predicate": rows}}})

    monkeypatch.setenv("WEAVIATE_HOST", "iagent-weaviate")
    monkeypatch.setattr(m.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(m.json, "load", lambda f: json.loads(f.read()))
    return m.fetch_registered_entries()


def test_c_newest_is_top_level_and_both_are_under_versions(monkeypatch):
    e = _read(monkeypatch, [
        _row(frontend_version="1.0.0", registered_at="2026-10-01T00:00:00.000000Z",
             archetype="OLD_ARCH"),
        _row(frontend_version="2.0.0", registered_at="2026-10-05T00:00:00.000000Z",
             archetype="NEW_ARCH"),
    ])["cortex"]
    assert e["frontend_version"] == "2.0.0"
    assert [c["archetype"] for c in e["capabilities"]] == ["NEW_ARCH"]
    assert set(e["versions"]) == {"1.0.0", "2.0.0"}
    assert e["versions"]["1.0.0"]["capabilities"][0]["archetype"] == "OLD_ARCH"
    assert e["versions"]["2.0.0"]["registered_at"] == "2026-10-05T00:00:00.000000Z"


def test_c_legacy_unversioned_rows_rank_below_versioned(monkeypatch):
    e = _read(monkeypatch, [
        _row(archetype="LEGACY", registered_at="2026-12-31T00:00:00.000000Z"),
        _row(frontend_version="1.0.0", registered_at="2026-10-01T00:00:00.000000Z",
             archetype="VERSIONED"),
    ])["cortex"]
    assert e["frontend_version"] == "1.0.0"
    assert [c["archetype"] for c in e["capabilities"]] == ["VERSIONED"]
    assert set(e["versions"]) == {"", "1.0.0"}


def test_c_unversioned_only_keeps_reporting_graph(monkeypatch):
    e = _read(monkeypatch, [_row()])["cortex"]
    assert e["frontend_version"] == "graph"
    assert len(e["capabilities"]) == 1


def test_c_a_store_without_the_new_properties_still_reads(monkeypatch):
    e = _read(monkeypatch, [_row()], with_version_props=False)["cortex"]
    assert e["frontend_version"] == "graph"


# ═══════════════════════════ d. menu_for ═══════════════════════════

def _entry(fid="cortex"):
    return {
        "frontend_id": fid, "frontend_version": "2.0.0",
        "capabilities": [{"subject_uri": "A", "archetype": "NEW"}],
        "versions": {
            "1.0.0": {"capabilities": [{"subject_uri": "A", "archetype": "OLD"}],
                      "registered_at": "2026-10-01T00:00:00.000000Z"},
            "2.0.0": {"capabilities": [{"subject_uri": "A", "archetype": "NEW"}],
                      "registered_at": "2026-10-05T00:00:00.000000Z"},
        },
    }


@pytest.fixture
def entries(monkeypatch):
    e = [_entry("cortex"), {**_entry("openddil"), "frontend_version": "9"}]
    monkeypatch.setattr(cr, "_entries", lambda: e)
    return e


def test_d_asked_registered_version_gets_its_own_menu(entries):
    m = cr.menu_for("cortex", "1.0.0")
    assert m["version_basis"] == "asked" and m["frontend_version"] == "1.0.0"
    assert m["capabilities"][0]["archetype"] == "OLD"


def test_d_asked_unregistered_version_falls_back_to_newest(entries):
    m = cr.menu_for("cortex", "0.0.1")
    assert m["version_basis"] == "newest-fallback"
    assert m["capabilities"][0]["archetype"] == "NEW"


def test_d_no_version_asked_is_newest(entries):
    m = cr.menu_for("cortex")
    assert m["version_basis"] == "newest" and m["capabilities"][0]["archetype"] == "NEW"


def test_d_selection_carries_the_version_and_the_basis(entries):
    cap, prov = cr.select_archetype("cortex", "A", frontend_version="1.0.0")
    assert cap["archetype"] == "OLD"
    assert prov["registration_version"] == "1.0.0" and prov["version_basis"] == "asked"
    cap, prov = cr.select_archetype("cortex", "A", frontend_version="nope")
    assert cap["archetype"] == "NEW" and prov["version_basis"] == "newest-fallback"
    cap, prov = cr.select_presentation("cortex", "A", {}, frontend_version="1.0.0")
    assert prov.get("version_basis") == "asked"


# ═══════════════════════════ e. union ═══════════════════════════

def test_e_union_includes_only_newest_versions(entries):
    archetypes = {c["archetype"] for c in cr.union_menu()["capabilities"]}
    assert "NEW" in archetypes and "OLD" not in archetypes


# ═══════════════════════════ f. eviction ═══════════════════════════

class _Obj:
    def __init__(self, uuid, **props):
        self.uuid = uuid
        self.properties = props


def _holds(flt, props):
    """Evaluate a weaviate Filter tree (equal / and) against a property dict."""
    if hasattr(flt, "filters"):
        return all(_holds(f, props) for f in flt.filters)
    return props.get(flt.target) == flt.value


class _EvictClient:
    def __init__(self, rows):
        self.objs = rows
        self.deleted = []
        outer = self

        class _Query:
            @staticmethod
            def fetch_objects(filters=None, limit=100):
                r = type("R", (), {})()
                r.objects = [o for o in outer.objs if filters is None or _holds(filters, o.properties)]
                return r

        class _Data:
            @staticmethod
            def delete_by_id(uuid):
                outer.deleted.append(uuid)
                outer.objs = [o for o in outer.objs if o.uuid != uuid]

        class _Coll:
            query = _Query
            data = _Data

        class _Collections:
            @staticmethod
            def get(name):
                return _Coll

        self.collections = _Collections()


NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)


def _ts(delta_s):
    return (NOW - timedelta(seconds=delta_s)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _p(uuid, ver, age_s, *, fid="cortex", kind="Presentation", arch="A"):
    return _Obj(uuid, tool_kind=kind, frontend_id=fid, frontend_version=ver,
                registered_at=_ts(age_s) if age_s is not None else "",
                archetype=arch, input_uri=f"{_MESH}{uuid}")


def _evict(rows, keep, retention=3600):
    c = _EvictClient(rows)
    out = sub.evict_undeployed_frontend_versions(
        weaviate_client=c, frontend_id="cortex", keep_version=keep,
        retention_s=retention, now=NOW)
    return c, out


def test_f_deletes_old_past_retention_and_unversioned_keeps_the_rest():
    rows = [
        _p("old-past", "1.0.0", 7200),
        _p("legacy", "", None),
        _p("old-fresh", "1.5.0", 60),
        _p("kept", "2.0.0", 7200),
        _p("other-fid", "1.0.0", 7200, fid="openddil"),
        _p("verb", "1.0.0", 7200, kind="Engine"),
    ]
    c, out = _evict(rows, "2.0.0")
    assert {d["uuid"] for d in out} == {"old-past", "legacy"}
    assert set(c.deleted) == {"old-past", "legacy"}
    assert {o.uuid for o in c.objs} == {"old-fresh", "kept", "other-fid", "verb"}
    assert set(out[0]) == {"uuid", "frontend_version", "archetype", "input_uri"}


def test_f_a_versioned_row_with_no_stamp_is_evictable():
    c, out = _evict([_p("undated", "1.0.0", None)], "2.0.0")
    assert [d["uuid"] for d in out] == ["undated"]


def test_f_empty_keep_version_deletes_no_unversioned_row():
    rows = [_p("legacy", "", None), _p("old-past", "1.0.0", 7200), _p("old-fresh", "1.5.0", 60)]
    c, out = _evict(rows, "")
    assert {d["uuid"] for d in out} == {"old-past"}
    assert "legacy" in {o.uuid for o in c.objs}


# ═══════════════════════════ g. the saga ═══════════════════════════

@pytest.fixture
def saga_calls(monkeypatch):
    order = []

    def rec(name, ret=None):
        def f(**kw):
            order.append((name, kw))
            return ret
        return f

    for name, ret in [
        ("merge_neo4j_predicate_edge", None), ("upsert_weaviate_predicate_row", None),
        ("probe_both_stores", {"neo4j": {}, "weaviate_uuid": "u"}),
        ("mark_registration_complete", True),
        ("evict_undeployed_frontend_versions", []),
    ]:
        monkeypatch.setattr(v2_saga.substrate, name, rec(name, ret))
    return order


def _saga(**over):
    kw = dict(
        driver=MagicMock(), weaviate_client=MagicMock(), verb_iri="mesh:rendersAs",
        input_uri="mesh:I", output_uri="mesh:O", tool_urn="urn:x", rel_props={},
        description="d", endpoint_url="", owner_persona="ANY", domains=[],
        cost_class="fast", requires_human_approval=False, synonyms=[], anti_synonyms=[],
        budget_s=2.0,
    )
    kw.update(over)
    return v2_saga.run_registration_saga(**kw)


def test_g_presentation_evicts_after_mark_with_its_version(saga_calls, monkeypatch):
    monkeypatch.setenv("FRONTEND_VERSION_RETENTION_S", "120")
    out = _saga(tool_kind="Presentation", frontend_id="cortex", archetype="A",
                frontend_version="2.0.0")
    assert out.status == "registered"
    names = [n for n, _ in saga_calls]
    assert names.index("evict_undeployed_frontend_versions") > names.index("mark_registration_complete")
    up = dict(saga_calls[names.index("upsert_weaviate_predicate_row")][1])
    assert up["frontend_version"] == "2.0.0"
    for n in ("probe_both_stores", "mark_registration_complete"):
        assert dict(saga_calls[names.index(n)][1])["frontend_version"] == "2.0.0"
    ev = dict(saga_calls[names.index("evict_undeployed_frontend_versions")][1])
    assert ev["frontend_id"] == "cortex" and ev["keep_version"] == "2.0.0"
    assert ev["retention_s"] == 120.0


def test_g_an_engine_registration_never_evicts(saga_calls):
    _saga(tool_kind="Engine")
    assert "evict_undeployed_frontend_versions" not in [n for n, _ in saga_calls]


def test_g_a_failed_mark_does_not_evict(saga_calls, monkeypatch):
    monkeypatch.setattr(v2_saga.substrate, "mark_registration_complete", lambda **kw: False)
    _saga(tool_kind="Presentation", frontend_id="cortex", archetype="A", frontend_version="2")
    assert "evict_undeployed_frontend_versions" not in [n for n, _ in saga_calls]


# ═══════════════════════════ h. the wire ═══════════════════════════

def test_h_interview_request_accepts_frontend_version():
    from iagent.gateway import InterviewRequest
    r = InterviewRequest(message="m", session_id="s", frontend_id="cortex",
                         frontend_version="1.2.3")
    assert r.frontend_version == "1.2.3"
    assert InterviewRequest(message="m", session_id="s").frontend_version is None


def _fields(path, cls):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == cls:
            return {s.target.id for s in n.body if isinstance(s, ast.AnnAssign)}
    raise AssertionError(cls)


def test_h_render_request_accepts_frontend_version_and_passes_it_to_the_selector():
    main = _PRESENTATION / "main.py"
    assert "frontend_version" in _fields(main, "RenderRequest")
    tree = ast.parse(main.read_text(encoding="utf-8"))
    hits = [
        kw for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_select_presentation"
        for kw in n.keywords if kw.arg == "frontend_version"
    ]
    assert hits and all(ast.unparse(k.value) == "request.frontend_version" for k in hits)


def test_h_the_gateway_forwards_the_version_to_the_render_call_and_the_run():
    src = (_SRC / "iagent" / "gateway.py").read_text(encoding="utf-8")
    assert '"frontend_version": frontend_version or None' in src
    assert "frontend_version=(request.frontend_version or \"\")" in src
    assert "X-Frontend-Version" in src
    sup = (_SRC / "iagent" / "defs" / "dynamic_supervisor.py").read_text(encoding="utf-8")
    assert '"frontend_version": config.frontend_version or None' in sup
