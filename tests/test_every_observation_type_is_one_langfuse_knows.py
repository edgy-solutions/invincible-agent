"""Every `as_type=` the fleet passes to a Langfuse observation is a type Langfuse knows.

Langfuse does not refuse an unknown type. It logs "Invalid as_type ..." and records the
observation as a plain span. `as_type="retrieval"` did that on engines A and E for the mem0
lookup (Langfuse's name is `retriever`). The valid set is read from Langfuse itself, exactly as
its `observe` decides, never restated here.

Run: uv run pytest tests/test_every_observation_type_is_one_langfuse_knows.py -q
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytest.importorskip("langfuse")

from langfuse._client.constants import (  # noqa: E402
    ObservationTypeLiteralNoEvent, get_observation_types_list)

_REPO = Path(__file__).resolve().parents[1]
_ROOTS = [_REPO / "agent_fleet", _REPO / "src", _REPO / "baml_shared" / "telemetry.py"]
_SKIP_PARTS = {".venv", "__pycache__", "baml_client", "site-packages", "node_modules"}


def _valid() -> set[str]:
    return set(get_observation_types_list(ObservationTypeLiteralNoEvent))


def _sources():
    for root in _ROOTS:
        files = [root] if root.is_file() else root.rglob("*.py")
        for f in files:
            if not _SKIP_PARTS.intersection(f.parts):
                yield f


def _as_types(text: str) -> list[tuple[int, str]]:
    """(line, value) of every string-literal `as_type=` keyword in a call."""
    out = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "as_type" and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, str):
                    out.append((kw.value.lineno, kw.value.value))
    return out


def _census() -> list[tuple[str, int, str]]:
    rows = []
    for f in _sources():
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        try:
            found = _as_types(text)
        except SyntaxError:
            continue
        rows += [(str(f.relative_to(_REPO)), ln, v) for ln, v in found]
    return rows


def test_EVERY_AS_TYPE_IN_THE_FLEET_IS_A_LANGFUSE_OBSERVATION_TYPE():
    bad = [r for r in _census() if r[2] not in _valid()]
    assert bad == [], f"Langfuse would log 'Invalid as_type' and record a span: {bad}"


def test_THE_MEM0_LOOKUP_IS_RECORDED_AS_A_RETRIEVER_ON_BOTH_ENGINES():
    rows = [r for r in _census() if r[2] == "retriever"]
    files = {r[0].replace("\\", "/") for r in rows}
    assert {"agent_fleet/restate_analyst/main.py", "agent_fleet/neo4j_expert/service.py"} <= files


def test_CONTROL_THE_DETECTOR_FINDS_THE_FORM_AND_LANGFUSE_REFUSES_THE_OLD_NAME():
    """Positive control: the census reads the decorator form the fix touched, and the old value is
    outside the set Langfuse reads, so the census above can fail."""
    src = '@safe_observe(as_type="retrieval", name="x")\ndef f():\n    pass\n'
    assert _as_types(src) == [(1, "retrieval")]
    assert "retrieval" not in _valid() and "retriever" in _valid()
    assert len(_census()) >= 2, "the census found no as_type at all: its roots are wrong"
