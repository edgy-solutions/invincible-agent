"""The person guard is an ALLOWLIST in every copy, and a kind nobody has declared is refused.

**What this file is defending, in one sentence.** ``require_person`` decides whether a read may be
attributed to whoever asked for it, and until 2026-09-27 every copy of it was written as
``if kind == "service": raise`` -- a comparison that names what it refuses and therefore ADMITS
everything it does not name. The SDK then grew a third kind (``delegate``, iagent-mesh-sdk
``7e429d5``, still untagged). Every one of those copies would have passed a delegate through
silently. This file seals the flip to ``!= "person"`` in the two fleet copies, and it seals it in
the form that cannot rot: the population comes from the type, and the arm that matters uses a kind
that has never been declared at all.

**WHY A STAND-IN, AND WHY IT IS NOT A CHEAT.** The pin is ``iagent-mesh @ v0.9.3``, whose
``Initiator.kind`` is ``Literal["person", "service"]`` -- so *this tree cannot construct a
delegate*, and an arm restricted to constructible kinds could not tell the flip from the defect it
replaced (over two kinds, denylist and allowlist are behaviour-identical, which is exactly why the
defect survived three copies). The undeclared-kind arms therefore hand the guards a duck-typed
object. ``test_the_STAND_IN_is_faithful_because_the_guards_read_NOTHING_ELSE`` is that probe's
control: it derives, from the AST, every attribute each guard reads off its initiator parameter and
fails if one is not something the stand-in carries. A probe that stops matching its caller stops
being evidence, and here that is a measured property rather than an assurance.

Run: uv run --frozen pytest tests/test_the_person_guard_is_an_allowlist_everywhere.py -v
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

import pytest

# No sys.path surgery -- ``tests`` is a package, so pytest has already prepended the repo root.
# Inserting it again is pollution with no purpose, and this suite has already paid for one of
# those (pyproject.toml's dev group records a file that could only pass by borrowing another
# file's sys.path setup, and broke nine security tests with its own sys.modules cleanup).
_REPO = Path(__file__).resolve().parents[1]

from iagent_mesh.interfaces import Initiator, ServiceIdentityRefused  # noqa: E402

from agent_fleet.ontology_service.mesh_graph import Neo4jGraph  # noqa: E402
from agent_fleet.ontology_service.mesh_vectors import WeaviateVectors  # noqa: E402

# -- the population, derived from the type and never typed -----------------------------------

#: Every kind the PINNED SDK permits. Read off the annotation so that widening the Literal widens
#: this file's coverage without anyone remembering to come back here.
DECLARED_KINDS: tuple[str, ...] = get_args(Initiator.model_fields["kind"].annotation)

#: The kinds that must be refused, derived by SUBTRACTION rather than listed. If a future kind is
#: added to the Literal and is meant to be admitted, this file goes red and says so -- which is
#: the correct outcome for a boundary check: a new kind's admission is a decision, not a default.
REFUSED_KINDS: tuple[str, ...] = tuple(k for k in DECLARED_KINDS if k != "person")

#: Kinds NO Literal declares. ``delegate`` is real in the SDK's source and unreachable at this pin
#: (see the ratchet arms at the end); the other two are arbitrary on purpose -- an allowlist must
#: refuse a kind nobody has thought of yet, and enumerating the ones we HAVE thought of is the
#: denylist mistake one layer up.
UNDECLARED_KINDS: tuple[str, ...] = ("delegate", "robot", "")

#: The two fleet copies. Statics, so they are callable without building an implementation.
FLEET_GUARDS = {
    "mesh_vectors.WeaviateVectors": WeaviateVectors._require_person,
    "mesh_graph.Neo4jGraph": Neo4jGraph._require_person,
}

_GUARD_SOURCES = {
    "mesh_vectors.WeaviateVectors": _REPO / "agent_fleet" / "ontology_service" / "mesh_vectors.py",
    "mesh_graph.Neo4jGraph": _REPO / "agent_fleet" / "ontology_service" / "mesh_graph.py",
}

_SEARCH_ROOTS = ("agent_fleet", "src")


@dataclass(frozen=True)
class _StandIn:
    """An initiator of a kind the pin cannot mint. Carries exactly what the guards read."""

    subject: str
    kind: str
    on_behalf_of: str | None = None


def _sdk_guard(initiator, operation: str) -> None:
    """The SDK's own copy, called the way the fleet's ontology implementation calls it."""
    initiator.require_person(operation)


# -- the population is real ------------------------------------------------------------------


def test_the_POPULATION_comes_from_the_TYPE_and_contains_a_person_and_a_refusal() -> None:
    """Without this, every parametrized arm below could be running over an empty list."""
    assert "person" in DECLARED_KINDS, (
        f"the allowlist's ALLOWED value is not in the declared kinds {DECLARED_KINDS!r} -- "
        "either the SDK renamed it or this file is guarding a value nothing can carry"
    )
    assert REFUSED_KINDS, (
        f"declared kinds {DECLARED_KINDS!r} leave nothing to refuse, so every refusal arm in "
        "this file would pass over an empty parametrization"
    )
    assert UNDECLARED_KINDS, "the arms that distinguish an allowlist from a denylist would vanish"


# -- the constructible kinds: refused, and the person admitted -------------------------------


@pytest.mark.parametrize("kind", REFUSED_KINDS)
@pytest.mark.parametrize("where", sorted(FLEET_GUARDS))
def test_every_DECLARED_non_person_kind_is_refused_by_both_fleet_guards(
    where: str, kind: str
) -> None:
    with pytest.raises(ServiceIdentityRefused):
        FLEET_GUARDS[where](Initiator(subject=f"subj:{kind}", kind=kind), "op")


@pytest.mark.parametrize("kind", REFUSED_KINDS)
def test_every_DECLARED_non_person_kind_is_refused_by_the_SDK_guard(kind: str) -> None:
    with pytest.raises(ServiceIdentityRefused):
        _sdk_guard(Initiator(subject=f"subj:{kind}", kind=kind), "op")


@pytest.mark.parametrize("where", sorted(FLEET_GUARDS))
def test_a_PERSON_is_ADMITTED_by_both_fleet_guards(where: str) -> None:
    """The positive control. Deny-by-default has to prove its allow path or it proves nothing."""
    assert FLEET_GUARDS[where](Initiator(subject="alice@example.com", kind="person"), "op") is None


def test_a_PERSON_is_ADMITTED_by_the_SDK_guard() -> None:
    _sdk_guard(Initiator(subject="alice@example.com", kind="person"), "op")


# -- the arm the denylist could not pass -----------------------------------------------------


@pytest.mark.parametrize("kind", UNDECLARED_KINDS)
@pytest.mark.parametrize("where", sorted(FLEET_GUARDS))
def test_an_UNDECLARED_kind_is_refused_by_both_fleet_guards(where: str, kind: str) -> None:
    """THE ARM THAT MATTERS. Against the old ``== "service"`` body every case here PASSED the
    guard, and this arm is the only red in the file: over the pin's two kinds no other arm here
    can tell the two bodies apart.
    """
    with pytest.raises(ServiceIdentityRefused):
        FLEET_GUARDS[where](_StandIn(subject=f"subj:{kind or 'blank'}", kind=kind), "op")


@pytest.mark.parametrize("kind", UNDECLARED_KINDS)
@pytest.mark.parametrize("where", sorted(FLEET_GUARDS))
def test_the_refusal_NAMES_the_kind_it_refused(where: str, kind: str) -> None:
    """``DelegateIdentityRefused`` is not importable at this pin, so the kind has to be legible in
    the message or a delegate refusal is indistinguishable from a service one in a log.
    """
    with pytest.raises(ServiceIdentityRefused) as exc:
        FLEET_GUARDS[where](_StandIn(subject="subj:x", kind=kind), "some_operation")
    assert repr(kind) in str(exc.value), (
        f"{where} refused kind {kind!r} without naming it: {str(exc.value)!r}"
    )
    assert "some_operation" in str(exc.value), "the refusal does not say which operation refused"


# -- on_behalf_of is provenance, never a gate input ------------------------------------------


@pytest.mark.parametrize("where", sorted(FLEET_GUARDS))
def test_ON_BEHALF_OF_CANNOT_CHANGE_A_DECISION(where: str) -> None:
    """ca's acceptance negative 4. Vary the accountable person, hold subject and kind: a delegate
    stays refused, and no value of this field buys admission. The field names who a delegate
    answers to; letting it decide anything is the authz-subject / provenance-actor collapse.
    """
    guard = FLEET_GUARDS[where]
    for on_behalf_of in (None, "", "alice@example.com", "person:root", "bob@example.com"):
        with pytest.raises(ServiceIdentityRefused):
            guard(
                _StandIn(subject="delegate:lane-74", kind="delegate", on_behalf_of=on_behalf_of),
                "op",
            )
    # ...and it cannot take admission AWAY from a person either: the same field, the other
    # direction, which is the half a "vary it and stay refused" arm alone would miss.
    for on_behalf_of in (None, "alice@example.com", "bob@example.com"):
        assert (
            guard(
                _StandIn(subject="alice@example.com", kind="person", on_behalf_of=on_behalf_of),
                "op",
            )
            is None
        )


# -- the census: no third fleet copy, and no copy in the denylist form -----------------------


def _kind_comparisons() -> list[tuple[str, int, str, str]]:
    """Every comparison against a declared kind literal, anywhere the fleet ships code.

    AST rather than text, so the prose in a docstring that QUOTES the old denylist (this file and
    both guards do) is not mistaken for the code being sealed.
    """
    out: list[tuple[str, int, str, str]] = []
    for root in _SEARCH_ROOTS:
        for path in sorted((_REPO / root).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                for comparator in node.comparators:
                    if isinstance(comparator, ast.Constant) and comparator.value in DECLARED_KINDS:
                        rel = path.relative_to(_REPO).as_posix()
                        out.append((rel, node.lineno, ast.unparse(node.left), comparator.value))
    return out


def _initiator_kind_readers() -> dict[str, set[str]]:
    """Functions that read ``.kind`` off a parameter annotated ``Initiator`` -> the attributes they
    read off it. Keyed on the ANNOTATION, so a new copy is found whatever it names its parameter
    and whatever comparison form it uses -- including ``not in ALLOWED``, which the comparison
    census above cannot see.
    """
    readers: dict[str, set[str]] = {}
    for root in _SEARCH_ROOTS:
        for path in sorted((_REPO / root).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                args = fn.args
                params = {
                    a.arg
                    for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
                    if a.annotation is not None and "Initiator" in ast.unparse(a.annotation)
                }
                if not params:
                    continue
                attrs = {
                    n.attr
                    for n in ast.walk(fn)
                    if isinstance(n, ast.Attribute)
                    and isinstance(n.value, ast.Name)
                    and n.value.id in params
                }
                if "kind" in attrs:
                    readers[f"{path.relative_to(_REPO).as_posix()}::{fn.name}"] = attrs
    return readers


EXPECTED_COPIES = {
    "agent_fleet/ontology_service/mesh_graph.py::_require_person",
    "agent_fleet/ontology_service/mesh_vectors.py::_require_person",
}


def test_the_only_kind_literal_the_fleet_NAMES_is_person() -> None:
    """The denylist form, caught at the declaration. A guard written as ``== "service"`` names a
    kind it refuses, and naming what to refuse is the defect itself -- so the sealed property is
    not "this line says ``!= person``" but "no shipped comparison names any other kind at all."
    That holds for a fourth copy written from scratch, not only for a revert of these two.
    """
    comparisons = _kind_comparisons()
    assert comparisons, (
        "no comparison against any declared kind found in "
        f"{_SEARCH_ROOTS!r} -- the guards are gone, or the matcher no longer reaches them"
    )
    offenders = [c for c in comparisons if c[3] != "person"]
    assert not offenders, (
        "a shipped comparison names a kind other than 'person', which is the denylist shape this "
        f"file exists to keep out: {offenders!r}"
    )


def test_the_set_of_fleet_COPIES_is_exactly_the_two_that_are_sealed_here() -> None:
    """A FOURTH copy is the failure mode, not a fourth kind. Both existing copies were written
    before anyone intended two, and the third (the SDK's) drifted out of step with them for long
    enough that widening the Literal became a silent admission. A new one reds here on the day it
    is written, because the population is derived from the annotation rather than remembered.
    """
    found = set(_initiator_kind_readers())
    assert found == EXPECTED_COPIES, (
        "the set of functions reading an Initiator's kind has changed.\n"
        f"  unsealed copies: {sorted(found - EXPECTED_COPIES)}\n"
        f"  sealed but gone: {sorted(EXPECTED_COPIES - found)}\n"
        "A new copy must be added to EXPECTED_COPIES *and* to FLEET_GUARDS, so every arm in this "
        "file runs against it. Better: delete it and call Initiator.require_person once the pin "
        "moves (ca's packet, 2026-09-27)."
    )


@pytest.mark.parametrize("where", sorted(FLEET_GUARDS))
def test_the_STAND_IN_is_faithful_because_the_guards_read_NOTHING_ELSE(where: str) -> None:
    """The control for the undeclared-kind probe. Those arms hand the guards a duck-typed object
    because the pin cannot mint the kind; that is evidence only while the guards read nothing the
    stand-in does not carry. Derived from the AST, so it is measured rather than assumed.
    """
    carried = set(_StandIn.__dataclass_fields__)
    source = _GUARD_SOURCES[where].relative_to(_REPO).as_posix()
    reads = [
        attrs for key, attrs in _initiator_kind_readers().items() if key.startswith(source + "::")
    ]
    assert reads, f"no Initiator-kind reader found in {source} to control"
    for attrs in reads:
        assert attrs <= carried, (
            f"{where} reads {sorted(attrs - carried)} off its initiator, which the stand-in does "
            f"not carry -- the undeclared-kind arms are no longer probing the real guard. Add the "
            f"attribute to _StandIn (it carries {sorted(carried)})."
        )


# -- the ratchet: what is blocked, stated so that it reds when it unblocks --------------------


def test_THE_PIN_CANNOT_MINT_A_DELEGATE_and_this_arm_reds_when_it_can() -> None:
    """A BLOCKER WRITTEN AS A MEASUREMENT. The SDK's source has ``delegate`` and ``on_behalf_of``;
    the installed pin (v0.9.3) does not, and v0.9.4 is not cut. So the delegate half of this work
    cannot be finished here, and saying so only in prose would leave the next person to
    rediscover it.

    WHEN THIS GOES RED the pin has moved, and three things become possible in the same commit:
      1. move "delegate" out of UNDECLARED_KINDS -- REFUSED_KINDS picks it up from the Literal;
      2. delete both fleet copies and call ``Initiator.require_person`` (ca's packet) -- at THIS
         pin that call is still the denylist, which is why the copies exist at all;
      3. raise ``DelegateIdentityRefused`` instead of naming the kind in the message.
    """
    assert "delegate" not in DECLARED_KINDS, (
        "the pin now declares a delegate kind -- see this docstring for the three changes it "
        f"unblocks. Declared kinds are {DECLARED_KINDS!r}."
    )
    with pytest.raises(Exception):
        Initiator(subject="delegate:lane-74", kind="delegate", on_behalf_of="alice@example.com")


def test_DELEGATE_IDENTITY_REFUSED_is_not_importable_at_this_pin() -> None:
    """The refusal TYPE half of the same ratchet. While this passes, a delegate refusal can only be
    told from a service refusal by reading the message -- which is why one arm above asserts that
    the message names the kind.
    """
    import iagent_mesh.interfaces as sdk

    assert not hasattr(sdk, "DelegateIdentityRefused"), (
        "the pin now exports DelegateIdentityRefused: both fleet guards should raise it for a "
        "delegate, and anything catching ServiceIdentityRefused must catch the sibling too "
        "(ca's packet, 2026-09-27 -- measured then: nothing in this repo catches either)."
    )
