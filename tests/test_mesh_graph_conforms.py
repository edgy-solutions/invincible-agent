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
    VERBS_FOR_CYPHER,
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

    **THE PIN IS A REVISION, NOT A VERSION** (second revision, 2026-10-02). A caller proves a
    change on a sha pin before the SDK tags it (caller-proves-then-tag), and the distribution built
    from that sha still reports the LAST tag's version: `c5fec431` installs as `0.9.5`. The old arm
    read only `@vX.Y.Z` pins, so it went red on the sha pin -- and comparing version strings would
    have passed a v0.9.5 install against a pin ahead of it. The identity is the revision the
    installer recorded in the distribution's `direct_url.json`.

    This arm judges IDENTITY only. Whether a sha pin may sit on master is the FORM question, and
    `test_sdk_pin_is_a_version` / `test_every_consuming_package_pins_the_sdk_to_a_tag` own it.
    """
    import importlib.metadata as md
    import json

    try:
        dist = md.distribution("iagent-mesh")
    except md.PackageNotFoundError as exc:  # pragma: no cover - a broken environment
        pytest.fail(f"iagent-mesh is not an installed distribution: {exc}")

    pins = set(_PIN.findall((_REPO / "pyproject.toml").read_text(encoding="utf-8")))
    assert pins, "pyproject declares no iagent-mesh git pin to compare against"
    assert len(pins) == 1, f"the fleet's own SDK pins disagree: {sorted(pins)}"
    pin = pins.pop()

    raw = dist.read_text("direct_url.json")
    assert raw, (f"iagent-mesh {dist.version} records no direct_url.json: it was not installed "
                 f"from the git pin {pin}, so nothing says which revision this is")
    vcs = json.loads(raw).get("vcs_info") or {}
    assert vcs.get("requested_revision") == pin, (
        f"conformance is running against iagent-mesh built from "
        f"{vcs.get('requested_revision')!r}, the fleet pins {pin!r}")


#: The revision after `@` in pyproject's git pin: a tag (`v0.9.5`) or a full sha.
_PIN = re.compile(r"iagent-mesh @ git\+\S+?\.git@([0-9A-Za-z][\w.\-]*)")


def test_CONTROL_THE_PIN_READER_TAKES_BOTH_FORMS_AND_ONLY_THE_REVISION():
    """A sha pin and a tag pin each yield their revision, whole; a line naming another package
    yields nothing."""
    sha = "c5fec431ba6f12b298b43ad316db1e77ad867c84"
    url = "git+https://github.com/edgy-solutions/iagent-mesh-sdk.git"
    assert _PIN.findall(f'    "iagent-mesh @ {url}@{sha}",') == [sha]
    assert _PIN.findall(f'    "iagent-mesh @ {url}@v0.9.5",') == ["v0.9.5"]
    assert _PIN.findall(f'    "iagent-other @ {url}@v0.9.5",') == []


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
    """A chain it could not walk must not become an empty verb list. That silent narrowing is the
    pre-ADR-0018 behaviour the whole chain exists to prevent. `verbs_for` walks the chain and reads
    the edges in one statement now, so the walk failing is that statement failing."""
    r = _graph(raises=RuntimeError("down")).verbs_for(PERSON, "idp:Table", max_hops=5)
    assert r.outcome == "failed", r
    assert "verbs_for" in r.detail and "down" in r.detail


# ── verbs_for: the route's row and the route's walk (SDK 0.9.8) ────────────────────────────


def _sdk_verbs_for_fields() -> list[str]:
    """The row SDK 0.9.8 declares for `verbs_for`, read from the Protocol's own table rather than
    restated here: every `| ``name`` |` row of its docstring."""
    return re.findall(r"^\s*\|\s*``([a-z_]+)``\s*\|", MeshGraph.verbs_for.__doc__ or "", re.M)


def _returned_columns(cypher: str) -> list[str]:
    return re.findall(r"\bAS ([a-z_]+)\s*(?:,|$)", cypher[cypher.index("RETURN DISTINCT"):], re.M)


def _strip_comments(cypher: str) -> str:
    return "\n".join(line for line in cypher.splitlines() if not line.strip().startswith("//"))


def test_verbs_for_RETURNS_THE_ROW_THE_SDK_DECLARES():
    declared = _sdk_verbs_for_fields()
    assert len(declared) == 14 and "verb_local" in declared, (
        f"the SDK's verbs_for table reads {declared!r}; this module pins 0.9.8's fourteen fields"
    )
    assert sorted(_returned_columns(VERBS_FOR_CYPHER)) == sorted(declared)
    assert "verb_type" not in _returned_columns(VERBS_FOR_CYPHER), "0.9.8 renamed it; one fact, one name"


def test_verbs_for_IS_THE_ROUTES_LEG_1():
    """`/find_compatible_verbs` reads LEG 1 through `verbs_for` with `COMPATIBLE_VERBS_VIA_MESH`
    on, and through its own `_FIND_COMPAT_VERBS_CYPHER` with it off. The two give one answer only
    while they are one statement: comments aside, `verbs_for`'s must equal the route's first leg.
    When the route's flag-off path is retired, delete this arm, not the assertion."""
    src = _MAIN.read_text(encoding="utf-8", errors="replace")
    route = _const(src, "_FIND_COMPAT_VERBS_CYPHER")
    assert route is not None, "_FIND_COMPAT_VERBS_CYPHER is gone from main.py; re-point this arm"
    legs = route.split("\nUNION ALL\n")
    assert len(legs) == 3, f"the route's statement has {len(legs)} legs; this arm expects three"
    assert "'subject'" in legs[0] and "AS compatibility" in legs[0]
    assert _norm(_strip_comments(VERBS_FOR_CYPHER)) == _norm(_strip_comments(legs[0])), (
        f"verbs_for has drifted from the route's LEG 1.\n  main.py: "
        f"{_norm(_strip_comments(legs[0]))[:200]}\n  here   : {_norm(VERBS_FOR_CYPHER)[:200]}"
    )


def test_verbs_for_BOUNDS_THE_HOPS_BEFORE_IT_TEMPLATES_THEM():
    lo, hi = PATH_HOP_BOUNDS
    for bad in (0, hi + 1, -1, "5", True):
        g = _graph(rows=[{"verb_iri": "x"}])
        r = g.verbs_for(PERSON, "idp:Table", max_hops=bad)  # type: ignore[arg-type]
        assert r.outcome == "failed" and "max_hops" in r.detail, (bad, r)
        assert g._driver.session_obj.seen == [], f"a statement was sent for max_hops={bad!r}"
    g = _graph(rows=[{"verb_iri": "x"}])
    assert g.verbs_for(PERSON, "idp:Table", max_hops=hi).outcome == "answered"
    ((cypher, params),) = g._driver.session_obj.seen
    assert params == {"subject_uri": "idp:Table"}
    assert f"*0..{hi}]" in cypher and "$MAXHOPS$" not in cypher


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
