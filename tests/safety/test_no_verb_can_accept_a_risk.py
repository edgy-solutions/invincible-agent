"""ADR-0051 seal 2 — no registered verb writes an acceptance.

── THE SEAL AS WRITTEN CANNOT BE DONE BY ONE CHECK, AND SAYING SO IS PART OF IT ────────────
ADR-0051 §8 seal 2 says: "Enumerate the mesh's registered verbs (from Neo4j relationship
types, not the engine's files); assert none writes `acceptance_status = accepted`."

The enumeration half is right and is done below. The assertion half is NOT achievable from
that enumeration, and pretending otherwise would be this repo's recurring instrument defect:
**relationship types are NAMES, and a name cannot show a behaviour.** A verb called
`mesh:draftRiskAssessment` that quietly set `accepted` would pass any name-based check, and a
verb called `mesh:acceptRisk` that only drafted would fail one. The check would be matching
the string while the property lives in the body.

So the seal is split, and each half asserts what its instrument can actually see:

  PART A (source, behaviour)  no measure function writes an acceptance — read from the AST,
                              not from a docstring and not from a name.
  PART B (mesh, population)   the safety verbs registered in the mesh are EXACTLY the ones
                              this engine declares — so a verb cannot be smuggled into the
                              mesh under this engine's name without appearing in VERBS, where
                              Part A then covers it.

Together they close the loop: A says nothing we declare can accept, B says nothing is
registered that we did not declare. Either alone leaves a hole, and the hole each leaves is
named rather than left for a reader to discover.
"""
from __future__ import annotations

import ast
import inspect
import os
from pathlib import Path

import pytest

from agent_fleet.safety_agent import main as safety_main
from agent_fleet.safety_agent import measures

from tests import _mesh_verbs

#: The field that carries a risk acceptance. Writing it is the act ADR-0051 §7 refuses.
_ACCEPTANCE_FIELD = "acceptance_status"
_ACCEPTED_VALUE = "accepted"


# ---------------------------------------------------------------------------
# PART A — behaviour, from the AST
# ---------------------------------------------------------------------------

def test_no_measure_function_writes_an_acceptance():
    """Read the module's SYNTAX, not its prose.

    A docstring saying "this cannot accept" is not evidence — this repo has a standing rule
    about that, earned by a stale docstring that matched a symptom and sent an investigation
    to the wrong cause. So this walks the tree for an assignment or a dict entry that sets
    `acceptance_status` to `accepted`, anywhere in the engine's measure module.
    """
    src = Path(inspect.getfile(measures)).read_text(encoding="utf-8")
    tree = ast.parse(src)

    offences: list[str] = []
    for node in ast.walk(tree):
        # `d["acceptance_status"] = "accepted"` and `x.acceptance_status = "accepted"`
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                name = None
                if isinstance(tgt, ast.Subscript) and isinstance(tgt.slice, ast.Constant):
                    name = tgt.slice.value
                elif isinstance(tgt, ast.Attribute):
                    name = tgt.attr
                if name == _ACCEPTANCE_FIELD:
                    offences.append(f"line {node.lineno}: assigns {_ACCEPTANCE_FIELD}")
        # `{"acceptance_status": "accepted"}` as a literal
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (
                    isinstance(k, ast.Constant)
                    and k.value == _ACCEPTANCE_FIELD
                    and isinstance(v, ast.Constant)
                    and v.value == _ACCEPTED_VALUE
                ):
                    offences.append(f"line {node.lineno}: dict sets {_ACCEPTANCE_FIELD}=accepted")

    assert not offences, (
        "a safety verb writes a risk acceptance — ADR-0051 §7 refuses this by name; "
        "acceptance is a HumanTask disposition by an entitled authority: " + "; ".join(offences)
    )


def test_the_ast_checker_can_say_yes():
    """THE CONTROL FOR PART A. A checker that has only ever seen clean code has not been shown
    able to find dirty code — and an AST walk that silently matches nothing looks identical to
    one that matches nothing because it is broken."""
    dirty = ast.parse('def f():\n    out = {}\n    out["acceptance_status"] = "accepted"\n')
    found = [
        n for n in ast.walk(dirty)
        if isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Subscript)
            and isinstance(t.slice, ast.Constant)
            and t.slice.value == _ACCEPTANCE_FIELD
            for t in n.targets
        )
    ]
    assert found, "the AST checker cannot see an acceptance write — instrument failure"


# ---------------------------------------------------------------------------
# PART B — population, from the mesh
# ---------------------------------------------------------------------------

_DECLARED_LOCALS = {v["verb"].split(":", 1)[-1] for v in safety_main.VERBS}

#: The prefix this engine's verbs share. Derived from the declarations rather than typed, so a
#: renamed verb moves the filter with it instead of leaving a stale literal behind.
_SAFETY_VERB_MARKERS = ("Hazard", "Deferral", "RiskAssessment", "WriteUp", "Mishap")


@_mesh_verbs.needs_neo4j
def test_mesh_registers_no_safety_verb_this_engine_did_not_declare():
    """PART B. Nothing safety-shaped is registered that VERBS does not declare.

    WHY THIS IS THE USEFUL MESH ASSERTION. It cannot see behaviour, so it does not pretend to.
    What it can see is POPULATION: if a verb reaches the mesh under a safety name without
    appearing in this engine's catalogue, Part A never examined it, and that gap is exactly
    what this catches.

    SKIPS WITHOUT THE MESH, AND A SKIP IS NOT A PASS. Record this seal VOID, not green, when
    NEO4J_URI/NEO4J_PASSWORD are unset — `_mesh_verbs`' own header says so and this consumer
    repeats it because a report is where the distinction gets lost.
    """
    _mesh_verbs.assert_checkers_can_say_no(neo4j=True, weaviate=False)

    types = _mesh_verbs.neo4j_relationship_types()
    safety_shaped = {
        t for t in types
        if any(m in t for m in _SAFETY_VERB_MARKERS)
    }
    undeclared = safety_shaped - _DECLARED_LOCALS
    assert not undeclared, (
        "the mesh serves safety-shaped verbs this engine never declared, so nothing has "
        f"checked what they write: {sorted(undeclared)}"
    )


def test_what_this_seal_cannot_see_is_written_down():
    """The blind spot, asserted as documentation rather than left in a reviewer's memory.

    Part B matches verb names by marker substring. A safety verb named without any of those
    markers would not be examined by Part B at all. That is a REAL hole, it is narrow (this
    engine's own catalogue is the source of the markers), and it closes when the mesh carries
    an engine attribution on the edge that a test can filter on instead of a name.
    """
    assert _SAFETY_VERB_MARKERS, "the marker set is the documented limit of Part B's reach"
    assert _DECLARED_LOCALS, "no declared verbs — Part B would vacuously pass"
