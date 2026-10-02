"""CONFORMANCE FOR THE EDGE-TYPE REGISTRY: the registrar writes exactly what the SDK declares.

The declaration lives in `iagent_mesh.edge_types` — beside the Protocol that promises the writes
— and the writes live here. That split is deliberate (it is how `MeshVectors` is built:
declaration where the contract is, conformance where the writes happen) and it creates a risk
this file exists to close.

THE RISK, STATED PLAINLY: the SDK has no graph driver, so it declares edges it cannot emit.
Rename the type in `v2_substrate.py` and the SDK keeps declaring a type nobody writes, while the
census reports an undeclared one nobody declared. Silent, cross-repo, invisible from either side
alone. **Duplicate only where a wrong copy FAILS LOUDLY** — this is the referee that makes one
copy in each repo safe.

BOTH DIRECTIONS, AND THE SECOND IS THE ONE THAT CATCHES THE DRIFT:

    written and NOT declared    a new structural edge type nobody registered
    declared and NEVER written  the rename above, or a type that was removed

"NEVER WRITTEN" MEANS NO WRITER IN THIS INTERFACE — not "no edges in the graph". Measured: every
type the SDK does not declare still has live edges (INSTANCE_OF 21, HAS_CHILD 54, SUBJECT_TO 20,
GOVERNED_BY 7, REQUIRES_TOOL 2, HAS_PART 1, REPLACED_BY 1, REFERENCES 1), written by doc-tools'
domain-plugin ingest — a THIRD writer outside ADR-0054's two doors. A seal that read the graph
would red because another repo is the author, which is not the drift it is for.

THE DYNAMIC WRITE IS EXCLUDED BY CONSTRUCTION AND ON PURPOSE. The registrar also emits one
relationship per registered verb, typed by the verb's own local name (`PREDICATE_EDGE_FAMILY`'s
`relationship_type` is a FUNCTION, `_get_verb_local_name`). That set is whatever the fleet
registers, so it cannot be declared as literals — the derivation below takes STRING CONSTANTS
only, and `test_the_dynamic_verb_write_is_recognised_and_excluded` pins that the exclusion is
deliberate rather than a gap in the derivation.

TWO WRITE FORMS, TWO DERIVATIONS. Since the registrar adopted the SDK's `MeshGraphWriter`
(v0.9.5), it holds no Cypher: an edge type is the `relationship_type` of a FAMILY — a module-level
dict handed to the writer. The trace writer still writes Cypher. `written_edge_types` takes the
union of both, so a raw Cypher write re-added to the registrar is still seen.

Run: uv run --frozen pytest tests/test_the_registrar_writes_what_the_sdk_declares.py -v
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_REGISTRAR = _ROOT / "agent_fleet" / "mesh_registrar" / "v2_substrate.py"

#: BOTH DOORS, now that the write census has landed and the trace writer's set is declared rather
#: than unset. ADR-0054 names two; the census partitions all thirteen structural types 13/13 with
#: the remaining eight belonging to doc-tools' ingest — a THIRD door, in a sibling repo, which is
#: a finding rather than an entry and therefore has no row here.
_SOURCES = {
    "registrar": _REGISTRAR,
    "trace_writer": _ROOT / "src" / "iagent" / "answer_artifact_writer.py",
}

#: A Cypher relationship type is SCREAMING_CASE here. Two write forms, and the first version of
#: this derivation knew only the second — `PARAMETERISED_BY` goes through apoc, so a
#: bracket-only regex MISSED THE WRITE ITS AUTHOR HAD JUST MADE. An enumeration that cannot see a
#: known write has unreliable negatives, which is fatal for the "declared and never written" arm.
_APOC_LITERAL = re.compile(r"apoc\.merge\.relationship\s*\(\s*\w+\s*,\s*'([A-Z][A-Z0-9_]{2,})'")
_BRACKET_LITERAL = re.compile(r"-\[\s*\w*\s*:\s*([A-Z][A-Z0-9_]{2,})\s*\]")


def _cypher_strings(path: Path) -> list:
    """Every string CONSTANT in the module, by AST.

    Constants rather than raw text on purpose: a comment mentioning an edge type is not a write,
    and a line scan cannot tell them apart. That distinction has cost this fleet three false
    findings in a day — a seal tripping on prose that documented compliance with it, a violation
    report drafted against a reader, and a regex that swept `DELIBERATELY` out of a comment.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _families(path: Path) -> dict:
    """Every writer FAMILY the module uses: name -> the AST of its `relationship_type` value.

    A family is a MODULE-LEVEL DICT LITERAL WITH A `relationship_type` KEY THAT THE MODULE PASSES
    AS AN ARGUMENT. All three halves discriminate: a dict without the key is not writer config, and
    one that is declared but never handed to anything writes nothing. An inline
    `Neo4jGraphWriter(..., relationship_type=...)` is collected too, under its call's source, so a
    writer constructed without a family cannot hide from this.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    declared = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for key, value in zip(node.value.keys, node.value.values):
                if isinstance(key, ast.Constant) and key.value == "relationship_type":
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            declared[target.id] = value
    passed = set()
    inline = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                if isinstance(arg, ast.Name) and arg.id in declared:
                    passed.add(arg.id)
            for kw in node.keywords:
                if kw.arg == "relationship_type":
                    inline[ast.unparse(node)] = kw.value
    return {**{n: declared[n] for n in sorted(passed)}, **inline}


def written_edge_types(interface: str = "registrar") -> set:
    """The STRUCTURAL edge types ``interface`` actually writes: its families' constant types plus
    any its own Cypher names."""
    found = {v.value for v in _families(_SOURCES[interface]).values()
             if isinstance(v, ast.Constant) and isinstance(v.value, str)}
    for s in _cypher_strings(_SOURCES[interface]):
        if "apoc.merge.relationship" in s or "-[" in s:
            found |= set(_APOC_LITERAL.findall(s))
            found |= set(_BRACKET_LITERAL.findall(s))
    return found


def _declared(interface: str = "registrar") -> set:
    try:
        from iagent_mesh.edge_types import declared_edge_types
    except ImportError:
        pytest.skip(
            "the pinned iagent-mesh predates `edge_types` (needs >= 0.9.3). THIS IS A SKIP, NOT "
            "A PASS: the registrar's writes are UNVERIFIED against any declaration until the "
            "fleet pin moves. Re-run after the pin."
        )
    return set(declared_edge_types(interface))


# ── the derivation must be shown to work before either direction is trusted ──────────────

def test_THE_DERIVATION_FINDS_THE_KNOWN_WRITE():
    """POSITIVE CONTROL, AND IT IS NOT CEREMONIAL. A derivation that found nothing would make
    "declared and never written" red on everything and "written and not declared" pass on
    everything — both arms wrong, in opposite directions, from one silent failure."""
    written = written_edge_types()
    assert "PARAMETERISED_BY" in written, (
        f"the derivation cannot see the registrar's own PARAMETERISED_BY write (found: "
        f"{sorted(written)}). Both conformance arms below are meaningless until it can."
    )


def test_THE_DERIVATION_READS_CONSTANTS_NOT_PROSE():
    """A comment naming an edge type is not a write. The registrar's docstrings discuss
    PARAMETERISED_BY at length; if those counted, the derivation would report types from
    explanations of types."""
    fake = _ROOT / "agent_fleet" / "mesh_registrar" / "v2_substrate.py"
    src = fake.read_text(encoding="utf-8")
    assert "PARAMETERISED_BY" in src
    # the module's own comments mention it; the AST read must still find exactly the writes
    assert written_edge_types() == {"PARAMETERISED_BY"}, (
        f"the derivation picked up something that is not a write: {sorted(written_edge_types())}"
    )


def test_the_dynamic_verb_write_is_recognised_and_excluded():
    """The per-verb relationship is typed by a FUNCTION of the verb, so it CANNOT be declared as
    a literal. Asserted so the exclusion is deliberate rather than a hole in the derivation — if
    this write ever became a literal, the registry would need it and this arm says so."""
    dynamic = {name: ast.unparse(v) for name, v in _families(_REGISTRAR).items()
               if not isinstance(v, ast.Constant)}
    assert dynamic == {"PREDICATE_EDGE_FAMILY": "_get_verb_local_name"}, (
        f"the dynamic per-verb write is gone, renamed or joined by another ({dynamic}) — if it "
        f"became a literal type, add it to the SDK registry; if it moved, re-derive this exclusion"
    )


def test_THE_FAMILY_DERIVATION_SEES_ONLY_WHAT_IS_PASSED():
    """THE CONTROL FOR `_families`, differing from the registrar in exactly what the rule decides
    on: one family is passed, one is only declared, and one writer is built inline."""
    import tempfile

    src = (
        "USED = {'relationship_type': 'USED_T'}\n"
        "IDLE = {'relationship_type': 'IDLE_T'}\n"
        "w = make(USED)\n"
        "x = Neo4jGraphWriter(driver=d, relationship_type='INLINE_T')\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "m.py"
        path.write_text(src, encoding="utf-8")
        got = {ast.unparse(v) for v in _families(path).values()}
    assert got == {"'USED_T'", "'INLINE_T'"}, got


# ── the two directions ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("interface", sorted(_SOURCES))
def test_EVERY_TYPE_A_DOOR_WRITES_IS_DECLARED(interface):
    """A structural edge type written and not declared is a write path the census will report
    forever and nobody owns."""
    undeclared = written_edge_types(interface) - _declared(interface)
    assert not undeclared, (
        f"{interface} writes {sorted(undeclared)} and the SDK declares none of them. Add them to "
        f"iagent_mesh.edge_types, or route the write through a door that owns it."
    )


@pytest.mark.parametrize("interface", sorted(_SOURCES))
def test_EVERY_TYPE_THE_SDK_DECLARES_IS_ACTUALLY_WRITTEN(interface):
    """THE ARM THAT CLOSES THE CROSS-REPO DRIFT, and the reason this file exists.

    Rename the type in the writing module and the SDK keeps declaring a type nobody emits.
    Without this direction the census reports an undeclared type while the SDK quietly declares a
    dead one, and neither repo can see the disagreement.

    NOT checked against the graph: live edges prove a writer existed somewhere, and doc-tools
    writes eight types neither door does. The question is whether THIS interface still writes
    what it promised.
    """
    unwritten = _declared(interface) - written_edge_types(interface)
    assert not unwritten, (
        f"the SDK declares {sorted(unwritten)} for {interface} and that module writes none of "
        f"them. Either a write was renamed or removed and the declaration was not, or the "
        f"declaration was never true. A live edge of that type does NOT clear it — another "
        f"writer may be the author."
    )


def test_THE_DERIVATION_REPRODUCES_THE_CENSUS_PARTITION():
    """CROSS-CHECK AGAINST A DIFFERENT METHOD. The eo lane's write census partitioned all thirteen
    types by walking the fleet; this file derives two of the three sets by AST over the writing
    modules. Two instruments, one answer — and if they ever disagree, the census is the authority
    and this derivation is the thing to fix, because membership is DERIVED not guessed."""
    assert written_edge_types("trace_writer") == {
        "CITES", "DERIVED_FROM", "PRODUCED_BY", "PRODUCED_FOR"
    }, "the artifact writer's writes no longer match the census's partition for it"
    assert written_edge_types("registrar") == {"PARAMETERISED_BY"}
