"""`Neo4jGraph` against the SDK's `MeshGraph` contract — the conformance seal.

Mirrors `test_mesh_vectors_conforms.py` one substrate over: the SDK declares the Protocol, the
implementation lives where the driver lives, and this file is the referee that keeps one copy in
each repo safe.

THE ARM THAT IS NOT ABOUT THIS MODULE AT ALL: `test_the_imported_sdk_IS_the_pinned_artifact`. A
conformance suite that passes against whatever `iagent_mesh` happens to be importable proves the
implementation conforms to *something*, and the fleet pins one SDK version by construction.

AND THE DRIFT ARM. The Cypher in `mesh_graph.py` also exists in `main.py`, because the routes have
not migrated yet. **Duplicate only where a wrong copy FAILS LOUDLY** — so the queries are compared
by AST here, and drift reds rather than producing two engines that answer one question differently.

Run: uv run --frozen pytest tests/test_mesh_graph_conforms.py -v
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from iagent_mesh.conformance import (  # noqa: E402
    assert_fixture_discriminates,
    check_offline,
)
from iagent_mesh.interfaces import Initiator, MeshGraph, ServiceIdentityRefused  # noqa: E402
from iagent_mesh.results import MeshResult  # noqa: E402

from agent_fleet.ontology_service.mesh_graph import (  # noqa: E402
    ANCESTORS_CYPHER,
    CLASSES_WITH_A_VERB_CYPHER,
    OPERABLE_SUBJECTS_CYPHER,
    PATH_HOP_BOUNDS,
    PATH_MAX_HOPS,
    VALID_COST_CLASSES,
    Neo4jGraph,
    build_path_cypher,
)

_MAIN = _REPO / "agent_fleet" / "ontology_service" / "main.py"

PERSON = Initiator(subject="user:cnogradi", kind="person")
SERVICE = Initiator(subject="svc:engine-o", kind="service")


# ── stub driver ─────────────────────────────────────────────────────────────────────────────


class _Session:
    def __init__(self, rows, raises=None):
        self._rows, self._raises = rows, raises
        self.seen: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, **params):
        self.seen.append((cypher, params))
        if self._raises:
            raise self._raises
        return list(self._rows)


class _Driver:
    def __init__(self, rows=(), raises=None):
        self.session_obj = _Session(list(rows), raises)

    def session(self):
        return self.session_obj


def _graph(rows=(), raises=None):
    return Neo4jGraph(driver=_Driver(rows, raises))


#: Every operation, with arguments the implementer supplies — `check_offline` cannot know them.
def _operations(g: Neo4jGraph):
    return [
        ("ancestors", lambda i: g.ancestors(i, "idp:Table", max_hops=5)),
        ("verbs_for", lambda i: g.verbs_for(i, "idp:Table", max_hops=5)),
        ("classes_with_a_verb", lambda i: g.classes_with_a_verb(i, ["FINANCE"])),
        ("operable_subjects", lambda i: g.operable_subjects(i, "FINANCE")),
        ("edge", lambda i: g.edge(i, "idp:Table", "mesh:queryKnowledgeGraph")),
        ("path", lambda i: g.path(i, "idp:Table", "idp:Dataset", cost_classes=["fast"])),
        ("providers_for", lambda i: g.providers_for(i, "mesh:queryKnowledgeGraph")),
        ("data_assets_for", lambda i: g.data_assets_for(i, "idp:Table")),
        ("registry", lambda i: g.registry(i)),
    ]


# ── the contract ────────────────────────────────────────────────────────────────────────────


def test_the_imported_sdk_IS_the_pinned_artifact():
    """CONFORMANCE AGAINST AN UNPINNED SDK PROVES CONFORMANCE TO SOMETHING.

    The fleet pins one SDK version by construction (`test_lock_coherence` refuses disagreement), so
    this file must read the same artifact the fleet ships — not whatever happens to be importable.

    **NO `skip` PATH, AND THAT COST A REVISION.** The first version fell back to
    `iagent_mesh.__version__`, which this SDK does not define, so the arm SKIPPED — a green suite
    with the one check that guards every other check in it quietly not running. The installed
    distribution's metadata always carries the version; if it cannot be read, that is a failure of
    this arm, not a reason to pass.
    """
    import importlib.metadata as md

    try:
        installed = md.version("iagent-mesh")
    except md.PackageNotFoundError as exc:  # pragma: no cover - a broken environment
        pytest.fail(f"iagent-mesh is not an installed distribution: {exc}")

    pins = {
        m.group(1)
        for line in (_REPO / "pyproject.toml").read_text(encoding="utf-8").splitlines()
        if (m := re.search(r"iagent-mesh @ git\+\S+@v?(\d+\.\d+\.\d+)", line))
    }
    assert pins, "pyproject declares no iagent-mesh git pin to compare against"
    assert len(pins) == 1, f"the fleet's own SDK pins disagree: {sorted(pins)}"
    assert installed.lstrip("v") == pins.pop(), (
        f"conformance is running against iagent-mesh {installed}, the fleet pins {pins}"
    )


def test_it_satisfies_the_protocol_structurally():
    """Every operation the Protocol declares, with a matching signature."""
    import inspect

    impl = _graph()
    assert isinstance(impl, MeshGraph), "Neo4jGraph does not satisfy the MeshGraph Protocol"
    for name, fn in inspect.getmembers(MeshGraph, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        assert hasattr(impl, name), f"MeshGraph declares {name} and the implementation has none"
        declared = inspect.signature(fn).parameters
        actual = inspect.signature(getattr(impl, name)).parameters
        assert set(declared) - {"self"} == set(actual) - {"self"}, (
            f"{name}: declared {sorted(set(declared) - {'self'})}, "
            f"implemented {sorted(set(actual) - {'self'})}"
        )


def test_check_offline_passes_for_every_operation():
    """The SDK's own offline conformance — ALWAYS RUN THIS, per its docstring."""
    g = _graph(rows=[{"uri": "idp:Dataset"}])
    check_offline(g, operations=_operations(g))


@pytest.mark.parametrize("name,_call", [(n, c) for n, c in _operations(_graph())])
def test_EVERY_operation_refuses_a_service_identity(name, _call):
    """Identity is an argument, and a service identity is refused at the boundary — on all nine,
    not on the ones the author happened to think of."""
    g = _graph(rows=[{"uri": "x"}])
    call = dict(_operations(g))[name]
    with pytest.raises(ServiceIdentityRefused):
        call(SERVICE)


# ── the four outcomes ───────────────────────────────────────────────────────────────────────


def test_NO_DRIVER_IS_UNREACHABLE_not_empty():
    """A deployment that never configured a driver is a configuration answer, not a data answer."""
    g = Neo4jGraph(driver=None)
    r = g.operable_subjects(PERSON, "FINANCE")
    assert r.outcome == "unreachable"
    assert "no Neo4j driver" in r.detail


def test_A_MID_QUERY_FAILURE_IS_FAILED_not_empty():
    """THE DEFECT THIS RESULT TYPE EXISTS FOR. `[]` meant both *nothing matched* and *the substrate
    could not be asked*, and a caller holding it read an outage as a confident zero."""
    g = _graph(raises=RuntimeError("ServiceUnavailable"))
    r = g.operable_subjects(PERSON, "FINANCE")
    assert r.outcome == "failed"
    assert "ServiceUnavailable" in r.detail


def test_NOTHING_MATCHED_IS_EMPTY_and_that_is_an_ANSWER():
    assert _graph(rows=[]).operable_subjects(PERSON, "FINANCE").outcome == "empty"


def test_THE_FIXTURE_TELLS_EMPTY_FROM_FAILED():
    """assert_fixture_discriminates BEFORE the arms above, so an undiscriminating pair is a loud
    failure rather than a silent pass. Both of the SDK's authors shipped one."""
    empty = _graph(rows=[]).operable_subjects(PERSON, "FINANCE")
    failed = _graph(raises=RuntimeError("boom")).operable_subjects(PERSON, "FINANCE")
    assert_fixture_discriminates("empty vs failed", empty, failed, describe=lambda r: r.outcome)


def test_rows_come_back_as_plain_dicts():
    r = _graph(rows=[{"uri": "idp:Table", "label": "Table"}]).operable_subjects(PERSON, "FINANCE")
    assert r.outcome == "answered"
    assert r.rows[0]["uri"] == "idp:Table"


# ── the contracts each operation's docstring makes ──────────────────────────────────────────


def test_verbs_for_FAILS_when_the_ancestor_chain_fails():
    """`ancestors` REFUSES RATHER THAN DEGRADING, and `verbs_for` is built on it — so a chain it
    could not walk must not become an empty verb list. That silent narrowing is the pre-ADR-0018
    behaviour the whole chain exists to prevent."""
    r = _graph(raises=RuntimeError("down")).verbs_for(PERSON, "idp:Table", max_hops=5)
    assert r.outcome == "failed", r
    assert "ancestor chain unavailable" in r.detail


def test_providers_for_HOLDS_NO_CACHE():
    """`unreachable` must never be cached — one blip would silence enumeration for a whole TTL,
    which is how a failed lookup came to render as "no provider is registered". The cheapest way to
    obey that is to hold no cache, and this asserts the implementation holds none."""
    g = _graph(raises=RuntimeError("blip"))
    assert g.providers_for(PERSON, "mesh:x").outcome == "failed"
    g._driver = _Driver(rows=[{"provider": "engine_d"}])          # substrate comes back
    assert g.providers_for(PERSON, "mesh:x").outcome == "answered", (
        "a cached unreachable would still be failing here"
    )


def test_path_REFUSES_an_unknown_cost_class_rather_than_widening():
    """Falling back to all cost classes would answer a question nobody asked, with a permission the
    caller did not give."""
    r = _graph(rows=[{"hops": 1}]).path(PERSON, "a", "b", cost_classes=["free-lunch"])
    assert r.outcome == "failed" and "cost class" in r.detail
    ok = _graph(rows=[{"hops": 1}]).path(PERSON, "a", "b", cost_classes=["fast"])
    assert ok.outcome == "answered", "the control: a VALID cost class must still resolve"


def test_registry_without_its_views_is_UNREACHABLE_not_empty():
    assert _graph().registry(PERSON).outcome == "unreachable"


def test_registry_is_ALL_OR_NOTHING():
    """A caller told which personas exist but not which domains would filter against a set it
    cannot see — a partial registry is a failure, not half an answer."""
    g = Neo4jGraph(
        driver=_Driver(rows=[{"persona": "COST_ANALYST"}]),
        persona_registry_cypher="MATCH (p) RETURN p",
        domain_registry_cypher="MATCH (d) RETURN d",
    )
    assert g.registry(PERSON).outcome == "answered"
    g._driver = _Driver(raises=RuntimeError("half down"))
    assert g.registry(PERSON).outcome == "failed"


# ── the templated hop range ─────────────────────────────────────────────────────────────────


def test_THE_HOP_RANGE_IS_BOUNDED_BEFORE_IT_IS_INTERPOLATED():
    """A hop range cannot be a Cypher parameter, so it is templated — and a bound is the only thing
    between a templated value and an injected clause. This is the call-site arm; the statement arm
    is below."""
    lo, hi = PATH_HOP_BOUNDS
    assert build_path_cypher(lo) and build_path_cypher(hi)
    for bad in (0, hi + 1, -1, "4", 4.0, True, None):
        with pytest.raises(ValueError):
            build_path_cypher(bad)  # type: ignore[arg-type]


def test_THE_STATEMENT_ITSELF_CARRIES_NO_INJECTED_VALUE():
    """The statement arm: every value except the bounded hop range reaches Cypher as a PARAMETER.
    Removing the bound reds the arm above; it cannot red this one, which is why both exist."""
    q = build_path_cypher(PATH_MAX_HOPS)
    assert "$start_uri" in q and "$end_uri" in q and "$allowed_cost_classes" in q
    assert f"*1..{PATH_MAX_HOPS}" in q


def test_the_default_hop_bound_is_READ_from_the_fleet_declaration_not_invented():
    """`path` has no `max_hops` in the Protocol, so the implementation must choose — and a default
    invented locally becomes a contract. This asserts it equals `main.py`'s declared default."""
    src = _MAIN.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"max_hops:\s*int\s*=\s*Field\(\s*(\d+)\s*,\s*ge=(\d+)\s*,\s*le=(\d+)", src)
    assert m, "main.py no longer declares FindPathRequest.max_hops; re-derive the default"
    assert (int(m.group(1)), (int(m.group(2)), int(m.group(3)))) == (PATH_MAX_HOPS, PATH_HOP_BOUNDS)


# ── the drift arm: duplicated Cypher must fail loudly ───────────────────────────────────────


def _const(src: str, name: str) -> str | None:
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name and isinstance(node.value.value, str):
                    return node.value.value
    return None


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", q or "").strip()


@pytest.mark.parametrize(
    "here,there",
    [
        (ANCESTORS_CYPHER, "_SUBJECT_ANCESTOR_CHAIN_CYPHER"),
        (OPERABLE_SUBJECTS_CYPHER, "_OPERABLE_SUBJECTS_CYPHER"),
        (CLASSES_WITH_A_VERB_CYPHER, "_SERVED_CLASSES_CYPHER"),
    ],
)
def test_THE_DUPLICATED_CYPHER_STILL_AGREES_WITH_MAIN(here, there):
    """TWO COPIES OF ONE QUERY, AND THIS IS WHAT MAKES THAT SAFE.

    The routes have not migrated to `MeshGraph` yet, so `main.py` still holds its own copies. A
    wrong copy would produce two engines answering the same question differently, silently. Read by
    AST rather than imported, because `main.py` needs a stub harness to import at all.

    When a route migrates, delete its row here — **not** the assertion.
    """
    src = _MAIN.read_text(encoding="utf-8", errors="replace")
    other = _const(src, there)
    assert other is not None, (
        f"{there} is gone from main.py. If the route migrated to MeshGraph, drop this row; if it "
        f"was renamed, re-point it. Do not delete the check because it went red."
    )
    assert _norm(here) == _norm(other), (
        f"{there} has drifted from mesh_graph's copy.\n  main.py: {_norm(other)[:160]}\n"
        f"  here   : {_norm(here)[:160]}"
    )


def test_the_cost_classes_agree_with_main():
    src = _MAIN.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"_VALID_COST_CLASSES\s*=\s*\(([^)]*)\)", src)
    assert m, "main.py no longer declares _VALID_COST_CLASSES"
    declared = tuple(re.findall(r"[\"'](\w+)[\"']", m.group(1)))
    assert declared == VALID_COST_CLASSES, (declared, VALID_COST_CLASSES)


def test_THIS_MODULE_IMPORTS_NO_DRIVER():
    """The injected-driver rule, asserted rather than trusted: the module's value is that a test
    can exercise it where `main.py` cannot be imported, and one `import neo4j` ends that."""
    src = (_REPO / "agent_fleet" / "ontology_service" / "mesh_graph.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "neo4j" not in imported, "mesh_graph.py must not import a driver; it is injected"
    assert imported <= {"__future__", "typing", "iagent_mesh"}, (
        f"mesh_graph.py grew a dependency beyond the SDK: {sorted(imported)}"
    )
