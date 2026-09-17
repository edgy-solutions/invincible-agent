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
relationship per registered verb, typed by the verb's own local name via `$verb_local`. That set
is whatever the fleet registers, so it cannot be declared as literals — the derivation below
takes QUOTED literals only, and `test_the_dynamic_verb_write_is_recognised_and_excluded` pins
that the exclusion is deliberate rather than a gap in the regex.

Run: uv run --frozen pytest tests/test_the_registrar_writes_what_the_sdk_declares.py -v
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_REGISTRAR = _ROOT / "agent_fleet" / "mesh_registrar" / "v2_substrate.py"

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


def written_edge_types() -> set:
    """The STRUCTURAL edge types this registrar actually writes, derived from its Cypher."""
    found = set()
    for s in _cypher_strings(_REGISTRAR):
        if "apoc.merge.relationship" in s or "-[" in s:
            found |= set(_APOC_LITERAL.findall(s))
            found |= set(_BRACKET_LITERAL.findall(s))
    return found


def _declared() -> set:
    try:
        from iagent_mesh.edge_types import declared_edge_types
    except ImportError:
        pytest.skip(
            "the pinned iagent-mesh predates `edge_types` (needs >= 0.9.3). THIS IS A SKIP, NOT "
            "A PASS: the registrar's writes are UNVERIFIED against any declaration until the "
            "fleet pin moves. Re-run after the pin."
        )
    return set(declared_edge_types("registrar"))


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
    """The per-verb relationship is typed by `$verb_local`, so it CANNOT be declared as a
    literal. Asserted so the exclusion is deliberate rather than a hole in the regex — if this
    write ever became a literal, the registry would need it and this arm says so."""
    src = _REGISTRAR.read_text(encoding="utf-8")
    assert "$verb_local" in src, (
        "the dynamic per-verb write is gone or renamed — if it became a literal type, add it to "
        "the SDK registry; if it moved, this exclusion needs re-deriving"
    )


# ── the two directions ───────────────────────────────────────────────────────────────────

def test_EVERY_TYPE_THE_REGISTRAR_WRITES_IS_DECLARED():
    """A structural edge type written and not declared is a write path the census will report
    forever and nobody owns."""
    undeclared = written_edge_types() - _declared()
    assert not undeclared, (
        f"the registrar writes {sorted(undeclared)} and the SDK declares none of them. Add them "
        f"to iagent_mesh.edge_types.REGISTRAR_EDGE_TYPES, or route the write through a door "
        f"that owns it."
    )


def test_EVERY_TYPE_THE_SDK_DECLARES_IS_ACTUALLY_WRITTEN():
    """THE ARM THAT CLOSES THE CROSS-REPO DRIFT, and the reason this file exists.

    Rename the type in v2_substrate.py and the SDK keeps declaring a type nobody emits. Without
    this direction the census reports an undeclared type while the SDK quietly declares a dead
    one, and neither repo can see the disagreement.

    NOT checked against the graph: live edges prove a writer existed somewhere, and doc-tools
    writes several types this interface does not. The question is whether THIS interface still
    writes what it promised.
    """
    unwritten = _declared() - written_edge_types()
    assert not unwritten, (
        f"the SDK declares {sorted(unwritten)} for the registrar and this registrar writes none "
        f"of them. Either a write was renamed or removed and the declaration was not, or the "
        f"declaration was never true. Both are the silent cross-repo drift this arm exists for — "
        f"a live edge of that type in the graph does NOT clear it, because another writer may be "
        f"the author."
    )
