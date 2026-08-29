"""`duration_ms` is a real measurement or it is nothing (2026-08-24).

The producer half of the render work cortex-ui shipped in 340c969. Both halves of the
measurement already existed and were never subtracted: `valid_as_of` is stamped at bundle
birth, and `status` flips to "complete" at exactly one site whose own comment says so. The
gap was three declarations, not a mechanism.

WHY ABSENCE IS THE DEFAULT AND MUST STAY REPRESENTABLE. Every artifact in the substrate
predates this field and will never have a duration, so on day one absence is most of the
list. `0` beside an answer is a CLAIM that it returned instantly; NULL/None is the honest
absence of a measurement. Zero itself is legal and meaningful — a cache hit is a real
sub-millisecond result — so absence and zero must not collapse onto one falsy value.

SCOPE. IN: the model default, the success-only rule, and the SUBTRACTION'S OPERANDS.
OUT: that a live gateway run produces a plausible number — that needs a live stream, and
this file cannot see it. Stated per [[a-green-check-proves-only-its-scope]].
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_GATEWAY = _REPO / "src" / "iagent" / "gateway.py"
_WRITER = _REPO / "src" / "iagent" / "answer_artifact_writer.py"
_PROJECTOR = _REPO / "src" / "iagent" / "projector" / "apply_loop.py"


# ── PROOF 3: absence is the default, and zero is not absence ────────────────
def test_the_field_defaults_to_None_never_zero():
    from iagent.answer_artifact_writer import AnswerArtifactBundle

    fld = {f.name: f for f in dataclasses.fields(AnswerArtifactBundle)}["duration_ms"]
    assert fld.default is None, (
        "duration_ms defaulted to something other than None. Every pre-existing artifact "
        "would then claim a duration it never had — 0 reads as 'returned instantly'."
    )


def test_zero_survives_as_a_real_value():
    """A cache hit is a genuine sub-millisecond measurement. If absence and zero collapse
    onto falsy, the FASTEST answers become the ones that look unmeasured."""
    src = _PROJECTOR.read_text(encoding="utf-8")
    line = next(l for l in src.splitlines() if '"duration_ms":' in l)
    assert "or 0" not in line and "or 0" not in line.replace(" ", ""), (
        f"projector coerces absence to zero: {line.strip()!r}"
    )


# ── PROOF 1 + 4: the stamp exists, and its OPERANDS are pinned ──────────────
def _stamp_assignment() -> ast.Assign:
    """The single `_artifact_bundle["duration_ms"] = ...` assignment, located by AST."""
    tree = ast.parse(_GATEWAY.read_text(encoding="utf-8"))
    found = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Subscript)
                and isinstance(t.slice, ast.Constant)
                and t.slice.value == "duration_ms"
                for t in n.targets)
    ]
    assert len(found) == 1, (
        f"expected exactly ONE duration_ms stamp in gateway.py, found {len(found)}. "
        "More than one site is how a stamp drifts away from the status it measures."
    )
    return found[0]


def test_the_stamp_exists():
    """PROOF 1 — remove it and the measurement silently stops being taken."""
    _stamp_assignment()


def test_the_stamp_is_computed_from_THIS_bundles_valid_as_of():
    """PROOF 4 — pin the arithmetic's INPUTS, not just that a number appears.

    The field means birth-to-complete FOR THIS BUNDLE. A refactor that reads a request
    timestamp or a step-start time keeps the name and changes the meaning, and no
    output-shaped assertion would notice.
    """
    src = ast.unparse(_stamp_assignment().value)
    assert "valid_as_of" in src, (
        f"the stamp no longer subtracts valid_as_of: {src!r}. Whatever it measures now, it "
        "is not this bundle's birth-to-complete."
    )
    assert "_artifact_bundle['valid_as_of']" in src.replace('"', "'"), (
        f"the stamp reads valid_as_of from something other than THIS bundle: {src!r}"
    )
    assert "elapsed_ms" not in src, (
        "the stamp was wired from elapsed_ms — a DIFFERENT field with a different lifetime. "
        "elapsed_ms rides an SSE event and dies with the stream; duration_ms is persisted. "
        "Coupling them makes the persisted field go absent whenever the SSE path changes."
    )


# ── PROOF 2: the failed path is not an answer's duration ────────────────────
def test_only_the_complete_flip_is_stamped():
    """PROOF 2 — a failed artifact has a wall-clock lifetime, but stamping it would put a
    number beside rows the UI shows nothing for, and would make 'median answer time'
    silently include every 502 death."""
    tree = ast.parse(_GATEWAY.read_text(encoding="utf-8"))
    # Match by LINE, not identity: `_stamp_assignment()` parses its own tree, so the node
    # objects are never the same objects as these. (Identity looked right and could not
    # work — the check would have reported "block not found" forever.)
    stamp_line = _stamp_assignment().lineno

    for node in ast.walk(tree):
        for field_name in ("body", "orelse", "finalbody"):
            block = getattr(node, field_name, None)
            if not isinstance(block, list) or not any(
                getattr(st, "lineno", None) == stamp_line for st in block
            ):
                continue
            statuses = [
                s.value.value for s in block
                if isinstance(s, ast.Assign) and isinstance(s.value, ast.Constant)
                and any(isinstance(t, ast.Subscript)
                        and isinstance(t.slice, ast.Constant)
                        and t.slice.value == "status" for t in s.targets)
            ]
            assert statuses == ["complete"], (
                f"the duration stamp shares a block with status={statuses!r}. It must sit "
                "only with the 'complete' flip — a failed artifact's lifetime is not an "
                "answer's duration."
            )
            return
    raise AssertionError("could not locate the block containing the stamp")


# ── the field reaches the store, both hops ──────────────────────────────────
def test_both_persistence_hops_carry_the_field():
    """Hand-listed projections, so each hop needs its own row. NOTE (not fixed here): the
    Neo4j SET clause and the projector's INSERT/UPDATE enumerate fields BY HAND rather than
    deriving them from the bundle model — this is the fourth field to walk that path. The
    derivation is its own small item; adding it inside this commit would mix a refactor
    into a measurement change."""
    assert "a.duration_ms = $duration_ms" in _WRITER.read_text(encoding="utf-8"), \
        "the Neo4j writeback does not persist duration_ms"
    proj = _PROJECTOR.read_text(encoding="utf-8")
    for frag in ("duration_ms,", "%(duration_ms)s", "duration_ms = EXCLUDED.duration_ms"):
        assert frag in proj, f"projector missing {frag!r} — the field dies at hop 2"
