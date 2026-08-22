"""THE MENU COMES FROM THE GRAPH — and survives a poisoned substrate.

WHY. `capability_registry._REGISTRY` is a module-local dict and registration and
selection run in DIFFERENT PODS (`/register_frontend_capabilities` in cortex-bff,
`/render_ui` in presentation-agent), so registration could never reach the
selector: every caller looked anonymous, the union was always empty, every answer
fell to the labelled floor. 71 green tests proved the LOGIC and never touched the
TOPOLOGY — which is the whole reason this packet exists.

THE SCOPING ARM IS THE POINT. `menu_for(frontend_id)` exists to stop Cortex's
capabilities reaching OpenDDIL. One frontend proves the pipe; only TWO prove the
scoping.

TWO TOLERANCES, both found by checking the cluster before writing the reader:

  * PAYLOAD-LESS PRESENTATION ROWS are not menu entries. Ten existed after the
    row key gained its frontend component. They were swept, but the skip is
    STRUCTURAL: the next partial write or interrupted re-register mints fresh
    ones, and a reader whose correctness depends on a clean substrate is a reader
    with a poisoned population.
  * `recomputes` MAY NOT EXIST AS A PROPERTY. Weaviate auto-schema creates a
    property when something first writes it, and `recomputes` is omitted when
    undeclared (ADR-0042 Ruling 9's honest default, ab0bcfd). Until the first
    live view registers, selecting it is a GraphQL ERROR, not a null column.

Run: uv run --frozen --with pytest pytest tests/test_graph_menu_source.py -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_MESH = "http://invincible-agent/mesh#"


def _gms():
    spec = importlib.util.spec_from_file_location(
        "graph_menu_source__test",
        _REPO / "agent_fleet" / "presentation_agent" / "graph_menu_source.py",
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    try:
        spec.loader.exec_module(m)
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(spec.name, None)
        pytest.skip(f"graph_menu_source not importable: {type(exc).__name__}: {exc}")
    return m


def _row(**over):
    base = {
        "verb_iri": "mesh:rendersAs",
        "input_uri": f"{_MESH}OwnershipFact",
        "output_uri": f"{_MESH}KnowledgeDocument",
        "tool_kind": "Presentation",
        "frontend_id": "cortex",
        "archetype": "KNOWLEDGE_DOCUMENT",
        "expected_fields": ["owner"],
        "description": "renders ownership facts",
    }
    base.update(over)
    return base


class _Fake:
    """Stands in for Weaviate's REST+GraphQL surface."""

    def __init__(self, rows, *, has_recomputes=False, has_marker=False,
                 gql_errors=None, boom=False):
        self.rows = rows
        self.has_recomputes = has_recomputes
        self.has_marker = has_marker
        self.gql_errors = gql_errors
        self.boom = boom
        self.selected_fields = None

    def urlopen(self, req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if self.boom:
            raise OSError("connection refused")
        if "/v1/schema/" in url:
            props = [{"name": "verb_iri"}, {"name": "frontend_id"}]
            if self.has_recomputes:
                props.append({"name": "recomputes"})
            if self.has_marker:
                props.append({"name": "registration_complete"})
            return _Resp({"properties": props})
        body = json.loads(req.data.decode())
        self.selected_fields = body["query"]
        if self.gql_errors:
            return _Resp({"errors": self.gql_errors})
        return _Resp({"data": {"Get": {"Predicate": self.rows}}})


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def read(self):
        return json.dumps(self._p).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _install(monkeypatch, m, fake):
    monkeypatch.setenv("WEAVIATE_HOST", "iagent-weaviate")
    monkeypatch.setattr(m.urllib.request, "urlopen", fake.urlopen)
    monkeypatch.setattr(m.json, "load", lambda f: json.loads(f.read()))
    return fake


# ── THE SCOPING ARM — the packet's whole reason ────────────────────────────

def test_two_frontends_get_only_their_OWN_capabilities(monkeypatch):
    """THE DISCRIMINATING ARM. One frontend proves the pipe; two prove the
    SCOPING, and scoping is what menu_for() exists for."""
    m = _gms()
    _install(monkeypatch, m, _Fake([
        _row(frontend_id="cortex", input_uri=f"{_MESH}OwnershipFact"),
        _row(frontend_id="cortex", input_uri=f"{_MESH}ImpactSet"),
        _row(frontend_id="openddil", input_uri=f"{_MESH}LineageTopology",
             archetype="PROCESS_TOPOLOGY"),
    ]))
    entries = m.fetch_registered_entries()
    assert set(entries) == {"cortex", "openddil"}
    cortex_subjects = {c["subject_uri"] for c in entries["cortex"]["capabilities"]}
    openddil_subjects = {c["subject_uri"] for c in entries["openddil"]["capabilities"]}
    assert cortex_subjects == {f"{_MESH}OwnershipFact", f"{_MESH}ImpactSet"}
    assert openddil_subjects == {f"{_MESH}LineageTopology"}
    assert not (cortex_subjects & openddil_subjects), "menus bled across frontends"


def test_the_SAME_subject_registered_by_both_stays_on_both_menus(monkeypatch):
    """The common case, and the one the row-key collision used to destroy: both
    surfaces render OwnershipFact the same way. Two menu entries, not one."""
    m = _gms()
    _install(monkeypatch, m, _Fake([
        _row(frontend_id="cortex"),
        _row(frontend_id="openddil"),
    ]))
    e = m.fetch_registered_entries()
    assert len(e["cortex"]["capabilities"]) == 1
    assert len(e["openddil"]["capabilities"]) == 1


# ── TOLERANCE 1: payload-less rows are not menu entries ────────────────────

def test_a_presentation_row_with_no_frontend_id_is_SKIPPED(monkeypatch):
    """An orphan belongs to no menu. Returning it would widen every anonymous
    union with a ghost duplicate of a real capability."""
    m = _gms()
    _install(monkeypatch, m, _Fake([
        _row(frontend_id="cortex"),
        _row(frontend_id=""),
        _row(frontend_id=None),
    ]))
    e = m.fetch_registered_entries()
    assert set(e) == {"cortex"}
    assert len(e["cortex"]["capabilities"]) == 1


def test_verb_rows_are_not_menu_entries(monkeypatch):
    """Both species share the Predicate collection. A verb is not a rendering."""
    m = _gms()
    _install(monkeypatch, m, _Fake([
        _row(frontend_id="cortex"),
        _row(tool_kind="Engine", verb_iri="mesh:lookupOwnership", frontend_id=""),
    ]))
    e = m.fetch_registered_entries()
    assert sum(len(v["capabilities"]) for v in e.values()) == 1


# ── TOLERANCE 2: recomputes may not exist as a property ────────────────────

def test_it_does_not_SELECT_recomputes_when_the_schema_lacks_it(monkeypatch):
    """Selecting a never-written property is a GraphQL ERROR, not a null column.
    Asking for it before any live view registers would break every menu read."""
    m = _gms()
    f = _install(monkeypatch, m, _Fake([_row()], has_recomputes=False))
    m.fetch_registered_entries()
    assert "recomputes" not in f.selected_fields


def test_property_absent_reads_as_NOT_a_live_view(monkeypatch):
    """Same answer absence-on-the-row gives: nothing. `contract` must be absent
    so `_is_live_view()` says False without inventing a declaration."""
    m = _gms()
    _install(monkeypatch, m, _Fake([_row()], has_recomputes=False))
    cap = m.fetch_registered_entries()["cortex"]["capabilities"][0]
    assert "contract" not in cap


def test_a_declared_live_view_arrives_as_contract_recomputes(monkeypatch):
    """The positive control: when the row says so, the reader must carry it, or
    ADR-0042 Ruling 9 has nothing to refuse on."""
    m = _gms()
    _install(monkeypatch, m, _Fake([_row(recomputes=True)], has_recomputes=True))
    cap = m.fetch_registered_entries()["cortex"]["capabilities"][0]
    assert cap["contract"]["recomputes"] is True


def test_recomputes_FALSE_is_carried_as_a_real_declaration(monkeypatch):
    """Declared not-live is not the same as never-said, and the reader must keep
    them distinguishable."""
    m = _gms()
    _install(monkeypatch, m, _Fake([_row(recomputes=False)], has_recomputes=True))
    cap = m.fetch_registered_entries()["cortex"]["capabilities"][0]
    assert cap["contract"]["recomputes"] is False


# ── UNREACHABLE IS NOT EMPTY ───────────────────────────────────────────────

def test_unreachable_returns_None_not_an_empty_registry(monkeypatch):
    """None and {} have OPPOSITE repairs — fix the network vs nobody registered.
    Collapsing them makes a blip look like an empty registry, and the caller
    would floor to default-menu instead of falling back to what it holds."""
    m = _gms()
    _install(monkeypatch, m, _Fake([], boom=True))
    assert m.fetch_registered_entries() is None


def test_graphql_errors_return_None_not_a_silent_empty_menu(monkeypatch):
    """Schema drift here empties every menu, which reads exactly like 'nobody has
    registered'. It must be reported as a failure to read, not as a fact."""
    m = _gms()
    _install(monkeypatch, m, _Fake([], gql_errors=[{"message": "no such prop"}]))
    assert m.fetch_registered_entries() is None


def test_reached_but_empty_returns_an_EMPTY_dict(monkeypatch):
    """The distinction's other half: a reachable graph with no registrations is a
    real answer and must not be reported as a failure."""
    m = _gms()
    _install(monkeypatch, m, _Fake([]))
    assert m.fetch_registered_entries() == {}


def test_no_weaviate_host_is_inactive_not_an_error(monkeypatch):
    """A deployment without a graph source falls back; it does not 500."""
    m = _gms()
    monkeypatch.delenv("WEAVIATE_HOST", raising=False)
    monkeypatch.delenv("WEAVIATE_URL", raising=False)
    assert m.fetch_registered_entries() is None


# ── A PROVIDER IS NOT A FRONTEND ───────────────────────────────────────────

def _reg():
    spec = importlib.util.spec_from_file_location(
        "capability_registry__sentinel_test",
        _REPO / "agent_fleet" / "presentation_agent" / "capability_registry.py",
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    try:
        spec.loader.exec_module(m)
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(spec.name, None)
        pytest.skip(f"capability_registry not importable: {type(exc).__name__}: {exc}")
    return m


def test_the_system_default_sentinel_is_NOT_a_callable_menu(monkeypatch):
    """THE PROVENANCE-UPGRADE HOLE, closed.

    Engine F advertises the UNIVERSAL FALLBACK -- the population `default-menu`
    provenance names -- not a surface's private menu. While those rows were
    stamped "engine-f", a caller sending frontend_id="engine-f" would have been
    served them as a SCOPED menu and labelled `registered`: provenance upgraded
    by naming a provider, for a caller that registered nothing.

    Anonymous is the honest answer, so the union serves them as `default-menu`.
    """
    m = _reg()
    monkeypatch.setenv("PRESENTATION_GRAPH_MENU", "0")
    m.clear()
    m.register(m.SYSTEM_DEFAULT_FRONTEND_ID, "1.0", [
        {"subject_uri": f"{_MESH}OwnershipFact", "archetype": "KNOWLEDGE_DOCUMENT"},
    ])
    assert m.menu_for(m.SYSTEM_DEFAULT_FRONTEND_ID) is None


def test_the_defaults_still_reach_anonymous_callers_through_the_UNION(monkeypatch):
    """THE POSITIVE CONTROL. Refusing the sentinel as a menu must not make the
    system defaults unreachable -- they are precisely what an anonymous caller
    should get, labelled honestly."""
    m = _reg()
    monkeypatch.setenv("PRESENTATION_GRAPH_MENU", "0")
    m.clear()
    m.register(m.SYSTEM_DEFAULT_FRONTEND_ID, "1.0", [
        {"subject_uri": f"{_MESH}OwnershipFact", "archetype": "KNOWLEDGE_DOCUMENT"},
    ])
    caps = m.union_menu()["capabilities"]
    assert any(c.get("subject_uri") == f"{_MESH}OwnershipFact" for c in caps)


def test_a_real_frontend_is_still_served_its_own_menu(monkeypatch):
    """The refusal is narrow: it applies to the sentinel alone, not to callers."""
    m = _reg()
    monkeypatch.setenv("PRESENTATION_GRAPH_MENU", "0")
    m.clear()
    m.register("cortex", "1.0", [
        {"subject_uri": f"{_MESH}ImpactSet", "archetype": "KNOWLEDGE_DOCUMENT"},
    ])
    menu = m.menu_for("cortex")
    assert menu is not None and menu["frontend_id"] == "cortex"


def test_the_LAUNDERING_ATTACK_end_to_end(monkeypatch):
    """THE ATTACK ITSELF, through the public path rather than the unit.

    menu_for() returning None is the mechanism; what an attacker actually gets
    is what matters. A caller naming the sentinel must receive the union labelled
    `default-menu` -- the honest "you have no menu" -- and never `registered`,
    which would assert it chose from capabilities it registered.

    Provenance is the only thing separating a caller's decision from a fallback,
    and a caller that can pick its own provenance makes every downstream reading
    of that field worthless.
    """
    m = _reg()
    monkeypatch.setenv("PRESENTATION_GRAPH_MENU", "0")
    m.clear()
    m.register(m.SYSTEM_DEFAULT_FRONTEND_ID, "1.0", [
        {"subject_uri": f"{_MESH}OwnershipFact", "archetype": "KNOWLEDGE_DOCUMENT"},
    ])
    _cap, prov = m.select_presentation(
        m.SYSTEM_DEFAULT_FRONTEND_ID,
        f"{_MESH}OwnershipFact",
        {"owner": "x"},
    )
    assert prov["presentation_source"] != "registered", (
        "a caller upgraded its own provenance by naming the system-default "
        "sentinel — it registered nothing"
    )
    assert prov["presentation_source"] == "default-menu"


# ── THE COMPLETENESS MARKER: debris is not a menu entry ────────────────────
#
# The registrar writes BOTH stores and the system's invariant is conjunctive.
# This reader consults Weaviate alone, so without a marker a row whose Neo4j
# edge is missing -- the debris a failed-and-compensated registration leaves --
# is served as a valid menu entry. Observed for real on 2026-08-21: a saga bug
# left ten such rows standing and they WOULD have been served as
# cortex-ui-desktop's menu.

def test_an_UNMARKED_row_is_not_served_once_the_marker_exists(monkeypatch):
    """THE DEBRIS ARM. A complete-looking row that never finished registering
    must not reach a menu."""
    m = _gms()
    _install(monkeypatch, m, _Fake([
        _row(frontend_id="cortex", registration_complete=True),
        _row(frontend_id="cortex", input_uri=f"{_MESH}ImpactSet"),  # no marker
    ], has_marker=True))
    e = m.fetch_registered_entries()
    subjects = {c["subject_uri"] for c in e["cortex"]["capabilities"]}
    assert subjects == {f"{_MESH}OwnershipFact"}, "debris reached the menu"


def test_an_explicitly_FALSE_marker_is_not_served(monkeypatch):
    """A row mid-registration is not a capability yet."""
    m = _gms()
    _install(monkeypatch, m, _Fake([
        _row(frontend_id="cortex", registration_complete=False),
    ], has_marker=True))
    assert m.fetch_registered_entries() == {}


def test_the_filter_is_INERT_until_the_property_exists(monkeypatch):
    """THE ERA ARM, and the reason this rollout is safe.

    Until the registrar marks its first row the property does not exist, and
    filtering on it would empty every menu — turning a new guard into a total
    outage. The filter activates exactly when there is something to filter by.
    """
    m = _gms()
    _install(monkeypatch, m, _Fake([_row(frontend_id="cortex")], has_marker=False))
    e = m.fetch_registered_entries()
    assert len(e["cortex"]["capabilities"]) == 1


def test_it_does_not_SELECT_the_marker_before_the_property_exists(monkeypatch):
    """Selecting a never-written property is a GraphQL error, not a null."""
    m = _gms()
    f = _install(monkeypatch, m, _Fake([_row(frontend_id="cortex")], has_marker=False))
    m.fetch_registered_entries()
    assert "registration_complete" not in f.selected_fields


def test_a_marked_row_still_carries_its_menu_payload(monkeypatch):
    """The positive control: filtering must not cost the fields the menu needs."""
    m = _gms()
    _install(monkeypatch, m, _Fake([
        _row(frontend_id="cortex", registration_complete=True),
    ], has_marker=True))
    cap = m.fetch_registered_entries()["cortex"]["capabilities"][0]
    assert cap["archetype"] == "KNOWLEDGE_DOCUMENT"
    assert cap["expected_fields"] == ["owner"]
