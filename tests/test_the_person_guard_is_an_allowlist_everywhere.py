"""The person guard is an ALLOWLIST, written ONCE (the SDK's), and a kind nobody declared is refused.

**What this file is defending, in one sentence.** ``require_person`` decides whether a read may be
attributed to whoever asked for it, and until 2026-09-27 every copy of it was written as
``if kind == "service": raise`` -- a comparison that names what it refuses and therefore ADMITS
everything it does not name. The SDK then grew a third kind (``delegate``). This file sealed the
flip to ``!= "person"`` in the fleet's two copies while the pin (v0.9.3) still shipped the
denylist, and carried two ratchet arms that would red when the pin moved.

**THEY REDDED ON 2026-10-01**, when the merge of master moved the pin to v0.9.5, and this file now
holds the state their docstring named: ``delegate`` is a DECLARED kind (so the refusal population,
derived from the Literal, picks it up), both fleet copies are one call to
``Initiator.require_person``, and a delegate is refused by its own TYPE,
``DelegateIdentityRefused``, which is a SIBLING of ``ServiceIdentityRefused`` (both
``PermissionError``), not a subclass.

**WHY ``model_construct`` AND NOT A STAND-IN.** The undeclared-kind arms need an initiator the
Literal refuses. The old file handed the copies a duck-typed dataclass, which was faithful only
while the copies read nothing but ``kind`` and ``subject`` (an arm measured that). The guards now
CALL A METHOD on the initiator, so a stand-in would test the stand-in. ``model_construct`` builds
the real class and skips validation, so the method under test is the SDK's own.

Run: uv run --frozen pytest tests/test_the_person_guard_is_an_allowlist_everywhere.py -v
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import get_args

import pytest

# No sys.path surgery -- ``tests`` is a package, so pytest has already prepended the repo root.
_REPO = Path(__file__).resolve().parents[1]

from iagent_mesh.interfaces import (  # noqa: E402
    DelegateIdentityRefused,
    Initiator,
    ServiceIdentityRefused,
)

from agent_fleet.ontology_service.mesh_graph import Neo4jGraph  # noqa: E402
from agent_fleet.utils.mesh_vectors import WeaviateVectors  # noqa: E402

# -- the population, derived from the type and never typed -----------------------------------

#: Every kind the PINNED SDK permits, read off the annotation, so widening the Literal widens this
#: file's coverage without anyone remembering to come back here.
DECLARED_KINDS: tuple[str, ...] = get_args(Initiator.model_fields["kind"].annotation)

#: The kinds that must be refused, derived by SUBTRACTION rather than listed. A future kind meant
#: to be admitted reds here, which is right: a new kind's admission is a decision, not a default.
REFUSED_KINDS: tuple[str, ...] = tuple(k for k in DECLARED_KINDS if k != "person")

#: Kinds NO Literal declares, arbitrary on purpose: an allowlist must refuse a kind nobody has
#: thought of yet, and enumerating the ones we HAVE thought of is the denylist mistake one layer up.
UNDECLARED_KINDS: tuple[str, ...] = ("robot", "")

#: The refusal TYPE each declared non-person kind gets. Only ``delegate`` has its own; everything
#: else is the service refusal. Not derived: this is the SDK's contract, stated so it is checked.
_REFUSAL_TYPE = {"delegate": DelegateIdentityRefused}

#: The two fleet wrappers. Statics, so they are callable without building an implementation.
FLEET_GUARDS = {
    "mesh_vectors.WeaviateVectors": WeaviateVectors._require_person,
    "mesh_graph.Neo4jGraph": Neo4jGraph._require_person,
}

_GUARD_SOURCES = {
    "mesh_vectors.WeaviateVectors": _REPO / "agent_fleet" / "utils" / "mesh_vectors.py",
    "mesh_graph.Neo4jGraph": _REPO / "agent_fleet" / "ontology_service" / "mesh_graph.py",
}

_SEARCH_ROOTS = ("agent_fleet", "src")


def _valid(kind: str, subject: str = "") -> Initiator:
    """A VALIDATED initiator of a declared kind. A delegate must name who it acts for."""
    extra = {"on_behalf_of": "alice@example.com"} if kind == "delegate" else {}
    return Initiator(subject=subject or f"subj:{kind}", kind=kind, **extra)


def _unvalidated(**fields) -> Initiator:
    """The real class with validation skipped: the only way to hand the guard a kind, or a field
    combination, that the Literal and the validators refuse."""
    return Initiator.model_construct(**fields)


def _sdk_guard(initiator, operation: str) -> None:
    """The SDK's own guard, called the way the fleet's ontology implementation calls it."""
    initiator.require_person(operation)


ALL_GUARDS = {**FLEET_GUARDS, "sdk.Initiator.require_person": _sdk_guard}


# -- the population is real ------------------------------------------------------------------


def test_the_POPULATION_comes_from_the_TYPE_and_contains_a_person_and_a_delegate() -> None:
    """Without this, every parametrized arm below could be running over an empty list. ``delegate``
    is asserted by name because its arrival in the Literal is what retired the fleet copies."""
    assert "person" in DECLARED_KINDS, (
        f"the allowlist's ALLOWED value is not in the declared kinds {DECLARED_KINDS!r}"
    )
    assert "delegate" in REFUSED_KINDS, (
        f"the pin no longer declares a delegate kind ({DECLARED_KINDS!r}), so the guards' "
        "delegation to the SDK is untested on the kind it was adopted for"
    )
    assert UNDECLARED_KINDS, "the arms that distinguish an allowlist from a denylist would vanish"


# -- the declared kinds: refused by type, and the person admitted ----------------------------


@pytest.mark.parametrize("kind", REFUSED_KINDS)
@pytest.mark.parametrize("where", sorted(ALL_GUARDS))
def test_every_DECLARED_non_person_kind_is_refused_with_ITS_OWN_type(where: str, kind: str) -> None:
    """Exact type, not ``PermissionError``: the two refusals are siblings, so a caller catching
    ``ServiceIdentityRefused`` alone would not catch a delegate, and that is a contract to see."""
    expected = _REFUSAL_TYPE.get(kind, ServiceIdentityRefused)
    with pytest.raises(PermissionError) as exc:
        ALL_GUARDS[where](_valid(kind), "some_operation")
    assert type(exc.value) is expected, (
        f"{where} refused kind {kind!r} with {type(exc.value).__name__}, not {expected.__name__}"
    )
    assert "some_operation" in str(exc.value), "the refusal does not say which operation refused"


@pytest.mark.parametrize("where", sorted(ALL_GUARDS))
def test_a_PERSON_is_ADMITTED(where: str) -> None:
    """The positive control. Deny-by-default has to prove its allow path or it proves nothing."""
    ALL_GUARDS[where](_valid("person", "alice@example.com"), "op")


# -- the arm the denylist could not pass -----------------------------------------------------


@pytest.mark.parametrize("kind", UNDECLARED_KINDS)
@pytest.mark.parametrize("where", sorted(ALL_GUARDS))
def test_an_UNDECLARED_kind_is_refused(where: str, kind: str) -> None:
    """THE ARM THAT MATTERS. Against an ``== "service"`` body every case here PASSES the guard.

    The SDK's message for an undeclared kind says "received a service identity", so the kind is
    not legible in it (reported to ca, 2026-10-01). Unreachable through a validated Initiator, so
    this arm asserts the refusal and its operation, not the wording.
    """
    with pytest.raises(ServiceIdentityRefused) as exc:
        ALL_GUARDS[where](_unvalidated(subject=f"subj:{kind or 'blank'}", kind=kind), "some_op")
    assert "some_op" in str(exc.value)


# -- on_behalf_of is provenance, never a gate input ------------------------------------------


@pytest.mark.parametrize("where", sorted(ALL_GUARDS))
def test_ON_BEHALF_OF_CANNOT_CHANGE_A_DECISION(where: str) -> None:
    """ca's acceptance negative 4. Vary the accountable person, hold subject and kind: a delegate
    stays refused and a person stays admitted, whatever the field holds -- including values the
    validators refuse, because a gate must not depend on validation having run."""
    guard = ALL_GUARDS[where]
    for on_behalf_of in (None, "", "alice@example.com", "person:root", "bob@example.com"):
        with pytest.raises(DelegateIdentityRefused):
            guard(_unvalidated(subject="delegate:lane-74", kind="delegate",
                               on_behalf_of=on_behalf_of), "op")
    for on_behalf_of in (None, "alice@example.com", "bob@example.com"):
        guard(_unvalidated(subject="alice@example.com", kind="person",
                           on_behalf_of=on_behalf_of), "op")


# -- the fleet wrappers ARE the SDK call -----------------------------------------------------


@pytest.mark.parametrize("where", sorted(FLEET_GUARDS))
def test_each_fleet_wrapper_is_ONE_call_to_the_SDK_guard(where: str) -> None:
    """The behavioural arms above cannot tell a faithful copy from the call. This one can: a copy
    reintroduced beside the call, or in place of it, changes the body's shape."""
    tree = ast.parse(_GUARD_SOURCES[where].read_text(encoding="utf-8"))
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_require_person"]
    assert len(fns) == 1, f"{where}: expected one _require_person, found {len(fns)}"
    body = [s for s in fns[0].body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    assert [ast.unparse(s) for s in body] == ["initiator.require_person(operation)"], (
        f"{where}._require_person is no longer exactly the SDK call: "
        f"{[ast.unparse(s) for s in body]}"
    )


# -- the census: no copy anywhere, and no comparison in the denylist form --------------------


def _kind_comparisons_in(tree: ast.AST) -> list[tuple[int, str, str]]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for comparator in node.comparators:
                if isinstance(comparator, ast.Constant) and comparator.value in DECLARED_KINDS:
                    out.append((node.lineno, ast.unparse(node.left), comparator.value))
    return out


def _initiator_kind_readers_in(tree: ast.AST) -> dict[str, set[str]]:
    """Functions that read ``.kind`` off a parameter annotated ``Initiator`` -> the attributes they
    read off it. Keyed on the ANNOTATION, so a copy is found whatever it names its parameter and
    whatever comparison form it uses, including ``not in ALLOWED``."""
    readers: dict[str, set[str]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = fn.args
        params = {
            a.arg
            for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
            if a.annotation is not None and "Initiator" in ast.unparse(a.annotation)
        }
        attrs = {
            n.attr for n in ast.walk(fn)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in params
        }
        if params and "kind" in attrs:
            readers[fn.name] = attrs
    return readers


def _shipped_trees(base: Path = _REPO):
    """Every module under the search roots EXCEPT inside a virtualenv. A venv is identified by its
    ``pyvenv.cfg``, not by a directory name: Lane 1's 09-29 census found this walk inside an
    untracked ``agent_fleet/docs_agent/.venv/`` flagging the SDK's own installed copy, and a name
    list (``.venv``) would miss the next venv someone names differently."""
    for root in _SEARCH_ROOTS:
        venvs = {cfg.parent for cfg in (base / root).rglob("pyvenv.cfg")}
        for path in sorted((base / root).rglob("*.py")):
            if any(v in path.parents for v in venvs):
                continue
            try:
                yield path.relative_to(base).as_posix(), ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue


#: THE COPY THIS FILE ONCE SEALED, in shape. The positive control for both matchers: an empty
#: census below is evidence only while the matchers still find this.
_THE_OLD_COPY = """
def _require_person(initiator: Initiator, operation: str) -> None:
    if initiator.kind == "service":
        raise ServiceIdentityRefused(operation)
"""


def test_the_census_matchers_still_FIND_the_copy_they_exist_to_catch() -> None:
    tree = ast.parse(_THE_OLD_COPY)
    assert _kind_comparisons_in(tree) == [(3, "initiator.kind", "service")]
    assert _initiator_kind_readers_in(tree) == {"_require_person": {"kind"}}


def test_no_shipped_code_compares_a_kind_or_reads_an_Initiators_kind() -> None:
    """The fleet holds NO copy of the guard. A fourth copy written from scratch reds here on the
    day it is written, because the population is derived from the annotation, not remembered.
    The walk's reach is asserted too, so an empty result is not an empty walk."""
    trees = list(_shipped_trees())
    assert any(rel == "agent_fleet/ontology_service/mesh_graph.py" for rel, _ in trees), (
        "the walk no longer reaches the module that held a copy"
    )
    comparisons = [(rel, *c) for rel, t in trees for c in _kind_comparisons_in(t)]
    readers = [f"{rel}::{name}" for rel, t in trees for name in _initiator_kind_readers_in(t)]
    assert not comparisons, f"shipped code compares against a declared kind: {comparisons!r}"
    assert not readers, (
        f"shipped code reads an Initiator's kind: {readers!r}. Call Initiator.require_person "
        "instead, so the allowlist stays written once."
    )


def test_the_walk_skips_a_VENV_by_its_pyvenv_cfg_and_keeps_its_sibling(tmp_path: Path) -> None:
    """Lane 1's red (e), reproduced in a tree this arm owns. The venv's directory name is one no
    name list would carry, and the sibling outside it holds the same copy, so the arm differs in
    exactly one thing: whether a ``pyvenv.cfg`` sits above the file."""
    venv = tmp_path / "agent_fleet" / "docs_agent" / "env-anything"
    (venv / "lib" / "site-packages" / "iagent_mesh").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = x", encoding="utf-8")
    (venv / "lib" / "site-packages" / "iagent_mesh" / "interfaces.py").write_text(
        _THE_OLD_COPY, encoding="utf-8")
    shipped = tmp_path / "agent_fleet" / "docs_agent" / "guard.py"
    shipped.write_text(_THE_OLD_COPY, encoding="utf-8")
    walked = [rel for rel, _ in _shipped_trees(tmp_path)]
    assert walked == ["agent_fleet/docs_agent/guard.py"], walked
